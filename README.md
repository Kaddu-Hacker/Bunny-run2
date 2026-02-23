# 🐰 BunnyBot — Termux + ADB Edition

A Bunny Runner 3D bot that runs entirely inside **Termux** via **Wireless ADB**. No APK, no Root, no PC required.

---

## ✨ How It Works

- **Screen Capture**: `adb exec-out screencap -p` pipes the screen frame directly into RAM.
- **Fence Detection**: Two "invisible sensor boxes" (ROI) scan for bright white pixels (HSV mask). No PNG templates needed.
- **ZigZag Engine**: If the left box fills with white → tap right. If right box fills → tap left.
- **Ad Dodge**: Detects the Win/End screen and force-kills + relaunches the game, skipping 30-second ads.

---

## 🛠️ Setup (One Time)

### 1. Install Termux
Install from [F-Droid](https://f-droid.org/packages/com.termux/) (NOT the Play Store — it's outdated).

### 2. Install Dependencies
```bash
pkg update -y && pkg upgrade -y
pkg install python opencv android-tools -y
termux-setup-storage
pip install numpy
```

### 3. Enable Wireless Debugging
Go to **Settings → Developer Options → Wireless Debugging** and toggle it ON. Tap it to see your IP and Port.

### 4. Connect ADB
```bash
adb connect 192.168.x.x:PORT   # Replace with your IP:Port
```
A popup will appear on the phone — tap **Always Allow**.

### 5. Get the Bot
```bash
cd ~/storage/shared
git clone https://github.com/Kaddu-Hacker/Bunny-run2.git
cd Bunny-run2
```

---

## 🚀 Running the Bot

```bash
python bot.py
```
Choose **[1] Run Bot** or **[2] Calibration**.

Immediately switch to Bunny Runner 3D — the bot will start scanning in 5 seconds.

To stop: press **CTRL+C**.

---

## 🎨 Calibration

If the bot is not reacting to fences, run in Calibration mode (`[2]`) with the bunny running on the path. It will print:

```
LEFT  sensor white pixels  : 12   (SENSITIVITY = 300)
RIGHT sensor white pixels  : 847  (SENSITIVITY = 300)
```

If fences are seen but count is below 300, **lower the SENSITIVITY** in `bot.py`.

---

## 📁 Files

```
Bunny-run2/
└── bot.py       # The entire bot — capture, detect, tap, loop
```

---

## 📝 License
MIT License
