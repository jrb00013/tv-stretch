#include "sys/tvs_watchdog.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "tvs_wdt";

#define MAX_WDT_TASKS 8

typedef struct {
    TaskHandle_t task;
    char name[16];
    bool subscribed;
    uint32_t timeout_ms;
} wdt_task_entry_t;

static bool s_initialized = false;
static uint32_t s_global_timeout_ms = 30000;
static wdt_task_entry_t s_tasks[MAX_WDT_TASKS];
static int s_task_count = 0;
static uint32_t s_feed_count = 0;
static uint32_t s_timeout_count = 0;

esp_err_t tvs_watchdog_init(uint32_t timeout_sec)
{
    if (s_initialized) {
        return ESP_OK;
    }

    s_global_timeout_ms = timeout_sec * 1000;
    memset(s_tasks, 0, sizeof(s_tasks));
    s_task_count = 0;
    s_feed_count = 0;

    esp_task_wdt_config_t cfg = {
        .timeout_ms = s_global_timeout_ms,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };

    esp_err_t err = esp_task_wdt_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WDT init failed: %s", esp_err_to_name(err));
        return err;
    }

    err = esp_task_wdt_add(NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WDT add current task failed: %s", esp_err_to_name(err));
        return err;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "watchdog initialized, timeout=%ums", s_global_timeout_ms);
    return ESP_OK;
}

esp_err_t tvs_watchdog_add_task(TaskHandle_t task, const char *name, uint32_t timeout_ms)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_task_count >= MAX_WDT_TASKS) {
        ESP_LOGE(TAG, "max WDT tasks reached");
        return ESP_ERR_NO_MEM;
    }

    esp_err_t err = esp_task_wdt_add(task);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "WDT add task %s failed: %s", name, esp_err_to_name(err));
        return err;
    }

    if (timeout_ms > 0 && timeout_ms != s_global_timeout_ms) {
        esp_task_wdt_status_t status;
        if (esp_task_wdt_status(task, &status) == ESP_OK) {
            esp_task_wdt_delete(task);
            esp_task_wdt_config_t cfg = {
                .timeout_ms = timeout_ms,
                .idle_core_mask = 0,
                .trigger_panic = true,
            };
            esp_task_wdt_init(&cfg);
            esp_task_wdt_add(task);
            esp_task_wdt_add(NULL);
            s_global_timeout_ms = timeout_ms;
        }
    }

    wdt_task_entry_t *entry = &s_tasks[s_task_count++];
    entry->task = task;
    entry->timeout_ms = timeout_ms > 0 ? timeout_ms : s_global_timeout_ms;
    entry->subscribed = true;
    strncpy(entry->name, name, sizeof(entry->name) - 1);
    entry->name[sizeof(entry->name) - 1] = '\0';

    ESP_LOGD(TAG, "WDT subscribed: %s (timeout=%ums)", entry->name, entry->timeout_ms);
    return ESP_OK;
}

esp_err_t tvs_watchdog_remove_task(TaskHandle_t task)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }

    for (int i = 0; i < s_task_count; i++) {
        if (s_tasks[i].task == task) {
            esp_task_wdt_delete(task);
            s_tasks[i] = s_tasks[--s_task_count];
            ESP_LOGD(TAG, "WDT unsubscribed: %s", s_tasks[i].name);
            return ESP_OK;
        }
    }
    return ESP_ERR_NOT_FOUND;
}

void tvs_watchdog_feed(void)
{
    if (s_initialized) {
        esp_task_wdt_reset();
        s_feed_count++;
    }
}

void tvs_watchdog_feed_task(TaskHandle_t task)
{
    if (s_initialized) {
        esp_task_wdt_reset();
    }
}

void tvs_watchdog_disable(void)
{
    if (s_initialized) {
        for (int i = 0; i < s_task_count; i++) {
            esp_task_wdt_delete(s_tasks[i].task);
        }
        s_task_count = 0;
        esp_task_wdt_deinit();
        s_initialized = false;
        ESP_LOGW(TAG, "watchdog disabled (fed %lu times)", (unsigned long)s_feed_count);
    }
}

bool tvs_watchdog_is_enabled(void)
{
    return s_initialized;
}

uint32_t tvs_watchdog_feed_count(void)
{
    return s_feed_count;
}
