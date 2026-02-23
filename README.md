# 🐰 BunnyBot — Gemini AI Edition

> Fully autonomous **Bunny Runner 3D** bot running inside **Termux** on Android.  
> Powered by **Google Gemini 1.5 Flash** AI for real-time screen analysis.  
> Supports local (one phone) and remote (two-phone) ADB control.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux-green)
![AI](https://img.shields.io/badge/AI-Gemini%201.5%20Flash-orange)

---

## 📋 Table of Contents

1. [Features](#-features)
2. [Prerequisites](#-prerequisites)
3. [Step 1 — Termux Package Setup](#-step-1--termux-package-setup)
4. [Step 2 — Get a Free Gemini API Key](#-step-2--get-a-free-gemini-api-key)
5. [Step 3 — Clone the Repository](#-step-3--clone-the-repository)
6. [Step 4 — Install Python Dependencies](#-step-4--install-python-dependencies)
7. [Step 5 — Connect ADB](#-step-5--connect-adb)
8. [Step 6 — Run the Bot](#-step-6--run-the-bot)
9. [Menu Reference](#-menu-reference)
10. [Troubleshooting](#-troubleshooting)
11. [How It Works](#-how-it-works)

---

## ✨ Features

- 🤖 **Gemini 1.5 Flash AI** — Lightweight, fast Google AI model analyzes the screen and decides the next move
- ⚡ **Pixel Reflex Layer** — Sub-second obstacle detection via OpenCV (no API call needed) for instant dodging
- 📱 **Termux-native** — No C++ compilation; all deps install cleanly via `pkg` or `pip`
- 🔗 **Local & Remote ADB** — Control the game on the same phone or remotely over Wi-Fi
- 🔄 **Ad-Skip** — Auto force-stops and relaunches the game to skip unskippable ads
- 🛡️ **Graceful Fallback** — If AI is unavailable, the bot runs in pixel-only mode

---

## 🔧 Prerequisites

Before you begin, ensure the following:

- ✅ **Termux** is installed on your Android phone ([F-Droid recommended](https://f-droid.org/packages/com.termux/))
- ✅ **Developer Options** are enabled on your Android device
- ✅ **Wireless Debugging** is turned ON (Settings → Developer Options → Wireless Debugging)
- ✅ You have a working **internet connection** (for package downloads and AI API calls)

---

## 📦 Step 1 — Termux Package Setup

Open **Termux** and run the following commands **one by one**:

```bash
# 1. Update package lists
pkg update && pkg upgrade -y
```

```bash
# 2. Install core tools
pkg install git python android-tools -y
```

```bash
# 3. Install OpenCV and NumPy (mandatory for pixel-reflex feature)
#    ⚠️ Use pkg — do NOT use pip install opencv-python (it will hang!)
pkg install python-numpy opencv-python -y
```

```bash
# 4. Grant Termux access to shared storage (optional but recommended)
termux-setup-storage
```

---

## 🔑 Step 2 — Get a Free Gemini API Key

1. Go to **[https://aistudio.google.com](https://aistudio.google.com)**
2. Sign in with your Google account
3. Click **"Get API Key"** → **"Create API Key"**
4. Copy your key — you will paste it into the bot menu in Step 6

> **Note:** The free tier is sufficient for running the bot. No credit card required.

---

## 📥 Step 3 — Clone the Repository

```bash
cd ~/storage/shared
git clone https://github.com/Kaddu-Hacker/Bunny-run2.git
cd Bunny-run2
```

---

## 📦 Step 4 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs `google-generativeai` — the only pip dependency needed.

> **Optional:** Install `Pillow` for slightly faster image handling:
> ```bash
> pip install Pillow
> ```

---

## 🔗 Step 5 — Connect ADB

### Option A — Same Phone (Local Control)

1. Go to **Settings → Developer Options → Wireless Debugging**
2. Tap **"Pair device with pairing code"** — note the **IP address** and **Pairing Port**
3. In Termux, run:

```bash
adb pair <IP_ADDRESS>:<PAIRING_PORT>
```

*(Enter the 6-digit pairing code when prompted)*

4. Now connect:

```bash
adb connect <IP_ADDRESS>:<CONNECTION_PORT>
```

*(The connection port is shown on the main Wireless Debugging screen, different from pairing port)*

5. Verify:

```bash
adb devices
```

You should see your device listed as `<IP>:<PORT> device`.

---

### Option B — Two Phones (Remote Control)

Use **Phone A** (running Termux + the script) to control **Phone B** (running the game).

1. Connect both phones to the **same Wi-Fi network**
2. On **Phone B**: Enable Wireless Debugging (Settings → Developer Options)
3. On **Phone A** (Termux): Pair and connect to **Phone B's** IP and ports (same steps as Option A)
4. Run `adb devices` on Phone A — Phone B's IP should appear in the list
5. Note the IP:PORT — you will enter it into the bot menu

---

## 🚀 Step 6 — Run the Bot

```bash
python bunny_bot.py
```

The interactive menu will appear. Follow the on-screen prompts:

1. Set your **Gemini API Key** (option `2`) — paste the key you got in Step 2
2. Optionally set a **Target Device** (option `1`) — leave blank for local, or enter `IP:PORT` for remote
3. Press **`S`** to start the bot
4. **Switch to the game** — you have 5 seconds before the bot goes live

To stop the bot at any time, press **`Ctrl + C`** in Termux.

> **Pro Tip:** You can skip the API key prompt by setting it as an environment variable:
> ```bash
> export GEMINI_API_KEY="your_key_here"
> python bunny_bot.py
> ```

---

## 🎮 Menu Reference

| Option | Key | Description |
|---|---|---|
| Set Target Device | `1` | Leave blank for local. Enter `IP:PORT` for a remote phone. |
| Set Gemini API Key | `2` | Paste your Google AI Studio key here. |
| Toggle AI Mode | `3` | Switch between AI-assisted and pixel-only mode. |
| Start Bot | `S` | Launch the bot with current settings. |
| Quit | `Q` | Exit the program. |

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| `adb: command not found` | Run `pkg install android-tools -y` |
| Screen capture fails immediately | Run `adb kill-server`, then reconnect with `adb connect` |
| Bot not reacting to obstacles | Make sure OpenCV is installed via `pkg install opencv-python` |
| `ModuleNotFoundError: google.generativeai` | Run `pip install google-generativeai` |
| AI returning gibberish or errors | Check your API key is correct (Option 2 in menu) |
| Bot tap-spamming on open road | The reflex sensor is over-sensitive — this usually self-corrects after a few frames |
| `protocol fault` ADB error | Run `adb kill-server` first, then retry `adb connect` |
| Game not found when auto-restarting | Verify the package name in `bunny_bot.py` matches your installed game version |

---

## ⚙️ How It Works

BunnyBot uses a **two-layer decision system**:

```
Screen (ADB screencap)
        │
        ▼
┌─────────────────────────┐
│   AI Layer (every 2s)   │  ← Gemini 1.5 Flash reads the screen image
│   • Menu navigation     │     and outputs: MOVE LEFT / MOVE RIGHT / JUMP / TAP x y
│   • Ad detection        │
│   • Strategic decisions │
└─────────────────────────┘
        │
        ▼
┌─────────────────────────┐
│  Pixel Reflex (10fps)   │  ← OpenCV detects bright white fence pixels
│  • <100ms response      │     in the left/right danger zones
│  • No API calls needed  │     for instant sub-second dodging
└─────────────────────────┘
        │
        ▼
     ADB Tap / Swipe → Device
```

- The **AI layer** runs every ~2 seconds to handle complex decisions (menus, ads, strategic moves)
- The **Pixel Reflex layer** runs every frame (~100ms) for instant obstacle dodging without consuming API quota
- If OpenCV is not installed, the bot falls back to **AI-only mode**
- If no API key is provided, the bot runs in **pixel-only mode**

---

*Made with ❤️ — contributions welcome!*
