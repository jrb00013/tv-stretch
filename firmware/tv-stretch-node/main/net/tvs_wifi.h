#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Start STA using given credentials (idempotent with app_main flow). */
esp_err_t tvs_wifi_start_sta(const char *ssid, const char *pass);

/** Block until connected or timeout_ms (0 = default 60000). */
bool tvs_wifi_wait_connected(uint32_t timeout_ms);

#ifdef __cplusplus
}
#endif
