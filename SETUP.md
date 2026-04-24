# 安装指引：M5StickS3 + Claude Code Buddy

从零开始，把一台全新的 Mac + 全新的 M5StickS3 设置成可以和 Claude Code 联动的硬件 buddy。通读 + 操作约 20 分钟。

## 这东西是什么

原版 Anthropic 的 [claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) 是给 **M5StickC Plus**（ESP32 classic）做的固件 + Claude Desktop 桌面版配套。

这份 fork 加了两件事：

1. **M5StickS3 固件移植**：让新一代 S3 芯片的设备能跑起来。
2. **Claude Code 桥接**：一个 Python 守护进程 + hook 脚本，把 Claude Code（CLI 版本）的事件翻译成设备能听懂的 BLE 协议。**固件本身不需要改动**，设备不知道自己连的是桌面版还是 CLI。

跑起来你能得到：
- Claude Code 想执行 `Bash` / `Edit` / `Write` / `NotebookEdit` 时，设备屏幕亮起 approve / deny 提示，按键确认。
- 你提交 prompt、Claude 发通知、会话开始/结束，都会在设备屏幕上反映。

---

## 准备清单

**硬件：**
- M5StickS3（ESP32-S3-PICO-1-N8R2）× 1
- USB-C 数据线 × 1

**电脑：**
- macOS（Intel 或 Apple Silicon 都可）
- Claude Code 已安装（`claude` 命令可用）
- Claude Desktop 已安装（**只为一次性 BLE 配对使用**，配完可以卸载）

**软件依赖**（下一步一条命令装齐）：
- Python 3.12 或 3.13（**不要用 3.14**，`bleak` 在 macOS 上会崩）
- PlatformIO（烧录固件）
- gh CLI（git push 认证）

---

## 第一步：装依赖

```bash
brew install python@3.13 platformio gh
```

装完登录 GitHub（gh 会引导，选 HTTPS + 浏览器授权即可）：

```bash
gh auth login && gh auth setup-git
```

---

## 第二步：拉代码

```bash
git clone https://github.com/EiYaFi/claude-desktop-buddy-s3.git
cd claude-desktop-buddy-s3
```

---

## 第三步：跑 setup 脚本

```bash
./tools/claude-code-bridge/setup.sh
```

这个脚本是幂等的（重复跑不会出问题），它会：
1. 在 `~/.claude-buddy-venv/` 创建 Python 虚拟环境，装 `bleak`
2. 写一个 launchd agent 到 `~/Library/LaunchAgents/com.claude.buddy-bridge.plist`，设置成开机自启 + 掉线自动重连
3. 把 Claude Code hooks 合并到 `~/.claude/settings.json`（保留你已有的 hook，不会覆盖）

脚本末尾会打印剩余的手动步骤清单。

---

## 第四步：授权蓝牙

macOS 的 TCC 机制默认阻止终端访问蓝牙，而且**不会主动弹权限窗口**，所以必须手动开。

1. 打开 **系统设置 → 隐私与安全 → 蓝牙**
2. 点 `+`，加上你用的终端（Terminal、iTerm、WarpTerminal 之类）
3. 把开关打开

> 如果之前误拒绝过，跑一下 `tccutil reset Bluetooth` 重置权限状态再来一次。

---

## 第五步：烧固件

**5.1 进下载模式**

把 S3 用 USB-C 线接上电脑，**长按机身侧边复位按键**，等侧面绿色 LED 开始闪烁，松手。这表示进入下载模式。

> 和老款 StickC Plus 不一样——S3 不是"按 A 键加通电"，是长按侧边键。

**5.2 烧录固件 + 文件系统**

```bash
pio run -e m5stick-s3 -t upload -t uploadfs
```

- `upload` 刷程序本体
- `uploadfs` 刷 LittleFS 分区（第一次必须跑，否则设备启动时 `characterInit()` 会挂住）

**5.3 启动**

烧完 PlatformIO 不会自动复位（S3 的 USB-Serial/JTAG 不支持 RTS 自动复位）。**短按**一下侧边键，设备启动，屏幕应该出现像素风宠物 + "no claude connected"。

---

## 第六步：配对（一次性）

设备用的是 **BLE LE Secure Connections + bonding**，bond 信息存在 macOS 系统里。我们借 Claude Desktop 完成配对，之后桥接程序可以直接复用这个 bond。

