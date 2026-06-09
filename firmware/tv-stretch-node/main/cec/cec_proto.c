#include "cec/cec_proto.h"
#include "cec/cec_bitbang.h"
#include "esp_log.h"
#include "esp_timer.h"
#include <string.h>

static const char *TAG = "tvs_cec_proto";

static tvs_cec_frame_cb s_frame_cb = NULL;
static cec_device_info_t s_devices[CEC_SCAN_LOGICAL_ADDRS];
static bool s_scanning = false;
static uint8_t s_scan_addr = 0;
static int64_t s_scan_start_us = 0;
static cec_device_type_t s_own_device_type = CEC_DEVICE_TYPE_PLAYBACK;

static const char *ADDR_NAMES[16] = {
    "TV", "REC1", "REC2", "TUN1", "PB1", "AUDIO", "TUN2", "TUN3",
    "PB2", "REC3", "TUN4", "PB3", "FREE1", "FREE2", "SPECIFIC", "BROADCAST",
};

static const char *OPCODE_NAMES[256] = {
    [0x00] = "FEATURE_ABORT",
    [0x04] = "IMAGE_VIEW_ON",
    [0x0D] = "TEXT_VIEW_ON",
    [0x32] = "SET_MENU_LANGUAGE",
    [0x36] = "STANDBY",
    [0x44] = "USER_CONTROL_PRESSED",
    [0x45] = "USER_CONTROL_RELEASED",
    [0x46] = "GIVE_OSD_NAME",
    [0x47] = "SET_OSD_NAME",
    [0x80] = "ROUTING_CHANGE",
    [0x82] = "ACTIVE_SOURCE",
    [0x83] = "GIVE_PHYSICAL_ADDR",
    [0x84] = "REPORT_PHYSICAL_ADDR",
    [0x85] = "REQUEST_ACTIVE_SOURCE",
    [0x86] = "SET_STREAM_PATH",
    [0x87] = "DEVICE_VENDOR_ID",
    [0x8F] = "GIVE_DEVICE_POWER_STATUS",
    [0x90] = "REPORT_POWER_STATUS",
    [0xC7] = "VENDOR_ID",
    [0xFF] = "ABORT",
};

void tvs_cec_proto_init(tvs_cec_frame_cb cb)
{
    s_frame_cb = cb;
    tvs_cec_proto_reset();
    ESP_LOGI(TAG, "CEC protocol layer initialized");
}

void tvs_cec_proto_reset(void)
{
    memset(s_devices, 0, sizeof(s_devices));
    for (int i = 0; i < CEC_SCAN_LOGICAL_ADDRS; i++) {
        s_devices[i].logical_addr = (uint8_t)i;
        s_devices[i].physical_addr = 0xFFFF;
        s_devices[i].power_status = -1;
    }
    s_scanning = false;
}

