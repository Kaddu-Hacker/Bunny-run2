import subprocess
import cv2
import numpy as np
import os
import sys

# =============================================================================
#
#  BunnyBot for Termux — Part 1: Foundation
#
#  This script acts as the "Clean Slate" foundation for the bot.
#  It handles ADB connection, screen capture, color detection, and
#  prints a single calibration frame so you can tune the color values
#  to your specific phone and game settings.
#
#  HOW TO RUN:
#    1. Connect via ADB: `adb connect <your_ip>:<your_port>`
#    2. Run this script: `python bot.py`
#    3. Look at the HSV values it prints for your phone's pixel colors.
#
# =============================================================================


# --- STEP 1: COORDINATE MAP (Tuned for 1080x2400 resolution) ---------------
# Adjust these for your specific phone resolution!
# Format: (X, Y)
COORDINATES = {
    "START_BUTTON":  (540, 2000),  # Center-bottom of the main menu start button
    "LEFT_SENSOR":   (300, 1800),  # Bottom-left area where fences appear
    "RIGHT_SENSOR":  (780, 1800),  # Bottom-right area where fences appear
    "SCREEN_CENTER": (540, 1200),  # Dead center of the screen (used for calibration)
}


# --- STEP 2: HSV COLOR RANGES -----------------------------------------------
# These are starting values. You will need to tune them to match
# the exact colors of the fences and path in your game.
# Use the calibration output from this script to dial them in.
HSV_FENCE_WHITE = {
    "lower": np.array([0,   0,   200]),  # Very bright, near-white pixels
    "upper": np.array([180, 30,  255]),
}
HSV_PATH_BROWN = {
    "lower": np.array([5,   70,  80]),   # The earthy brown running path
    "upper": np.array([20,  255, 200]),
}


# =============================================================================
# CORE ENGINE — Functions
# =============================================================================

def check_adb_connection():
    """Checks if ADB is connected to a device. Exits if not."""
    output = os.popen("adb devices").read()
    lines = output.strip().split("\n")
    # lines[0] is always "List of devices attached"
    # lines[1] onward are actual devices (or empty)
    connected = any("device" in line for line in lines[1:])
    if not connected:
        print("=" * 50)
        print("❌ ERROR: ADB is NOT connected.")
        print("   Please run: adb connect <your_ip>:<your_port>")
        print("   (You can find the IP and Port in Developer Options > Wireless Debugging)")
        print("=" * 50)
        sys.exit(1)
    else:
        print("✅ ADB Connected:", lines[1].split()[0])


def get_screen():
    """
    Captures the screen using ADB and pipes it DIRECTLY into RAM as a BGR image.
    No slow disk writes. No intermediate PNG files on your SD card.
    Returns an OpenCV image (NumPy array) or None if the capture fails.
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
            print("⚠️  Warning: Screen capture returned too few bytes. Is the screen on?")
            return None

        image = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        return image
    except Exception as e:
        print(f"⚠️  Screen capture error: {e}")
        return None


def tap(x, y):
    """Injects a raw tap into the Android system via ADB. Fast and direct."""
    os.system(f"adb shell input tap {x} {y}")


def is_color_present(image, lower_hsv, upper_hsv, region=None):
    """
    Detects if an HSV color range is visible in the image (or a sub-region of it).

    Args:
        image:      The full-screen OpenCV BGR image.
        lower_hsv:  NumPy array for the lower HSV bound.
        upper_hsv:  NumPy array for the upper HSV bound.
        region:     Optional tuple (x, y, width, height) to restrict scanning.
                    If None, scans the entire image.

    Returns:
        True if the color is found in the region, False otherwise.
    """
    target = image
    if region is not None:
        x, y, w, h = region
        target = image[y:y+h, x:x+w]

    hsv = cv2.cvtColor(target, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
    # Consider "found" if even a small number of matching pixels exist
    return np.count_nonzero(mask) > 0


def get_pixel_hsv(image, x, y):
    """Returns the HSV color at a single pixel coordinate (x, y)."""
    pixel_bgr = image[y, x]  # OpenCV uses [row, col] = [y, x]
    # cv2.cvtColor needs a 1x1x3 array
    pixel_bgr_arr = np.uint8([[pixel_bgr]])
    pixel_hsv = cv2.cvtColor(pixel_bgr_arr, cv2.COLOR_BGR2HSV)
    return pixel_hsv[0][0]


# =============================================================================
# CALIBRATION ONE-SHOT — Run this first to get your color values!
# =============================================================================

def run_calibration():
    """
    Captures ONE frame and prints the HSV value of the key coordinate points.
    Use this to tune the HSV_FENCE_WHITE and HSV_PATH_BROWN ranges above.
    """
    print("\n" + "="*50)
    print("🎨  CALIBRATION MODE")
    print("="*50)
    print("Capturing a single frame... Make sure the game is on screen!")
    
    screen = get_screen()
    if screen is None:
        print("❌ Capture failed. Exiting.")
        return

    height, width = screen.shape[:2]
    print(f"✅ Screen captured! Resolution: {width}x{height}")
    print()

    print("Reading pixel colors at defined COORDINATE points:\n")
    for name, (x, y) in COORDINATES.items():
        # Ensure coordinates are within the captured screen bounds
        if y < height and x < width:
            hsv = get_pixel_hsv(screen, x, y)
            print(f"  🔎 {name:20s} @ ({x:4d}, {y:4d})  →  HSV: [{hsv[0]:3d}, {hsv[1]:3d}, {hsv[2]:3d}]")
        else:
            print(f"  ⚠️  {name:20s} @ ({x:4d}, {y:4d})  →  OUT OF BOUNDS for this screen!")

    print()
    print("HOW TO USE THIS:")
    print("  1. Run the bot while on the GAME screen (on the brown path).")
    print("  2. Look at the HSV values of LEFT_SENSOR and RIGHT_SENSOR.")
    print("     Those are your 'path brown' values. Set HSV_PATH_BROWN accordingly.")
    print("  3. Run it again when a WHITE FENCE is visible near a sensor.")
    print("     Those are your fence values. Set HSV_FENCE_WHITE accordingly.")
    print("="*50 + "\n")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("🐰 BunnyBot — Part 1 Foundation")
    print("================================")
    
    # 1. Verify ADB connection first. Will exit if not connected.
    check_adb_connection()
    
    # 2. Run the calibration one-shot.
    run_calibration()