1. 打开 Claude Desktop
2. **Settings → Developer → Open Hardware Buddy → Connect**
3. 设备屏幕会显示 6 位数字 passkey，macOS 弹窗让你输入，输完连接成功
4. **退出 Claude Desktop**（完全退出，不是最小化。只有一个 BLE central 能占着设备）

配对一次就够了。之后桥接程序自己连。

---

## 第七步：让 Claude Code 加载 hooks

新装的 hooks 不会热加载到**当前已打开**的 Claude Code 会话里。两种方式：

- **简单**：完全退出 Claude Code，重新启动一次，新会话自动生效。
- **不关会话**：在 Claude Code 里敲 `/hooks`，打开一下，Claude Code 会重新读 settings.json。

---

## 验证能用了

**8.1 桥接在跑吗**

```bash
launchctl list | grep claude.buddy
tail /tmp/claude-buddy.err.log
```

日志里应该看到 `connected, heartbeat pushed` 之类的字样。

**8.2 设备屏幕变化**

屏幕上的 `no claude connected` 会变成显示你的名字（默认取 `$USER`）。

**8.3 Claude Code 触发 gate**

```bash
claude
# > 输入：请跑一下 ls 命令
```

应该看到：
1. 屏幕滚动区出现 `> 请跑一下 ls 命令`
2. Claude 准备跑 Bash 时，屏幕亮起 `approve: Bash` 提示
3. 按**正面 M5 Logo 键**批准 / 按**侧边按键**拒绝，Claude Code 对应放行或阻断

---

## 常见问题

**Python 启动退出码 134 / SIGABRT**
你用到了 Python 3.14，换 3.13：`brew install python@3.13`，然后重跑 `setup.sh`。

**桥接报 Bluetooth 权限错，或什么也没发生**
TCC 没开。回到第四步。如果找不到开关，`tccutil reset Bluetooth` 重置后再给权限。

**设备卡在 "Hello! a buddy appears"**
固件跑了，但 LittleFS 没刷（或者 button GPIO 没对）。确认：
- `pio run -e m5stick-s3 -t uploadfs` 跑过
- 你用的固件是这份 fork（`src/main.cpp` 里有 `cfg.fallback_board = board_M5StickS3`）

**设备屏幕显示 "no claude connected"，不变**
桥接没连上。依次查：
```bash
launchctl list | grep claude.buddy    # 服务在不在
cat /tmp/claude-buddy.err.log         # 有没有报错
ls /tmp/claude-buddy.sock             # 套接字文件在不在
```
也要确认 **Claude Desktop 已退出**，不然它占着 BLE，桥接抢不到。

**PlatformIO 选错了串口（比如连上麦克风被当成串口）**
手动指定：`pio run -e m5stick-s3 -t upload --upload-port /dev/cu.usbmodem101`（实际端口用 `ls /dev/cu.*` 看）。

**hook 看起来没触发**
Claude Code 只在报错或耗时长的时候显示 "Ran N hooks"，沉默即成功。想确认是否在跑，临时在 `~/.claude/settings.json` 的 hook command 前加一句 `echo "$(date) hook fired" >> /tmp/hook-check.txt;`，触发一次再看 `/tmp/hook-check.txt`。

---

## 想关掉 / 卸载

**临时停桥接：**
```bash
launchctl unload ~/Library/LaunchAgents/com.claude.buddy-bridge.plist
```

**完全卸载：**
```bash
launchctl unload ~/Library/LaunchAgents/com.claude.buddy-bridge.plist
rm ~/Library/LaunchAgents/com.claude.buddy-bridge.plist
rm -rf ~/.claude-buddy-venv
# 手动从 ~/.claude/settings.json 里删掉 hooks 部分（或者用 Claude Code 的 /hooks 菜单）
```

固件想恢复空设备，烧官方 M5 Burner 里的任何 demo 都行。

---

## 多台设备 / 多台电脑

- **一台电脑、多台 S3**：默认桥接只连上第一个名字以 `Claude` 开头的设备。想区分，改 `setup.sh` 里 plist 的 `--name-prefix` 到具体后缀（比如 `Claude-56E1`）。
- **多台电脑、同一台 S3**：BLE 同时只允许一个 central。你得手动在哪台电脑上用就 quit 另一台的 Claude Desktop / bridge。

---

## 相关文档

- [`tools/claude-code-bridge/README.md`](tools/claude-code-bridge/README.md) — 桥接架构细节和手动安装步骤
- [`M5StickS3.md`](M5StickS3.md) — S3 固件移植的深度说明
- [`REFERENCE.md`](REFERENCE.md) — 原始 BLE 协议文档（来自上游）
