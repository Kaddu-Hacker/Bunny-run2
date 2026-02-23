import subprocess
import cv2
import numpy as np
import os
import sys
import time

# =============================================================================
#
#  BunnyBot for Termux — Part 2: Dynamic Reflex Engine
#
#  HOW TO RUN:
#    1. Enable Wireless Debugging in Developer Options.
#    2. In Termux: pkg install python opencv android-tools -y
#    3. Connect: adb connect <your_ip>:<your_port>
#    4. Run:     python bot.py
#
#  CALIBRATING FOR YOUR PHONE:
#    - Different phones have different resolutions. The key variables to
#      adjust are ROI_LEFT, ROI_RIGHT, and the tap coordinates in COORDINATES.
#    - Run in CALIBRATE mode first to see your screen's actual colors.
#
# =============================================================================


# --- GAME SETTINGS -----------------------------------------------------------
GAME_PACKAGE = "com.bunny.runner3D.dg"

# --- COORDINATES (Tuned for 1080x2400) ---------------------------------------
# If your phone has a different resolution, scale these proportionally.
# E.g. for 1080x1920: scale Y values by 1920/2400 = 0.8
COORDINATES = {
    "START_BUTTON":     (540, 2000),  # Main menu start button
    "TAP_LEFT":         (200, 1200),  # Where to tap to dodge left
    "TAP_RIGHT":        (880, 1200),  # Where to tap to dodge right
    "SCREEN_CENTER":    (540, 1200),  # Used for calibration
}

# --- ROI (Region Of Interest) SENSOR BOXES -----------------------------------
# Format: (x_start, y_start, x_end, y_end)
# These define the two invisible "tripwire" boxes on screen.
# Place them at the "knee level" of the bunny — just ahead of where
# the bunny is running, where fences first become a threat.
#
# HOW TO TUNE:
#   - On a 1080x2400 screen, the path occupies roughly x: 200-880, y: 1600-2000
#   - Place sensors in the lower third of that running zone
ROI_LEFT  = (200, 1750, 480, 1900)   # (x1, y1, x2, y2) — Left sensor box
ROI_RIGHT = (600, 1750, 880, 1900)   # (x1, y1, x2, y2) — Right sensor box

# --- HSV COLOR RANGES --------------------------------------------------------
# White fence HSV range. Fences are bright, nearly-white objects.
# HSV white = low Saturation, high Value.
# Tweak FENCE_LOWER[2] (Value/Brightness) if you get false positives.
FENCE_LOWER = np.array([0,   0,   200])
FENCE_UPPER = np.array([180, 50,  255])

# --- SENSITIVITY -------------------------------------------------------------
# Min "white pixel count" in an ROI to trigger a dodge.
# Lower = more sensitive (will react earlier, may false-trigger on bright sky).
# Higher = less sensitive (might miss a thin fence).
# Start at 300 and adjust based on test runs.
SENSITIVITY = 300

# Scale factor for ROI resize before processing (speeds up color masking)
# 0.5 = shrink to half size → 4x fewer pixels to process
RESIZE_SCALE = 0.5

# --- COOLDOWN ----------------------------------------------------------------
# Minimum time between taps (seconds). Prevents double-tap spam on one fence.
TAP_COOLDOWN = 0.15


# =============================================================================
# CORE ENGINE
# =============================================================================

def check_adb_connection():
    """Verifies ADB is connected. Exits with a clear error if not."""
    output = os.popen("adb devices").read()
    lines = output.strip().split("\n")
    connected = any("device" in line for line in lines[1:])
    if not connected:
        print("=" * 50)
        print("❌  ADB is NOT connected.")
        print("    Run: adb connect <your_ip>:<your_port>")
        print("    (Find it in Settings > Developer Options > Wireless Debugging)")
        print("=" * 50)
        sys.exit(1)
    device_id = lines[1].split()[0]
    print(f"✅  ADB Connected: {device_id}")
    return device_id


