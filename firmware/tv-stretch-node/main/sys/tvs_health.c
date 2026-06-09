#include "sys/tvs_health.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "tvs_health";

static uint64_t s_start_us = 0;
static uint32_t s_cec_tx = 0;
static uint32_t s_cec_rx = 0;
static uint32_t s_ws_reconnects = 0;
static uint32_t s_cmd_depth = 0;

void tvs_health_init(void)
{
    s_start_us = esp_timer_get_time();
    ESP_LOGI(TAG, "health monitoring initialized");
}

void tvs_health_collect(tvs_health_t *out)
{
    memset(out, 0, sizeof(*out));

    out->uptime_sec = (uint32_t)((esp_timer_get_time() - s_start_us) / 1000000);
    out->cec_tx_frames = s_cec_tx;
    out->cec_rx_frames = s_cec_rx;
    out->ws_reconnects = s_ws_reconnects;
    out->cmd_queue_depth = s_cmd_depth;
    out->free_heap = (uint32_t)esp_get_free_heap_size();
    out->min_free_heap = (uint32_t)esp_get_minimum_free_heap_size();

    wifi_ap_record_t ap = {0};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        out->wifi_rssi = ap.rssi;
    } else {
        out->wifi_rssi = -128;
    }
}

void tvs_health_inc_cec_tx(void)
{
    s_cec_tx++;
}

void tvs_health_inc_cec_rx(void)
{
    s_cec_rx++;
}

void tvs_health_inc_ws_reconnect(void)
{
    s_ws_reconnects++;
}

void tvs_health_set_cmd_depth(uint32_t depth)
{
    s_cmd_depth = depth;
}
