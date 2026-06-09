#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CEC_ADDR_TV          0x00
#define CEC_ADDR_RECORD1     0x01
#define CEC_ADDR_RECORD2     0x02
#define CEC_ADDR_TUNER1      0x03
#define CEC_ADDR_PLAYBACK1   0x04
#define CEC_ADDR_AUDIO       0x05
#define CEC_ADDR_TUNER2      0x06
#define CEC_ADDR_TUNER3      0x07
#define CEC_ADDR_PLAYBACK2   0x08
#define CEC_ADDR_RECORD3     0x09
#define CEC_ADDR_TUNER4      0x0A
#define CEC_ADDR_PLAYBACK3   0x0B
#define CEC_ADDR_FREE1       0x0C
#define CEC_ADDR_FREE2       0x0D
#define CEC_ADDR_SPECIFIC    0x0E
#define CEC_ADDR_BROADCAST   0x0F
#define CEC_ADDR_UNREGISTERED 0x0F

#define CEC_OP_FEATURE_ABORT         0x00
#define CEC_OP_IMAGE_VIEW_ON         0x04
#define CEC_OP_TEXT_VIEW_ON          0x0D
#define CEC_OP_STANDBY               0x36
#define CEC_OP_SET_MENU_LANGUAGE     0x32
#define CEC_OP_USER_CONTROL_PRESSED  0x44
#define CEC_OP_USER_CONTROL_RELEASED 0x45
#define CEC_OP_GIVE_OSD_NAME         0x46
#define CEC_OP_SET_OSD_NAME          0x47
#define CEC_OP_ROUTING_CHANGE        0x80
#define CEC_OP_ACTIVE_SOURCE         0x82
#define CEC_OP_GIVE_PHYSICAL_ADDR    0x83
#define CEC_OP_REPORT_PHYSICAL_ADDR  0x84
#define CEC_OP_REQUEST_ACTIVE_SOURCE 0x85
#define CEC_OP_SET_STREAM_PATH       0x86
#define CEC_OP_DEVICE_VENDOR_ID      0x87
#define CEC_OP_GIVE_DEVICE_POWER_STATUS 0x8F
#define CEC_OP_REPORT_POWER_STATUS   0x90
#define CEC_OP_VENDOR_ID             0xC7
#define CEC_OP_ABORT                 0xFF

#define CEC_POWER_STATE_ON              0x00
#define CEC_POWER_STATE_STANDBY         0x01
#define CEC_POWER_STATE_TRANSITION_ON   0x02
#define CEC_POWER_STATE_TRANSITION_STANDBY 0x03
#define CEC_POWER_STATE_UNKNOWN         0x04

#define CEC_MAX_FRAME_BYTES      16
#define CEC_SCAN_LOGICAL_ADDRS   16

typedef enum {
    CEC_DEVICE_TYPE_TV = 0,
    CEC_DEVICE_TYPE_RECORDING = 1,
    CEC_DEVICE_TYPE_RESERVED = 2,
    CEC_DEVICE_TYPE_TUNER = 3,
    CEC_DEVICE_TYPE_PLAYBACK = 4,
    CEC_DEVICE_TYPE_AUDIO = 5,
    CEC_DEVICE_TYPE_UNREGISTERED = 7,
} cec_device_type_t;

typedef struct {
    uint8_t logical_addr;
    uint16_t physical_addr;
    cec_device_type_t device_type;
    char osd_name[16];
    uint32_t vendor_id;
    bool present;
    int8_t power_status;
} cec_device_info_t;

typedef void (*tvs_cec_frame_cb)(uint8_t initiator, uint8_t destination,
                                  const uint8_t *body, uint8_t body_len);

void tvs_cec_proto_init(tvs_cec_frame_cb cb);
void tvs_cec_proto_process_frame(uint8_t initiator, uint8_t destination,
                                  const uint8_t *body, uint8_t body_len);
void tvs_cec_proto_scan_bus(void);
bool tvs_cec_proto_is_scanning(void);
cec_device_info_t *tvs_cec_proto_get_device(uint8_t logical_addr);
int tvs_cec_proto_get_device_count(void);
const char *tvs_cec_opcode_name(uint8_t opcode);
const char *tvs_cec_addr_name(uint8_t addr);
bool tvs_cec_proto_is_broadcast(uint8_t destination);
void tvs_cec_proto_reset(void);

#ifdef __cplusplus
}
#endif
