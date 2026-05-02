# HDMI-CEC notes (tv-stretch-node)

## Pin reference (Type A HDMI)

| Pin | Name | Node connection |
|-----|------|-----------------|
| 13 | CEC | MCU GPIO (open-drain), ESD diode |
| 17 | DDC/CEC GND | Ground |
| 18 | +5V | Optional sense / tie per design |

**Do not** connect TMDS pairs to the MCU; this design is **CEC-only**, not a video path.

## Electrical

- CEC is **single-wire**, **open-drain**, typically **3.3 V** I/O on modern implementations.
- Bit timing: start bit + data blocks per **HDMI 1.4b / CEC 1.4** (Consult HDMI Licensing / IEC 62388-1 for product compliance).
- Use **scope or logic analyzer** when bringing up a new TV.

## Firmware subset

The in-tree driver implements a **minimal** subset sufficient for demos:

- Low-level **start bit**, **byte TX/RX** with ACK bit handling (simplified).
- Helpers for **broadcast** and **directed** frames.
- Example opcodes: `<Give Physical Address>`, `<Report Physical Address>`, `<Active Source>`, `<Set Stream Path>`, `<Standby>`, `<User Control Pressed>` (power, select).

TVs may require correct **logical** and **physical** addresses. Set `physical_address` in Kconfig to match topology (e.g. `0x2000`).

## Compatibility

- Some TVs disable CEC unless enabled in menus (Samsung Anynet+, Sony Bravia Sync, etc.).
- AVRs in the path change routing; you may need to address the **receiver** instead of the TV.

## References (external)

- Community implementations (license differs): ESPHome native HDMI-CEC projects.
- HDMI organization specifications (paid / license agreement) for shipping products.
