#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TVS_LED_PATTERN_OFF,
    TVS_LED_PATTERN_BOOT,
    TVS_LED_PATTERN_CONNECTING,
    TVS_LED_PATTERN_CONNECTED,
    TVS_LED_PATTERN_COMMAND,
    TVS_LED_PATTERN_ERROR,
    TVS_LED_PATTERN_OTA,
} tvs_led_pattern_t;

esp_err_t tvs_led_init(gpio_num_t pin);
void tvs_led_set_pattern(tvs_led_pattern_t pattern);
void tvs_led_pulse(void);

#ifdef __cplusplus
}
#endif
