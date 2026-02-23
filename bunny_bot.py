import subprocess
import time
import os
import sys
import base64

# ─────────────────────────────────────────────────────────────────────────────
#  BunnyBot — Gemini AI Edition 🧠
#  Lightweight bot for Bunny Runner 3D
#  AI: Google Gemini 1.5 Flash (free tier, Termux-friendly)
#  Control: Wireless ADB (local or remote phone)
# ─────────────────────────────────────────────────────────────────────────────

PACKAGE_NAME  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60
AI_CALL_INTERVAL = 2.0   # Seconds between AI API calls (saves quota + CPU)

# ── Optional: heavy vision deps (only used in pixel-reflex mode) ─────────────
try:
    import cv2
    import numpy as np
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False

# ── Google Gemini AI ──────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    AI_LIB_AVAILABLE = True
except ImportError:
    AI_LIB_AVAILABLE = False


def configure_ai(api_key: str):
    """Configure Gemini with the provided API key."""
    if AI_LIB_AVAILABLE and api_key:
        genai.configure(api_key=api_key)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────────────────────────────────────

def main_menu():
    # Try to load API key from environment first
    api_key = os.environ.get("GEMINI_API_KEY", "")

    config = {
        "device_id":    "",       # Leave blank for local ADB
        "api_key":      api_key,
        "use_ai":       True,
        "ai_model":     "gemini-1.5-flash",
        "tap_cooldown": 0.15,
    }

    while True:
        os.system("clear")
        ai_ready = AI_LIB_AVAILABLE and bool(config["api_key"])
        print("╔══════════════════════════════════════════════════╗")
        print("║   🐰  BUNNY RUNNER 3D — AI BOT (Gemini Flash)   ║")
        print("╠══════════════════════════════════════════════════╣")
        print(f"║  AI Status  : {'READY ✅' if ai_ready else 'NOT CONFIGURED ❌'}                  ║")
        print(f"║  AI Mode    : {'ON ✅ ' if config['use_ai'] else 'OFF ❌'}                         ║")
        print(f"║  Vision     : {'READY ✅' if VISION_AVAILABLE else 'pkg not installed ⚠️ '}        ║")
        print("╠══════════════════════════════════════════════════╣")
        print("║  1. Set Target Device (IP:PORT or blank=local)  ║")
        print("║  2. Set Gemini API Key                          ║")
        print("║  3. Toggle AI Mode                              ║")
        print("╠══════════════════════════════════════════════════╣")
        print("║  S. START BOT     Q. QUIT                       ║")
        print("╚══════════════════════════════════════════════════╝")

        if not AI_LIB_AVAILABLE:
            print("\n💡 TIP: pip install google-generativeai")
        elif not config["api_key"]:
            print("\n💡 TIP: Get a free API key at https://aistudio.google.com")
            print("        Then set option 2, or export GEMINI_API_KEY=<key>")

        choice = input("\nSelect Option: ").strip().upper()

        if choice == "1":
            config["device_id"] = input("  Enter Device IP:PORT (blank = local): ").strip()
        elif choice == "2":
            key = input("  Paste Gemini API Key: ").strip()
            config["api_key"] = key
        elif choice == "3":
            config["use_ai"] = not config["use_ai"]
        elif choice == "S":
            return config
        elif choice == "Q":
            sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
