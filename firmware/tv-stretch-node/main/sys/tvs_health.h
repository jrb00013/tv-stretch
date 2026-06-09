#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t uptime_sec;
    int8_t wifi_rssi;
    uint32_t cec_tx_frames;
    uint32_t cec_rx_frames;
    uint32_t cec_rx_errors;
    uint32_t ws_reconnects;
    uint32_t cmd_queue_depth;
    uint32_t free_heap;
    uint32_t min_free_heap;
    uint32_t ota_attempts;
    uint32_t ota_successes;
    uint32_t ack_count;
    uint32_t nack_count;
    int8_t temperature;
} tvs_health_t;

void tvs_health_init(void);
void tvs_health_collect(tvs_health_t *out);
int tvs_health_build_json(char *buf, size_t buf_size);

void tvs_health_inc_cec_tx(void);
void tvs_health_inc_cec_rx(void);
void tvs_health_inc_cec_rx_err(void);
void tvs_health_inc_ws_reconnect(void);
void tvs_health_inc_ota_attempt(void);
void tvs_health_inc_ota_success(void);
void tvs_health_inc_ack(void);
void tvs_health_inc_nack(void);
void tvs_health_set_cmd_depth(uint32_t depth);
void tvs_health_set_rssi(int8_t rssi);

uint32_t tvs_health_uptime_sec(void);
void tvs_health_reset(void);

#ifdef __cplusplus
}
#endif
