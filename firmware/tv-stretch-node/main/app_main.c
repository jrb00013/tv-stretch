#include "cec/cec_bitbang.h"
#include "cec/cec_proto.h"
#include "cec/cec_rx.h"
#include "core/tvs_cmd_queue.h"
#include "core/tvs_state.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
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
#include "sys/tvs_health.h"
#include "sys/tvs_led.h"
#include "sys/tvs_watchdog.h"
#include <cJSON.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "tvs_main";

static char s_room_id[48];
static char s_home_id[48];

static void scpy(char *d, const char *s, size_t n)
{
    if (n == 0) return;
    strncpy(d, s, n - 1);
    d[n - 1] = 0;
}

static void nvs_get_str_d(nvs_handle_t h, const char *key, char *out, size_t out_sz,
                           const char *def)
{
    size_t len = out_sz;
    esp_err_t e = nvs_get_str(h, key, out, &len);
    if (e != ESP_OK && def) {
        scpy(out, def, out_sz);
    }
}

static int payload_int(cJSON *payload, const char *key, int fallback)
{
    if (!payload || !key) return fallback;
    cJSON *it = cJSON_GetObjectItem(payload, key);
    if (!it) return fallback;
    if (cJSON_IsNumber(it)) return (int)it->valuedouble;
    return fallback;
}

typedef struct {
    int mode;
    char s[300];
    bool only_diff;
} ota_job_t;

static void ota_task(void *p)
{
    ota_job_t *j = (ota_job_t *)p;
    tvs_led_set_pattern(TVS_LED_PATTERN_OTA);
    tvs_health_inc_ota_attempt();
    esp_err_t ret;
    if (j->mode == 0) {
        ret = tvs_ota_apply_from_url(j->s);
    } else {
        ret = tvs_ota_apply_from_manifest_url(j->s, j->only_diff);
    }
    if (ret == ESP_OK) {
        tvs_health_inc_ota_success();
    }
    free(j);
    tvs_led_set_pattern(TVS_LED_PATTERN_CONNECTED);
    vTaskDelete(NULL);
}

#if CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT
static void boot_ota_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(5000));
    if (CONFIG_TVS_OTA_BOOT_MANIFEST_URL[0] != '\0') {
        ESP_LOGI(TAG, "Boot OTA check: %s", CONFIG_TVS_OTA_BOOT_MANIFEST_URL);
        tvs_led_set_pattern(TVS_LED_PATTERN_OTA);
        tvs_health_inc_ota_attempt();
        esp_err_t ret = tvs_ota_apply_from_manifest_url(CONFIG_TVS_OTA_BOOT_MANIFEST_URL, true);
        if (ret == ESP_OK) {
            tvs_health_inc_ota_success();
        }
    }
    tvs_led_set_pattern(TVS_LED_PATTERN_CONNECTING);
    vTaskDelete(NULL);
}
#endif

