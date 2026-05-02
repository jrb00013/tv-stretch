#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Download and switch to firmware at URL (HTTP/HTTPS per IDF config), then reboot on success. */
esp_err_t tvs_ota_apply_from_url(const char *firmware_url);

/**
 * GET manifest JSON { "version": "x.y.z", "url": "http://.../firmware.bin" }.
 * If only_if_version_differs, skips download when version matches CONFIG_TVS_FW_VERSION.
 */
esp_err_t tvs_ota_apply_from_manifest_url(const char *manifest_url, bool only_if_version_differs);

#ifdef __cplusplus
}
#endif
