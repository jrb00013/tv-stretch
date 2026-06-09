#include "sys/tvs_led.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/ledc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "tvs_led";

static gpio_num_t s_led_pin = GPIO_NUM_NC;
static tvs_led_pattern_t s_pattern = TVS_LED_PATTERN_OFF;
static tvs_led_pattern_t s_cmd_restore = TVS_LED_PATTERN_OFF;
static TaskHandle_t s_led_task = NULL;

#define LEDC_TIMER      LEDC_TIMER_0
#define LEDC_CHANNEL    LEDC_CHANNEL_0
#define LEDC_MODE       LEDC_LOW_SPEED_MODE
#define LEDC_DUTY_RES   LEDC_TIMER_8_BIT
#define LEDC_FREQ_HZ    5000

#define CMD_FLASH_BRIGHTNESS 255
#define CMD_FLASH_DURATION_MS 60

static const uint8_t PATTERN_BRIGHTNESS[TVS_LED_PATTERN_COUNT] = {
    [TVS_LED_PATTERN_OFF]        = 0,
    [TVS_LED_PATTERN_BOOT]       = 80,
    [TVS_LED_PATTERN_CONNECTING] = 40,
    [TVS_LED_PATTERN_CONNECTED]  = 20,
    [TVS_LED_PATTERN_COMMAND]    = 255,
    [TVS_LED_PATTERN_ERROR]      = 255,
    [TVS_LED_PATTERN_OTA]        = 255,
};

static inline void ledc_set_duty_brightness(uint8_t brightness)
{
    uint32_t duty = (brightness * brightness) / 255;
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, duty);
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

static void led_fade_to(uint8_t target_brightness, uint32_t duration_ms)
{
    uint32_t current = ledc_get_duty(LEDC_MODE, LEDC_CHANNEL);
    uint32_t target = (target_brightness * target_brightness) / 255;
    if (current == target) {
        return;
    }
    uint32_t steps = duration_ms / 10;
    if (steps < 2) steps = 2;
    int32_t delta = ((int32_t)target - (int32_t)current);
    int32_t step_size = delta / (int32_t)steps;
    if (step_size == 0) {
        step_size = (delta > 0) ? 1 : -1;
    }
    for (uint32_t i = 0; i < steps; i++) {
        current += step_size;
        if ((step_size > 0 && current > target) ||
            (step_size < 0 && current < target)) {
            current = target;
        }
        ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, current);
        ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, target);
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

static void led_task(void *arg)
{
    (void)arg;

    ledc_set_duty_brightness(0);

    while (1) {
        tvs_led_pattern_t current = s_pattern;

        switch (current) {
        case TVS_LED_PATTERN_OFF:
            led_fade_to(0, 100);
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case TVS_LED_PATTERN_BOOT:
            led_fade_to(PATTERN_BRIGHTNESS[TVS_LED_PATTERN_BOOT], 150);
            vTaskDelay(pdMS_TO_TICKS(200));
            led_fade_to(0, 150);
            vTaskDelay(pdMS_TO_TICKS(200));
            break;

        case TVS_LED_PATTERN_CONNECTING:
            led_fade_to(PATTERN_BRIGHTNESS[TVS_LED_PATTERN_CONNECTING], 100);
            vTaskDelay(pdMS_TO_TICKS(80));
            led_fade_to(0, 300);
            vTaskDelay(pdMS_TO_TICKS(800));
            break;

        case TVS_LED_PATTERN_CONNECTED:
            led_fade_to(PATTERN_BRIGHTNESS[TVS_LED_PATTERN_CONNECTED], 300);
            vTaskDelay(pdMS_TO_TICKS(200));
            led_fade_to(0, 500);
            vTaskDelay(pdMS_TO_TICKS(2500));
            break;

        case TVS_LED_PATTERN_COMMAND:
            ledc_set_duty_brightness(CMD_FLASH_BRIGHTNESS);
            vTaskDelay(pdMS_TO_TICKS(CMD_FLASH_DURATION_MS));
            ledc_set_duty_brightness(0);
            s_pattern = s_cmd_restore;
            break;

        case TVS_LED_PATTERN_ERROR:
            ledc_set_duty_brightness(PATTERN_BRIGHTNESS[TVS_LED_PATTERN_ERROR]);
            vTaskDelay(pdMS_TO_TICKS(100));
            ledc_set_duty_brightness(0);
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case TVS_LED_PATTERN_OTA:
            ledc_set_duty_brightness(PATTERN_BRIGHTNESS[TVS_LED_PATTERN_OTA]);
            vTaskDelay(pdMS_TO_TICKS(500));
            ledc_set_duty_brightness(0);
            vTaskDelay(pdMS_TO_TICKS(500));
            break;

        default:
            vTaskDelay(pdMS_TO_TICKS(100));
            break;
        }
    }
}

esp_err_t tvs_led_init(gpio_num_t pin)
{
    s_led_pin = pin;

    ledc_timer_config_t timer_cfg = {
        .speed_mode = LEDC_MODE,
        .duty_resolution = LEDC_DUTY_RES,
        .timer_num = LEDC_TIMER,
        .freq_hz = LEDC_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "LEDC timer config failed: %s", esp_err_to_name(err));
        return err;
    }

    ledc_channel_config_t ch_cfg = {
        .gpio_num = pin,
        .speed_mode = LEDC_MODE,
        .channel = LEDC_CHANNEL,
        .timer_sel = LEDC_TIMER,
        .duty = 0,
        .hpoint = 0,
    };
    err = ledc_channel_config(&ch_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "LEDC channel config failed: %s", esp_err_to_name(err));
        return err;
    }

    if (s_led_task == NULL) {
        xTaskCreate(led_task, "tvs_led", 2048, NULL, 1, &s_led_task);
    }

    ESP_LOGI(TAG, "LED PWM on GPIO %d", (int)pin);
    return ESP_OK;
}

void tvs_led_set_pattern(tvs_led_pattern_t pattern)
{
    if (pattern == TVS_LED_PATTERN_COMMAND) {
        s_cmd_restore = s_pattern;
    }
    if (pattern != s_pattern) {
        ESP_LOGD(TAG, "LED pattern %d -> %d", s_pattern, pattern);
        s_pattern = pattern;
    }
}

void tvs_led_pulse(void)
{
    tvs_led_set_pattern(TVS_LED_PATTERN_COMMAND);
}
