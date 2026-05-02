#include "prov_http.h"
#include "sdkconfig.h"

#if CONFIG_TVS_HTTP_PROVISIONING

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include <cJSON.h>
#include <stdio.h>
#include <string.h>

static const char *TAG = "tvs_prov";

static const char *HTML =
    "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
    "<title>tv-stretch setup</title><style>body{font-family:system-ui;max-width:520px;margin:2rem auto;padding:0 "
    "1rem}label{display:block;margin:.6rem 0 .2rem}input{width:100%;padding:.5rem}button{margin-top:1rem;padding:.6rem "
    "1rem}</style></head><body>"
    "<h1>tv-stretch node</h1><p>Connect this phone/laptop to this AP, then submit Wi-Fi + coordinator settings.</p>"
    "<form id='f'>"
    "<label>Wi-Fi SSID</label><input name='wifi_ssid' required>"
    "<label>Wi-Fi password</label><input name='wifi_pass' type='password'>"
    "<label>WebSocket URL (device)</label><input name='ws_url' placeholder='ws://192.168.1.10:8000/ws/device' "
    "required>"
    "<label>Node API key</label><input name='api_key' required>"
    "<label>Home UUID</label><input name='home_id' required>"
    "<label>Room UUID</label><input name='room_id' required>"
    "<button type='submit'>Save &amp; reboot</button></form>"
    "<pre id='o'></pre>"
    "<script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();const fd=new "
    "FormData(e.target);const body={};fd.forEach((v,k)=>body[k]=v);document.getElementById('o').textContent='Saving…';"
    "const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});"
    "document.getElementById('o').textContent=await r.text();};</script>"
    "</body></html>";

static esp_err_t root_get(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, HTML, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t save_post(httpd_req_t *req) {
    char buf[1024];
    int rlen = req->content_len;
    if (rlen <= 0 || rlen >= (int)sizeof(buf)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad len");
        return ESP_FAIL;
    }
    int recvd = 0;
    while (recvd < rlen) {
        int ret = httpd_req_recv(req, buf + recvd, rlen - recvd);
        if (ret <= 0) {
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "recv");
            return ESP_FAIL;
        }
        recvd += ret;
    }
    buf[rlen] = 0;

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "json");
        return ESP_FAIL;
    }

    const char *keys[] = {"wifi_ssid", "wifi_pass", "ws_url", "api_key", "home_id", "room_id"};
    nvs_handle_t h;
    if (nvs_open("tvstretch", NVS_READWRITE, &h) != ESP_OK) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "nvs");
        return ESP_FAIL;
    }
    for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
        cJSON *it = cJSON_GetObjectItem(root, keys[i]);
        if (!cJSON_IsString(it) || it->valuestring == NULL) {
            nvs_close(h);
            cJSON_Delete(root);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, keys[i]);
            return ESP_FAIL;
        }
        nvs_set_str(h, keys[i], it->valuestring);
    }
    nvs_set_u8(h, "provisioned", 1);
    nvs_commit(h);
    nvs_close(h);
    cJSON_Delete(root);

    const char *ok = "{\"ok\":true,\"message\":\"rebooting\"}";
    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, ok, HTTPD_RESP_USE_STRLEN);
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

void tvs_prov_run_http_setup(void) {
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t icfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&icfg));

    wifi_config_t ap = {0};
    strncpy((char *)ap.ap.ssid, CONFIG_TVS_PROV_AP_SSID, sizeof(ap.ap.ssid) - 1);
    strncpy((char *)ap.ap.password, CONFIG_TVS_PROV_AP_PASS, sizeof(ap.ap.password) - 1);
    ap.ap.channel = CONFIG_TVS_PROV_AP_CHANNEL;
    ap.ap.max_connection = 4;
    ap.ap.authmode = WIFI_AUTH_WPA_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_ERROR_CHECK(esp_wifi_start());

    httpd_handle_t server = NULL;
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.stack_size = 8192;
    ESP_ERROR_CHECK(httpd_start(&server, &cfg));

    httpd_uri_t u_root = {.uri = "/", .method = HTTP_GET, .handler = root_get, .user_ctx = NULL};
    httpd_uri_t u_save = {.uri = "/save", .method = HTTP_POST, .handler = save_post, .user_ctx = NULL};
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &u_root));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &u_save));

    ESP_LOGI(TAG, "Provisioning AP '%s' pass '%s' — open http://192.168.4.1", CONFIG_TVS_PROV_AP_SSID,
             CONFIG_TVS_PROV_AP_PASS);

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

#else /* !CONFIG_TVS_HTTP_PROVISIONING */

void tvs_prov_run_http_setup(void) {}

#endif
