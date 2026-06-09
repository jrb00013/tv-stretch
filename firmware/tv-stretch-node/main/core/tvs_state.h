#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TVS_STATE_COLD_START = 0,
    TVS_STATE_PROVISIONING,
    TVS_STATE_WIFI_CONNECT,
    TVS_STATE_WIFI_WAIT,
    TVS_STATE_WS_CONNECT,
    TVS_STATE_WS_CONNECTED,
    TVS_STATE_DISCONNECTED,
    TVS_STATE_ERROR,
    TVS_STATE_DEEP_SLEEP,
    TVS_STATE_COUNT,
} tvs_state_t;

typedef void (*tvs_state_change_cb)(tvs_state_t old_state, tvs_state_t new_state);

void tvs_state_init(tvs_state_change_cb cb);
void tvs_state_transition(tvs_state_t new_state);
tvs_state_t tvs_state_get(void);
const char *tvs_state_name(tvs_state_t s);
bool tvs_state_is_connected(void);

#ifdef __cplusplus
}
#endif
