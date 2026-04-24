# M5StickS3 移植指南

Anthropic 官方 `claude-desktop-buddy` 固件原本只支持 **M5StickC Plus**（ESP32 classic）。
本分支把它移植到了 **M5StickS3**（ESP32-S3），这是目前更好买、性能也更强的一代。

BLE 协议、JSON 格式、字符包格式都与上游完全兼容，配对流程不变。

## 硬件要求

- **M5StickS3**（ESP32-S3-PICO-1-N8R2，8MB Flash + 2MB PSRAM）
- 数据线一根（**必须是数据线，不能是充电线**）
- Mac 或 Linux 主机（本指南以 macOS 为例）

## 烧录步骤

### 1. 安装 PlatformIO Core

```bash
# 任选一种：
python3 -m pip install -U platformio
# 或
brew install platformio
```

### 2. 克隆并进入目录

```bash
git clone https://github.com/<YOUR-GITHUB>/claude-desktop-buddy.git
cd claude-desktop-buddy
```

### 3. 让设备进入下载模式

**M5StickS3 的下载模式与 M5StickC Plus 不同**：

1. 确保设备已插上 USB
2. **长按机身侧边按键**
3. 观察设备内部 **绿色 LED 闪烁** ⇒ 已进入下载模式
4. 松开按键，设备停留在下载模式（屏幕黑屏、绿灯亮）

### 4. 烧录固件

```bash
pio run -e m5stick-s3 -t upload
```

上传完成后 esptool 会尝试硬复位，但 S3 的 USB-Serial/JTAG 没有真正的 RTS 线，有时复位不会触发。如果屏幕没变化，**短按一次侧边按键**手动复位。

### 5. 首次使用：写入空的 LittleFS（仅第一次）

出厂状态下 LittleFS 分区未格式化，直接启动会挂载失败。需要写一个空镜像格式化：

```bash
mkdir -p data && touch data/.keep
# 重新进入下载模式（长按侧边键，绿灯闪）
pio run -e m5stick-s3 -t uploadfs
```

完成后**短按侧边键**复位。屏幕上应该出现 ASCII 小生物，底栏显示 `no claude connected`。

## 与 Claude 桌面端配对

1. **Claude 桌面 app** 菜单栏 → Help → Troubleshooting → **Enable Developer Mode**
2. 菜单栏 → **Developer → Open Hardware Buddy…**
3. 在弹出窗口点 **Connect**，选择 `Claude-XXXX`（XXXX 是 BT MAC 后四位）
4. 首次 macOS 会请求蓝牙权限，允许即可
5. 设备屏幕显示 6 位 passkey，输入到 Mac 端完成配对

## 常见问题

### 屏幕卡在 "Hello! a buddy appears" 动不了

LittleFS 没格式化。按上面"首次使用"步骤烧空 filesystem 镜像。

### 烧录时 `Failed to connect to ESP32-S3: No serial data received`

设备没进入下载模式。S3 的 USB-Serial/JTAG 不支持 esptool 的 RTS/DTR 自动复位，**必须手动**长按侧边键进下载模式（等到绿灯闪）后再烧。

### 烧录后 `pio` 日志显示 "waiting for download"，设备不自启

上传完毕但没跳出下载模式。**短按一次侧边按键**手动复位。

### `pio` 自动选中了错误的串口（比如 DJI 麦克风）

显式指定端口：

```bash
pio run -e m5stick-s3 -t upload --upload-port /dev/cu.usbmodem101
```

### 按钮没反应、屏幕一直是 Hello

M5Unified 没识别成 M5StickS3，按钮 GPIO 读错了。这个分支已在 `main.cpp` 里显式设置了 `cfg.fallback_board = board_M5StickS3`；如果你 fork 了代码并移除了这行，会复现此问题。

### 擦除重来

完整擦除 flash 后重烧：

```bash
pio run -e m5stick-s3 -t erase
# 再次长按侧边进入下载模式
pio run -e m5stick-s3 -t upload
pio run -e m5stick-s3 -t uploadfs
```

或者从设备自己的菜单：**长按 M5 Logo → settings → reset → factory reset → 点两次**。

## 与原版代码的主要差异

如果你想移植到其它 ESP32-S3 板子，以下是本次移植触及的所有变更点：

| 方面 | 原版（M5StickC Plus） | 本分支（M5StickS3） |
|---|---|---|
| MCU | ESP32 classic | ESP32-S3 (PSRAM, OPI flash) |
| 驱动库 | `M5StickCPlus` | `M5Unified` v0.2.14 |
| 图形库 | `TFT_eSPI` / `TFT_eSprite` | `LovyanGFX` / `M5Canvas`（M5GFX 提供） |
| 电源管理 | `M5.Axp` (AXP192) | `M5.Power` (M5PM1) |
| RTC | 外部 RTC | ESP32 内部 + `time.h` shim |
| USB | CH9102 UART 桥接 | 原生 USB-Serial/JTAG |
| 红色 LED | GPIO 10 | 无（GPIO 19/20 被 USB 占用，`LED_PIN = -1`） |
| 按钮 GPIO | BtnA=37, BtnB=39 | BtnA=11, BtnB=12（由 M5Unified 处理） |
| 蜂鸣器 | `M5.Beep`（GPIO 2） | `M5.Speaker`（I²S） |
| 下载模式 | 按住 M5 Logo + 接 USB | 长按侧边键至绿灯闪 |

### 关键配置（`platformio.ini`）

```ini
[env:m5stick-s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
board_build.filesystem = littlefs
board_build.partitions = no_ota.csv
board_build.f_cpu = 240000000L
board_build.arduino.memory_type = qio_opi
board_upload.flash_size = 8MB
board_upload.maximum_size = 8388608
build_flags =
    -DCORE_DEBUG_LEVEL=0
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MODE=1
build_src_filter = +<*> +<buddies/>
lib_deps =
    m5stack/M5Unified @ ^0.2.0
    bitbank2/AnimatedGIF @ ^2.1.1
    bblanchon/ArduinoJson @ ^7.0.0
```

### `setup()` 关键一行（`src/main.cpp`）

```cpp
void setup() {
  auto cfg = M5.config();
#if CONFIG_IDF_TARGET_ESP32S3
  cfg.fallback_board = m5::board_t::board_M5StickS3;   // 必须！否则按钮失效
#endif
  M5.begin(cfg);
  ...
}
```

M5GFX 的自动板型检测在 StickS3 上可能返回非预期结果，回退到 `board_M5AtomS3Lite`，导致按钮 GPIO 读错。显式 fallback 是关键。

## License & Credits

- 上游：Anthropic [claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
- M5StickS3 移植：本仓库作者
- 遵循上游 License

欢迎 Issue / PR。如果你在其它 M5Stack ESP32-S3 板子（Core S3、Cardputer 等）上跑通了，也欢迎提交。
