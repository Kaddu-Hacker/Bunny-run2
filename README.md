# 🐰 BunnyBot v3 — Bunny Runner 3D Automation

> Fully autonomous **Bunny Runner 3D** bot running in **Termux** on Android.  
> **100% local** — pure OpenCV computer vision. No internet. No AI. No API keys.  
> **Dual backend:** `adbutils` (pure Python) **+** ADB subprocess — auto-selects the best one.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux-green)
![Vision](https://img.shields.io/badge/Vision-OpenCV%20only-orange)

---

## 🔀 Two Backends — Which One Is Better?

| | adbutils (Backend 2) | ADB subprocess (Backend 1) |
|---|---|---|
| Requires | `pip install adbutils` | `adb` binary (`android-tools`) |
| Screencap | Direct socket → PIL image | subprocess call → PNG file |
| Speed | ⚡ Faster | Slower (process spawn each frame) |
| Reliability | ✅ Better error recovery | ⚠️ Can hang/timeout |
| CRLF issue | ✅ Handled internally | Needs manual fix |
| Install | 1 pip command | Already in android-tools |

**In auto mode, the bot tries adbutils first and falls back to ADB subprocess.** Install both for maximum reliability.

---

## 📋 Contents

1. [How It Works](#-how-it-works)
2. [Prerequisites](#-prerequisites)
3. [Step 1 — Termux Setup](#-step-1--termux-setup)
4. [Step 2 — Connect ADB](#-step-2--connect-adb)
5. [Step 3 — Run the Bot](#-step-3--run-the-bot)
6. [Menu Reference](#-menu-reference)
7. [Tuning Guide](#-tuning-guide)
8. [Troubleshooting](#-troubleshooting)

---

## ⚙️ How It Works

```
ADB / adbutils screencap  →  BGR image  →  OpenCV analysis  →  tap (left or right)
      (every ~100ms)                                             via chosen backend
```

### Decision logic (priority order)

```
1. Dark overlay + bright retry UI visible?       → RESTART   (tap retry button)
2. Fence pixels / template in LEFT danger zone   → RIGHT     (dodge away)
3. Fence pixels / template in RIGHT danger zone  → LEFT      (dodge away)
4. More path pixels on RIGHT half of look-ahead  → RIGHT     (follow the path)
5. More path pixels on LEFT half of look-ahead   → LEFT
6. Otherwise                                     → STRAIGHT  (do nothing)
```

---

## 🔧 Prerequisites

- ✅ **Termux** ([F-Droid](https://f-droid.org/packages/com.termux/) recommended, not Play Store)
- ✅ **Developer Options** enabled on the game phone
- ✅ **Wireless Debugging** ON (Settings → Developer Options → Wireless Debugging)

---

## 📦 Step 1 — Termux Setup

```bash
pkg update && pkg upgrade -y
pkg install python android-tools python-numpy opencv-python -y
pip install adbutils --break-system-packages     # ← strongly recommended
```

> ⚠️ **Never** `pip install opencv-python` on Termux — it will hang compiling C++.  
> Always use `pkg install opencv-python`.

---

## 🔗 Step 2 — Connect ADB

1. **Settings → Developer Options → Wireless Debugging** → ON
2. Tap **"Pair device with pairing code"** — note the IP and pairing port
3. In Termux:

```bash
adb pair <IP>:<PAIRING_PORT>    # enter 6-digit code when prompted
adb connect <IP>:<CONN_PORT>    # port shown on main Wireless Debugging screen
adb devices                     # must show "device" — NOT "unauthorized"
```

> **Two phones?** Do the above from Phone A (Termux) targeting Phone B's IP/port. Then in the bot menu, option 1, set the device to Phone B's `IP:PORT`.

---

## 🚀 Step 3 — Run the Bot

```bash
python bunny_bot.py
```

**Recommended first-time flow:**

1. Get the game running on your phone (active running screen)
2. Press **`0`** — run full diagnostics on both backends
3. Press **`B`** — set backend to `adbutils` if it passed, otherwise leave `auto`
4. Press **`C`** — calibrate path colour for your specific device
5. Press **`S`** — start! You have 5 seconds to switch to the game.

**Ctrl+C anytime to stop.**

---

## 🎮 Menu Reference

| Key | Option | Notes |
|-----|--------|-------|
| `0` | **Full diagnostics** | **Start here — tests both backends** |
| `1` | Set target device | Blank = auto-detect |
| `B` | **Set backend** | `auto` / `adbutils` / `adb` |
| `2` | Change loop FPS | Default 10 |
| `3` | Change action cooldown | Default 0.18s |
| `4` | Toggle debug logging | Frame-by-frame decisions |
| `5` | Toggle save debug frames | Annotated screenshots → `./debug_frames/` |
| `6` | Change game package name | Default: `com.kwalee.bunnyrunner` |
| `7` | Adjust fence sensitivity | Default 250px |
| `8` | Adjust path deadband | Default 12% |
| `9` | ADB screencap method | `auto` / `exec-out` / `local` / `pull` |
| `C` | **Calibrate path colour** | Run on active running screen |
| `S` | Start the bot | |
| `Q` | Quit | |

---

## 🎛️ Tuning Guide

### Bot always says STRAIGHT / not turning
Path colour doesn't match your game. Press **`C`** to calibrate — takes 10 seconds.

### Bot turns too much / jittery
Increase path deadband (`8`). Default 12% → try 18%–22%.

### Fences not detected  
Lower fence pixel threshold (`7`). Default 250 → try 120–150.

### Taps not registering in-game
Adjust tap position in CFG:
```python
"tap_left_x":  0.25,   # left side of screen
"tap_right_x": 0.75,   # right side of screen
"tap_y":       0.60,   # vertical position
```

### adbutils screencap is slow
This usually means PIL→numpy conversion overhead. The bot handles this automatically. If it's still slow, try switching to ADB subprocess: menu `B` → `adb`.

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| `adb: command not found` | `pkg install android-tools -y` |
| `ModuleNotFoundError: cv2` | `pkg install opencv-python -y` |
| `ModuleNotFoundError: adbutils` | `pip install adbutils --break-system-packages` |
| Screen capture failed | Run menu `0` (full diagnostics) |
| ADB shows "unauthorized" | Phone → revoke USB debugging → reconnect → allow popup |
| Bot always STRAIGHT | Menu `C` — calibrate path colour |
| Bot turns wrong direction | Swap `tap_left_x` / `tap_right_x` in CFG |
| Game-over not detected | Lower `gameover_dark_frac` in CFG |
| `adb kill-server` doesn't help | Try `adbutils` backend — no binary, socket only |
| Taps too slow for later levels | Lower `action_cooldown` to 0.10s |

---

## 🏗️ File Structure

```
BunnyBot/
├── bunny_bot.py          ← the bot (only file you need)
├── template_fence.png    ← fence reference image  ← IMPORTANT for obstacle detection
├── template_carrot.png   ← carrot reference (optional)
├── template_rabbit.png   ← rabbit reference (optional)
├── requirements.txt      ← install instructions
└── README.md
```

---

*Made with ❤️ — contributions welcome!*
