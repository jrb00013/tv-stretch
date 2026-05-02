# Hardware components (detailed)

This file describes **tv-stretch-node** (ESP32-C3 HDMI CEC dongle). For **optical SLAM / presence companion** hardware (ToF, RGB-D, SBC), see [HARDWARE_OPTICAL_SLAM_STACK.md](HARDWARE_OPTICAL_SLAM_STACK.md) and the optional BOM section in [BOM.md](BOM.md).

## U1 — ESP32-C3-MINI-1

- **Role:** Main MCU, Wi‑Fi (2.4 GHz), TLS-capable client, GPIO bit-bang CEC.
- **Supply:** 3.0–3.6 V typical; use 3.3 V LDO.
- **Antenna:** On-module PCB antenna; keep ground clearance per Espressif layout guide.
- **Footprint:** Espressif reference land pattern for MINI-1 module.
- **Notes:** GPIO4/GPIO5 often strapping; pick CEC pin per `sdkconfig` (default GPIO 4). Avoid USB pins if using USB-JTAG.

## U2 — AP2112K-3.3 (or equivalent LDO)

- **Role:** Regulate 5 V (USB VBUS) to 3.3 V.
- **Iout:** ≥ 500 mA recommended for Wi‑Fi peaks.
- **Caps:** 1–10 µF ceramic on input and output close to pins.

## J1 — USB-C receptacle

- **Role:** 5 V power only for v1 (no USB data required).
- **CC:** 5.1 kΩ Rd to GND on each CC line for **UFP sink**.
- **ESD:** Optional TVS array on D+/D- if data lines routed later.

## J2/J3 — HDMI connector / pigtail

- **Role:** Electrical access to **CEC** (pin 13), **DDC/CEC GND** (pin 17), optional **+5 V** (pin 18) for “connected” sense.
- **Wiring:** CEC is **open-drain**, ~3.3 V logic; MCU GPIO must be **open-drain** or external FET if required.
- **ESD:** Protect CEC line near connector (D1).

## D1 — PESD5V0S1BA (CEC ESD)

- **Role:** Clamp transients on CEC entering from HDMI cable.

## R1 — CEC pull-up

- **Role:** HDMI CEC bus is open-collector with pull-up. Some designs rely on TV-side pull-up only; if the node only listens, you may omit **local** pull-up—verify with scope. Many DIY ESP32 CEC adapters use **MCU internal pull-up + series resistor** or external 27k per HDMI 1.4b guidance.

## LED1 / R4 — Status

- **Role:** Blink on Wi‑Fi / WebSocket activity (firmware-defined).

## SW1 — User / boot

- **Role:** Force provisioning mode or factory reset (firmware policy).

---

See also [CEC_NOTES.md](CEC_NOTES.md) and KiCad nets in `hardware/kicad/tv-stretch-node/`.
