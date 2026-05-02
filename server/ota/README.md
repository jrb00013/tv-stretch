# OTA artifacts (optional)

Place a built ESP-IDF binary here (e.g. copy `build/tv-stretch-node.bin` after `idf.py build`) and point the server at it:

```bash
export TV_STRETCH_OTA_FIRMWARE_PATH="$PWD/server/ota/tv-stretch-node.bin"
export TV_STRETCH_OTA_FIRMWARE_VERSION="0.3.0"
export TV_STRETCH_PUBLIC_BASE_URL="http://192.168.1.10:8000"
```

- `GET /ota/manifest` returns JSON with `version` and `url` for devices.
- `GET /ota/firmware.bin` streams the file.

Devices can pull via coordinator command:

```json
{"cmd":"ota_pull","payload":{"manifest_url":"http://192.168.1.10:8000/ota/manifest","only_if_version_differs":true}}
```

or direct URL:

```json
{"cmd":"ota_pull","payload":{"url":"http://192.168.1.10:8000/ota/firmware.bin"}}
```
