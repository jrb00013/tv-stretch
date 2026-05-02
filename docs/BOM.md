# Bill of materials — tv-stretch-node (rev A)

Columns: Ref | Qty | Manufacturer | MPN | Description | Footprint | Supplier notes

| Ref | Qty | Manufacturer | MPN | Description | Footprint | Supplier notes |
|-----|-----|--------------|-----|-------------|-----------|----------------|
| U1 | 1 | Espressif | ESP32-C3-MINI-1-N4 | Wi-Fi MCU module, 4 MB flash | Module ESP32-C3-MINI-1 | LCSC C2838500 / Mouser |
| U2 | 1 | Diodes Inc. | AP2112K-3.3TRG1 | LDO 3.3 V, 600 mA | SOT-23-5 | |
| J1 | 1 | GCT or equiv. | USB4085-GF-A | USB-C receptacle, 16-pin mid-mount | USB-C 16P | Verify CC routing |
| J2 | 1 | — | HDMI-A receptacle (SMD) | HDMI Type A female | HDMI19SMD | Match mechanical to pigtail if used |
| J3 | 1 | — | HDMI-A plug (or cable assembly) | To TV | Cable | Many builds use short pigtail from J2 |
| D1 | 1 | Nexperia | PESD5V0S1BA | ESD on CEC | SOD-323 | Optional USBLC6 for USB pair |
| R1 | 1 | — | 10k 1% | CEC pull-up to 3V3 | 0402 | HDMI spec pull-up often ~27k on bus; follow TV node design |
| R2,R3 | 2 | — | 5.1k 1% | USB-C CC resistors (Rd) | 0402 | If using “sink 5 V only” |
| C1,C2 | 2 | — | 10 µF 10 V X5R | LDO in/out | 0805 | |
| C3,C4 | 2 | — | 100 nF 50 V | Decoupling | 0402 | |
| LED1 | 1 | — | Green LED | Status | 0603 | |
| R4 | 1 | — | 1k | LED current limit | 0402 | |
| SW1 | 1 | — | Tactile | Boot / provision | 6x6mm | |
| — | 1 | — | PCB | 2-layer, 1 mm or 1.6 mm | — | Impedance not critical |

**Alternates:** ESP32-C3-WROOM-02; LDO AP7363 or TLV75533; HDMI pigtail instead of on-board plug.

**Mechanical:** screws, enclosure — see [MECHANICAL.md](MECHANICAL.md).
