#include "core/tvs_cmd_queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include <string.h>

static const char *TAG = "tvs_cmdq";

static tvs_cmd_entry_t s_queue[TVS_CMD_QUEUE_SIZE];
static uint32_t s_head = 0;
static uint32_t s_tail = 0;
static uint32_t s_count = 0;
static tvs_cmd_complete_cb s_complete_cb = NULL;

static const char *STATUS_NAMES[] = {
    "PENDING",
    "IN_FLIGHT",
    "ACKED",
    "FAILED",
    "SKIPPED",
};

static uint32_t next_slot(uint32_t idx)
{
    return (idx + 1) % TVS_CMD_QUEUE_SIZE;
}

void tvs_cmd_queue_init(tvs_cmd_complete_cb cb)
{
    s_head = 0;
    s_tail = 0;
    s_count = 0;
    s_complete_cb = cb;
    memset(s_queue, 0, sizeof(s_queue));
    ESP_LOGI(TAG, "command queue initialized (size=%d)", TVS_CMD_QUEUE_SIZE);
}

bool tvs_cmd_enqueue(const char *batch_id, const char *cmd, const char *payload_json)
{
    if (s_count >= TVS_CMD_QUEUE_SIZE) {
        ESP_LOGW(TAG, "queue full, cannot enqueue %s/%s", batch_id, cmd);
        return false;
    }
    tvs_cmd_entry_t *e = &s_queue[s_head];
    e->status = TVS_CMD_STATUS_PENDING;
    e->retries_remaining = TVS_CMD_DEFAULT_RETRIES;
    e->max_retries = TVS_CMD_DEFAULT_RETRIES;
    e->enqueued_ms = (uint32_t)(esp_timer_get_time() / 1000);
    e->last_attempt_ms = 0;
    strncpy(e->batch_id, batch_id, sizeof(e->batch_id) - 1);
    strncpy(e->cmd, cmd, sizeof(e->cmd) - 1);
    if (payload_json) {
        strncpy(e->payload_json, payload_json, sizeof(e->payload_json) - 1);
    } else {
        e->payload_json[0] = '\0';
    }
    s_head = next_slot(s_head);
    s_count++;
    ESP_LOGD(TAG, "enqueued %s/%s (depth=%u)", batch_id, cmd, s_count);
    return true;
}

bool tvs_cmd_dequeue(tvs_cmd_entry_t *entry)
{
    if (s_count == 0) {
        return false;
    }
    uint32_t idx = s_tail;
    uint32_t checked = 0;
    while (checked < TVS_CMD_QUEUE_SIZE) {
        tvs_cmd_entry_t *e = &s_queue[idx];
        if (e->status == TVS_CMD_STATUS_PENDING) {
            memcpy(entry, e, sizeof(tvs_cmd_entry_t));
            e->status = TVS_CMD_STATUS_IN_FLIGHT;
            e->last_attempt_ms = (uint32_t)(esp_timer_get_time() / 1000);
            return true;
        }
        idx = next_slot(idx);
        checked++;
    }
    return false;
}

void tvs_cmd_ack(const char *batch_id, const char *cmd)
{
    for (uint32_t i = 0; i < TVS_CMD_QUEUE_SIZE; i++) {
        tvs_cmd_entry_t *e = &s_queue[i];
        if (e->status == TVS_CMD_STATUS_IN_FLIGHT &&
            strncmp(e->batch_id, batch_id, sizeof(e->batch_id)) == 0 &&
            strncmp(e->cmd, cmd, sizeof(e->cmd)) == 0) {
            e->status = TVS_CMD_STATUS_ACKED;
            s_tail = next_slot(s_tail);
            s_count--;
            ESP_LOGD(TAG, "acked %s/%s", batch_id, cmd);
            if (s_complete_cb) {
                s_complete_cb(batch_id, cmd, true);
            }
            return;
        }
    }
}

void tvs_cmd_nack(const char *batch_id, const char *cmd)
{
    for (uint32_t i = 0; i < TVS_CMD_QUEUE_SIZE; i++) {
        tvs_cmd_entry_t *e = &s_queue[i];
        if (e->status == TVS_CMD_STATUS_IN_FLIGHT &&
            strncmp(e->batch_id, batch_id, sizeof(e->batch_id)) == 0 &&
            strncmp(e->cmd, cmd, sizeof(e->cmd)) == 0) {
            if (e->retries_remaining > 0) {
                e->retries_remaining--;
                e->status = TVS_CMD_STATUS_PENDING;
                ESP_LOGW(TAG, "nack %s/%s, %u retries left", batch_id, cmd, e->retries_remaining);
            } else {
                e->status = TVS_CMD_STATUS_FAILED;
                s_tail = next_slot(s_tail);
                s_count--;
                ESP_LOGE(TAG, "failed %s/%s (no retries left)", batch_id, cmd);
                if (s_complete_cb) {
                    s_complete_cb(batch_id, cmd, false);
                }
            }
            return;
        }
    }
}

void tvs_cmd_retry(tvs_cmd_entry_t *entry)
{
    for (uint32_t i = 0; i < TVS_CMD_QUEUE_SIZE; i++) {
        tvs_cmd_entry_t *e = &s_queue[i];
        if (strncmp(e->batch_id, entry->batch_id, sizeof(e->batch_id)) == 0 &&
            strncmp(e->cmd, entry->cmd, sizeof(e->cmd)) == 0) {
            if (e->retries_remaining > 0) {
                e->retries_remaining--;
                e->status = TVS_CMD_STATUS_PENDING;
                ESP_LOGW(TAG, "retrying %s/%s, %u left", entry->batch_id, entry->cmd, e->retries_remaining);
            } else {
                e->status = TVS_CMD_STATUS_FAILED;
                s_tail = next_slot(s_tail);
                s_count--;
                ESP_LOGE(TAG, "retries exhausted %s/%s", entry->batch_id, entry->cmd);
                if (s_complete_cb) {
                    s_complete_cb(entry->batch_id, entry->cmd, false);
                }
            }
            return;
        }
    }
}

uint32_t tvs_cmd_queue_depth(void)
{
    return s_count;
}

uint32_t tvs_cmd_pending_count(void)
{
    uint32_t pending = 0;
    for (uint32_t i = 0; i < TVS_CMD_QUEUE_SIZE; i++) {
        if (s_queue[i].status == TVS_CMD_STATUS_PENDING ||
            s_queue[i].status == TVS_CMD_STATUS_IN_FLIGHT) {
            pending++;
        }
    }
    return pending;
}

void tvs_cmd_queue_clear(void)
{
    s_head = 0;
    s_tail = 0;
    s_count = 0;
    memset(s_queue, 0, sizeof(s_queue));
    ESP_LOGW(TAG, "command queue cleared");
}

void tvs_cmd_dump(void)
{
    ESP_LOGI(TAG, "--- cmd queue dump (count=%lu) ---", (unsigned long)s_count);
    for (uint32_t i = 0; i < TVS_CMD_QUEUE_SIZE; i++) {
        tvs_cmd_entry_t *e = &s_queue[i];
        if (e->cmd[0] != '\0') {
            ESP_LOGI(TAG, "  [%lu] %s/%s status=%s retries=%u",
                     (unsigned long)i,
                     e->batch_id, e->cmd,
                     STATUS_NAMES[e->status],
                     (unsigned)e->retries_remaining);
        }
    }
}
