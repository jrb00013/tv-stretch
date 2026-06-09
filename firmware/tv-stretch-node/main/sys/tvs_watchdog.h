#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t tvs_watchdog_init(uint32_t timeout_sec);
esp_err_t tvs_watchdog_add_task(TaskHandle_t task, const char *name, uint32_t timeout_ms);
esp_err_t tvs_watchdog_remove_task(TaskHandle_t task);
void tvs_watchdog_feed(void);
void tvs_watchdog_feed_task(TaskHandle_t task);
void tvs_watchdog_disable(void);
bool tvs_watchdog_is_enabled(void);
uint32_t tvs_watchdog_feed_count(void);

#ifdef __cplusplus
}
#endif
