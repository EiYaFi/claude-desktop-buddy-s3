# Port firmware to M5StickS3 (ESP32-S3)

## Summary

Adds support for **M5StickS3** (ESP32-S3-PICO-1-N8R2) alongside the existing
M5StickC Plus target. The original M5StickC Plus has been discontinued in most
regions; M5StickS3 is its de-facto successor and has a more capable MCU
(ESP32-S3 with PSRAM, native USB).

Wire protocol, JSON schema, and character-pack format are unchanged — devices
flashed with this firmware pair with Claude Desktop exactly like the original.

## What changed

| Area | From | To |
|---|---|---|
| MCU | ESP32 classic | ESP32-S3 (PSRAM, OPI flash) |
| Library | `M5StickCPlus` | `M5Unified` v0.2.x |
| Graphics | `TFT_eSPI` / `TFT_eSprite` | `LovyanGFX` / `M5Canvas` (via M5GFX) |
| Power mgmt | `M5.Axp` (AXP192) | `M5.Power` (M5PM1) |
| RTC | External RTC | ESP32 internal + `time.h` shim |
| USB | CH9102 UART bridge | Native USB-Serial/JTAG |
| Buzzer | `M5.Beep` | `M5.Speaker` (I²S) |
| LED | GPIO 10 (user LED) | `LED_PIN = -1` (no user LED; GPIO 19/20 are USB D-/D+) |
| Buttons | GPIO 37/39 | GPIO 11/12 (handled by M5Unified once board type is set) |

## Critical gotchas (worth keeping in mind if you fork this)

1. **M5Unified auto-detection falls through to `board_M5AtomS3Lite` on
   M5StickS3**, which maps buttons to the wrong GPIOs. Fix: set
   `cfg.fallback_board = m5::board_t::board_M5StickS3` before `M5.begin(cfg)`.

2. **GPIO 19 and 20 are USB D-/D+ on ESP32-S3.** Driving them as outputs
   (e.g. for a user LED) kills USB enumeration — the device hangs and you can
   no longer re-flash over USB without entering download mode manually.

3. **LittleFS partition ships unformatted.** First-time users must run
   `pio run -e m5stick-s3 -t uploadfs` with an empty `data/` directory, or the
   firmware will hang on `characterInit()` → `LittleFS.open()` after a failed
   mount.

4. **Download mode on M5StickS3 is different.** The M5StickC Plus procedure
   (hold M5 Logo while plugging USB) does **not** work. Instead: **long-press
   the side button** until the internal green LED starts blinking. esptool's
   RTS/DTR auto-reset also doesn't work over USB-Serial/JTAG, so manual entry
   is required every time.

## Testing

Verified end-to-end on hardware:
- [x] Firmware compiles and flashes on M5StickS3
- [x] Display renders ASCII buddy + status line
- [x] M5 Logo button cycles through display modes
- [x] Side button toggles screen
- [x] BLE advertises as `Claude-XXXX` (MAC suffix)
- [x] Pairs with Claude Desktop via **Developer → Open Hardware Buddy…**
- [x] Passkey displayed on device, entered on Mac → connection established
- [x] Permission prompts from Claude render on device; approve/deny buttons work

## Files touched

- `platformio.ini` — new `[env:m5stick-s3]` with ESP32-S3 + PSRAM + native USB flags
- `src/main.cpp` — `fallback_board`, `LED_PIN = -1` guard, RTC shim, `M5.Power` / `M5.Speaker` APIs
- `src/character.h`, `src/buddy.h` — `LovyanGFX` include instead of forward decl (M5GFX type conflict)
- `src/data.h`, `src/xfer.h` — RTC + battery API adjustments
- Includes across 22 files: `M5StickCPlus.h` → `M5Unified.h`, `TFT_eSprite` → `M5Canvas`, `TFT_eSPI` → `LovyanGFX`

See `M5StickS3.md` for the end-user flashing guide.

## Screenshots

<!-- Suggested placeholders — replace with your own images -->

- `docs/sticks3-device.jpg` — M5StickS3 running the buddy firmware
- `docs/sticks3-pairing.png` — passkey shown on device during BLE pairing