void tvs_cec_proto_process_frame(uint8_t initiator, uint8_t destination,
                                  const uint8_t *body, uint8_t body_len)
{
    if (body_len == 0) {
        if (destination == CEC_ADDR_BROADCAST) {
            ESP_LOGD(TAG, "polling from 0x%X", initiator);
        }
        return;
    }

    uint8_t opcode = body[0];
    ESP_LOGD(TAG, "CEC frame 0x%X -> 0x%X op=0x%02X (%s) len=%u",
             initiator, destination, opcode,
             tvs_cec_opcode_name(opcode), body_len);

    if (initiator >= CEC_SCAN_LOGICAL_ADDRS) {
        return;
    }
    cec_device_info_t *dev = &s_devices[initiator];

    switch (opcode) {
    case CEC_OP_REPORT_PHYSICAL_ADDR:
        if (body_len >= 4) {
            uint16_t pa = ((uint16_t)body[1] << 8) | body[2];
            cec_device_type_t dt = (cec_device_type_t)(body[3] & 0x0F);
            dev->present = true;
            dev->physical_addr = pa;
            dev->device_type = dt;
            ESP_LOGI(TAG, "dev 0x%X PA=0x%04X type=%d %s",
                     initiator, pa, dt, tvs_cec_addr_name(initiator));
        }
        break;

    case CEC_OP_REPORT_POWER_STATUS:
        if (body_len >= 2) {
            dev->present = true;
            dev->power_status = (int8_t)body[1];
            ESP_LOGI(TAG, "dev 0x%X power=%d %s",
                     initiator, body[1], tvs_cec_addr_name(initiator));
        }
        break;

    case CEC_OP_SET_OSD_NAME:
        if (body_len >= 2) {
            uint8_t name_len = body_len - 1;
            if (name_len > 15) name_len = 15;
            memcpy(dev->osd_name, &body[1], name_len);
            dev->osd_name[name_len] = '\0';
            dev->present = true;
            ESP_LOGI(TAG, "dev 0x%X OSD='%s'", initiator, dev->osd_name);
        }
        break;

    case CEC_OP_DEVICE_VENDOR_ID:
        if (body_len >= 4) {
            dev->present = true;
            dev->vendor_id = ((uint32_t)body[1] << 16) |
                             ((uint32_t)body[2] << 8) | body[3];
        }
        break;

    case CEC_OP_GIVE_PHYSICAL_ADDR:
        {
            uint8_t resp[4] = {
                CEC_OP_REPORT_PHYSICAL_ADDR,
                (uint8_t)(CONFIG_TVS_CEC_PHYSICAL_ADDR >> 8),
                (uint8_t)(CONFIG_TVS_CEC_PHYSICAL_ADDR & 0xFF),
                (uint8_t)s_own_device_type,
            };
            tvs_cec_send_frame(CONFIG_TVS_CEC_LOGICAL_ADDR, initiator, resp, 4);
        }
        break;

    case CEC_OP_GIVE_OSD_NAME:
        {
            const char *name = CONFIG_TVS_CEC_OSD_NAME;
            size_t name_len = strlen(name);
            if (name_len > 14) name_len = 14;
            uint8_t resp[16] = {CEC_OP_SET_OSD_NAME};
            memcpy(&resp[1], name, name_len);
            tvs_cec_send_frame(CONFIG_TVS_CEC_LOGICAL_ADDR, initiator, resp, 1 + name_len);
        }
        break;

    case CEC_OP_GIVE_DEVICE_POWER_STATUS:
        {
            uint8_t resp[2] = {CEC_OP_REPORT_POWER_STATUS, CEC_POWER_STATE_ON};
            tvs_cec_send_frame(CONFIG_TVS_CEC_LOGICAL_ADDR, initiator, resp, 2);
        }
        break;

    case CEC_OP_REQUEST_ACTIVE_SOURCE:
        {
            uint8_t resp[3] = {
                CEC_OP_ACTIVE_SOURCE,
                (uint8_t)(CONFIG_TVS_CEC_PHYSICAL_ADDR >> 8),
                (uint8_t)(CONFIG_TVS_CEC_PHYSICAL_ADDR & 0xFF),
            };
            tvs_cec_send_frame(CONFIG_TVS_CEC_LOGICAL_ADDR, CEC_ADDR_BROADCAST, resp, 3);
        }
        break;

    case CEC_OP_ACTIVE_SOURCE:
        if (body_len >= 3) {
            uint16_t pa = ((uint16_t)body[1] << 8) | body[2];
            ESP_LOGI(TAG, "active source PA=0x%04X from 0x%X", pa, initiator);
        }
        break;

    case CEC_OP_STANDBY:
        ESP_LOGI(TAG, "standby from 0x%X (%s)", initiator, tvs_cec_addr_name(initiator));
        break;

    case CEC_OP_FEATURE_ABORT:
        if (body_len >= 2) {
            ESP_LOGW(TAG, "feature abort: op=0x%02X reason=%d",
                     body[1], body_len >= 3 ? body[2] : 0);
        }
        break;

    case CEC_OP_SET_STREAM_PATH:
        if (body_len >= 3) {
            uint16_t pa = ((uint16_t)body[1] << 8) | body[2];
            ESP_LOGI(TAG, "set stream path PA=0x%04X from 0x%X", pa, initiator);
        }
        break;

    default:
        if (opcode <= 0x7F) {
            ESP_LOGD(TAG, "unhandled opcode 0x%02X", opcode);
        }
        break;
    }

    if (s_frame_cb) {
        s_frame_cb(initiator, destination, body, body_len);
    }
}

