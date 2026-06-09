#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*tvs_ws_on_message_cb)(const char *json, void *ctx);
typedef void (*tvs_ws_on_connect_cb)(bool connected, void *ctx);

esp_err_t tvs_ws_start(const char *ws_uri, const char *api_key, const char *home_id,
                       const char *room_id, tvs_ws_on_message_cb on_message,
                       tvs_ws_on_connect_cb on_connect, void *ctx);

void tvs_ws_stop(void);

bool tvs_ws_send_text(const char *text);

#ifdef __cplusplus
}
#endif
