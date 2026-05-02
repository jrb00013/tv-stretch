#include "cec_bitbang.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include <string.h>

static const char *TAG = "tvs_cec";

static gpio_num_t s_cec_pin = GPIO_NUM_NC;

/* Standard CEC data bit timings (microseconds), see HDMI 1.4b CEC overview. */
#define US_LOW_0 1500
#define US_HIGH_0 900
#define US_LOW_1 600
#define US_HIGH_1 600
#define US_START_LOW 3700
#define US_START_HIGH 800

static inline void cec_drive_low(void) {
    gpio_set_level(s_cec_pin, 0);
}

static inline void cec_release(void) {
    gpio_set_level(s_cec_pin, 1);
}

static inline void cec_data_bit(bool one) {
    if (one) {
        cec_drive_low();
        esp_rom_delay_us(US_LOW_1);
        cec_release();
        esp_rom_delay_us(US_HIGH_1);
    } else {
        cec_drive_low();
        esp_rom_delay_us(US_LOW_0);
        cec_release();
        esp_rom_delay_us(US_HIGH_0);
    }
}

static void cec_start_bit(void) {
    cec_drive_low();
    esp_rom_delay_us(US_START_LOW);
    cec_release();
    esp_rom_delay_us(US_START_HIGH);
}

esp_err_t tvs_cec_init(gpio_num_t pin) {
    s_cec_pin = pin;
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&io);
    if (err != ESP_OK) {
        return err;
    }
    cec_release();
    ESP_LOGI(TAG, "CEC on GPIO %d", (int)pin);
    return ESP_OK;
}

esp_err_t tvs_cec_send_byte(uint8_t byte, bool eom) {
    if (s_cec_pin == GPIO_NUM_NC) {
        return ESP_ERR_INVALID_STATE;
    }
    for (int i = 0; i < 8; i++) {
        bool bit = (byte >> i) & 1;
        cec_data_bit(bit);
    }
    cec_data_bit(eom);
    /* ACK slot: follower pulls low; we release and sample (simplified: delay). */
    cec_release();
    esp_rom_delay_us(400);
    return ESP_OK;
}

esp_err_t tvs_cec_send_frame(uint8_t initiator, uint8_t destination, const uint8_t *data,
                             size_t data_len) {
    if (s_cec_pin == GPIO_NUM_NC) {
        return ESP_ERR_INVALID_STATE;
    }
    cec_start_bit();
    uint8_t header = (initiator << 4) | (destination & 0x0F);
    ESP_LOGI(TAG, "CEC TX hdr 0x%02X + %u bytes", header, (unsigned)data_len);
    tvs_cec_send_byte(header, data_len == 0);
    for (size_t i = 0; i < data_len; i++) {
        bool eom = (i == data_len - 1);
        tvs_cec_send_byte(data[i], eom);
    }
    return ESP_OK;
}