void tvs_cec_proto_scan_bus(void)
{
    uint8_t self_addr = CONFIG_TVS_CEC_LOGICAL_ADDR;

    ESP_LOGI(TAG, "CEC bus scan starting (self=0x%X %s)",
             self_addr, tvs_cec_addr_name(self_addr));
    tvs_cec_proto_reset();
    s_devices[self_addr].present = true;
    s_devices[self_addr].logical_addr = self_addr;
    s_devices[self_addr].physical_addr = CONFIG_TVS_CEC_PHYSICAL_ADDR;
    s_devices[self_addr].device_type = s_own_device_type;

    s_scanning = true;
    s_scan_start_us = esp_timer_get_time();

    for (uint8_t addr = 0; addr < CEC_ADDR_BROADCAST; addr++) {
        if (addr == self_addr) {
            continue;
        }
        esp_rom_delay_us(5000);

        uint8_t poll_frame[1] = {0};
        esp_err_t err = tvs_cec_send_frame(addr, addr, poll_frame, 0);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "scan: addr 0x%X (%s) ACKed", addr, tvs_cec_addr_name(addr));
            s_devices[addr].present = true;
            s_devices[addr].logical_addr = addr;

            tvs_cec_send_frame(self_addr, addr,
                                (uint8_t[1]){CEC_OP_GIVE_PHYSICAL_ADDR}, 1);
            esp_rom_delay_us(3000);
            tvs_cec_send_frame(self_addr, addr,
                                (uint8_t[1]){CEC_OP_GIVE_OSD_NAME}, 1);
            esp_rom_delay_us(3000);
            tvs_cec_send_frame(self_addr, addr,
                                (uint8_t[1]){CEC_OP_GIVE_DEVICE_POWER_STATUS}, 1);
            esp_rom_delay_us(3000);
        } else {
            s_devices[addr].present = false;
        }
    }

    s_scanning = false;
    int64_t elapsed = (esp_timer_get_time() - s_scan_start_us) / 1000;

    int found = 0;
    for (int i = 0; i < CEC_SCAN_LOGICAL_ADDRS; i++) {
        if (s_devices[i].present) found++;
    }

    ESP_LOGI(TAG, "CEC bus scan complete: %d devices found in %lldms",
             found, (long long)elapsed);
}

bool tvs_cec_proto_is_scanning(void)
{
    return s_scanning;
}

cec_device_info_t *tvs_cec_proto_get_device(uint8_t logical_addr)
{
    if (logical_addr >= CEC_SCAN_LOGICAL_ADDRS) {
        return NULL;
    }
    return &s_devices[logical_addr];
}

int tvs_cec_proto_get_device_count(void)
{
    int count = 0;
    for (int i = 0; i < CEC_SCAN_LOGICAL_ADDRS; i++) {
        if (s_devices[i].present) count++;
    }
    return count;
}

const char *tvs_cec_opcode_name(uint8_t opcode)
{
    const char *name = OPCODE_NAMES[opcode];
    return name ? name : "UNKNOWN";
}

const char *tvs_cec_addr_name(uint8_t addr)
{
    if (addr >= 16) {
        return "INVALID";
    }
    return ADDR_NAMES[addr];
}

bool tvs_cec_proto_is_broadcast(uint8_t destination)
{
    return destination == CEC_ADDR_BROADCAST;
}
