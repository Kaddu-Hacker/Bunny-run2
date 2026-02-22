# 🐰 Bunny Bot: Pure Python Edition (Google Colab Build)

A robust, standalone Android automation app for **Bunny Runner 3D**, built with Python, Kivy, and OpenCV. This version is optimized for stability and battery life.

---

## ✨ Key Features
- **🖼️ Smart Vision System**: Uses `cv2.matchTemplate` with dynamic loading to "see" the game.
- **🔋 Battery Optimized**: Runs vision checks on a 0.5s interval (Clock) instead of every frame.
- **📱 Floating UI**: All controls overlay the game using a robust `FloatLayout` architecture.
- **☁️ Google Colab Build**: No complex local setup required. Build your APK in the cloud.

---

## 🛠️ How to Build (Google Colab)

We have removed the GitHub Actions workflow in favor of a manual, controllable Colab build.

1. **Download this Repository**.
2. **Open Google Colab**: [colab.research.google.com](https://colab.research.google.com/).
3. **Upload Files**: Upload the following to the Colab runtime:
    - `colab_build.ipynb`
    - `main.py`
    - `buildozer.spec`
    - `core/` folder
    - `ui/` folder
    - `templates/` folder
4. **Open `colab_build.ipynb`** and run the cells in order.
5. **Download APK**: Once finished, download your APK from the `bin/` directory.

---

## 🏗️ New Architecture

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
├── colab_build.ipynb    # Build Script
├── main.py              # FloatLayout App Entry
├── buildozer.spec       # Build Configuration
├── templates/           # Reference Images (starting_btn.png, etc.)
├── core/                # Business Logic
│   ├── vision.py        # BunnyVision (Template Matching)
│   ├── controller.py    # Persistent Shell Controller
│   └── ...
└── ui/
    └── dashboard.py     # Menu UI
```

---

## 📝 License
MIT License - Developed by the Bunny Runner community.
