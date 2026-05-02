#include "cec/cec_bitbang.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "net/tvs_wifi.h"
#include "net/ws_client.h"
#include "ota/tvs_ota.h"
#include "prov/prov_http.h"
#include "prov/tvs_nvs.h"
#include "proto/tv_stretch_proto.h"
#include "sdkconfig.h"
#include <cJSON.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "tvs_main";

static void scpy(char *d, const char *s, size_t n) {
    if (n == 0) {
        return;
    }
    strncpy(d, s, n - 1);
    d[n - 1] = 0;
}

static void nvs_get_str_d(nvs_handle_t h, const char *key, char *out, size_t out_sz,
                          const char *def) {
    size_t len = out_sz;
    esp_err_t e = nvs_get_str(h, key, out, &len);
    if (e != ESP_OK && def) {
        scpy(out, def, out_sz);
    }
}

static void led_init(void) {
#ifdef CONFIG_TVS_STATUS_LED_GPIO
    gpio_reset_pin((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO);
    gpio_set_direction((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO, 0);
#endif
}

static void led_pulse(void) {
#ifdef CONFIG_TVS_STATUS_LED_GPIO
    gpio_set_level((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(40));
    gpio_set_level((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO, 0);
#endif
}

static int payload_int(cJSON *payload, const char *key, int fallback) {
    if (!payload || !key) {
        return fallback;
    }
    cJSON *it = cJSON_GetObjectItem(payload, key);
    if (!it) {
        return fallback;
    }
    if (cJSON_IsNumber(it)) {
        return (int)it->valuedouble;
    }
    return fallback;
}

typedef struct {
    int mode;
    char s[300];
    bool only_diff;
} ota_job_t;

static void ota_task(void *p) {
    ota_job_t *j = (ota_job_t *)p;
    if (j->mode == 0) {
        (void)tvs_ota_apply_from_url(j->s);
    } else {
        (void)tvs_ota_apply_from_manifest_url(j->s, j->only_diff);
    }
    free(j);
    vTaskDelete(NULL);
}

#if CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT
static void boot_ota_task(void *arg) {
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(5000));
    if (CONFIG_TVS_OTA_BOOT_MANIFEST_URL[0] != '\0') {
        ESP_LOGI(TAG, "Boot OTA check: %s", CONFIG_TVS_OTA_BOOT_MANIFEST_URL);
        (void)tvs_ota_apply_from_manifest_url(CONFIG_TVS_OTA_BOOT_MANIFEST_URL, true);
    }
    vTaskDelete(NULL);
}
#endif

static void handle_command(const char *cmd, const cJSON *payload) {
    if (!cmd) {
        return;
    }
    if (strcmp(cmd, "noop") == 0) {
        ESP_LOGD(TAG, "noop");
        return;
    }
    if (strcmp(cmd, "policy") == 0) {
        ESP_LOGI(TAG, "policy (see server coordinator)");
        (void)payload;
        return;
    }
    if (strcmp(cmd, "ota_pull") == 0 && payload) {
        cJSON *url = cJSON_GetObjectItem((cJSON *)payload, "url");
        cJSON *murl = cJSON_GetObjectItem((cJSON *)payload, "manifest_url");
        if (cJSON_IsString(url) && url->valuestring) {
            ota_job_t *j = (ota_job_t *)calloc(1, sizeof(ota_job_t));
            if (!j) {
                return;
            }
            j->mode = 0;
            scpy(j->s, url->valuestring, sizeof(j->s));
            xTaskCreate(ota_task, "ota", 10240, j, 5, NULL);
            return;
        }
        if (cJSON_IsString(murl) && murl->valuestring) {
            ota_job_t *j = (ota_job_t *)calloc(1, sizeof(ota_job_t));
            if (!j) {
                return;
            }
            j->mode = 1;
            j->only_diff = true;
            cJSON *od = cJSON_GetObjectItem((cJSON *)payload, "only_if_version_differs");
            if (cJSON_IsBool(od)) {
                j->only_diff = cJSON_IsTrue(od);
            }
            scpy(j->s, murl->valuestring, sizeof(j->s));
            xTaskCreate(ota_task, "ota", 10240, j, 5, NULL);
            return;
        }
        return;
    }
    if (strcmp(cmd, "cec_broadcast_ping") == 0) {
        uint8_t ping = 0x83;
        tvs_cec_send_frame(0x0F, 0x0F, &ping, 1);
        return;
    }
    if (strcmp(cmd, "cec_standby") == 0) {
        int initiator = payload_int((cJSON *)payload, "initiator", 0x0F);
        int destination = payload_int((cJSON *)payload, "destination", 0x00);
        uint8_t op = 0x36;
        tvs_cec_send_frame(initiator & 0x0F, destination & 0x0F, &op, 1);
        return;
    }
    if (strcmp(cmd, "cec_active_source") == 0 && payload) {
        int addr = payload_int((cJSON *)payload, "physical_address", 0x2000);
        uint8_t body[3] = {0x82, (uint8_t)((addr >> 8) & 0xFF), (uint8_t)(addr & 0xFF)};
        tvs_cec_send_frame(0x0F, 0x0F, body, sizeof(body));
        return;
    }
    if (strcmp(cmd, "cec_send_raw") == 0 && payload && cJSON_IsArray(payload)) {
        int n = cJSON_GetArraySize(payload);
        if (n <= 0 || n > 16) {
            return;
        }
        uint8_t buf[16];
        for (int i = 0; i < n; i++) {
            cJSON *it = cJSON_GetArrayItem(payload, i);
            if (!cJSON_IsNumber(it)) {
                return;
            }
            buf[i] = (uint8_t)it->valueint;
        }
        uint8_t initiator = (buf[0] >> 4) & 0x0F;
        uint8_t dest = buf[0] & 0x0F;
        tvs_cec_send_frame(initiator, dest, buf + 1, (size_t)(n - 1));
        return;
    }
    ESP_LOGW(TAG, "unknown cmd %s", cmd);
}

static void on_ws_message(const char *json, void *ctx) {
    (void)ctx;
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        ESP_LOGW(TAG, "JSON parse fail");
        return;
    }
    cJSON *v = cJSON_GetObjectItem(root, "v");
    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsNumber(v) || (int)v->valuedouble != TVS_PROTO_VER || !cJSON_IsString(type)) {
        cJSON_Delete(root);
        return;
    }
    if (strcmp(type->valuestring, "command_batch") == 0) {
        cJSON *cmds = cJSON_GetObjectItem(root, "commands");
        cJSON *bid = cJSON_GetObjectItem(root, "batch_id");
        const char *bs = cJSON_IsString(bid) ? bid->valuestring : "";
        if (cJSON_IsArray(cmds)) {
            int n = cJSON_GetArraySize(cmds);
            for (int i = 0; i < n; i++) {
                cJSON *c = cJSON_GetArrayItem(cmds, i);
                cJSON *cmd = cJSON_GetObjectItem(c, "cmd");
                cJSON *payload = cJSON_GetObjectItem(c, "payload");
                if (cJSON_IsString(cmd)) {
                    handle_command(cmd->valuestring, payload);
                }
            }
        }
        led_pulse();
        char ack[192];
        snprintf(ack, sizeof(ack), "{\"v\":1,\"type\":\"ack\",\"batch_id\":\"%s\",\"ok\":true}", bs);
        tvs_ws_send_text(ack);
    }
    cJSON_Delete(root);
}

static void heartbeat_task(void *arg) {
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(25000));
        const char *hb = "{\"v\":1,\"type\":\"heartbeat\"}";
        tvs_ws_send_text(hb);
    }
}

