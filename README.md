# claude-desktop-buddy-S3

**中文** · [English](README.en.md)

> **关于这个 fork**：在 [上游 anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) 的基础上加了 **M5StickS3 固件移植** 和 **Claude Code 桥接**。
> 一条命令装好新电脑：见 **[SETUP.md](SETUP.md)**（中文端到端指引）。

Claude 桌面版（macOS 和 Windows）可以让 Claude Cowork 和 Claude Code 通过 BLE 连接 maker 设备，开发者因此能做出带权限提示、消息滚动等交互的硬件小玩具。我们一直被 maker 社区围绕 Claude 做的各种创作打动——提供一套轻量、可选接入的 API，是我们帮大家更容易做出好玩硬件的方式。

> **想自己做设备？** 你不需要这里的任何代码。通讯协议（Nordic UART Service UUID、JSON schema、文件夹推送传输）见 **[REFERENCE.md](REFERENCE.md)**。

作为一个示例，我们在 ESP32 上做了一只桌面宠物——靠你批命令、和 Claude 互动为生。没事就睡觉，会话开始就醒，审批弹出时明显焦急，直接在设备上批或否。

<img width="360" height="480" alt="img_v3_02112_4055a15f-6392-4d1c-873e-c282e2f003eg" src="https://github.com/user-attachments/assets/5e67ca22-0936-4aa6-88b1-797a67c31f6a" />


## 硬件

固件基于 Arduino 框架跑在 ESP32 上。原版代码依赖 M5StickCPlus 库处理屏幕、IMU、按键——所以你要么买这块板子，要么 fork 一份替换成你自己板子的驱动和引脚。

本 fork 另外支持 **M5StickS3**（ESP32-S3-PICO-1-N8R2），关键差异见 [M5StickS3.md](M5StickS3.md)。

## 烧录

装好
[PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/)
，然后：

```bash
pio run -t upload
```

如果设备上有旧固件，先擦干净再烧：

```bash
pio run -t erase && pio run -t upload
```

跑起来之后也可以从设备上把所有数据擦掉：**长按 A → settings → reset → factory reset → 点两下**。

## 配对

先在 Claude 桌面版里开启**开发者模式**（**Help → Troubleshooting → Enable Developer Mode**）。然后 **Developer → Open Hardware Buddy…** 打开硬件 buddy 窗口，点 **Connect**，列表里选你的设备。第一次连接 macOS 会弹蓝牙权限请求，同意即可。

<p align="center">
  <img src="docs/menu.png" alt="Developer → Open Hardware Buddy… 菜单项" width="420">
  <img src="docs/hardware-buddy-window.png" alt="Hardware Buddy 窗口，含 Connect 按钮和文件夹投放区" width="420">
</p>

配对一次后，只要两边醒着，桥接会自动重连。

扫不到设备时：
- 确认设备醒着（按任意键）
- 检查设备 settings 菜单 → bluetooth 是开的

## 按键

|                         | 常规                  | 宠物        | 信息         | 审批           |
| ----------------------- | -------------------- | ----------- | ----------- | ------------- |
| **A**（正面）            | 下一页               | 下一页       | 下一页       | **批准**       |
| **B**（右侧）            | 滚动会话记录          | 下一页       | 下一页       | **拒绝**       |
| **长按 A**              | 菜单                 | 菜单         | 菜单         | 菜单           |
| **电源键**（左侧，短按）  | 屏幕开关              |             |             |               |
| **电源键**（左侧，~6s）  | 彻底关机              |             |             |               |
| **摇动**                | 晕头转向              |             |             | —             |
| **脸朝下**              | 午睡（回能量）        |             |             |               |

30 秒无操作屏幕自动关（审批提示在时保持亮）。任意键唤醒。

## ASCII 宠物

18 种宠物，每种 7 套动画（sleep、idle、busy、attention、celebrate、dizzy、heart）。菜单 → "next pet" 循环切换，选择存 NVS。

## GIF 宠物

想用自定义 GIF 人物代替 ASCII 宠物？把 character pack 目录拖到 Hardware Buddy 窗口的投放区，桌面版走 BLE 推给设备，设备实时切到 GIF 模式。**Settings → delete char** 退回 ASCII 模式。

一个 character pack 是一个目录，里面有 `manifest.json` 和 96 像素宽的 GIF：

```json
{
  "name": "bufo",
  "colors": {
    "body": "#6B8E23",
    "bg": "#000000",
    "text": "#FFFFFF",
    "textDim": "#808080",
    "ink": "#000000"
  },
  "states": {
    "sleep": "sleep.gif",
    "idle": ["idle_0.gif", "idle_1.gif", "idle_2.gif"],
    "busy": "busy.gif",
    "attention": "attention.gif",
    "celebrate": "celebrate.gif",
    "dizzy": "dizzy.gif",
    "heart": "heart.gif"
  }
}
```

状态值可以是单个文件名，也可以是数组。数组会轮播：每播完一次切下一个 GIF，适合做 idle 活动轮播，避免主屏一直循环同一段。

GIF 宽 96px；高到 ~140px 都能在 135×240 竖屏里放下。贴紧角色裁——透明边缘浪费屏幕，也让 sprite 看起来偏小。`tools/prep_character.py` 处理缩放：给它任意大小的 GIF，它产出 96px 宽、角色尺寸在各个状态下一致的输出。

整个目录得控制在 1.8MB 以下——`gifsicle --lossy=80 -O3 --colors 64` 通常能砍 40–60%。

工作样例见 `characters/bufo/`。

如果你在频繁调人物，不想走 BLE 来回推，`tools/flash_character.py characters/bufo` 直接把它塞到 `data/` 里并走 USB 跑 `pio run -t uploadfs`。

## 七种状态

| 状态        | 触发条件                  | 观感                        |
| ----------- | ------------------------ | --------------------------- |
| `sleep`     | 桥接未连接                | 闭眼、慢呼吸                 |
| `idle`      | 已连接，没啥要紧事        | 眨眼、东张西望               |
| `busy`      | 会话正在跑                | 出汗、干活                   |
| `attention` | 有审批等处理              | 警觉、**LED 闪烁**           |
| `celebrate` | 升级（每 50K tokens）     | 撒花、蹦跳                   |
| `dizzy`     | 你摇它                   | 眼睛转圈、晃来晃去            |
| `heart`     | 5 秒内批准                | 飘心                         |

## 项目结构

```
src/
  main.cpp       — 主循环、状态机、UI 屏
  buddy.cpp      — ASCII 宠物种类分发 + 渲染辅助
  buddies/       — 一个物种一个文件，各含 7 个动画函数
  ble_bridge.cpp — Nordic UART service，按行缓冲的 TX/RX
  character.cpp  — GIF 解码 + 渲染
  data.h         — 通讯协议、JSON 解析
  xfer.h         — 文件夹推送接收器
  stats.h        — NVS 持久化的统计、设置、主人、物种选择
characters/      — GIF 人物样例包
tools/           — 生成器和转换器；本 fork 另含 claude-code-bridge/
```

## 可用性

BLE API 只在桌面版开启**开发者模式**（**Help → Troubleshooting → Enable Developer Mode**）时可用。这是给 maker 和开发者的，不是官方支持的产品特性。
