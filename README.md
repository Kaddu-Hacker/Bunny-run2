🐰 BunnyBot — Termux + Wireless ADB Edition

Fully autonomous Bunny Runner 3D bot running inside Termux.
Control the game locally on your phone, OR use one phone to control another!

✨ What's New

Remote Device Support — Host the script on Device A, play the game on Device B.

Anti-Hallucination — Bot detects if the screen capture fails instead of generating "fake logs".

10-Second Start Delay — Plenty of time to switch to the game.

🛠️ Complete Setup (Copy-Paste These One by One)

We need to install specific X11 and DBUS libraries to ensure the screen capture pipeline works flawlessly in Termux. Open Termux and paste each line one at a time:

# 1. Update package lists
pkg update && pkg upgrade -y

# 2. Install X11 repo and core tools
pkg install x11-repo -y
pkg install dbus libx11 android-tools git python -y

# 3. Install OpenCV binaries
pkg install opencv -y
apt install opencv-python -y

# 4. Grant storage access
termux-setup-storage


🔗 Connecting ADB (Local or Remote)

Playing on the SAME Phone:

Turn on Wireless Debugging in Developer Options.

Pair using: adb pair <IP>:<Pairing_Port>

Connect using: adb connect <IP>:<Connection_Port>

Playing on a DIFFERENT Phone (Remote Control):

Connect both phones to the same WiFi network.

On Phone B (The Game Phone): Turn on Wireless Debugging. Get the IP and Pairing Port.

On Phone A (The Script Phone): Open Termux and pair/connect to Phone B's IP exactly as you would locally.

Run adb devices. You will see Phone B's IP address listed. Note this down!

🎮 Running the Bot

cd ~/storage/shared
git clone [https://github.com/Kaddu-Hacker/Bunny-run2.git](https://github.com/Kaddu-Hacker/Bunny-run2.git)
cd Bunny-run2
python bunny_bot.py


The Pre-Flight Menu Options

Option

What it does

1. Target Device

Leave blank for local. If remote, enter the IP:PORT of Phone B.

2. Fence Sensitivity

Lower = react to thin fences. Raise to ignore false triggers.

3. White Level

Brightness that counts as "fence". Lower if fences are missed.

4. Ad-Skip Mode

Auto force-kills + relaunches game to skip unskippable ads.

5. Tap Cooldown

Min time between taps. Lower for faster turns.

🐛 Troubleshooting

Problem

Fix

Bot exits immediately with "Screen capture failed"

Run adb kill-server, then adb connect again.

Bot not reacting to fences

Lower White Level (try 190) or Sensitivity (try 200).

Bot tap-spamming on road

Raise White Level (try 230) or Sensitivity (try 800).

protocol fault

Run adb kill-server first, then retry.
