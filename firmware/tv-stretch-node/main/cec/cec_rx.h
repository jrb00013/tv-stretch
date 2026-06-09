#pragma once

#include "driver/gpio.h"
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CEC_RX_RING_SIZE 128
#define CEC_RX_FRAME_MAX 16

typedef struct {
    int64_t timestamp_us;
    uint8_t level;
} cec_edge_t;

typedef void (*tvs_cec_rx_cb)(uint8_t initiator, uint8_t destination,
                                const uint8_t *data, size_t len);

esp_err_t tvs_cec_rx_init(gpio_num_t pin);
void tvs_cec_rx_set_callback(tvs_cec_rx_cb cb);
void tvs_cec_rx_start(void);
void tvs_cec_rx_stop(void);
void tvs_cec_rx_set_tx_active(bool active);
uint32_t tvs_cec_rx_frame_count(void);

#ifdef __cplusplus
}
#endif