void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    led_init();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

#if CONFIG_TVS_HTTP_PROVISIONING
    if (!tvs_nvs_is_provisioned()) {
        ESP_LOGW(TAG, "NVS not provisioned — setup SoftAP");
        tvs_prov_run_http_setup();
    }
#endif

    nvs_handle_t nvs;
    ESP_ERROR_CHECK(nvs_open("tvstretch", NVS_READONLY, &nvs));

    char ssid[64] = {0};
    char pass[64] = {0};
    char ws_url[160] = {0};
    char api_key[96] = {0};
    char room_id[48] = {0};
    char home_id[48] = {0};

    nvs_get_str_d(nvs, "wifi_ssid", ssid, sizeof(ssid), CONFIG_TVS_WIFI_SSID);
    nvs_get_str_d(nvs, "wifi_pass", pass, sizeof(pass), CONFIG_TVS_WIFI_PASSWORD);
    nvs_get_str_d(nvs, "ws_url", ws_url, sizeof(ws_url), CONFIG_TVS_SERVER_WS_URL);
    nvs_get_str_d(nvs, "api_key", api_key, sizeof(api_key), CONFIG_TVS_NODE_API_KEY);
    nvs_get_str_d(nvs, "room_id", room_id, sizeof(room_id), CONFIG_TVS_ROOM_ID);
    nvs_get_str_d(nvs, "home_id", home_id, sizeof(home_id), CONFIG_TVS_HOME_ID);
    nvs_close(nvs);

    esp_netif_create_default_wifi_sta();
    ESP_ERROR_CHECK(tvs_wifi_start_sta(ssid, pass));
    if (!tvs_wifi_wait_connected(0)) {
        ESP_LOGE(TAG, "WiFi connect timeout");
    }

    tvs_cec_init((gpio_num_t)CONFIG_TVS_CEC_GPIO);

#if CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT
    if (CONFIG_TVS_OTA_BOOT_MANIFEST_URL[0] != '\0') {
        xTaskCreate(boot_ota_task, "boot_ota", 8192, NULL, 3, NULL);
    }
#endif

    tvs_ws_start(ws_url, api_key, home_id, room_id, on_ws_message, NULL);
    vTaskDelay(pdMS_TO_TICKS(300));

    char hello[512];
    snprintf(hello, sizeof(hello),
             "{\"v\":1,\"type\":\"hello\",\"node\":{\"room_id\":\"%s\",\"home_id\":\"%s\",\"fw\":\"%s\"}}",
             room_id, home_id, CONFIG_TVS_FW_VERSION);
    tvs_ws_send_text(hello);

    xTaskCreate(heartbeat_task, "hb", 4096, NULL, 5, NULL);
}