static void handle_command(const char *cmd, const cJSON *payload)
{
    if (!cmd) return;

    if (strcmp(cmd, "noop") == 0) {
        ESP_LOGD(TAG, "noop");
        return;
    }
    if (strcmp(cmd, "policy") == 0) {
        ESP_LOGI(TAG, "policy (see server)");
        (void)payload;
        return;
    }
    if (strcmp(cmd, "ota_pull") == 0 && payload) {
        cJSON *url = cJSON_GetObjectItem((cJSON *)payload, "url");
        cJSON *murl = cJSON_GetObjectItem((cJSON *)payload, "manifest_url");
        if (cJSON_IsString(url) && url->valuestring) {
            ota_job_t *j = (ota_job_t *)calloc(1, sizeof(ota_job_t));
            if (!j) return;
            j->mode = 0;
            scpy(j->s, url->valuestring, sizeof(j->s));
            xTaskCreate(ota_task, "ota", 10240, j, 5, NULL);
            return;
        }
        if (cJSON_IsString(murl) && murl->valuestring) {
            ota_job_t *j = (ota_job_t *)calloc(1, sizeof(ota_job_t));
            if (!j) return;
            j->mode = 1;
            j->only_diff = true;
            cJSON *od = cJSON_GetObjectItem((cJSON *)payload, "only_if_version_differs");
            if (cJSON_IsBool(od)) j->only_diff = cJSON_IsTrue(od);
            scpy(j->s, murl->valuestring, sizeof(j->s));
            xTaskCreate(ota_task, "ota", 10240, j, 5, NULL);
            return;
        }
        return;
    }
    if (strcmp(cmd, "cec_broadcast_ping") == 0) {
        uint8_t ping = CEC_OP_GIVE_PHYSICAL_ADDR;
        tvs_cec_send_frame(CEC_ADDR_BROADCAST, CEC_ADDR_BROADCAST, &ping, 1);
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "cec_standby") == 0) {
        int initiator = payload_int((cJSON *)payload, "initiator", CONFIG_TVS_CEC_LOGICAL_ADDR);
        int destination = payload_int((cJSON *)payload, "destination", CEC_ADDR_TV);
        uint8_t op = CEC_OP_STANDBY;
        tvs_cec_send_frame(initiator & 0x0F, destination & 0x0F, &op, 1);
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "cec_active_source") == 0 && payload) {
        int addr = payload_int((cJSON *)payload, "physical_address", CONFIG_TVS_CEC_PHYSICAL_ADDR);
        uint8_t body[3] = {CEC_OP_ACTIVE_SOURCE, (uint8_t)((addr >> 8) & 0xFF), (uint8_t)(addr & 0xFF)};
        tvs_cec_send_frame(CONFIG_TVS_CEC_LOGICAL_ADDR, CEC_ADDR_BROADCAST, body, sizeof(body));
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "cec_user_control") == 0 && payload) {
        int key = payload_int((cJSON *)payload, "key", 0);
        uint8_t body[2] = {CEC_OP_USER_CONTROL_PRESSED, (uint8_t)(key & 0xFF)};
        int initiator = payload_int((cJSON *)payload, "initiator", CONFIG_TVS_CEC_LOGICAL_ADDR);
        int destination = payload_int((cJSON *)payload, "destination", CEC_ADDR_TV);
        tvs_cec_send_frame(initiator & 0x0F, destination & 0x0F, body, sizeof(body));
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "cec_set_stream_path") == 0 && payload) {
        int addr = payload_int((cJSON *)payload, "physical_address", CONFIG_TVS_CEC_PHYSICAL_ADDR);
        uint8_t body[3] = {CEC_OP_SET_STREAM_PATH, (uint8_t)((addr >> 8) & 0xFF), (uint8_t)(addr & 0xFF)};
        tvs_cec_send_frame(CEC_ADDR_TV, CEC_ADDR_BROADCAST, body, sizeof(body));
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "cec_send_raw") == 0 && payload && cJSON_IsArray(payload)) {
        int n = cJSON_GetArraySize(payload);
        if (n <= 0 || n > CEC_MAX_FRAME_BYTES) return;
        uint8_t buf[CEC_MAX_FRAME_BYTES];
        for (int i = 0; i < n; i++) {
            cJSON *it = cJSON_GetArrayItem(payload, i);
            if (!cJSON_IsNumber(it)) return;
            buf[i] = (uint8_t)it->valueint;
        }
        uint8_t initiator = (buf[0] >> 4) & 0x0F;
        uint8_t dest = buf[0] & 0x0F;
        tvs_cec_send_frame(initiator, dest, buf + 1, (size_t)(n - 1));
        tvs_health_inc_cec_tx();
        return;
    }
    if (strcmp(cmd, "scan_bus") == 0) {
        tvs_cec_proto_scan_bus();
        return;
    }
    if (strcmp(cmd, "health_report") == 0) {
        char hjson[512];
        tvs_health_build_json(hjson, sizeof(hjson));
        tvs_ws_send_text(hjson);
        return;
    }
    if (strcmp(cmd, "reset_health") == 0) {
        tvs_health_reset();
        return;
    }
    ESP_LOGW(TAG, "unknown cmd %s", cmd);
}

static void cmd_complete_cb(const char *batch_id, const char *cmd, bool ok)
{
    if (ok) {
        tvs_health_inc_ack();
    } else {
        tvs_health_inc_nack();
    }
}

static void on_cec_frame(uint8_t initiator, uint8_t destination,
                          const uint8_t *body, uint8_t body_len)
{
    tvs_health_inc_cec_rx();
    tvs_cec_proto_process_frame(initiator, destination, body, body_len);
}

