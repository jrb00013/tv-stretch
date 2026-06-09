#include "sys/tvs_health.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "tvs_health";

static uint64_t s_start_us = 0;
static uint32_t s_cec_tx = 0;
static uint32_t s_cec_rx = 0;
static uint32_t s_cec_rx_err = 0;
static uint32_t s_ws_reconnects = 0;
static uint32_t s_cmd_depth = 0;
static uint32_t s_ota_attempts = 0;
static uint32_t s_ota_successes = 0;
static uint32_t s_ack_count = 0;
static uint32_t s_nack_count = 0;
static int8_t s_last_rssi = -128;
static uint32_t s_last_collect_ms = 0;

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
    out->cec_rx_errors = s_cec_rx_err;
    out->ws_reconnects = s_ws_reconnects;
    out->cmd_queue_depth = s_cmd_depth;
    out->free_heap = (uint32_t)esp_get_free_heap_size();
    out->min_free_heap = (uint32_t)esp_get_minimum_free_heap_size();
    out->ota_attempts = s_ota_attempts;
    out->ota_successes = s_ota_successes;
    out->ack_count = s_ack_count;
    out->nack_count = s_nack_count;
    out->temperature = 0;

    wifi_ap_record_t ap = {0};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        out->wifi_rssi = ap.rssi;
        s_last_rssi = ap.rssi;
    } else {
        out->wifi_rssi = s_last_rssi;
    }

    s_last_collect_ms = (uint32_t)(esp_timer_get_time() / 1000);
}

int tvs_health_build_json(char *buf, size_t buf_size)
{
    tvs_health_t h;
    tvs_health_collect(&h);

    return snprintf(buf, buf_size,
        "{"
        "\"v\":1,"
        "\"type\":\"health\","
        "\"uptime\":%u,"
        "\"rssi\":%d,"
        "\"cec_tx\":%u,"
        "\"cec_rx\":%u,"
        "\"cec_rx_err\":%u,"
        "\"ws_recon\":%u,"
        "\"cmdq\":%u,"
        "\"heap\":%u,"
        "\"min_heap\":%u,"
        "\"ota_attempts\":%u,"
        "\"ota_ok\":%u,"
        "\"acks\":%u,"
        "\"nacks\":%u"
        "}",
        h.uptime_sec, h.wifi_rssi,
        h.cec_tx_frames, h.cec_rx_frames, h.cec_rx_errors,
        h.ws_reconnects, h.cmd_queue_depth,
        h.free_heap, h.min_free_heap,
        h.ota_attempts, h.ota_successes,
        h.ack_count, h.nack_count);
}

void tvs_health_inc_cec_tx(void)
{
    s_cec_tx++;
}

void tvs_health_inc_cec_rx(void)
{
    s_cec_rx++;
}

void tvs_health_inc_cec_rx_err(void)
{
    s_cec_rx_err++;
}

void tvs_health_inc_ws_reconnect(void)
{
    s_ws_reconnects++;
}

void tvs_health_inc_ota_attempt(void)
{
    s_ota_attempts++;
}

void tvs_health_inc_ota_success(void)
{
    s_ota_successes++;
}

void tvs_health_inc_ack(void)
{
    s_ack_count++;
}

void tvs_health_inc_nack(void)
{
    s_nack_count++;
}

void tvs_health_set_cmd_depth(uint32_t depth)
{
    s_cmd_depth = depth;
}

void tvs_health_set_rssi(int8_t rssi)
{
    s_last_rssi = rssi;
}

uint32_t tvs_health_uptime_sec(void)
{
    return (uint32_t)((esp_timer_get_time() - s_start_us) / 1000000);
}

void tvs_health_reset(void)
{
    s_cec_tx = 0;
    s_cec_rx = 0;
    s_cec_rx_err = 0;
    s_ws_reconnects = 0;
    s_cmd_depth = 0;
    s_ota_attempts = 0;
    s_ota_successes = 0;
    s_ack_count = 0;
    s_nack_count = 0;
    ESP_LOGI(TAG, "health counters reset");
}
