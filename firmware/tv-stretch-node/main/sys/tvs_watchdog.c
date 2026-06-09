#include "sys/tvs_watchdog.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "tvs_wdt";

static bool s_initialized = false;

esp_err_t tvs_watchdog_init(uint32_t timeout_sec)
{
    if (s_initialized) {
        return ESP_OK;
    }

    esp_task_wdt_config_t cfg = {
        .timeout_ms = timeout_sec * 1000,
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
    ESP_LOGI(TAG, "watchdog initialized, timeout=%us", timeout_sec);
    return ESP_OK;
}

void tvs_watchdog_feed(void)
{
    if (s_initialized) {
        esp_task_wdt_reset();
    }
}

void tvs_watchdog_disable(void)
{
    if (s_initialized) {
        esp_task_wdt_delete(NULL);
        esp_task_wdt_deinit();
        s_initialized = false;
        ESP_LOGW(TAG, "watchdog disabled");
    }
}
