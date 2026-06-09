#include "cec/cec_rx.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "tvs_cec_rx";

static gpio_num_t s_rx_pin = GPIO_NUM_NC;
static tvs_cec_rx_cb s_rx_cb = NULL;
static volatile bool s_rx_active = false;
static volatile bool s_tx_active = false;
static volatile uint32_t s_frame_count = 0;
static volatile uint32_t s_error_count = 0;

static cec_edge_t s_ring[CEC_RX_RING_SIZE];
static volatile uint32_t s_ring_head = 0;
static volatile uint32_t s_ring_tail = 0;

static TaskHandle_t s_decode_task = NULL;

#define IN_RANGE(min, max, val)  ((val) >= (min) && (val) <= (max))

#define START_BIT_LOW_MIN  3000
#define START_BIT_LOW_MAX  4500
#define START_BIT_HIGH_MIN  400
#define START_BIT_HIGH_MAX 1200

#define BIT_0_LOW_MIN  1000
#define BIT_0_LOW_MAX  2000
#define BIT_0_HIGH_MIN  400
#define BIT_0_HIGH_MAX 1400

#define BIT_1_LOW_MIN   350
#define BIT_1_LOW_MAX   950
#define BIT_1_HIGH_MIN  350
#define BIT_1_HIGH_MAX  950

#define ACK_LOW_MIN  600
#define ACK_LOW_MAX 2000

#define FRAME_IDLE_TIMEOUT_US 5000
#define DEBOUNCE_SKIP_US 20

static bool ring_push(int64_t ts, uint8_t level)
{
    uint32_t next = (s_ring_head + 1) % CEC_RX_RING_SIZE;
    if (next == s_ring_tail) {
        return false;
    }
    s_ring[s_ring_head].timestamp_us = ts;
    s_ring[s_ring_head].level = level;
    s_ring_head = next;
    return true;
}

static bool ring_pop(int64_t *ts, uint8_t *level)
{
    if (s_ring_tail == s_ring_head) {
        return false;
    }
    *ts = s_ring[s_ring_tail].timestamp_us;
    *level = s_ring[s_ring_tail].level;
    s_ring_tail = (s_ring_tail + 1) % CEC_RX_RING_SIZE;
    return true;
}

static void IRAM_ATTR cec_isr_handler(void *arg)
{
    (void)arg;
    if (s_tx_active) {
        return;
    }
    int64_t now = esp_timer_get_time();
    uint8_t level = (uint8_t)gpio_get_level(s_rx_pin);
    ring_push(now, level);
}

static int decode_bit(int64_t low_us, int64_t high_us)
{
    if (IN_RANGE(START_BIT_LOW_MIN, START_BIT_LOW_MAX, low_us) &&
        IN_RANGE(START_BIT_HIGH_MIN, START_BIT_HIGH_MAX, high_us)) {
        return 2;
    }
    if (IN_RANGE(BIT_0_LOW_MIN, BIT_0_LOW_MAX, low_us) &&
        IN_RANGE(BIT_0_HIGH_MIN, BIT_0_HIGH_MAX, high_us)) {
        return 0;
    }
    if (IN_RANGE(BIT_1_LOW_MIN, BIT_1_LOW_MAX, low_us) &&
        IN_RANGE(BIT_1_HIGH_MIN, BIT_1_HIGH_MAX, high_us)) {
        return 1;
    }
    return -1;
}

static void dispatch_frame(const uint8_t *buf, uint8_t len)
{
    if (len < 1 || !s_rx_cb || s_tx_active) {
        return;
    }
    uint8_t header = buf[0];
    uint8_t initiator = (header >> 4) & 0x0F;
    uint8_t dest = header & 0x0F;
    s_rx_cb(initiator, dest, len > 1 ? &buf[1] : NULL, len > 1 ? len - 1 : 0);
    s_frame_count++;
}

