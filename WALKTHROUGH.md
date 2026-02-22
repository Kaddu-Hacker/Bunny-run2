# 🎮 BunnyBot Pro - Standalone APK Walkthrough

## � Overview
Welcome to **BunnyBot Pro**, the standalone Android automation suite for Bunny Runner 3D. This app uses professional-grade OpenCV vision and native Android shell controllers to provide a "Zero-PC" automation experience.

---

## 🏗️ Core Technology

### 1. 🖼️ Robust Vision Engine (`core/vision.py`)
- **Multi-Scale Template Matching**: Automatically scales templates (80%, 90%, 100%) to ensure perfect UI detection regardless of your phone's resolution or DPI.
- **Canny Edge Detection**: Detects white picket fences as geometric lines, ensuring pinpoint navigation accuracy that is immune to shadows.

### 2. 📱 Native Android Controller (`core/controller.py`)
- **Kernel-Level Force Stop**: Uses `am force-stop` to reliably terminate the game and bypass mandatory ads.
- **Precision Relaunch**: Uses the `monkey` tool for a clean, cold-boot start of the game.
- **Hardware Gestures**: Executes direct `input tap` and `swipe` commands for ultra-fast response times.

---

## � Project Structure

```text
.
├── main.py              # Main Kivy Entry Point
├── buildozer.spec       # Android Build Config
├── assets/              # Template Images
├── core/                # Automation Logic
│   ├── vision.py        # OpenCV Eyes
│   ├── controller.py    # Gesture Hands
│   ├── wizard.py        # Config & Calibration
│   ├── vision_auto.py   # UI Scanner
│   └── permissions.py   # System Permission Links
└── ui/
    └── dashboard.py     # Kivy Menu System
```

---

## 🛠️ Setup & Calibration

### Step 1: APK Deployment
Since we have configured a CI/CD pipeline, you can simply push a version tag to GitHub to generate the installer:
```bash
git tag v1.0.0
git push origin v1.0.0
```

### Step 2: Permissions
When you launch the app for the first time:
1. Grant **Display Over Other Apps**.
2. Enable **Accessibility Service** (for non-root gesture support).

### Step 3: Passive Calibration
Open **BunnyBot Pro** and select **🎨 Step 1: Calibrate Path**. Play the game normally for 30 seconds while the bot "learns" the path's DNA in the background.

---

## ⚙️ Advanced Features

- **Ghost Reset**: Toggle this in the Dashboard to automatically skip ads via app restarting.
- **Multi-Scale Detection**: Already enabled! The bot works on 1080p, 1440p, and 720p screens out of the box.
- **Safe-Exit**: Press **Volume Down** for 2 seconds to immediately kill the automation loop.

---

## � Troubleshooting

- **Bot Misses Turns**: Check if "Blue Light Filter" or "Eye Comfort Shield" is active. These change screen colors and can interfere with OpenCV.
- **Ad-Dodge Fails**: Ensure you are in **One-Handed mode** if your device uses gestural navigation (swiping to kill cards works best with standard button nav).

---
**Happy Botting! 🐰🐍🏆**
