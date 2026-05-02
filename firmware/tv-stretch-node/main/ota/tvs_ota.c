#include "tvs_ota.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include <cJSON.h>
#include <string.h>

static const char *TAG = "tvs_ota";

esp_err_t tvs_ota_apply_from_url(const char *firmware_url) {
    if (!firmware_url || !firmware_url[0]) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_LOGW(TAG, "Starting OTA from %s", firmware_url);

    esp_http_client_config_t http_cfg = {
        .url = firmware_url,
        .timeout_ms = 120000,
        .keep_alive_enable = true,
    };
    esp_https_ota_config_t ota_cfg = {
        .http_config = &http_cfg,
    };
    esp_err_t ret = esp_https_ota(&ota_cfg);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA success, restarting");
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    }
    ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(ret));
    return ret;
}

static esp_err_t http_get_small(const char *url, char *out, size_t out_sz) {
    if (!url || !out || out_sz < 8) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_http_client_config_t cfg = {
        .url = url,
        .timeout_ms = 30000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        return ESP_FAIL;
    }
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        return err;
    }
    (void)esp_http_client_fetch_headers(client);
    size_t total = 0;
    err = ESP_OK;
    while (total < out_sz - 1) {
        int r = esp_http_client_read(client, out + total, (int)(out_sz - 1 - total));
        if (r < 0) {
            err = ESP_FAIL;
            break;
        }
        if (r == 0) {
            break;
        }
        total += (size_t)r;
    }
    out[total] = 0;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}

esp_err_t tvs_ota_apply_from_manifest_url(const char *manifest_url, bool only_if_version_differs) {
    char buf[512];
    esp_err_t err = http_get_small(manifest_url, buf, sizeof(buf));
    if (err != ESP_OK) {
        return err;
    }
    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        return ESP_FAIL;
    }
    cJSON *ver = cJSON_GetObjectItem(root, "version");
    cJSON *url = cJSON_GetObjectItem(root, "url");
    if (!cJSON_IsString(url) || url->valuestring == NULL) {
        cJSON_Delete(root);
        return ESP_FAIL;
    }
    if (only_if_version_differs && cJSON_IsString(ver) && ver->valuestring) {
        if (strcmp(ver->valuestring, CONFIG_TVS_FW_VERSION) == 0) {
            ESP_LOGI(TAG, "Manifest version matches running (%s), skip", CONFIG_TVS_FW_VERSION);
            cJSON_Delete(root);
            return ESP_OK;
        }
    }
    const char *fw = url->valuestring;
    cJSON_Delete(root);
    return tvs_ota_apply_from_url(fw);
}
