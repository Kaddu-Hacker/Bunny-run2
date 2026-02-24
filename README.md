# 🐰 BunnyBot — Bunny Runner 3D Automation

> Fully autonomous **Bunny Runner 3D** bot running in **Termux** on Android.  
> **100% local** — pure OpenCV computer vision. No internet. No AI API. No API keys.  
> Supports same-phone (local ADB) and two-phone (remote ADB over Wi-Fi).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux-green)
![Vision](https://img.shields.io/badge/Vision-OpenCV%20only-orange)

---

## 📋 Contents

1. [How It Works](#-how-it-works)
2. [Template Files](#-template-files)
3. [Prerequisites](#-prerequisites)
4. [Step 1 — Termux Setup](#-step-1--termux-setup)
5. [Step 2 — Connect ADB](#-step-2--connect-adb)
6. [Step 3 — Run the Bot](#-step-3--run-the-bot)
7. [Menu Reference](#-menu-reference)
8. [Tuning Guide](#-tuning-guide)
9. [Troubleshooting](#-troubleshooting)

---

## ⚙️ How It Works

Bunny Runner 3D is a lane-switching endless runner. The bunny runs on a winding
3D track; you swipe left or right to steer around turns and dodge fences.

The bot replaces your swipes using **ADB** (Android Debug Bridge) and decides
what to do using **OpenCV pixel analysis** — no cloud, no AI, no internet.

```
ADB screencap  →  BGR image  →  OpenCV analysis  →  ADB swipe
(every ~100ms)                                     (left or right)
```

### Decision logic (priority order)

```
1.  Dark overlay + bright UI visible?           →  RESTART  (tap retry)
2.  Fence pixels / template in LEFT  danger zone →  RIGHT   (dodge away)
3.  Fence pixels / template in RIGHT danger zone →  LEFT    (dodge away)
4.  More path pixels on RIGHT half of lookahead  →  RIGHT   (follow the path)
5.  More path pixels on LEFT  half of lookahead  →  LEFT
6.  Otherwise                                    →  STRAIGHT (do nothing)
```

### Where the bot looks on screen

```
┌─────────────────────────────┐  ← top of screen
│                             │
│  ┌───────────────────────┐  │  ← 30% down
│  │   LOOK-AHEAD STRIP    │  │    bot measures left vs right path pixels here
│  │          │            │  │    to determine which way the track curves
│  └───────────────────────┘  │  ← 55% down
│                             │
│  ┌──────┐       ┌──────┐    │  ← danger zones (28%–68% vertically)
│  │  DZ  │       │  DZ  │    │    monitors for fence colour + template match
│  │ LEFT │       │RIGHT │    │
│  └──────┘       └──────┘    │
│                             │
└─────────────────────────────┘  ← bottom of screen
```

---

## 🖼️ Template Files

Place these three images in the **same folder as `bunny_bot.py`**:

| File | Purpose |
|------|---------|
| `template_carrot.png` | Reference carrot sprite |
| `template_fence.png`  | Reference fence sprite — used for obstacle detection |
| `template_rabbit.png` | Reference rabbit/bunny sprite |

The bot tests each template at **7 different scales** (35%–150%) so it works
across different phone resolutions without any manual sizing.

> **Only `template_fence.png` is critical for gameplay.**  
> Carrot and rabbit templates are loaded but don't trigger any movement — they're
> available for future enhancements (e.g. targeting carrot lanes).

---

## 🔧 Prerequisites

- ✅ **Termux** installed ([F-Droid build recommended](https://f-droid.org/packages/com.termux/))
- ✅ **Developer Options** enabled on your Android device
- ✅ **Wireless Debugging** turned ON (Settings → Developer Options → Wireless Debugging)

---

## 📦 Step 1 — Termux Setup

Open Termux and run these commands:

```bash
# 1. Update packages
pkg update && pkg upgrade -y

# 2. Install everything needed
pkg install python android-tools python-numpy opencv-python git -y

# 3. Grant storage access (recommended)
termux-setup-storage

# 4. Clone the repo
cd ~/storage/shared
git clone https://github.com/Kaddu-Hacker/Bunny-run2.git
cd Bunny-run2
```

> ⚠️  **Never** run `pip install opencv-python` on Termux.  
> It will try to compile C++ for hours and likely fail.  
> Always use `pkg install opencv-python`.

---

## 🔗 Step 2 — Connect ADB

### Option A — Same phone (Termux controls itself)

1. **Settings → Developer Options → Wireless Debugging** → enable it
2. Tap **"Pair device with pairing code"** — note the IP and pairing port
3. In Termux:

```bash
adb pair <IP>:<PAIRING_PORT>
# enter the 6-digit code when asked
```

4. Then connect (use the port on the main Wireless Debugging screen):

```bash
adb connect <IP>:<CONNECTION_PORT>
```

5. Verify:

```bash
adb devices
# should show:  <IP>:<PORT>   device
```

### Option B — Two phones (Phone A runs Termux, Phone B runs the game)

1. Both phones on the **same Wi-Fi network**
2. Enable Wireless Debugging on **Phone B**
3. From **Phone A** (Termux), pair and connect to **Phone B's** IP:PORT (same steps above)
4. In the bot menu, set the device to Phone B's `IP:PORT`

---

## 🚀 Step 3 — Run the Bot

```bash
cd ~/storage/shared/Bunny-run2
python bunny_bot.py
```

**Recommended first-time flow:**

1. Open the game on your phone and get to a running screen
2. In the bot menu, press **`C`** — this auto-detects the path colour for your device
3. Apply the suggested values when prompted
4. Press **`S`** to start — you have 5 seconds to switch to the game

**Press `Ctrl+C` at any time to stop.**

---

## 🎮 Menu Reference

| Key | Option | Notes |
|-----|--------|-------|
| `1` | Set target device | Blank = auto-detect first connected device |
| `2` | Change loop FPS | Default 10. Higher = faster reaction, more CPU |
| `3` | Change swipe speed/distance | Default 80ms / 300px |
| `4` | Change action cooldown | Default 0.20s — prevents swipe spam |
| `5` | Toggle debug logging | Prints every frame decision to terminal |
| `6` | Toggle save debug frames | Saves annotated screenshots to `./debug_frames/` |
| `7` | Change game package name | Default: `com.kwalee.bunnyrunner` |
| `8` | Adjust fence sensitivity | Default threshold: 280px |
| `9` | Adjust path deadband | Default 12% — how imbalanced L/R must be to act |
| `C` | Calibrate path colour | **Run this first while in-game on a running screen** |
| `S` | Start the bot | |
| `Q` | Quit | |

---

## 🎛️ Tuning Guide

### The bot isn't turning / always says STRAIGHT

**This is the most common issue** and almost always means the path colour
is wrong. Fix it in two minutes:

1. Open the game to an active running screen
2. In the bot menu press `C` (Calibrate)
3. The bot samples the path colour under the bunny and prints:
   ```
   path_hsv_lo = [12, 22, 145]
   path_hsv_hi = [34, 95, 255]
   ```
4. Press `Y` to apply for the current session, or copy them into `CFG` in the script

### The bot turns too much / jittery

Increase the path deadband (menu `9`). The default is 12% — try 18% or 22%.

```python
"path_deadband": 0.18,   # in CFG at top of script
```

### Fences aren't being detected

Lower the fence pixel threshold (menu `8`). Default is 280 — try 150.

```python
"fence_px_threshold": 150,
```

### Swipes aren't registering in the game

The game might need a larger or faster swipe:

```python
"swipe_ms": 60,    # faster
"swipe_px": 400,   # longer
```

### Enable debug mode to see what the bot is thinking

Press `5` in the menu (debug log ON), then start the bot. Every frame prints:

```
[00042] RIGHT     FENCE → RIGHT    pathL/R=2100/1800  fenceL/R=420/85  9.8fps
[00043] STRAIGHT  PATH → STRAIGHT  pathL/R=1950/2020  fenceL/R=40/30   9.9fps
```

Enable frame saving (`6`) to get annotated screenshots in `./debug_frames/` showing
exactly which zones the bot is looking at.

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| `adb: command not found` | `pkg install android-tools -y` |
| `ModuleNotFoundError: cv2` | `pkg install opencv-python -y` (never pip) |
| Screen capture returns None | `adb kill-server` then `adb connect <IP>:<PORT>` |
| Bot always says STRAIGHT | Run calibration: menu → `C` |
| Bot turning randomly (wrong direction) | Swap `dz_left_x` and `dz_right_x` values in CFG |
| Game-over not detected | Adjust `gameover_dark_frac` or `gameover_bright_px` in CFG |
| `protocol fault` ADB error | `adb kill-server` then reconnect |
| Package not found on restart | Check package name: `adb shell pm list packages \| grep bunny` |

---

## 🏗️ File Structure

```
Bunny-run2/
├── bunny_bot.py          ← the bot (only file you need to run)
├── template_carrot.png   ← carrot reference image
├── template_fence.png    ← fence reference image  (most important)
├── template_rabbit.png   ← rabbit reference image
├── requirements.txt      ← explains pkg installs (no pip deps)
└── README.md
```

---

*Made with ❤️ — contributions welcome!*
