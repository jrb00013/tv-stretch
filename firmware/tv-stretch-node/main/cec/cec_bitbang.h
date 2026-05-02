#pragma once

#include "driver/gpio.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Initialize CEC GPIO as open-drain output with pull-up. */
esp_err_t tvs_cec_init(gpio_num_t pin);

/** Send one byte on CEC bus (8 data bits + EOM + ACK), follower ACK assumed. */
esp_err_t tvs_cec_send_byte(uint8_t byte, bool eom);

/** Send a minimal CEC frame: header byte + optional data bytes. */
esp_err_t tvs_cec_send_frame(uint8_t initiator, uint8_t destination, const uint8_t *data,
                             size_t data_len);

#ifdef __cplusplus
}
#endif
