[app]
title = BunnyBot Pro
package.name = bunnybot
package.domain = org.bunnybot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0

# CRITICAL: Must include 'android' and 'opencv' (not opencv-python)
requirements = python3,kivy==2.2.1,opencv,numpy,android

# Permissions for Zero-PC Automation
android.permissions = INTERNET,SYSTEM_ALERT_WINDOW,FOREGROUND_SERVICE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 31
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True

# Features
android.entrypoint = org.kivy.android.PythonActivity
android.wakelock = True
android.bootstrap = sdl2
android.arch = armeabi-v7a

# Supported orientations
orientation = portrait

# Fullscreen mode
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 1
