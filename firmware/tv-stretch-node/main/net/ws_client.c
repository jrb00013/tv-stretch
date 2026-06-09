#include "ws_client.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include <stdlib.h>
#include <string.h>

static const char *TAG = "tvs_ws";

static esp_websocket_client_handle_t s_ws;
static tvs_ws_on_message_cb s_cb;
static tvs_ws_on_connect_cb s_conn_cb;
static void *s_ctx;
static char s_headers[512];

static void ws_event(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;
    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "WS connected");
        if (s_conn_cb) s_conn_cb(true, s_ctx);
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "WS disconnected");
        if (s_conn_cb) s_conn_cb(false, s_ctx);
        break;
    case WEBSOCKET_EVENT_DATA:
        if (data->op_code == 0x01 && data->data_ptr && data->data_len > 0 && s_cb) {
            char *tmp = calloc(1, data->data_len + 1);
            if (tmp) {
                memcpy(tmp, data->data_ptr, data->data_len);
                s_cb(tmp, s_ctx);
                free(tmp);
            }
        }
        break;
    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGE(TAG, "WS error");
        break;
    default:
        break;
    }
}

esp_err_t tvs_ws_start(const char *ws_uri, const char *api_key, const char *home_id,
                       const char *room_id, tvs_ws_on_message_cb on_message,
                       tvs_ws_on_connect_cb on_connect, void *ctx) {
    if (s_ws) {
        tvs_ws_stop();
    }
    s_cb = on_message;
    s_conn_cb = on_connect;
    s_ctx = ctx;

    snprintf(
        s_headers, sizeof(s_headers),
        "Authorization: Bearer %s\r\nX-TV-Stretch-Home: %s\r\nX-TV-Stretch-Room: %s\r\n",
        api_key ? api_key : "", home_id ? home_id : "", room_id ? room_id : "");

    esp_websocket_client_config_t cfg = {
        .uri = ws_uri,
        .headers = s_headers,
        .disable_auto_reconnect = false,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 10000,
    };

    s_ws = esp_websocket_client_init(&cfg);
    if (!s_ws) {
        return ESP_FAIL;
    }

    esp_websocket_register_events(s_ws, WEBSOCKET_EVENT_ANY, ws_event, NULL);
    return esp_websocket_client_start(s_ws);
}

void tvs_ws_stop(void) {
    if (s_ws) {
        esp_websocket_client_stop(s_ws);
        esp_websocket_client_destroy(s_ws);
        s_ws = NULL;
    }
}

bool tvs_ws_send_text(const char *text) {
    if (!s_ws || !text) {
        return false;
    }
    return esp_websocket_client_send_text(s_ws, text, strlen(text), portMAX_DELAY) >= 0;
}
