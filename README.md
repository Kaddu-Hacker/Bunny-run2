# 🐰 Bunny Bot: Pure Python Edition (Automatic Build)

A robust, standalone Android automation app for **Bunny Runner 3D**, built with Python, Kivy, and OpenCV. This version is optimized for stability, compatibility, and automatic releases.

---

## ✨ Key Features
- **🖼️ Smart Vision System**: Uses `cv2.matchTemplate` with dynamic loading to "see" the game.
- **🔋 Battery Optimized**: Runs vision checks on a 0.5s interval (Clock) instead of every frame.
- **📱 Floating UI**: All controls overlay the game using a robust `FloatLayout` architecture.
- **🤖 Automatic Builds**: GitHub Actions automatically builds and releases APKs on every push.
- **✅ Fixed OpenCV**: Proper Android-compatible OpenCV integration (no more opencv-python issues).
- **🛡️ Enhanced Error Handling**: Crash logs saved to `/sdcard/bunnybot_crash.log` for debugging.

---

## 🚀 How to Get the APK

### Option 1: Download from GitHub Releases (Recommended)
1. Go to the [Releases page](../../releases)
2. Download the latest `BunnyBot-v*.apk` file
3. Install on your Android device
4. Grant all requested permissions

### Option 2: Build Automatically with GitHub Actions
1. Fork this repository
2. Push any changes to the `main` branch
3. GitHub Actions will automatically build the APK
4. Download from the Releases page or Actions artifacts

### Option 3: Manual Build (Advanced)
```bash
# Install buildozer
pip install buildozer

# Build APK
buildozer android debug

# APK will be in bin/ directory
```

---

## 🔧 What Was Fixed

### 1. **buildozer.spec** (Critical)
- ✅ Changed `opencv-python` to `opencv` (Android compatible)
- ✅ Added `FOREGROUND_SERVICE` permission
- ✅ Set API level to 31 (more stable than 33)
- ✅ Proper requirements: `python3,kivy==2.2.1,opencv,numpy,android`

### 2. **main.py** (Entry Point)
- ✅ All imports moved inside `build()` method for Android compatibility
- ✅ Path verification at startup to catch missing templates
- ✅ Enhanced error handling with crash logs
- ✅ Proper exception catching at app level

### 3. **GitHub Actions** (Automation)
- ✅ Automatic APK building on every push
- ✅ Automatic release creation with versioning
- ✅ APK uploaded as both release asset and artifact
- ✅ No manual intervention needed

### 4. **Cleanup**
- ✅ Removed `colab_build.ipynb` (obsolete)
- ✅ Removed `build.gradle` (not needed for buildozer)
- ✅ Removed `build.sh` (replaced by GitHub Actions)

---

## 🏗️ Architecture

### 1. Vision (`core/vision.py`)
- **Logic**: Grayscale Template Matching (Threshold: 0.85).
- **Templates**: All reference images are stored in `templates/`.
- **Dynamic**: Automatically loads any `.png` found in the folder.

### 2. UI (`main.py` & `ui/dashboard.py`)
- **Root**: `FloatLayout`.
- **Overlay**: The dashboard sits at the bottom 40% of the screen.

### 3. Controller (`core/controller.py`)
- **Persistent Shell**: Maintains an open connection to the Android shell for instant tap response.

---

## 📁 Project Structure

```text
.
├── .github/
│   └── workflows/
│       └── build-apk.yml     # Automatic APK build workflow
├── main.py                   # Fixed entry point with error handling
├── buildozer.spec            # Fixed configuration for Android
├── templates/                # Reference Images (starting_btn.png, etc.)
├── core/                     # Business Logic
│   ├── vision.py             # BunnyVision (Template Matching)
│   ├── controller.py         # Persistent Shell Controller
│   ├── wizard.py             # Configuration wizard
│   ├── vision_auto.py        # Auto UI scanning
│   └── permissions.py        # Permission handling
└── ui/
    └── dashboard.py          # Menu UI
```

---

## 🐛 Debugging

If the app crashes on your device:

1. Check `/sdcard/bunnybot_crash.log` for error details
2. Ensure all permissions are granted (especially `SYSTEM_ALERT_WINDOW`)
3. Verify templates are included in the APK (they should be)
4. Check Android version (min API 21, recommended 31+)

---

## 📝 License
MIT License - Developed by the Bunny Runner community.

---

## 🎯 Next Steps

After installation:
1. **Grant Permissions**: Allow overlay and storage access
2. **Calibrate Path**: Use "Step 1: Calibrate Path" in the app
3. **Run Bot**: Click "🚀 RUN BOT" and let it play!

---

## 🤝 Contributing

1. Fork the repository
2. Make your changes
3. Push to `main` branch
4. GitHub Actions will automatically build and test
5. Create a Pull Request

---

**Enjoy your automated Bunny Runner! 🐰✨**
