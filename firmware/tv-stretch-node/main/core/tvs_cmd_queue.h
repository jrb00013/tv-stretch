#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TVS_CMD_QUEUE_SIZE 16
#define TVS_CMD_NAME_LEN 32
#define TVS_CMD_PAYLOAD_LEN 256
#define TVS_CMD_DEFAULT_RETRIES 3

typedef enum {
    TVS_CMD_STATUS_PENDING = 0,
    TVS_CMD_STATUS_IN_FLIGHT,
    TVS_CMD_STATUS_ACKED,
    TVS_CMD_STATUS_FAILED,
    TVS_CMD_STATUS_SKIPPED,
} tvs_cmd_status_t;

typedef struct {
    char cmd[TVS_CMD_NAME_LEN];
    char payload_json[TVS_CMD_PAYLOAD_LEN];
    char batch_id[48];
    uint8_t retries_remaining;
    uint8_t max_retries;
    tvs_cmd_status_t status;
    uint32_t enqueued_ms;
    uint32_t last_attempt_ms;
} tvs_cmd_entry_t;

typedef void (*tvs_cmd_complete_cb)(const char *batch_id, const char *cmd, bool ok);

void tvs_cmd_queue_init(tvs_cmd_complete_cb cb);
bool tvs_cmd_enqueue(const char *batch_id, const char *cmd, const char *payload_json);
bool tvs_cmd_dequeue(tvs_cmd_entry_t *entry);
void tvs_cmd_ack(const char *batch_id, const char *cmd);
void tvs_cmd_nack(const char *batch_id, const char *cmd);
void tvs_cmd_retry(tvs_cmd_entry_t *entry);
uint32_t tvs_cmd_queue_depth(void);
uint32_t tvs_cmd_pending_count(void);
void tvs_cmd_queue_clear(void);
void tvs_cmd_dump(void);

#ifdef __cplusplus
}
#endif