#  BOT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BunnyBotAI:
    def __init__(self, config: dict):
        self.config = config
        self._last_ai_call = 0.0

        # Configure Gemini
        self.ai_ready = configure_ai(config["api_key"])
        if self.ai_ready:
            self.model = genai.GenerativeModel(config["ai_model"])
        else:
            self.model = None

        # Get screen resolution
        self._get_resolution()

        # Pixel-sensor ROIs for fast reflex dodging (left / right obstacle zones)
        self.left_roi  = (int(self.h * 0.65), int(self.h * 0.75),
                          int(self.w * 0.10), int(self.w * 0.45))
        self.right_roi = (int(self.h * 0.65), int(self.h * 0.75),
                          int(self.w * 0.55), int(self.w * 0.90))

    # ── ADB helpers ───────────────────────────────────────────────────────────

    def _adb(self, command: str) -> str:
        """Build an adb command string, targeting the configured device."""
        dev = f"-s {self.config['device_id']} " if self.config["device_id"] else ""
        return f"adb {dev}{command}"

    def _run(self, command: str) -> bytes:
        return subprocess.check_output(command, shell=True)

    def _get_resolution(self):
        try:
            raw = self._run(self._adb("shell wm size")).decode()
            size = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size.split("x"))
        except Exception:
            self.w, self.h = 1080, 2400  # Safe default

    def get_frame_bytes(self) -> bytes:
        """Capture screenshot via ADB and return raw PNG bytes."""
        return self._run(self._adb("exec-out screencap -p"))

    def tap(self, x: float, y: float):
        """Send a tap at (x, y) to the device."""
        os.system(self._adb(f"shell input tap {int(x)} {int(y)}"))
        time.sleep(self.config["tap_cooldown"])

    def swipe_left(self):
        mid_y = int(self.h * 0.5)
        os.system(self._adb(
            f"shell input swipe {int(self.w*0.7)} {mid_y} {int(self.w*0.3)} {mid_y} 80"
        ))

    def swipe_right(self):
        mid_y = int(self.h * 0.5)
        os.system(self._adb(
            f"shell input swipe {int(self.w*0.3)} {mid_y} {int(self.w*0.7)} {mid_y} 80"
        ))

    def restart_game(self):
        """Force-stop the game and relaunch (ad-skip strategy)."""
        print("🔄 Restarting game to skip ad...")
        os.system(self._adb(f"shell am force-stop {PACKAGE_NAME}"))
        time.sleep(1.5)
        os.system(self._adb(
            f"shell monkey -p {PACKAGE_NAME} -c android.intent.category.LAUNCHER 1"
        ))
        time.sleep(3)

    # ── AI Layer ──────────────────────────────────────────────────────────────

    def ai_analyze(self, frame_bytes: bytes) -> str | None:
        """
        Send the current screen to Gemini 1.5 Flash and get a game command.
        Returns a string like 'MOVE LEFT', 'MOVE RIGHT', 'TAP 540 1200', or None.
        Rate-limited to AI_CALL_INTERVAL seconds to protect quota and reduce CPU.
        """
        if not self.ai_ready or not self.config["use_ai"] or not self.model:
            return None

        now = time.time()
        if now - self._last_ai_call < AI_CALL_INTERVAL:
            return None
        self._last_ai_call = now

        prompt = (
            "You are a professional mobile game bot controller. "
            "Analyze this screenshot of 'Bunny Runner 3D'.\n\n"
            "Rules:\n"
            "- If the game is on a menu or loading screen: output TAP [X] [Y] "
            "  to tap the best button to start/continue the game.\n"
            "- If playing: look for the bunny character and detect fences, "
            "  obstacles, or walls ahead of it. Output exactly one of:\n"
            "    MOVE LEFT\n"
            "    MOVE RIGHT\n"
            "    JUMP\n"
            "    (blank) — if the path is clear\n"
            "- If an ad or popup is showing: find the close/skip/X button and "
            "  output TAP [X] [Y].\n\n"
            "Respond with ONLY the command and nothing else. No explanation."
        )

        try:
            import PIL.Image
            import io
            img = PIL.Image.open(io.BytesIO(frame_bytes))
            response = self.model.generate_content([prompt, img])
            return response.text.strip()
        except Exception as e:
            # Pillow not available — send raw base64 text prompt
            try:
                b64 = base64.b64encode(frame_bytes).decode()
                response = self.model.generate_content(
                    [{"role": "user", "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": b64}}
                    ]}]
                )
                return response.text.strip()
            except Exception as e2:
                print(f"⚠️  AI error: {e2}")
                return None

    # ── Pixel Reflex Layer ────────────────────────────────────────────────────

    def pixel_reflex(self, frame_bytes: bytes) -> str | None:
        """
        Fast pixel-based obstacle detection using OpenCV.
        Detects bright-white fence pixels in left/right sensor zones.
        Returns 'MOVE LEFT', 'MOVE RIGHT', or None.
        Only runs if OpenCV (python-numpy + opencv) is installed via pkg.
        """
        if not VISION_AVAILABLE:
            return None
        try:
            arr = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return None

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            r1y1, r1y2, r1x1, r1x2 = self.left_roi
            r2y1, r2y2, r2x1, r2x2 = self.right_roi

            left_zone  = gray[r1y1:r1y2, r1x1:r1x2]
            right_zone = gray[r2y1:r2y2, r2x1:r2x2]

            WHITE = 220
            left_count  = int(np.sum(left_zone  > WHITE))
            right_count = int(np.sum(right_zone > WHITE))

            THRESHOLD = 400
            if left_count > THRESHOLD and left_count >= right_count:
                return "MOVE RIGHT"
            elif right_count > THRESHOLD:
                return "MOVE LEFT"
        except Exception:
            pass
        return None

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def start_loop(self):
        print("\n🧠 BunnyBot starting up... Switch to the game now!")
        for i in range(5, 0, -1):
            print(f"   Starting in {i}s...", end="\r")
            time.sleep(1)
        print("\n🚀 Bot is LIVE! Press Ctrl+C to stop.\n")

        last_screenshot_fail = 0
        fail_streak = 0

        while True:
            try:
                frame_bytes = self.get_frame_bytes()
                fail_streak = 0
            except Exception as e:
                fail_streak += 1
                print(f"⚠️  Screen capture failed ({fail_streak}): {e}")
                if fail_streak >= 3:
                    print("❌ 3 consecutive failures — check ADB connection.")
                    break
                time.sleep(1)
                continue

            # ── AI strategic decision (every ~2 seconds) ──────────────────
            ai_decision = self.ai_analyze(frame_bytes)
            if ai_decision:
                print(f"🤖 AI → {ai_decision}")
                self._execute_command(ai_decision)

            # ── Pixel reflex (every iteration, ~60ms sub-second responses) ─
            reflex = self.pixel_reflex(frame_bytes)
            if reflex and not ai_decision:
                print(f"⚡ Reflex → {reflex}")
                self._execute_command(reflex)

            time.sleep(0.1)  # ~10 fps loop, light on CPU

    def _execute_command(self, command: str):
        """Translate a command string into ADB actions."""
        cmd = command.upper()
        if "MOVE LEFT" in cmd:
            self.swipe_left()
        elif "MOVE RIGHT" in cmd:
            self.swipe_right()
        elif "JUMP" in cmd:
            # Tap upper-center of screen as jump gesture
            self.tap(self.w * 0.5, self.h * 0.35)
        elif cmd.startswith("TAP"):
            parts = cmd.replace("[", "").replace("]", "").split()
            try:
                self.tap(int(parts[1]), int(parts[2]))
            except (IndexError, ValueError):
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = main_menu()
    bot = BunnyBotAI(cfg)
    bot.start_loop()
