# 🐰 BunnyBot — Termux + ADB Edition

Fully autonomous Bunny Runner 3D bot running inside **Termux** via **Wireless ADB**. No APK, no Root, no PC.

---

## ✨ How It Works

- **Auto-Resolution** — reads your phone's screen size via `adb shell wm size`. No manual pixel math.
- **RAM-Speed Capture** — pipes `screencap` directly into a NumPy array (no SD card writes).
- **Grayscale Sensors** — two "tripwire" ROI boxes count bright pixels for fence detection instantly.
- **Full State Machine** — `MENU → PLAYING → RECOVERING` with Watchdog and ADB liveness check.
- **Ad-Dodge** — force-kills + monkey-relaunches the game, skipping 30s ads in ~4 seconds.
- **Pre-Flight Menu** — configure Sensitivity, White Level, and cooldown before the bot starts.

---

## 🛠️ Setup (One Time)

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) (NOT Play Store).

2. In Termux:
```bash
pkg update -y && pkg upgrade -y
pkg install python opencv android-tools -y
pip install numpy
termux-setup-storage
```

3. Enable **Wireless Debugging** in Settings → Developer Options → Wireless Debugging.

4. Connect ADB:
```bash
adb connect <your_ip>:<your_port>    # IP shown on the Wireless Debugging screen
```
Allow the popup that appears on your phone.

5. Clone the bot:
```bash
cd ~/storage/shared
git clone https://github.com/Kaddu-Hacker/Bunny-run2.git
cd Bunny-run2
```

---

## 🚀 Running the Bot

```bash
python bunny_bot.py
```

You will see the settings menu. Use it to tune the values, then press **S** to start. Switch to Bunny Runner — the bot will kick in automatically.

To stop: **CTRL+C**

---

## 🎨 Settings Guide

| Setting | Default | What to do if bot is wrong |
|---|---|---|
| **Sensitivity** | 400 | Lower if fences are missed. Raise if bot twitches randomly. |
| **White Level** | 210 | Lower if fences aren't detected. Raise if road causes false triggers. |
| **Ad Level** | 240 | Lower if ad-dodge doesn't fire. Raise if it fires during gameplay. |
| **Tap Cooldown** | 0.15s | Lower for faster reflexes. Raise to reduce tap spam. |

---

## 🖥️ What You'll See in Termux

```
[ L:########  | R:          ] DODGE_RIGHT | State:PLAYING    | Road:True | Tap: 0.1s | 16.4 FPS
```

---

## 📁 Files

| File | Purpose |
|---|---|
| `bunny_bot.py` | The entire bot — one file, self-contained |

---

## 📝 License
MIT License