static void process_cmd_queue(void)
{
    tvs_cmd_entry_t entry;
    while (tvs_cmd_dequeue(&entry)) {
        cJSON *payload = NULL;
        if (entry.payload_json[0] != '\0') {
            payload = cJSON_Parse(entry.payload_json);
        }
        handle_command(entry.cmd, payload);
        if (payload) cJSON_Delete(payload);
        tvs_cmd_ack(entry.batch_id, entry.cmd);
    }
    tvs_health_set_cmd_depth(tvs_cmd_queue_depth());
}

static void on_ws_message(const char *json, void *ctx)
{
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
                    char *payload_str = payload ? cJSON_PrintUnformatted(payload) : NULL;
                    tvs_cmd_enqueue(bs, cmd->valuestring, payload_str);
                    if (payload_str) free(payload_str);
                }
            }
        }

        tvs_led_pulse();
        char ack[192];
        snprintf(ack, sizeof(ack), "{\"v\":1,\"type\":\"ack\",\"batch_id\":\"%s\",\"ok\":true}", bs);
        tvs_ws_send_text(ack);
    }
    cJSON_Delete(root);
}

static void on_ws_connect(bool connected, void *ctx)
{
    (void)ctx;
    if (connected) {
        tvs_state_transition(TVS_STATE_WS_CONNECTED);
        vTaskDelay(pdMS_TO_TICKS(200));
        char hello[512];
        snprintf(hello, sizeof(hello),
                 "{\"v\":1,\"type\":\"hello\",\"node\":{\"room_id\":\"%s\",\"home_id\":\"%s\",\"fw\":\"%s\"}}",
                 s_room_id, s_home_id, CONFIG_TVS_FW_VERSION);
        tvs_ws_send_text(hello);

        tvs_health_reset();
        tvs_cec_rx_reset_counts();
    } else {
        tvs_health_inc_ws_reconnect();
        tvs_state_transition(TVS_STATE_DISCONNECTED);
    }
}

static void on_state_change(tvs_state_t old_state, tvs_state_t new_state)
{
    (void)old_state;
    switch (new_state) {
    case TVS_STATE_COLD_START:
    case TVS_STATE_PROVISIONING:
        tvs_led_set_pattern(TVS_LED_PATTERN_BOOT);
        break;
    case TVS_STATE_WIFI_CONNECT:
    case TVS_STATE_WIFI_WAIT:
    case TVS_STATE_WS_CONNECT:
        tvs_led_set_pattern(TVS_LED_PATTERN_CONNECTING);
        break;
    case TVS_STATE_WS_CONNECTED:
        tvs_led_set_pattern(TVS_LED_PATTERN_CONNECTED);
        break;
    case TVS_STATE_DISCONNECTED:
        tvs_led_set_pattern(TVS_LED_PATTERN_CONNECTING);
        break;
    case TVS_STATE_ERROR:
        tvs_led_set_pattern(TVS_LED_PATTERN_ERROR);
        break;
    case TVS_STATE_DEEP_SLEEP:
        tvs_led_set_pattern(TVS_LED_PATTERN_OFF);
        break;
    default:
        break;
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(25000));
        if (tvs_state_is_connected()) {
            const char *hb = "{\"v\":1,\"type\":\"heartbeat\"}";
            tvs_ws_send_text(hb);
        }
    }
}

static void health_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(CONFIG_TVS_HEALTH_INTERVAL * 1000));
        tvs_health_t h;
        tvs_health_collect(&h);

        ESP_LOGI(TAG, "health: up=%us rssi=%d cec_tx=%lu cec_rx=%lu cec_err=%lu "
                 "ws_recon=%lu heap=%lu/%lu cmdq=%lu ota=%lu/%lu acks=%lu/%lu",
                 (unsigned)h.uptime_sec, h.wifi_rssi,
                 (unsigned long)h.cec_tx_frames, (unsigned long)h.cec_rx_frames,
                 (unsigned long)h.cec_rx_errors,
                 (unsigned long)h.ws_reconnects,
                 (unsigned long)h.free_heap, (unsigned long)h.min_free_heap,
                 (unsigned long)h.cmd_queue_depth,
                 (unsigned long)h.ota_attempts, (unsigned long)h.ota_successes,
                 (unsigned long)h.ack_count, (unsigned long)h.nack_count);

        if (tvs_state_is_connected()) {
            char hjson[512];
            tvs_health_build_json(hjson, sizeof(hjson));
            tvs_ws_send_text(hjson);
        }
    }
}