def get_screen():
    """
    Captures the screen, piping directly into RAM (no disk writes).
    Returns a BGR OpenCV image, or None on failure.
    """
    try:
        pipe = subprocess.Popen(
            "adb exec-out screencap -p",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        img_bytes = pipe.stdout.read()
        if len(img_bytes) < 100:
            return None
        img_array = np.frombuffer(img_bytes, np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception:
        return None


def tap(x, y):
    """Fires a raw tap into the Android system via ADB."""
    os.system(f"adb shell input tap {x} {y}")


def get_pixel_hsv(image, x, y):
    """Returns the HSV tuple at pixel (x, y). Useful for calibration."""
    pixel_bgr = image[y, x]
    pixel_arr = np.uint8([[pixel_bgr]])
    return cv2.cvtColor(pixel_arr, cv2.COLOR_BGR2HSV)[0][0]


# =============================================================================
# PART 2 — THE DYNAMIC REFLEX ENGINE
# =============================================================================

def get_sensor_data(frame):
    """
    Crops the frame into Left and Right ROI boxes, applies the HSV fence mask,
    and returns the white pixel count for each sensor after downscaling.

    Returns:
        (left_count, right_count) — number of white pixels detected in each box.
    """
    h, w = frame.shape[:2]

    # Unpack ROI coordinates
    l_x1, l_y1, l_x2, l_y2 = ROI_LEFT
    r_x1, r_y1, r_x2, r_y2 = ROI_RIGHT

    # Safety clamp to screen bounds
    l_x1, l_x2 = max(0, l_x1), min(w, l_x2)
    l_y1, l_y2 = max(0, l_y1), min(h, l_y2)
    r_x1, r_x2 = max(0, r_x1), min(w, r_x2)
    r_y1, r_y2 = max(0, r_y1), min(h, r_y2)

    left_roi  = frame[l_y1:l_y2, l_x1:l_x2]
    right_roi = frame[r_y1:r_y2, r_x1:r_x2]

    def count_fence_pixels(roi):
        if roi.size == 0:
            return 0
        # Downscale for speed (RESIZE_SCALE controls how small)
        small = cv2.resize(roi, None, fx=RESIZE_SCALE, fy=RESIZE_SCALE,
                           interpolation=cv2.INTER_NEAREST)
        hsv   = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask  = cv2.inRange(hsv, FENCE_LOWER, FENCE_UPPER)
        return cv2.countNonZero(mask)

    left_count  = count_fence_pixels(left_roi)
    right_count = count_fence_pixels(right_roi)

    return left_count, right_count


def check_obstacles(frame):
    """
    Reads sensor data and decides whether to dodge.

    Returns:
        'DODGE_LEFT'  — fence on the RIGHT sensor, tap left
        'DODGE_RIGHT' — fence on the LEFT sensor, tap right
        'CLEAR'       — nothing detected
    """
    left_count, right_count = get_sensor_data(frame)

    if left_count > SENSITIVITY and left_count >= right_count:
        return 'DODGE_RIGHT', left_count, right_count
    elif right_count > SENSITIVITY:
        return 'DODGE_LEFT', left_count, right_count
    return 'CLEAR', left_count, right_count


def render_ascii_radar(left_count, right_count, action):
    """
    Prints a mini ASCII radar bar to the terminal.
    Helps you visualize what the sensors are seeing without a GUI.

      [ L: #### | R:      ] DODGE_RIGHT
      [ L:      | R: #### ] DODGE_LEFT
      [ L:      | R:      ] CLEAR
    """
    def bar(count):
        filled = min(int(count / SENSITIVITY * 4), 8)
        return '#' * filled + ' ' * (8 - filled)

    l_bar = bar(left_count)
    r_bar = bar(right_count)
    label = f" → {action}" if action != 'CLEAR' else ""
    print(f"[ L:{l_bar} | R:{r_bar} ] {action}{label}          ", end='\r')


# =============================================================================
# CALIBRATION MODE
# =============================================================================

def run_calibration():
    """
    Captures ONE frame and reports HSV colors at key coordinates.
    Use this to tune FENCE_LOWER/FENCE_UPPER and the ROI positions.
    """
    print("\n" + "=" * 55)
    print("🎨  CALIBRATION MODE")
    print("    Open the game and make sure the bunny is running.")
    print("=" * 55)
    frame = get_screen()
    if frame is None:
        print("❌  Capture failed. Check ADB connection.")
        return

    h, w = frame.shape[:2]
    print(f"✅  Captured frame: {w}x{h}\n")

    for name, (x, y) in COORDINATES.items():
        if y < h and x < w:
            hsv = get_pixel_hsv(frame, x, y)
            print(f"  {name:20s} ({x:4d},{y:4d}) → HSV [{hsv[0]:3d}, {hsv[1]:3d}, {hsv[2]:3d}]")
        else:
            print(f"  {name:20s} ({x:4d},{y:4d}) → OUT OF BOUNDS")

    # Also show current sensor readings
    l_count, r_count = get_sensor_data(frame)
    print(f"\n  LEFT  sensor white pixels  : {l_count}  (SENSITIVITY = {SENSITIVITY})")
    print(f"  RIGHT sensor white pixels  : {r_count}  (SENSITIVITY = {SENSITIVITY})")
    print("\nRun again on the game screen while a fence is visible")
    print("to find the right SENSITIVITY value.")
    print("=" * 55 + "\n")


# =============================================================================
# MAIN GAME LOOP
# =============================================================================

def main():
    print("\n🐰  BunnyBot — Part 2: Dynamic Reflex Engine")
    print("=" * 45)
    check_adb_connection()
    print(f"    Sensitivity : {SENSITIVITY} pixels")
    print(f"    Cooldown    : {TAP_COOLDOWN}s")
    print(f"    ROI Left    : {ROI_LEFT}")
    print(f"    ROI Right   : {ROI_RIGHT}")

    mode = input("\nMode? [1] Run Bot  [2] Calibration  → ").strip()
    if mode == "2":
        run_calibration()
        return

    print("\n✅  Bot armed! Switch to the game. Starting in 5 seconds...")
    time.sleep(5)

    last_tap_time = 0.0
    state = "MENU"
    frame_count = 0

    while True:
        loop_start = time.time()

        frame = get_screen()
        if frame is None:
            time.sleep(0.05)
            continue

        if state == "MENU":
            # Tap the start button location every second until we start moving
            cx, cy = COORDINATES["START_BUTTON"]
            tap(cx, cy)
            print("🕹️   Waiting for game start...                          ", end='\r')
            time.sleep(1.0)
            state = "PLAYING"
            print("\n🎮  Switched to PLAYING state!")

        elif state == "PLAYING":
            action, l_count, r_count = check_obstacles(frame)
            render_ascii_radar(l_count, r_count, action)

            now = time.time()
            if action != 'CLEAR' and (now - last_tap_time) > TAP_COOLDOWN:
                if action == 'DODGE_RIGHT':
                    tap(*COORDINATES["TAP_RIGHT"])
                elif action == 'DODGE_LEFT':
                    tap(*COORDINATES["TAP_LEFT"])
                last_tap_time = now

        frame_count += 1
        elapsed = time.time() - loop_start
        fps = 1.0 / elapsed if elapsed > 0 else 0

        if frame_count % 30 == 0:
            print(f"\n  ⚡ {fps:.1f} FPS | Frames: {frame_count}                   ")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑  Bot stopped by user (CTRL+C). Bye!")
        sys.exit(0)
