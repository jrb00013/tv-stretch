#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Start SoftAP + HTTP server for one-time provisioning.
 * Blocks until device reboots (successful POST /save calls esp_restart).
 */
void tvs_prov_run_http_setup(void);

#ifdef __cplusplus
}
#endif
