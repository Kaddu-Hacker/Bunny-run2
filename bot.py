import subprocess
import cv2
import numpy as np
import os
import sys
import time

# =============================================================================
#
#  BunnyBot for Termux — FINAL (Part 1 + 2 + 3)
#  Image Capture + ZigZag Reflexes + State Machine + Ad-Dodge
#
#  HOW TO RUN:
#    1. Settings → Developer Options → Wireless Debugging → ON
#    2. pkg install python opencv android-tools -y && pip install numpy
#    3. adb connect <your_ip>:<your_port>
#    4. python bot.py
#
# =============================================================================

# --- SETTINGS ----------------------------------------------------------------
GAME_PACKAGE  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60      # If stuck in any state > 60s → force reset
ROAD_MISS_MAX = 30      # Consecutive frames with no road → assume ad/menu

# --- COORDINATES (1080x2400 screen — scale proportionally for other sizes) ---
COORDINATES = {
    "START_BUTTON":  (540, 2000),
    "TAP_LEFT":      (200, 1200),
    "TAP_RIGHT":     (880, 1200),
    "ROAD_PROBE":    (540, 1850),   # Sample point on the brown running path
}

# --- ROI SENSOR BOXES (x1, y1, x2, y2) — "tripwire" zones for fences --------
# Placed at bunny "knee level" where fences appear first.
# Lower the Y values if the bot reacts too late.
ROI_LEFT  = (200, 1750, 480, 1900)
ROI_RIGHT = (600, 1750, 880, 1900)

# --- HSV COLOR RANGES --------------------------------------------------------
# White fences: bright, low-saturation
FENCE_LOWER = np.array([0,   0,   200])
FENCE_UPPER = np.array([180, 50,  255])

# Brown road: warm hue, medium sat/value — tune with Calibration mode
ROAD_LOWER  = np.array([5,   60,  60])
ROAD_UPPER  = np.array([25,  255, 220])

# --- TUNING VARS -------------------------------------------------------------
SENSITIVITY  = 300      # Min white pixels in ROI to trigger dodge
RESIZE_SCALE = 0.5      # Downscale ROIs before HSV mask (speeds up detection)
TAP_COOLDOWN = 0.15     # Seconds between taps (prevents double-tap)


# === STATES ==================================================================
STATE_MENU      = "MENU"
STATE_PLAYING   = "PLAYING"
STATE_RECOVERING = "RECOVERING"


# =============================================================================
# CORE ENGINE
# =============================================================================

def check_adb_connection():
    output = os.popen("adb devices").read()
    lines  = output.strip().split("\n")
    connected = any("device" in ln for ln in lines[1:])
    if not connected:
        print("❌  ADB NOT connected. Run: adb connect <ip>:<port>")
        sys.exit(1)
    print(f"✅  ADB connected: {lines[1].split()[0]}")


def get_screen():
    """Captures screen directly to RAM. Returns BGR image or None."""
    try:
        pipe = subprocess.Popen(
            "adb exec-out screencap -p",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        img_bytes = pipe.stdout.read()
        if len(img_bytes) < 100:
            return None
        return cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def tap(x, y):
    os.system(f"adb shell input tap {x} {y}")


def get_pixel_hsv(image, x, y):
    pixel = np.uint8([[image[y, x]]])
    return cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]


# =============================================================================
# PART 2 — ZIGZAG REFLEX ENGINE
# =============================================================================

def get_sensor_data(frame):
    """Returns (left_white_count, right_white_count) for the two ROI boxes."""
    h, w = frame.shape[:2]

    def _crop_and_count(x1, y1, x2, y2):
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return 0
        small = cv2.resize(roi, None, fx=RESIZE_SCALE, fy=RESIZE_SCALE,
                           interpolation=cv2.INTER_NEAREST)
        mask = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV),
                           FENCE_LOWER, FENCE_UPPER)
        return cv2.countNonZero(mask)

    return _crop_and_count(*ROI_LEFT), _crop_and_count(*ROI_RIGHT)


def check_obstacles(frame):
    """Returns ('DODGE_LEFT'|'DODGE_RIGHT'|'CLEAR', l_count, r_count)."""
    l, r = get_sensor_data(frame)
    if l > SENSITIVITY and l >= r:
        return 'DODGE_RIGHT', l, r
    elif r > SENSITIVITY:
        return 'DODGE_LEFT', l, r
    return 'CLEAR', l, r


def render_ascii_radar(l, r, action, state, fps, last_dodge_secs, road_ok):
    def bar(v):
        n = min(int(v / SENSITIVITY * 8), 8)
        return '#' * n + ' ' * (8 - n)

    road_str = "YES" if road_ok else " NO"
    dodge_str = f"{last_dodge_secs:5.1f}s ago" if last_dodge_secs < 9999 else "never    "
    print(
        f"[ L:{bar(l)} | R:{bar(r)} ] {action:12s} | "
        f"State:{state:10s} | Road:{road_str} | "
        f"LastDodge:{dodge_str} | {fps:4.1f} FPS   ",
        end='\r'
    )


# =============================================================================
# PART 3 — STATE MACHINE & AD-DODGE
# =============================================================================

def is_game_running(frame):
    """Samples ROAD_PROBE pixel. Returns True if the path brown is visible."""
    x, y = COORDINATES["ROAD_PROBE"]
    h, w = frame.shape[:2]
    if y >= h or x >= w:
        return False
    hsv = get_pixel_hsv(frame, x, y)
    probe_arr = np.array([[hsv]])
    mask = cv2.inRange(probe_arr, ROAD_LOWER, ROAD_UPPER)
    return cv2.countNonZero(mask) > 0


