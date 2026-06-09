#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t tvs_watchdog_init(uint32_t timeout_sec);
void tvs_watchdog_feed(void);
void tvs_watchdog_disable(void);

#ifdef __cplusplus
}
#endif
