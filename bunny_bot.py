import subprocess
import cv2
import numpy as np
import time
import os
import sys

# =============================================================================
#
#  BunnyBot — Final Unified Edition
#  Combines: Auto-Resolution + OOP (bunny_bot.py)
#            HSV ROI + State Machine + Watchdog + Telemetry (bot.py)
#            Pre-Flight Settings Menu
#
#  HOW TO RUN (Termux):
#    pkg install python opencv android-tools -y && pip install numpy
#    adb connect <your_ip>:<your_port>
#    python bunny_bot.py
#
# =============================================================================

PACKAGE_NAME  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60      # Auto-reset if stuck in any state > 60 seconds
ROAD_MISS_MAX = 30      # Consecutive frames without road before RECOVERING

# ==================== PRE-FLIGHT SETTINGS MENU ==============================

def main_menu():
    """Interactive terminal menu. Returns config dict to the bot on 'S'."""
    config = {
        "sensitivity":      400,    # Min white pixels in ROI to trigger dodge
        "white_level":      210,    # Grayscale brightness threshold for fences
        "ad_level":         240,    # Center pixel brightness that means "ad / menu"
        "tap_cooldown":     0.15,   # Seconds between taps (debounce)
        "road_dark_max":    150,    # Centre brightness below this = road detected
    }

    while True:
        os.system("clear")
        print("╔══════════════════════════════════════╗")
        print("║  🐰  BUNNYBOT — PRE-FLIGHT SETTINGS  ║")
        print("╠══════════════════════════════════════╣")
        print(f"║  1. Sensitivity   : {config['sensitivity']:<6}               ║")
        print(f"║     (min fence pixels — lower = faster react) ║")
        print(f"║  2. White Level   : {config['white_level']:<6}               ║")
        print(f"║     (fence brightness, 0-255)           ║")
        print(f"║  3. Ad Level      : {config['ad_level']:<6}               ║")
        print(f"║     (screen brightness that means 'Ad')  ║")
        print(f"║  4. Tap Cooldown  : {config['tap_cooldown']:<6}s              ║")
        print(f"║     (seconds between taps, min 0.05)     ║")
        print("╠══════════════════════════════════════╣")
        print("║  S. START BOT                        ║")
        print("║  Q. QUIT                             ║")
        print("╚══════════════════════════════════════╝")

        choice = input("\nOption → ").strip().upper()

        if choice == '1':
            val = input(f"  Sensitivity [current: {config['sensitivity']}] (100–2000): ").strip()
            if val.isdigit():
                config['sensitivity'] = int(val)
        elif choice == '2':
            val = input(f"  White Level [current: {config['white_level']}] (150–255): ").strip()
            if val.isdigit():
                config['white_level'] = int(val)
        elif choice == '3':
            val = input(f"  Ad Level [current: {config['ad_level']}] (200–255): ").strip()
            if val.isdigit():
                config['ad_level'] = int(val)
        elif choice == '4':
            val = input(f"  Tap Cooldown [current: {config['tap_cooldown']}] (0.05–1.0): ").strip()
            try:
                config['tap_cooldown'] = float(val)
            except ValueError:
                pass
        elif choice == 'S':
            os.system("clear")
            print("🚀  Launching BunnyBot...")
            print(f"   Sensitivity  : {config['sensitivity']}")
            print(f"   White Level  : {config['white_level']}")
            print(f"   Ad Level     : {config['ad_level']}")
            print(f"   Tap Cooldown : {config['tap_cooldown']}s")
            print("\nSwitch to Bunny Runner NOW — starting in 4 seconds!")
            time.sleep(4)
            return config
        elif choice == 'Q':
            print("Bye!")
            sys.exit(0)


# ==================== MAIN BOT CLASS ========================================