static void decode_frame_task(void *arg)
{
    (void)arg;
    int64_t prev_ts = 0;
    uint8_t prev_level = 0;

    bool in_frame = false;
    int64_t low_stored = 0;
    bool have_low = false;
    bool start_bit_seen = false;

    uint8_t frame_buf[CEC_RX_FRAME_MAX];
    uint8_t frame_len = 0;
    uint8_t current_byte = 0;
    uint8_t bits_collected = 0;
    bool eom = false;

    while (1) {
        int64_t ts;
        uint8_t level;
        while (ring_pop(&ts, &level)) {
            if (level == prev_level) {
                continue;
            }
            if (ts - prev_ts < DEBOUNCE_SKIP_US) {
                continue;
            }

            if (level == 1) {
                int64_t low_us = ts - prev_ts;

                if (!in_frame) {
                    if (IN_RANGE(START_BIT_LOW_MIN, START_BIT_LOW_MAX, low_us)) {
                        in_frame = true;
                        start_bit_seen = true;
                        have_low = false;
                        frame_len = 0;
                        current_byte = 0;
                        bits_collected = 0;
                        eom = false;
                    }
                } else {
                    if (start_bit_seen) {
                        start_bit_seen = false;
                        have_low = false;
                    } else {
                        low_stored = low_us;
                        have_low = true;
                    }
                }
                prev_ts = ts;
                prev_level = level;
                continue;
            }

            if (level == 0) {
                int64_t high_us = ts - prev_ts;

                if (!in_frame) {
                    prev_ts = ts;
                    prev_level = level;
                    continue;
                }

                if (start_bit_seen) {
                    if (!IN_RANGE(START_BIT_HIGH_MIN, START_BIT_HIGH_MAX, high_us)) {
                        s_error_count++;
                        in_frame = false;
                    }
                    start_bit_seen = false;
                    have_low = false;
                    prev_ts = ts;
                    prev_level = level;
                    continue;
                }

                if (!have_low) {
                    s_error_count++;
                    in_frame = false;
                    prev_ts = ts;
                    prev_level = level;
                    continue;
                }

                int bit = decode_bit(low_stored, high_us);
                have_low = false;

                if (bit == 2) {
                    if (frame_len > 0) {
                        ESP_LOGD(TAG, "frame aborted by new start, len=%d", frame_len);
                    }
                    in_frame = true;
                    start_bit_seen = true;
                    frame_len = 0;
                    current_byte = 0;
                    bits_collected = 0;
                    eom = false;
                    prev_ts = ts;
                    prev_level = level;
                    continue;
                }

                if (bit < 0) {
                    if (bits_collected == 9 &&
                        IN_RANGE(ACK_LOW_MIN, ACK_LOW_MAX, low_stored)) {
                        if (frame_len < CEC_RX_FRAME_MAX) {
                            frame_buf[frame_len++] = current_byte;
                        }
                        current_byte = 0;
                        bits_collected = 0;
                        if (eom) {
                            dispatch_frame(frame_buf, frame_len);
                            in_frame = false;
                        }
                        prev_ts = ts;
                        prev_level = level;
                        continue;
                    }
                    s_error_count++;
                    in_frame = false;
                    prev_ts = ts;
                    prev_level = level;
                    continue;
                }

                bits_collected++;
                if (bits_collected <= 8) {
                    current_byte |= (uint8_t)(bit << (bits_collected - 1));
                } else if (bits_collected == 9) {
                    eom = (bit == 1);
                } else {
                    if (frame_len < CEC_RX_FRAME_MAX) {
                        frame_buf[frame_len++] = current_byte;
                    }
                    current_byte = 0;
                    bits_collected = 0;
                    if (eom) {
                        dispatch_frame(frame_buf, frame_len);
                        in_frame = false;
                    }
                }

                prev_ts = ts;
                prev_level = level;
                continue;
            }
        }

        if (in_frame) {
            int64_t idle = esp_timer_get_time() - prev_ts;
            if (idle > FRAME_IDLE_TIMEOUT_US) {
                if (frame_len > 0 || bits_collected > 0) {
                    ESP_LOGD(TAG, "frame timeout after %d bytes, %d bits", frame_len, bits_collected);
                    s_error_count++;
                }
                in_frame = false;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

esp_err_t tvs_cec_rx_init(gpio_num_t pin)
{
    s_rx_pin = pin;

    gpio_config_t io = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_ANYEDGE,
    };
    esp_err_t err = gpio_config(&io);
    if (err != ESP_OK) {
        return err;
    }

    err = gpio_install_isr_service(0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    err = gpio_isr_handler_add(pin, cec_isr_handler, NULL);
    if (err != ESP_OK) {
        return err;
    }

    gpio_set_intr_type(pin, GPIO_INTR_DISABLE);

    ESP_LOGI(TAG, "CEC RX on GPIO %d", (int)pin);
    return ESP_OK;
}

void tvs_cec_rx_set_callback(tvs_cec_rx_cb cb)
{
    s_rx_cb = cb;
}

void tvs_cec_rx_start(void)
{
    if (s_rx_active) {
        return;
    }
    s_rx_active = true;
    s_frame_count = 0;
    s_error_count = 0;

    s_ring_head = 0;
    s_ring_tail = 0;

    gpio_set_intr_type(s_rx_pin, GPIO_INTR_ANYEDGE);
    gpio_intr_enable(s_rx_pin);

    if (s_decode_task == NULL) {
        xTaskCreate(decode_frame_task, "cec_rx", 4096, NULL, 8, &s_decode_task);
    }
    ESP_LOGI(TAG, "CEC RX started");
}

void tvs_cec_rx_stop(void)
{
    gpio_intr_disable(s_rx_pin);
    s_rx_active = false;
    ESP_LOGI(TAG, "CEC RX stopped");
}

void tvs_cec_rx_set_tx_active(bool active)
{
    s_tx_active = active;
}

uint32_t tvs_cec_rx_frame_count(void)
{
    return s_frame_count;
}

uint32_t tvs_cec_rx_error_count(void)
{
    return s_error_count;
}

void tvs_cec_rx_reset_counts(void)
{
    s_frame_count = 0;
    s_error_count = 0;
}