static void cmd_queue_task(void *arg)
{
    (void)arg;
    while (1) {
        process_cmd_queue();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi disconnected");
        tvs_state_transition(TVS_STATE_WIFI_CONNECT);
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    tvs_led_init((gpio_num_t)CONFIG_TVS_STATUS_LED_GPIO);
    tvs_led_set_pattern(TVS_LED_PATTERN_BOOT);

    tvs_watchdog_init(CONFIG_TVS_WATCHDOG_TIMEOUT);

    tvs_state_init(on_state_change);
    tvs_state_transition(TVS_STATE_COLD_START);

    ESP_ERROR_CHECK(tvs_cec_init((gpio_num_t)CONFIG_TVS_CEC_GPIO));
    ESP_ERROR_CHECK(tvs_cec_rx_init((gpio_num_t)CONFIG_TVS_CEC_GPIO));
    tvs_cec_rx_set_callback(on_cec_frame);

    tvs_cec_proto_init(NULL);
    tvs_cmd_queue_init(cmd_complete_cb);
    tvs_health_init();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
                                                wifi_event_handler, NULL));

#if CONFIG_TVS_HTTP_PROVISIONING
    if (!tvs_nvs_is_provisioned()) {
        ESP_LOGW(TAG, "NVS not provisioned -- setup SoftAP");
        tvs_state_transition(TVS_STATE_PROVISIONING);
        tvs_prov_run_http_setup();
    }
#endif

    nvs_handle_t nvs;
    ESP_ERROR_CHECK(nvs_open("tvstretch", NVS_READONLY, &nvs));

    char ssid[64] = {0};
    char pass[64] = {0};
    char ws_url[160] = {0};
    char api_key[96] = {0};

    nvs_get_str_d(nvs, "wifi_ssid", ssid, sizeof(ssid), CONFIG_TVS_WIFI_SSID);
    nvs_get_str_d(nvs, "wifi_pass", pass, sizeof(pass), CONFIG_TVS_WIFI_PASSWORD);
    nvs_get_str_d(nvs, "ws_url", ws_url, sizeof(ws_url), CONFIG_TVS_SERVER_WS_URL);
    nvs_get_str_d(nvs, "api_key", api_key, sizeof(api_key), CONFIG_TVS_NODE_API_KEY);
    nvs_get_str_d(nvs, "room_id", s_room_id, sizeof(s_room_id), CONFIG_TVS_ROOM_ID);
    nvs_get_str_d(nvs, "home_id", s_home_id, sizeof(s_home_id), CONFIG_TVS_HOME_ID);
    nvs_close(nvs);

    esp_netif_create_default_wifi_sta();
    tvs_state_transition(TVS_STATE_WIFI_CONNECT);
    ESP_ERROR_CHECK(tvs_wifi_start_sta(ssid, pass));

#if CONFIG_TVS_CEC_RX_ENABLE
    tvs_cec_rx_start();
    ESP_LOGI(TAG, "CEC RX enabled");
#endif

    xTaskCreate(cmd_queue_task, "cmdq", 4096, NULL, 6, NULL);

#if CONFIG_TVS_OTA_AUTO_CHECK_ON_BOOT
    if (CONFIG_TVS_OTA_BOOT_MANIFEST_URL[0] != '\0') {
        xTaskCreate(boot_ota_task, "boot_ota", 8192, NULL, 3, NULL);
    }
#endif

    tvs_ws_start(ws_url, api_key, s_home_id, s_room_id,
                 on_ws_message, on_ws_connect, NULL);
    tvs_state_transition(TVS_STATE_WS_CONNECT);

    xTaskCreate(heartbeat_task, "hb", 3072, NULL, 5, NULL);
    xTaskCreate(health_task, "health", 3072, NULL, 2, NULL);

    while (1) {
        tvs_watchdog_feed();
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
