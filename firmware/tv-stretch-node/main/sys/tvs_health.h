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
    uint32_t ws_reconnects;
    uint32_t cmd_queue_depth;
    uint32_t free_heap;
    uint32_t min_free_heap;
} tvs_health_t;

void tvs_health_init(void);
void tvs_health_collect(tvs_health_t *out);
void tvs_health_inc_cec_tx(void);
void tvs_health_inc_cec_rx(void);
void tvs_health_inc_ws_reconnect(void);
void tvs_health_set_cmd_depth(uint32_t depth);

#ifdef __cplusplus
}
#endif
