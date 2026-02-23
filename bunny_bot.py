import subprocess
import time
import os
import sys
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    # Only used for type-checking (IDE). At runtime Termux has these installed.
    import cv2  # type: ignore[import]
    import numpy as np  # type: ignore[import]
else:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401

# =============================================================================
#
#  BunnyBot — Final Unified Edition
#  Termux + Wireless ADB | No APK | No Root | No PC
#
#  QUICK START (copy-paste into Termux):
#    pkg update && pkg upgrade -y
#    pkg install python ndk-sysroot clang make libjpeg-turbo opencv android-tools -y
#    pip install numpy opencv-python
#    python bunny_bot.py
#
# =============================================================================

PACKAGE_NAME  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60      # Auto-reset if stuck in any state > 60 seconds
ROAD_MISS_MAX = 30      # Consecutive frames without road → trigger RECOVERING


# ==================== PRE-FLIGHT SETTINGS MENU ==============================

def main_menu():
    """Interactive terminal menu. Returns config dict when user presses S."""
    config = {
        "sensitivity":   500,    # Min white pixels in ROI to trigger dodge
        "white_level":   220,    # Grayscale brightness that counts as "white fence"
        "ad_level":      240,    # Center brightness that means "ad / menu screen"
        "tap_cooldown":  0.15,   # Seconds between taps (debounce)
        "road_dark_max": 150,    # Centre brightness below this = road detected
        "reset_ads":     True,   # Toggle Ad-Skip (force-stop + relaunch) ON/OFF
    }

    while True:
        os.system("clear")
        print("╔══════════════════════════════════════════╗")
        print("║  🐰  BUNNY RUNNER 3D — TERMINAL BOT 🐰   ║")
        print("╠══════════════════════════════════════════╣")
        print(f"║  1. Fence Sensitivity : {config['sensitivity']:<6}              ║")
        print(f"║     (lower = faster reflexes)            ║")
        print(f"║  2. White Level       : {config['white_level']:<6}              ║")
        print(f"║     (brightness of white fences, 0-255) ║")
        print(f"║  3. Ad-Skip Mode      : {'ON ✅' if config['reset_ads'] else 'OFF ❌'}                ║")
        print(f"║     (force-kills game to skip 30s ads)  ║")
        print(f"║  4. Tap Cooldown      : {config['tap_cooldown']:<6}s            ║")
        print(f"║     (min seconds between taps)          ║")
        print("╠══════════════════════════════════════════╣")
        print("║  S. START BOT                            ║")
        print("║  Q. QUIT                                 ║")
        print("╚══════════════════════════════════════════╝")

        choice = input("\nSelect (1-4) to tweak or S to Start: ").strip().upper()

        if choice == '1':
            val = input(f"  Sensitivity [{config['sensitivity']}] (100–2000): ").strip()
            if val.isdigit(): config['sensitivity'] = int(val)
        elif choice == '2':
            val = input(f"  White Level [{config['white_level']}] (150–255): ").strip()
            if val.isdigit(): config['white_level'] = int(val)
        elif choice == '3':
            config['reset_ads'] = not config['reset_ads']
            print(f"  Ad-Skip is now {'ON' if config['reset_ads'] else 'OFF'}")
            time.sleep(0.8)
        elif choice == '4':
            val = input(f"  Tap Cooldown [{config['tap_cooldown']}] (0.05–1.0): ").strip()
            try: config['tap_cooldown'] = float(val)
            except ValueError: pass
        elif choice == 'S':
            os.system("clear")
            print("🚀  Launching BunnyBot!")
            print(f"   Sensitivity  : {config['sensitivity']}")
            print(f"   White Level  : {config['white_level']}")
            print(f"   Ad-Skip      : {'ON' if config['reset_ads'] else 'OFF'}")
            print(f"   Tap Cooldown : {config['tap_cooldown']}s")
            print("\nSwitch to Bunny Runner NOW — starting in 4 seconds...")
            time.sleep(4)
            return config
        elif choice == 'Q':
            print("Bye! 🐰")
            sys.exit(0)

    # Fallback — should never reach here, but satisfies the type checker
    return config


# ==================== MAIN BOT CLASS ========================================

