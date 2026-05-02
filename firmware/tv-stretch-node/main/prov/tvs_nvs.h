#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** True when NVS namespace tvstretch has provisioned==1. */
bool tvs_nvs_is_provisioned(void);

#ifdef __cplusplus
}
#endif