class BunnyBot:
    def __init__(self, config: dict):
        self.config         = config
        self.state          = "MENU"
        self.last_tap_time  = 0.0
        self.state_entered  = time.time()
        self.road_miss      = 0

        self._get_resolution()

        # Auto-calculate ROI sensor boxes as % of screen size
        # Left box:  20–40% width, 75–80% height
        # Right box: 60–80% width, 75–80% height
        # numpy slice order: [y_start:y_end, x_start:x_end]
        self.left_roi  = (int(self.h * 0.75), int(self.h * 0.80),
                          int(self.w * 0.20), int(self.w * 0.40))
        self.right_roi = (int(self.h * 0.75), int(self.h * 0.80),
                          int(self.w * 0.60), int(self.w * 0.80))

        # Pre-compute tap targets
        self.tap_left  = (int(self.w * 0.20), int(self.h * 0.50))
        self.tap_right = (int(self.w * 0.80), int(self.h * 0.50))
        self.tap_start = (self.w // 2,        int(self.h * 0.80))
        self.road_probe = (self.w // 2,       int(self.h * 0.80))

        print(f"✅  Screen: {self.w}x{self.h}")
        print(f"   Left  ROI : y {self.left_roi[0]}-{self.left_roi[1]}, "
              f"x {self.left_roi[2]}-{self.left_roi[3]}")
        print(f"   Right ROI : y {self.right_roi[0]}-{self.right_roi[1]}, "
              f"x {self.right_roi[2]}-{self.right_roi[3]}")

    # -------------------------------------------------------------------------
    # CORE: ADB / CAPTURE
    # -------------------------------------------------------------------------

    def _get_resolution(self):
        """Auto-detects screen resolution. Exits cleanly if ADB is not connected."""
        try:
            raw = subprocess.check_output(
                "adb shell wm size", shell=True, stderr=subprocess.DEVNULL
            ).decode().strip()
            # e.g. "Physical size: 1080x2400"
            size_part = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size_part.split("x"))
        except Exception:
            print("❌  ADB not connected. Run: adb connect <ip>:<port>")
            sys.exit(1)

    def get_screen(self):
        """
        Pipes screencap directly into RAM — no disk writes.
        Returns a GRAYSCALE image (faster than BGR for brightness checks).
        """
        try:
            pipe = subprocess.Popen(
                "adb exec-out screencap -p",
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            img_bytes = pipe.stdout.read()
            if len(img_bytes) < 100:
                return None
            return cv2.imdecode(
                np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_GRAYSCALE
            )
        except Exception:
            return None

    def _check_adb_alive(self):
        """Quick liveness check — returns False if ADB connection dropped."""
        try:
            out = os.popen("adb devices").read()
            lines = out.strip().split("\n")
            return any("device" in ln for ln in lines[1:])
        except Exception:
            return False

    def tap(self, x, y):
        """Fires a tap protected by the cooldown timer."""
        now = time.time()
        if now - self.last_tap_time < self.config["tap_cooldown"]:
            return
        os.system(f"adb shell input tap {int(x)} {int(y)}")
        self.last_tap_time = now

    # -------------------------------------------------------------------------
    # PART 2: ZIGZAG REFLEX ENGINE
    # -------------------------------------------------------------------------

    def check_sensors(self, screen):
        """
        Counts bright pixels in Left/Right ROI boxes using grayscale threshold.
        np.sum(roi > WHITE_LEVEL) is the fastest possible fence detection.
        Returns ('DODGE_LEFT'|'DODGE_RIGHT'|'CLEAR', l_count, r_count).
        """
        wl = self.config["white_level"]
        l_y1, l_y2, l_x1, l_x2 = self.left_roi
        r_y1, r_y2, r_x1, r_x2 = self.right_roi

        l_count = int(np.sum(screen[l_y1:l_y2, l_x1:l_x2] > wl))
        r_count = int(np.sum(screen[r_y1:r_y2, r_x1:r_x2] > wl))

        sensitivity = self.config["sensitivity"]
        if l_count > sensitivity and l_count >= r_count:
            return 'DODGE_RIGHT', l_count, r_count
        elif r_count > sensitivity:
            return 'DODGE_LEFT', l_count, r_count
        return 'CLEAR', l_count, r_count

    # -------------------------------------------------------------------------
    # PART 3: STATE MACHINE & AD-DODGE
    # -------------------------------------------------------------------------

    def _is_game_running(self, screen):
        """
        Checks if the road is visible by testing the brightness at road_probe.
        Returns True (dark road visible) or False (bright menu/ad).
        """
        px, py = self.road_probe
        if py >= screen.shape[0] or px >= screen.shape[1]:
            return False
        return int(screen[py, px]) < self.config["road_dark_max"]

    def _force_reset_game(self):
        """Kills and relaunches the game — bypasses 30-second ads in ~4 seconds."""
        print("\n🔴  AD/MENU DETECTED — Force resetting game...")
        os.system(f"adb shell am force-stop {PACKAGE_NAME}")
        time.sleep(1.5)
        os.system(f"adb shell monkey -p {PACKAGE_NAME} "
                  f"-c android.intent.category.LAUNCHER 1")
        print("🚀  Game relaunched. Waiting 7s for splash screen...")
        time.sleep(7)

    def _render_radar(self, l, r, action, fps):
        """Prints a one-line ASCII radar to give live visual feedback in Termux."""
        def bar(v):
            n = min(int(v / max(self.config["sensitivity"], 1) * 8), 8)
            return '#' * n + ' ' * (8 - n)

        dodge_ago = time.time() - self.last_tap_time
        print(
            f"[ L:{bar(l)} | R:{bar(r)} ] {action:12s} | "
            f"State:{self.state:10s} | Road:{self._last_road_ok!s:5} | "
            f"Tap:{dodge_ago:4.1f}s | {fps:4.1f} FPS    ",
            end='\r'
        )

    # -------------------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------------------

    def run(self):
        frame_count       = 0
        self._last_road_ok = False

        while True:
            loop_start = time.time()

            # ADB liveness check every 60 frames
            if frame_count % 60 == 0 and not self._check_adb_alive():
                print("\n⚠️   ADB dropped — retrying in 5s...")
                time.sleep(5)
                if not self._check_adb_alive():
                    print("❌  ADB still not connected. Exiting.")
                    sys.exit(1)

            # Watchdog: force reset if stuck in any state too long
            if time.time() - self.state_entered > WATCHDOG_SECS:
                print(f"\n⏱️   WATCHDOG: stuck in {self.state} — forcing reset")
                self._force_reset_game()
                self.state         = "MENU"
                self.state_entered = time.time()
                self.road_miss     = 0
                continue

            frame = self.get_screen()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_count += 1
            now = time.time()

            # ── MENU ─────────────────────────────────────────────────────────
            if self.state == "MENU":
                self._last_road_ok = self._is_game_running(frame)
                if self._last_road_ok:
                    print("\n🟢  Road detected — switching to PLAYING!")
                    self.state         = "PLAYING"
                    self.state_entered = now
                    self.road_miss     = 0
                else:
                    # Blind-tap start every 2 seconds
                    if now - self.last_tap_time > 2.0:
                        self.tap(*self.tap_start)
                        print("🕹️   Tapping Start...                             ", end='\r')

            # ── PLAYING ──────────────────────────────────────────────────────
            elif self.state == "PLAYING":
                self._last_road_ok = self._is_game_running(frame)

                # Track consecutive frames without road
                if self._last_road_ok:
                    self.road_miss = 0
                else:
                    self.road_miss += 1

                # Ad/game-over: check central brightness OR road-miss streak
                center_y, center_x = int(self.h * 0.8), self.w // 2
                center_bright = int(frame[center_y, center_x]) if \
                    center_y < frame.shape[0] and center_x < frame.shape[1] else 0

                if center_bright > self.config["ad_level"] or \
                        self.road_miss >= ROAD_MISS_MAX:
                    self.state         = "RECOVERING"
                    self.state_entered = now
                    continue

                # ZigZag reflexes
                action, l, r = self.check_sensors(frame)
                if action == 'DODGE_RIGHT':
                    self.tap(*self.tap_right)
                elif action == 'DODGE_LEFT':
                    self.tap(*self.tap_left)

                elapsed = time.time() - loop_start
                fps = 1.0 / elapsed if elapsed > 0 else 0
                self._render_radar(l, r, action, fps)

            # ── RECOVERING ───────────────────────────────────────────────────
            elif self.state == "RECOVERING":
                self._force_reset_game()
                self.state         = "MENU"
                self.state_entered = time.time()
                self.road_miss     = 0


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        config = main_menu()
        bot = BunnyBot(config)
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🛑  Bot stopped (CTRL+C). Bye!")
        sys.exit(0)