def force_reset_game():
    """Ad-Dodge: kills the game and relaunches it — bypasses unskippable ads."""
    print("\n🔴  AD/CRASH DETECTED — Force resetting game...")
    os.system(f"adb shell am force-stop {GAME_PACKAGE}")
    time.sleep(1.5)
    print("🚀  Relaunching game via monkey...")
    os.system(f"adb shell monkey -p {GAME_PACKAGE} -c android.intent.category.LAUNCHER 1")
    # Give splash screen time to appear before we start tapping
    print("⏳  Waiting 7s for splash screen to load...")
    time.sleep(7)


def check_adb_still_alive():
    """Lightweight ADB liveness check. Returns False if connection was dropped."""
    output = os.popen("adb devices").read()
    return "device" in output.split("\n")[1] if len(output.split("\n")) > 1 else False


# =============================================================================
# CALIBRATION MODE
# =============================================================================

def run_calibration():
    print("\n" + "="*55)
    print("🎨  CALIBRATION MODE — Point the phone at the running game")
    print("="*55)
    frame = get_screen()
    if frame is None:
        print("❌  Capture failed.")
        return

    h, w = frame.shape[:2]
    print(f"✅  Frame: {w}x{h}\n")

    for name, (x, y) in COORDINATES.items():
        if y < h and x < w:
            hsv = get_pixel_hsv(frame, x, y)
            print(f"  {name:16s} ({x:4d},{y:4d}) → HSV [{hsv[0]:3d}, {hsv[1]:3d}, {hsv[2]:3d}]")
        else:
            print(f"  {name:16s} ({x:4d},{y:4d}) → OUT OF BOUNDS")

    l, r = get_sensor_data(frame)
    road = is_game_running(frame)
    print(f"\n  LEFT  sensor white px : {l}   (vs SENSITIVITY={SENSITIVITY})")
    print(f"  RIGHT sensor white px : {r}   (vs SENSITIVITY={SENSITIVITY})")
    print(f"  Road detected (brown) : {'YES ✅' if road else 'NO ❌  — tune ROAD_LOWER/ROAD_UPPER'}")
    print("="*55 + "\n")


# =============================================================================
# MAIN BOT LOOP
# =============================================================================

def main():
    print("\n🐰  BunnyBot — Final (Part 1 + 2 + 3)")
    print("="*42)
    check_adb_connection()

    mode = input("\n[1] Run Bot   [2] Calibrate   → ").strip()
    if mode == "2":
        run_calibration()
        return

    print("\n✅  Armed! Switch to the game — starting in 5 seconds...")
    time.sleep(5)

    state           = STATE_MENU
    state_entered   = time.time()
    last_tap_time   = 0.0
    last_dodge_time = 9999.0
    road_miss_count = 0
    frame_count     = 0

    while True:
        loop_start = time.time()

        # --- ADB liveness watchdog ---
        if frame_count % 60 == 0 and not check_adb_still_alive():
            print("\n⚠️   ADB connection dropped — waiting 5s then retrying...")
            time.sleep(5)
            if not check_adb_still_alive():
                print("❌  ADB still down. Exiting.")
                sys.exit(1)

        frame = get_screen()
        if frame is None:
            time.sleep(0.1)
            continue

        frame_count += 1
        now = time.time()

        # --- Watchdog: stuck-state protection ---
        if now - state_entered > WATCHDOG_SECS:
            print(f"\n⏱️   WATCHDOG: Stuck in {state} for {WATCHDOG_SECS}s — forcing reset")
            force_reset_game()
            state         = STATE_MENU
            state_entered = now
            road_miss_count = 0
            continue

        # =====================================================================
        # STATE MACHINE
        # =====================================================================

        if state == STATE_MENU:
            # Blind-tap the start button every 3 seconds until road appears
            if now - last_tap_time > 3.0:
                tx, ty = COORDINATES["START_BUTTON"]
                tap(tx, ty)
                last_tap_time = now
                print("🕹️   Tapping START...                                  ", end='\r')

            if is_game_running(frame):
                print("\n🟢  Road detected! Switching to PLAYING...")
                state         = STATE_PLAYING
                state_entered = now
                road_miss_count = 0

        elif state == STATE_PLAYING:
            road_ok = is_game_running(frame)

            if road_ok:
                road_miss_count = 0
            else:
                road_miss_count += 1

            # If road is gone for too many consecutive frames → ad/game-over
            if road_miss_count >= ROAD_MISS_MAX:
                print(f"\n🔴  Road lost for {ROAD_MISS_MAX} frames → switching to RECOVERING")
                state         = STATE_RECOVERING
                state_entered = now
                road_miss_count = 0
                continue

            # Run the ZigZag reflex engine
            action, l_count, r_count = check_obstacles(frame)

            if action != 'CLEAR' and (now - last_tap_time) > TAP_COOLDOWN:
                if action == 'DODGE_RIGHT':
                    tap(*COORDINATES["TAP_RIGHT"])
                else:
                    tap(*COORDINATES["TAP_LEFT"])
                last_tap_time  = now
                last_dodge_time = now

            elapsed = time.time() - loop_start
            fps = 1.0 / elapsed if elapsed > 0 else 0
            dodge_ago = now - last_dodge_time if last_dodge_time != 9999.0 else 9999
            render_ascii_radar(l_count, r_count, action, state, fps, dodge_ago, road_ok)

        elif state == STATE_RECOVERING:
            force_reset_game()
            state         = STATE_MENU
            state_entered = time.time()
            last_tap_time = 0.0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑  Stopped by user (CTRL+C). Bye!")
        sys.exit(0)
