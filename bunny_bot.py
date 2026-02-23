import subprocess
import cv2
import numpy as np
import time
import os
import sys

# --- CONFIGURATION (Tweak these if needed) ---
SENSITIVITY  = 400   # How many 'white' pixels count as a fence
WHITE_LEVEL  = 210   # How 'bright' the white fence is (0-255)
AD_LEVEL     = 240   # How bright the center pixel must be to trigger ad-dodge
TAP_COOLDOWN = 0.15  # Seconds between taps (prevents spam-tapping one fence)
PACKAGE_NAME = "com.bunny.runner3D.dg"


class BunnyBot:
    def __init__(self):
        self.state          = "MENU"
        self.last_tap_time  = 0.0
        self.get_resolution()

        # Auto-calculate ROI sensor boxes from screen percentages.
        # Left box:  20–40% width,  75–80% height
        # Right box: 60–80% width,  75–80% height
        # ROI format for numpy slicing: [y_start, y_end, x_start, x_end]
        self.left_roi  = (int(self.h * 0.75), int(self.h * 0.80),
                          int(self.w * 0.20), int(self.w * 0.40))
        self.right_roi = (int(self.h * 0.75), int(self.h * 0.80),
                          int(self.w * 0.60), int(self.w * 0.80))

        # Pre-calculate tap targets (avoids repeated float math)
        self.tap_left  = (int(self.w * 0.2), int(self.h * 0.5))
        self.tap_right = (int(self.w * 0.8), int(self.h * 0.5))
        self.tap_start = (self.w // 2,       int(self.h * 0.8))

        print(f"   Left  ROI : rows {self.left_roi[0]}-{self.left_roi[1]}, "
              f"cols {self.left_roi[2]}-{self.left_roi[3]}")
        print(f"   Right ROI : rows {self.right_roi[0]}-{self.right_roi[1]}, "
              f"cols {self.right_roi[2]}-{self.right_roi[3]}")

    def get_resolution(self):
        """Auto-detects screen resolution via ADB. Exits if ADB is not connected."""
        try:
            raw = subprocess.check_output(
                "adb shell wm size", shell=True, stderr=subprocess.DEVNULL
            ).decode().strip()
            # Output is "Physical size: 1080x2400" (may vary by device)
            size_part = raw.split(":")[-1].strip()   # "1080x2400"
            self.w, self.h = map(int, size_part.split("x"))
            print(f"✅  Screen Detected: {self.w}x{self.h}")
        except Exception:
            print("❌  ADB is not connected or 'wm size' failed.")
            print("    Run: adb connect <your_ip>:<your_port>")
            sys.exit(1)

    def get_screen(self):
        """High-speed capture — pipes screencap directly to RAM (no disk writes)."""
        try:
            pipe = subprocess.Popen(
                "adb exec-out screencap -p",
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            img_bytes = pipe.stdout.read()
            if len(img_bytes) < 100:
                return None
            # Decode as GRAYSCALE — faster processing, 1/3 the data
            return cv2.imdecode(
                np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_GRAYSCALE
            )
        except Exception:
            return None

    def tap(self, x, y):
        """Fires a tap with cooldown protection to prevent double-tapping."""
        now = time.time()
        if now - self.last_tap_time < TAP_COOLDOWN:
            return
        os.system(f"adb shell input tap {int(x)} {int(y)}")
        self.last_tap_time = now

    def check_sensors(self, screen):
        """
        Counts bright (white) pixels in the Left and Right ROI sensor boxes.
        Uses numpy threshold instead of full HSV pipeline — extremely fast.
        Returns True if a tap was triggered.
        """
        l_y1, l_y2, l_x1, l_x2 = self.left_roi
        r_y1, r_y2, r_x1, r_x2 = self.right_roi

        l_crop = screen[l_y1:l_y2, l_x1:l_x2]
        r_crop = screen[r_y1:r_y2, r_x1:r_x2]

        l_count = int(np.sum(l_crop > WHITE_LEVEL))
        r_count = int(np.sum(r_crop > WHITE_LEVEL))

        # ASCII radar — visual debug in Termux console
        def bar(v):
            n = min(int(v / SENSITIVITY * 8), 8)
            return '#' * n + ' ' * (8 - n)
        print(f"[ L:{bar(l_count)} | R:{bar(r_count)} ]  State:{self.state}      ", end='\r')

        if l_count > SENSITIVITY:
            print(f"\n🚧 FENCE LEFT  → TAPPING RIGHT  (L:{l_count})")
            self.tap(*self.tap_right)
            return True
        if r_count > SENSITIVITY:
            print(f"\n🚧 FENCE RIGHT → TAPPING LEFT   (R:{r_count})")
            self.tap(*self.tap_left)
            return True
        return False

    def ad_dodge(self):
        """Force-kills the game and relaunches it — skips unskippable ads in ~4s."""
        print("\n🔴  WHITE SCREEN DETECTED — Killing game to skip ad...")
        os.system(f"adb shell am force-stop {PACKAGE_NAME}")
        time.sleep(1.5)
        os.system(f"adb shell monkey -p {PACKAGE_NAME} "
                  f"-c android.intent.category.LAUNCHER 1")
        print("🚀  Game relaunched. Waiting 7s for splash screen...")
        time.sleep(7)
        self.state = "MENU"

    def run(self):
        print("\n🤖  BOT STARTED. Switch to Bunny Runner NOW!")
        print("    (You have 3 seconds)")
        time.sleep(3)

        while True:
            frame = self.get_screen()
            if frame is None:
                time.sleep(0.05)
                continue

            if self.state == "MENU":
                # Blind-tap start every 2 seconds until the game screen loads.
                # The road path appears dark/brown (~50-120 brightness in grayscale).
                # If center is NO LONGER a very bright menu/white, we assume playing.
                self.tap(*self.tap_start)
                print("🕹️   Tapping Start button...                              ", end='\r')

                center_y = int(self.h * 0.8)
                center_x = self.w // 2
                center_brightness = int(frame[center_y, center_x])

                # If center is dark (road), we've entered gameplay
                if center_brightness < 150:
                    print(f"\n🟢  Road detected (brightness={center_brightness})! Switching to PLAYING")
                    self.state = "PLAYING"
                else:
                    time.sleep(2)

            elif self.state == "PLAYING":
                # 1. Run fence sensors
                self.check_sensors(frame)

                # 2. Check for ad / game-over (whole center becomes very bright white)
                center_pixel = int(frame[int(self.h * 0.8), self.w // 2])
                if center_pixel > AD_LEVEL:
                    self.ad_dodge()


if __name__ == "__main__":
    try:
        bot = BunnyBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🛑  Bot stopped (CTRL+C). Bye!")
        sys.exit(0)
