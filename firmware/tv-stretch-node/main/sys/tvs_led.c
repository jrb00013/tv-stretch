#include "sys/tvs_led.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "tvs_led";

static gpio_num_t s_led_pin = GPIO_NUM_NC;
static tvs_led_pattern_t s_pattern = TVS_LED_PATTERN_OFF;
static TaskHandle_t s_led_task = NULL;

static void led_task(void *arg)
{
    (void)arg;
    while (1) {
        switch (s_pattern) {
        case TVS_LED_PATTERN_OFF:
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case TVS_LED_PATTERN_BOOT:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(200));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(200));
            break;

        case TVS_LED_PATTERN_CONNECTING:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(50));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(950));
            break;

        case TVS_LED_PATTERN_CONNECTED:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(2900));
            break;

        case TVS_LED_PATTERN_COMMAND:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(40));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(60));
            break;

        case TVS_LED_PATTERN_ERROR:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case TVS_LED_PATTERN_OTA:
            gpio_set_level(s_led_pin, 1);
            vTaskDelay(pdMS_TO_TICKS(500));
            gpio_set_level(s_led_pin, 0);
            vTaskDelay(pdMS_TO_TICKS(500));
            break;
        }
    }
}

esp_err_t tvs_led_init(gpio_num_t pin)
{
    s_led_pin = pin;
    gpio_reset_pin(pin);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, 0);

    if (s_led_task == NULL) {
        xTaskCreate(led_task, "tvs_led", 2048, NULL, 1, &s_led_task);
    }

    ESP_LOGI(TAG, "LED on GPIO %d", (int)pin);
    return ESP_OK;
}

void tvs_led_set_pattern(tvs_led_pattern_t pattern)
{
    if (pattern != s_pattern) {
        ESP_LOGD(TAG, "LED pattern %d -> %d", s_pattern, pattern);
        s_pattern = pattern;
    }
}

void tvs_led_pulse(void)
{
    tvs_led_set_pattern(TVS_LED_PATTERN_COMMAND);
}