class BunnyBot:
    def __init__(self, config: dict):
        self.config        = config
        self.state         = "MENU"
        self.last_tap_time = 0.0
        self.state_entered = time.time()
        self.road_miss     = 0
        self._last_road_ok = False
        # Declared here so the type-checker knows they exist before _get_resolution sets them
        self.w: int        = 0
        self.h: int        = 0

        self._get_resolution()

        # ── ROI sensor boxes (auto-calculated as % of screen size) ──────────
        # Left box:  10–40% width,  80–85% height   (where left fences appear)
        # Right box: 60–90% width,  80–85% height   (where right fences appear)
        # numpy slice: [y_start:y_end, x_start:x_end]
        self.left_roi  = (int(self.h * 0.80), int(self.h * 0.85),
                          int(self.w * 0.10), int(self.w * 0.40))
        self.right_roi = (int(self.h * 0.80), int(self.h * 0.85),
                          int(self.w * 0.60), int(self.w * 0.90))

        # Pre-compute tap targets
        self.tap_left   = (int(self.w * 0.20), int(self.h * 0.50))
        self.tap_right  = (int(self.w * 0.80), int(self.h * 0.50))
        self.tap_start  = (self.w // 2,        int(self.h * 0.80))
        self.road_probe = (self.w // 2,        int(self.h * 0.80))

        print(f"✅  Screen : {self.w}x{self.h}")
        print(f"   Left  ROI : y {self.left_roi[0]}-{self.left_roi[1]}, "
              f"x {self.left_roi[2]}-{self.left_roi[3]}")
        print(f"   Right ROI : y {self.right_roi[0]}-{self.right_roi[1]}, "
              f"x {self.right_roi[2]}-{self.right_roi[3]}\n")

    # ── ADB / CAPTURE ────────────────────────────────────────────────────────

    def _get_resolution(self):
        """Auto-detects screen size via ADB. Exits cleanly if not connected."""
        try:
            raw = subprocess.check_output(
                "adb shell wm size", shell=True, stderr=subprocess.DEVNULL
            ).decode().strip()
            # e.g. "Physical size: 1080x2400"
            size_part = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size_part.split("x"))
        except Exception:
            print("❌  ADB not connected!")
            print("    Step 1: adb pair <ip>:<pair_port>  (use pairing code)")
            print("    Step 2: adb connect <ip>:<port>")
            sys.exit(1)

    def get_frame(self):
        """Pipes screencap directly into RAM — no SD card writes, near-instant."""
        try:
            pipe = subprocess.Popen(
                "adb exec-out screencap -p",
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            if pipe.stdout is None:
                return None
            data: bytes = cast(bytes, pipe.stdout.read())
            if len(data) < 100:
                return None
            return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        except Exception:
            return None

    def _check_adb_alive(self) -> bool:
        try:
            out: str = os.popen("adb devices").read()
            lines: list = out.strip().split("\n")
            rest = lines[1:]  # type: ignore[misc]
            return any("device" in ln for ln in rest)
        except Exception:
            return False

    def tap(self, x, y):
        """Fires a tap with cooldown guard to prevent double-tapping one fence."""
        now = time.time()
        if now - self.last_tap_time < self.config["tap_cooldown"]:
            return
        os.system(f"adb shell input tap {int(x)} {int(y)}")
        self.last_tap_time = now

    # ── ZIGZAG REFLEX ENGINE (Part 2) ────────────────────────────────────────

    def check_sensors(self, frame):
        """
        np.sum(roi > WHITE_LEVEL) is the fastest fence detection possible.
        No HSV conversion needed — grayscale brightness is enough for white fences.
        Returns ('DODGE_LEFT'|'DODGE_RIGHT'|'CLEAR', l_count, r_count).
        """
        wl           = self.config["white_level"]
        sensitivity  = self.config["sensitivity"]

        l_y1, l_y2, l_x1, l_x2 = self.left_roi
        r_y1, r_y2, r_x1, r_x2 = self.right_roi

        l_count = int(np.sum(frame[l_y1:l_y2, l_x1:l_x2] > wl))
        r_count = int(np.sum(frame[r_y1:r_y2, r_x1:r_x2] > wl))

        if l_count > sensitivity and l_count >= r_count:
            return 'DODGE_RIGHT', l_count, r_count
        elif r_count > sensitivity:
            return 'DODGE_LEFT', l_count, r_count
        return 'CLEAR', l_count, r_count

    # ── STATE MACHINE & AD-DODGE (Part 3) ────────────────────────────────────

    def _is_game_running(self, frame):
        """Returns True if the brown road is visible (dark center pixel)."""
        px, py = self.road_probe
        if py >= frame.shape[0] or px >= frame.shape[1]:
            return False
        return int(frame[py, px]) < self.config["road_dark_max"]

    def _force_reset_game(self):
        """Ad-Dodge: kills + relaunches game. Skips 30s ads in ~4 seconds."""
        if not self.config["reset_ads"]:
            print("\n⚠️   Ad detected but Ad-Skip is OFF. Waiting 35 seconds...")
            time.sleep(35)
            return
        print("\n🔴  AD/FREEZE DETECTED — Force resetting...")
        os.system(f"adb shell am force-stop {PACKAGE_NAME}")
        time.sleep(1.5)
        os.system(f"adb shell monkey -p {PACKAGE_NAME} "
                  f"-c android.intent.category.LAUNCHER 1")
        print("🚀  Relaunched. Waiting 7s for splash screen...")
        time.sleep(7)

    def _render_radar(self, l, r, action, fps):
        """One-line ASCII radar — shows what the bot sees without a GUI."""
        def bar(v):
            n = min(int(v / max(self.config["sensitivity"], 1) * 8), 8)
            return '#' * n + ' ' * (8 - n)
        dodge_ago = time.time() - self.last_tap_time
        ads_str   = "ON" if self.config["reset_ads"] else "OFF"
        print(
            f"[ L:{bar(l)} | R:{bar(r)} ] {action:12s} | "
            f"{self.state:10s} | Road:{self._last_road_ok!s:5} | "
            f"Tap:{dodge_ago:4.1f}s | AdSkip:{ads_str} | {fps:4.1f} FPS    ",
            end='\r'
        )

    # ── MAIN LOOP ─────────────────────────────────────────────────────────────

    def start_loop(self) -> None:
        frame_count: int = 0

        while True:
            loop_start = time.time()

            # ADB liveness check every 60 frames
            if (frame_count % 60) == 0 and not self._check_adb_alive():  # type: ignore[operator]
                print("\n⚠️   ADB connection dropped — waiting 5s...")
                time.sleep(5)
                if not self._check_adb_alive():
                    print("❌  ADB lost. Exiting.")
                    sys.exit(1)

            # Watchdog: stuck-state protection
            if time.time() - self.state_entered > WATCHDOG_SECS:
                print(f"\n⏱️   WATCHDOG fired in {self.state} — forcing reset")
                self._force_reset_game()
                self.state         = "MENU"
                self.state_entered = time.time()
                self.road_miss     = 0
                continue

            frame = self.get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_count = frame_count + 1  # type: ignore[operator]
            now = time.time()

            # ── MENU ─────────────────────────────────────────────────────────
            if self.state == "MENU":
                self._last_road_ok = self._is_game_running(frame)
                if self._last_road_ok:
                    print("\n🟢  Road detected — PLAYING!")
                    self.state         = "PLAYING"
                    self.state_entered = now
                    self.road_miss     = 0
                else:
                    # Blind-tap the start button every 2 seconds
                    if now - self.last_tap_time > 2.0:
                        self.tap(*self.tap_start)
                        print("🕹️   Tapping Start...                              ", end='\r')

            # ── PLAYING ──────────────────────────────────────────────────────
            elif self.state == "PLAYING":
                self._last_road_ok = self._is_game_running(frame)
                self.road_miss = 0 if self._last_road_ok else self.road_miss + 1

                # Detect ad: center pixel very bright OR road gone too long
                cx, cy        = self.w // 2, int(self.h * 0.8)
                center_bright = int(frame[cy, cx]) if cy < frame.shape[0] else 0

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
                fps     = 1.0 / elapsed if elapsed > 0 else 0
                self._render_radar(l, r, action, fps)

            # ── RECOVERING ───────────────────────────────────────────────────
            elif self.state == "RECOVERING":
                self._force_reset_game()
                self.state         = "MENU"
                self.state_entered = time.time()
                self.road_miss     = 0


# ==================== ENTRY POINT ============================================

if __name__ == "__main__":
    try:
        config = main_menu()
        bot    = BunnyBot(config)
        bot.start_loop()
    except KeyboardInterrupt:
        print("\n\n🛑  Bot stopped (CTRL+C). Bye! 🐰")
        sys.exit(0)
