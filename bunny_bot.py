import subprocess
import time
import os
import sys
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    import cv2  # type: ignore[import]
    import numpy as np  # type: ignore[import]
else:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401

# =============================================================================
#  BunnyBot — Tap Precision Edition
#  Termux + Wireless ADB | Multi-Device Support
# =============================================================================

PACKAGE_NAME  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60      
ROAD_MISS_MAX = 30      

def main_menu():
    config = {
        "device_id":     "",     
        "sensitivity":   500,    
        "white_level":   220,    
        "ad_level":      240,    
        "tap_cooldown":  0.15,   
        "road_dark_max": 150,    
        "reset_ads":     True,   
    }

    while True:
        os.system("clear")
        print("╔══════════════════════════════════════════════╗")
        print("║  🐰  BUNNY RUNNER 3D — TAP EDITION 🐰      ║")
        print("╠══════════════════════════════════════════════╣")
        dev_display = config['device_id'] if config['device_id'] else "Local/Default"
        print(f"║  1. Target Device  : {dev_display:<18} ║")
        print(f"║  2. Sensitivity    : {config['sensitivity']:<6}                 ║")
        print(f"║  3. White Level    : {config['white_level']:<6}                 ║")
        print(f"║  4. Ad-Skip Mode   : {'ON ✅' if config['reset_ads'] else 'OFF ❌'}                   ║")
        print(f"║  5. Tap Cooldown   : {config['tap_cooldown']:<6}s               ║")
        print("╠══════════════════════════════════════════════╣")
        print("║  S. START BOT                                ║")
        print("║  Q. QUIT                                     ║")
        print("╚══════════════════════════════════════════════╝")

        choice = input("\nSelect (1-5) to tweak or S to Start: ").strip().upper()

        if choice == '1':
            val = input("Enter Device IP:PORT (or leave blank for local): ").strip()
            config['device_id'] = val
        elif choice == '2':
            val = input(f"Sensitivity [{config['sensitivity']}] (100-2000): ").strip()
            if val.isdigit(): config['sensitivity'] = int(val)
        elif choice == '3':
            val = input(f"White Level [{config['white_level']}] (150-255): ").strip()
            if val.isdigit(): config['white_level'] = int(val)
        elif choice == '4':
            config['reset_ads'] = not config['reset_ads']
        elif choice == '5':
            val = input(f"Tap Cooldown [{config['tap_cooldown']}] (0.05-1.0): ").strip()
            try: config['tap_cooldown'] = float(val)
            except ValueError: pass
        elif choice == 'S':
            os.system("clear")
            print("🚀 Launching BunnyBot!")
            print(f"   Target : {config['device_id'] if config['device_id'] else 'Local Device'}")
            print("\nSwitch to Bunny Runner NOW!")
            print("Bot will take control in 10 seconds...")
            time.sleep(10) 
            return config
        elif choice == 'Q':
            sys.exit(0)

