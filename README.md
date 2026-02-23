# 🐰 BunnyBot — Termux + Wireless ADB Edition

Fully autonomous Bunny Runner 3D bot running inside **Termux** on your Android phone.  
No APK, No Root, No PC required.

---

## ✨ How It Works

- **Auto-Resolution** — reads screen size automatically via `adb shell wm size`
- **RAM-Speed Capture** — pipes `screencap` directly into Python (no SD card writes)
- **Grayscale Sensors** — two invisible ROI boxes count fence pixels instantly
- **State Machine** — `MENU → PLAYING → RECOVERING` handles every game situation
- **Ad-Dodge** — force-kills + relaunches the game, skipping 30s ads in ~4 seconds
- **Pre-Flight Menu** — tune Sensitivity, White Level, and Ad-Skip before starting

---

## 🛠️ Complete Setup (Copy-Paste These One by One)

### Step 1 — Install Termux

> ⚠️ Download from **[F-Droid](https://f-droid.org/packages/com.termux/)** only.  
> The Play Store version is outdated and will give errors.

---

### Step 2 — Install All Tools

Open Termux and paste **each line one at a time**:

```bash
# 1. Update package lists
pkg update && pkg upgrade -y

# 2. Install Python, Git, and ADB
pkg install python git android-tools -y

# 3. Enable the TUR repo and install OpenCV (the most reliable way)
pkg install tur-repo -y
pkg up
pkg install opencv -y
```

> 💡 **Why `opencv` instead of `python-opencv`?**  
> In many Termux versions, the package is just called `opencv`. Installing it after adding the `tur-repo` ensures you get the high-speed Python bindings automatically.

> ⚠️ **DO NOT run `pip install opencv-python`** — it tries to compile OpenCV from C++ source
> and will hang for hours. The `pkg install python-opencv` command above gives you the same
> library as a pre-built binary, installing in seconds.

```bash
# 4. Grant storage access (a popup will appear — tap Allow)
termux-setup-storage
```

---

### Step 3 — Enable Wireless Debugging (Android 11+)

1. Go to **Settings → About Phone** and tap **Build Number** 7 times to unlock Developer Options.
2. Go to **Settings → Developer Options → Wireless Debugging** and turn it **ON** (stay connected to WiFi).
3. **CRITICAL — THE TWO PORTS:**
   - **Main Screen:** Shows your IP and the **CONNECTION PORT** (e.g., `192.168.1.5:44321`).
   - **Inside "Pair device":** Tap it to see the **PAIRING PORT** (e.g., `192.168.1.5:33455`) and the **6-digit code**.

---

### Step 4 — Connect ADB in Termux

If `adb pair` gives an error like **"protocol fault"**, first run:  
`adb kill-server`  
Then try again.

#### Part A: Pair (Use the PAIRING Port)
Tap "Pair device with pairing code" on your phone. In Termux, type:
```bash
adb pair <IP>:<Pairing_Port>
```
Enter the **6-digit code** when asked. It should say "Successfully paired".

#### Part B: Connect (Use the CONNECTION Port)
Now look at the **MAIN Wireless Debugging screen** for the Port shown under "IP address & Port". This is usually different from the pairing port!
```bash
adb connect <IP>:<Connection_Port>
```

> 💡 **The Popup:** Only *after* you run the `connect` command will a popup appear on your phone asking to "Allow USB Debugging?". Tap **Always Allow**.

#### Part C: Verify
```bash
adb devices
# Success looks like: 192.168.x.x:PORT    device
```

---

### Step 5 — Get the Bot

```bash
cd ~/storage/shared
git clone https://github.com/Kaddu-Hacker/Bunny-run2.git
cd Bunny-run2
```

---

### Step 6 — Run It

```bash
python bunny_bot.py
```

The Pre-Flight menu appears. Tune your settings, then press **S**.  
Immediately switch to Bunny Runner — the bot starts in 4 seconds.

To stop: **CTRL+C**

---

## 🎮 Pre-Flight Menu Options

| Option | Default | What it does |
|---|---|---|
| **1. Fence Sensitivity** | 500 | Lower = react to thin fences. Raise to ignore false triggers. |
| **2. White Level** | 220 | Brightness that counts as "fence". Lower if fences are missed. |
| **3. Ad-Skip Mode** | ON | Auto force-kills + relaunches game to skip unskippable ads. |
| **4. Tap Cooldown** | 0.15s | Min time between taps. Lower for faster turns. |

---

## 🖥️ What You'll See in Termux

```
[ L:########  | R:          ] DODGE_RIGHT | PLAYING    | Road:True | Tap: 0.1s | AdSkip:ON | 16.4 FPS
```

---

## ❓ Pairing Code Keeps Changing?

The code and port reset every time you navigate away from the "Pair device" dialog. Use one of these two tricks:

### ✅ Method 1 — Split Screen (Easiest)
1. Open both **Termux** and **Settings** (Wireless Debugging on).
2. Long-press the **Recents button** → tap the Termux window title → choose **Split screen**.
3. Pick **Settings** for the bottom half.
4. Tap **"Pair device with pairing code"** in Settings (bottom half).
5. The port and code are visible — tap Termux (top half) and type `adb pair IP:PORT` while looking at the code below.
6. Enter the 6-digit code without ever switching screens. ✅

### ✅ Method 2 — Pre-Type
1. In Termux, type `adb pair 192.168.` but **don't press Enter yet**.
2. Switch to Settings → tap "Pair device" → quickly note the rest of the IP, port, and 6-digit code.
3. Switch back to Termux — your partial command is still there — finish typing and press Enter.
4. When it asks `Enter pairing code:` → type the 6 digits.

> 💡 **Good news:** Once you successfully pair, you **never need to pair again** — even after reboots. Only `adb connect` is needed next time.

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| `protocol fault` during pairing | Run `adb kill-server` first, then retry |
| `ADB not connected` | Re-run `adb connect <IP>:<Connection_Port>` |
| Bot not reacting to fences | Lower **Sensitivity** (try 200) or lower **White Level** (try 190) |
| Bot tap-spamming on road | Raise **Sensitivity** (try 800) or raise **White Level** (try 230) |
| Ad-Dodge not firing | Lower **Ad Level** in code to 220 |
| Screen capture too slow | Normal on first run — Termux warms up after ~10 frames |

---

## 📁 Files

| File | Purpose |
|---|---|
| `bunny_bot.py` | The entire bot — one file, self-contained |
| `requirements.txt` | Python dependencies (`pip install -r requirements.txt`) |

---

## 📝 License
MIT License
