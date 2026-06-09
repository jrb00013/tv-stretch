#include "core/tvs_state.h"
#include "esp_log.h"

static const char *TAG = "tvs_state";

static tvs_state_t s_current = TVS_STATE_COLD_START;
static tvs_state_change_cb s_cb = NULL;

static const char *STATE_NAMES[TVS_STATE_COUNT] = {
    "COLD_START",
    "PROVISIONING",
    "WIFI_CONNECT",
    "WIFI_WAIT",
    "WS_CONNECT",
    "WS_CONNECTED",
    "DISCONNECTED",
    "ERROR",
    "DEEP_SLEEP",
};

void tvs_state_init(tvs_state_change_cb cb)
{
    s_current = TVS_STATE_COLD_START;
    s_cb = cb;
    ESP_LOGI(TAG, "state machine initialized: %s", STATE_NAMES[s_current]);
}

void tvs_state_transition(tvs_state_t new_state)
{
    if (new_state == s_current) {
        return;
    }
    if (new_state >= TVS_STATE_COUNT) {
        ESP_LOGE(TAG, "invalid state transition target %d", new_state);
        return;
    }
    tvs_state_t old = s_current;
    s_current = new_state;
    ESP_LOGI(TAG, "state %s -> %s", STATE_NAMES[old], STATE_NAMES[new_state]);
    if (s_cb) {
        s_cb(old, new_state);
    }
}

tvs_state_t tvs_state_get(void)
{
    return s_current;
}

const char *tvs_state_name(tvs_state_t s)
{
    if (s >= TVS_STATE_COUNT) {
        return "UNKNOWN";
    }
    return STATE_NAMES[s];
}

bool tvs_state_is_connected(void)
{
    return s_current == TVS_STATE_WS_CONNECTED;
}
