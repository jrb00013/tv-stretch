#pragma once

#include <stdint.h>

#define TVS_PROTO_VER 1

typedef enum {
    TVS_MSG_HELLO = 0,
    TVS_MSG_HEARTBEAT,
    TVS_MSG_ACK,
    TVS_MSG_EVENT,
    TVS_MSG_COMMAND_BATCH,
} tvs_msg_type_t;

typedef struct {
    char batch_id[48];
    char cmd[32];
    char payload_json[256];
} tvs_command_t;
