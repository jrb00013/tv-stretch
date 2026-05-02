#include "tvs_nvs.h"
#include "esp_err.h"
#include "nvs.h"

bool tvs_nvs_is_provisioned(void) {
    nvs_handle_t h;
    if (nvs_open("tvstretch", NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    uint8_t v = 0;
    esp_err_t e = nvs_get_u8(h, "provisioned", &v);
    nvs_close(h);
    return (e == ESP_OK && v == 1);
}