class BunnyBot:
    def __init__(self, config: dict):
        self.config        = config
        self.state         = "MENU"
        self.last_tap_time = 0.0
        self.state_entered = time.time()
        self.road_miss     = 0
        self._last_road_ok = False
        self.w: int        = 0
        self.h: int        = 0

        self._get_resolution()

        # SENSORS: Placed higher (65-75% height) to see fences early
        self.left_roi  = (int(self.h * 0.65), int(self.h * 0.75),
                          int(self.w * 0.10), int(self.w * 0.45))
        self.right_roi = (int(self.h * 0.65), int(self.h * 0.75),
                          int(self.w * 0.55), int(self.w * 0.90))

        # Action Coordinates
        self.tap_left      = (int(self.w * 0.20), int(self.h * 0.50))
        self.tap_right     = (int(self.w * 0.80), int(self.h * 0.50))
        self.tap_try_again = (self.w // 2,        int(self.h * 0.50)) # Dead Center
        self.tap_start     = (self.w // 2,        int(self.h * 0.85)) # Bottom
        
        self.road_probe = (self.w // 2, int(self.h * 0.85))

    def _adb_cmd(self, command: str) -> str:
        dev_flag = f"-s {self.config['device_id']} " if self.config['device_id'] else ""
        return f"adb {dev_flag}{command}"

    def _get_resolution(self):
        cmd = self._adb_cmd("shell wm size")
        try:
            raw = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
            size_part = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size_part.split("x"))
        except Exception:
            print(f"❌ ADB Error: Could not get resolution. Check connection.")
            sys.exit(1)

    def get_frame(self):
        cmd = self._adb_cmd("exec-out screencap -p")
        try:
            pipe = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if pipe.stdout is None: return None
            data: bytes = cast(bytes, pipe.stdout.read())
            if len(data) < 1000: return None
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if frame is None or np.mean(frame) < 5: return None
            return frame
        except Exception:
            return None

    def tap(self, x, y, cooldown=True):
        now = time.time()
        if cooldown and (now - self.last_tap_time < self.config["tap_cooldown"]):
            return
        cmd = self._adb_cmd(f"shell input tap {int(x)} {int(y)}")
        os.system(cmd)
        self.last_tap_time = now

    def check_sensors(self, frame):
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

    def _is_game_running(self, frame):
        px, py = self.road_probe
        if py >= frame.shape[0] or px >= frame.shape[1]: return False
        val = int(frame[py, px])
        return 5 < val < self.config["road_dark_max"]

    def _force_reset_game(self):
        if not self.config["reset_ads"]:
            print("\n⚠️ Ad detected. Waiting...")
            time.sleep(35)
            return
        print("\n🔴 AD/FREEZE DETECTED — Force resetting...")
        os.system(self._adb_cmd(f"shell am force-stop {PACKAGE_NAME}"))
        time.sleep(1.5)
        os.system(self._adb_cmd(f"shell monkey -p {PACKAGE_NAME} -c android.intent.category.LAUNCHER 1"))
        time.sleep(10)

    def _render_radar(self, l, r, action, fps):
        def bar(v):
            n = min(int(v / max(self.config["sensitivity"], 1) * 8), 8)
            return '#' * n + ' ' * (8 - n)
        tgt = self.config['device_id'] if self.config['device_id'] else 'Local'
        print(f"[{tgt}] [ L:{bar(l)} | R:{bar(r)} ] {action:12s} | {self.state:10s} | FPS:{fps:4.1f}    ", end='\r')

    def start_loop(self) -> None:
        frame_count: int = 0
        while True:
            loop_start = time.time()
            if time.time() - self.state_entered > WATCHDOG_SECS:
                self._force_reset_game()
                self.state = "MENU"
                self.state_entered = time.time()
                continue

            frame = self.get_frame()
            if frame is None:
                time.sleep(0.5)
                continue

            frame_count += 1
            now = time.time()

            if self.state == "MENU":
                if self._is_game_running(frame):
                    print("\n🟢 Road detected — PLAYING!")
                    self.state = "PLAYING"
                    self.state_entered = now
                else:
                    if now - self.last_tap_time > 2.0:
                        # Try both common button locations (Try Again & Start)
                        self.tap(*self.tap_try_again, cooldown=False)
                        time.sleep(0.2)
                        self.tap(*self.tap_start, cooldown=False)
                        print("🕹️ Searching for Start/Try Again...            ", end='\r')

            elif self.state == "PLAYING":
                self._last_road_ok = self._is_game_running(frame)
                self.road_miss = 0 if self._last_road_ok else self.road_miss + 1

                cx, cy = self.road_probe
                center_bright = int(frame[cy, cx]) if cy < frame.shape[0] else 0

                if center_bright > self.config["ad_level"] or self.road_miss >= ROAD_MISS_MAX:
                    self.state = "RECOVERING"
                    self.state_entered = now
                    continue

                action, l, r = self.check_sensors(frame)
                if action == 'DODGE_RIGHT':
                    self.tap(*self.tap_right)
                elif action == 'DODGE_LEFT':
                    self.tap(*self.tap_left)

                elapsed = time.time() - loop_start
                fps = 1.0 / elapsed if elapsed > 0 else 0
                self._render_radar(l, r, action, fps)

            elif self.state == "RECOVERING":
                self._force_reset_game()
                self.state = "MENU"
                self.state_entered = time.time()

if __name__ == "__main__":
    try:
        cfg = main_menu()
        if cfg: BunnyBot(cfg).start_loop()
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped. 🐰")
        sys.exit(0)
