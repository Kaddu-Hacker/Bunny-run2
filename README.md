# 🐰 BunnyBot — Self-Learning AI Edition

> Fully autonomous **Bunny Runner 3D** bot running inside **Termux** on Android.
> Powered by a **Self-Learning AI system** using **PuterGenAI (Gemini)**, **OpenRouter**, or **Google AI Studio** for intelligent screen analysis and adaptive gameplay.
> Supports local (one phone) and remote (two-phone) ADB control.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux-green)
![AI](https://img.shields.io/badge/AI-OpenRouter%20%7C%20Google%20AI-orange)

---

## 📋 Table of Contents

1. [Features](#-features)
2. [Prerequisites](#-prerequisites)
3. [Step 1 — Termux Package Setup](#-step-1--termux-package-setup)
4. [Step 2 — Get an API Key](#-step-2--get-an-api-key)
5. [Step 3 — Clone the Repository](#-step-3--clone-the-repository)
6. [Step 4 — Install Python Dependencies](#-step-4--install-python-dependencies)
7. [Step 5 — Connect ADB](#-step-5--connect-adb)
8. [Step 6 — Run the Bot](#-step-6--run-the-bot)
9. [Menu Reference](#-menu-reference)
10. [How the Self-Learning System Works](#-how-the-self-learning-system-works)
11. [Template Images (Optional)](#-template-images-optional)
12. [Troubleshooting](#-troubleshooting)
13. [Architecture Overview](#-architecture-overview)

---

## ✨ Features

- 🧠 **Self-Learning AI** — On first run, the AI studies the game screen and builds a persistent `game_knowledge.json` rulebook. Rules are refined automatically after each session.
- 🤖 **Dual AI Provider Support** — Choose between **OpenRouter** (access to many models) or **Google AI Studio** directly. Switch live from the menu.
- 🆓 **PuterGenAI Bridge** — Optionally use the free [Puter.com](https://puter.com) AI bridge (no API key needed) via `putergenai`.
- ⚡ **Pixel Reflex Layer** — Sub-100ms obstacle detection via OpenCV with multi-scale template matching and lane brightness detection — no API calls needed during gameplay.
- 🎬 **Scrcpy H.264 Streaming** — Optional ultra-fast screen capture using a Scrcpy server and PyAV, bypassing slower `adb screencap` calls.
- 📱 **Termux-native** — No C++ compilation required; all dependencies install cleanly via `pkg` or `pip`.
- 🔗 **Local & Remote ADB** — Control the game on the same phone or remotely over Wi-Fi.
- 🛡️ **Graceful Fallback Chain** — Scrcpy stream → adbutils socket → subprocess `adb screencap`. If AI is unavailable, the bot runs in pixel-only mode.
- 👁️ **Supervisor AI Recovery** — If no obstacles are detected for 5 seconds, a background AI thread analyses the screen and handles menus, ads, or death screens automatically.
- 💾 **Persistent Knowledge Base** — The bot's learned rules survive across sessions and are stored in `game_knowledge.json`.

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
# 3. Install OpenCV and NumPy (mandatory for pixel-reflex and template matching)
#    ⚠️  Use pkg — do NOT use pip install opencv-python (it will hang or fail on Termux!)
pkg install python-numpy opencv-python -y
```

```bash
# 4. Grant Termux access to shared storage (recommended)
termux-setup-storage
```

---

## 🔑 Step 2 — Get an API Key

BunnyBot supports **two AI providers**. You only need one, but you can configure both and switch between them in the menu.

### Option A — OpenRouter (Recommended)

1. Go to **[https://openrouter.ai](https://openrouter.ai)**
2. Sign in and navigate to **Keys** → **Create Key**
3. Copy your key — it will start with `sk-or-...`
4. Many models on OpenRouter have a **free tier** — no credit card required for basic use

### Option B — Google AI Studio

1. Go to **[https://aistudio.google.com](https://aistudio.google.com)**
2. Sign in with your Google account
3. Click **"Get API Key"** → **"Create API Key"**
4. Copy your key — the free tier is sufficient for running the bot

> **Pro Tip:** You can also use the **PuterGenAI bridge** (Option `putergenai`) which requires no API key at all.
> Install it in Step 4 and the bot will use it automatically if no other key is configured.

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

This installs all required Python packages: `requests`, `adbutils`, `putergenai`, and optionally `av` (PyAV) for Scrcpy streaming.

### Full Dependency Summary

| Package | How to Install | Purpose |
|---|---|---|
| `python-numpy` | `pkg install python-numpy` | Required for pixel reflex (OpenCV) |
| `opencv-python` | `pkg install opencv-python` | Required for pixel reflex & template matching |
| `android-tools` | `pkg install android-tools` | Provides the `adb` command |
| `requests` | `pip install requests` | HTTP client for AI API calls |
| `adbutils` | `pip install adbutils` | Fast ADB socket interface (replaces subprocess) |
| `putergenai` | `pip install putergenai` | Free AI bridge via Puter.com (no key needed) |
| `av` (PyAV) | `pip install av` | Optional: Scrcpy H.264 stream decoding |

> ⚠️ **Termux Warning:** Never use `pip install opencv-python` or `pip install numpy` on Termux. Always use `pkg install python-numpy opencv-python`. The pip versions compile C++ and will hang indefinitely.

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

*(The connection port is shown on the main Wireless Debugging screen — it is different from the pairing port)*

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
5. Note the `IP:PORT` — you will enter it into the bot menu

---

## 🚀 Step 6 — Run the Bot

```bash
python bunny_bot.py
```

The interactive menu will appear. Follow the on-screen prompts:

1. Set your **OpenRouter Key** (option `1`) or **Google AI Key** (option `2`)
2. Select your **Active AI Method** (option `3`) — toggle between OpenRouter and Google
3. Optionally set a **Target Device** (option `4`) — leave blank for local, or enter `IP:PORT` for remote
4. Press **`S`** to start the bot
5. **Switch to the game** — you have 5 seconds before the bot goes live

To stop the bot at any time, press **`Ctrl + C`** in Termux. On shutdown, the bot will automatically consolidate any new observations into the knowledge base.

---

## 🎮 Menu Reference

| Option | Key | Description |
|---|---|---|
| Set OpenRouter API Key | `1` | Paste your OpenRouter key (starts with `sk-or-...`) |
| Set Google AI Studio Key | `2` | Paste your Google AI Studio key |
| Select Active AI Method | `3` | Toggle between OpenRouter and Google AI Studio |
| Set Target Device | `4` | Leave blank for local. Enter `IP:PORT` for a remote phone. |
| Toggle AI Mode | `5` | Switch between AI-assisted and pixel-only mode. |
| Clear Knowledge Base | `6` | Wipe `game_knowledge.json` and reset all learned rules. |
| Start Bot | `S` | Launch the bot with current settings. |
| Quit | `Q` | Exit the program. |

---

## 🧠 How the Self-Learning System Works

BunnyBot uses a **three-phase learning loop** combined with a **two-layer real-time decision system**:

### Phase 1 — Initial Game Learning (First Run Only)

On the very first session, if no rules exist in the knowledge base, the AI analyses a screenshot and generates a structured summary of the game: what to do in menus, how to react to obstacles, how to handle death screens and ads. This is saved to `game_knowledge.json`.

### Phase 2 — Live Gameplay

During each session, every action taken (by the reflex layer or AI) is logged as an observation along with the current game state (`PLAYING`, `DEAD`, `MAIN_MENU`, etc.).

### Phase 3 — Knowledge Consolidation (On Shutdown)

When you press `Ctrl+C`, the bot sends all new observations to the AI and asks it to extract any new rules not already covered. New rules are appended to the knowledge base for the next session. This means **the bot gets smarter every time you run it**.

```
game_knowledge.json
  ├── game_summary    — One-sentence game description
  ├── rules           — Accumulated gameplay rules
  ├── session_count   — Total sessions run
  └── new_observations— Current session log (cleared on consolidation)
```

---

## 🖼️ Template Images (Optional)

The pixel reflex layer supports **multi-scale template matching** for precise obstacle detection. To enable this, place grayscale PNG template images of in-game obstacles in the project root directory:

| Filename | Contents |
|---|---|
| `template_fence.png` | A cropped screenshot of a fence obstacle |
| `template_carrot.png` | A cropped screenshot of a carrot collectible |
| `template_rabbit.png` | A cropped screenshot of the bunny character |

Without these files, the bot falls back to **brightness-based lane detection**, which still works reliably.

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| `adb: command not found` | Run `pkg install android-tools -y` |
| Screen capture fails immediately | Run `adb kill-server`, then reconnect with `adb connect` |
| Bot not reacting to obstacles | Ensure OpenCV is installed via `pkg install opencv-python` |
| `ModuleNotFoundError: requests` | Run `pip install requests` |
| `ModuleNotFoundError: adbutils` | Run `pip install adbutils` |
| `ModuleNotFoundError: putergenai` | Run `pip install putergenai` |
| AI returning gibberish or no response | Verify your API key is correct via Option 1 or 2 in the menu |
| Bot tap-spamming on an open road | The reflex brightness threshold is triggering — this usually self-corrects after a few frames |
| `protocol fault` ADB error | Run `adb kill-server` first, then retry `adb connect` |
| Scrcpy stream not starting | Ensure `scrcpy-server.jar` is in the project root directory |
| Knowledge base seems wrong | Use Option 6 in the menu to reset it and let the bot re-learn |
| Game not found when auto-restarting | Verify `PACKAGE_NAME` in `bunny_bot.py` matches your installed game version (`com.bunny.runner3D.dg`) |

---

## ⚙️ Architecture Overview

BunnyBot uses a **two-layer real-time decision system** backed by a **persistent knowledge base**:

```
Screen (Scrcpy H.264 Stream / adbutils socket / adb screencap)
        │
        ▼
┌──────────────────────────────┐
│   AI Layer (background)      │  ← Only active on first run (Phase 1)
│   • Phase 1: Learn the game  │    or when Supervisor Recovery triggers.
│   • Phase 3: Consolidate     │    Uses OpenRouter / Google AI / PuterGenAI.
│   • Supervisor Recovery      │    Handles menus, ads, death screens.
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Pixel Reflex (~80ms loop)   │  ← Primary gameplay driver.
│  • Template matching (cv2)   │    No API calls. Uses OpenCV to detect
│  • Brightness lane detection │    obstacles and determine dodge direction.
│  • Supervisor trigger (5s)   │    Falls back to brightness scan if no
└──────────────────────────────┘    templates are found.
        │
        ▼
     ADB Tap / Swipe → Device
```

**Screen capture priority:** Scrcpy H.264 stream (fastest) → adbutils socket screenshot → subprocess `adb screencap` (slowest fallback).

**AI call priority:** PuterGenAI bridge → OpenRouter API → Google AI Studio API.

---

*Made with ❤️ — contributions welcome!*
