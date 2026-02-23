import subprocess
import time
import os
import sys
import base64
from typing import cast, TYPE_CHECKING

# Attempt to import Puter for AI capabilities
try:
    from putergenai import PuterClient
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

if TYPE_CHECKING:
    import cv2  # type: ignore[import]
    import numpy as np  # type: ignore[import]
else:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401

# =============================================================================
#  BunnyBot — Gemini 3.1 AI Edition 🧠
#  Integrated with Puter.js for autonomous decision making
# =============================================================================

PACKAGE_NAME  = "com.bunny.runner3D.dg"
WATCHDOG_SECS = 60      

def main_menu():
    config = {
        "device_id":     "",     
        "sensitivity":   500,    
        "white_level":   220,    
        "use_ai":        True,
        "ai_model":      "gemini-3.1-pro-preview",
        "tap_cooldown":  0.15,   
    }

    while True:
        os.system("clear")
        print("╔══════════════════════════════════════════════╗")
        print("║  🐰  BUNNY RUNNER 3D — AI BRAIN EDITION     ║")
        print("╠══════════════════════════════════════════════╣")
        print(f"║  AI STATUS     : {'READY ✅' if AI_AVAILABLE else 'NOT INSTALLED ❌'}            ║")
        print(f"║  1. Target Dev : {config['device_id'] if config['device_id'] else 'Local':<18} ║")
        print(f"║  2. Use AI Brain: {'ON ✅' if config['use_ai'] else 'OFF ❌'}                   ║")
        print(f"║  3. Model      : {config['ai_model']:<25} ║")
        print("╠══════════════════════════════════════════════╣")
        print("║  S. START BOT                                ║")
        print("║  Q. QUIT                                     ║")
        print("╚══════════════════════════════════════════════╝")
        if not AI_AVAILABLE:
            print("\n💡 TIP: Run 'pip install putergenai' to enable the AI brain!")

        choice = input("\nSelect Option: ").strip().upper()

        if choice == '1':
            config['device_id'] = input("Enter Device IP:PORT: ").strip()
        elif choice == '2':
            config['use_ai'] = not config['use_ai']
        elif choice == 'S':
            return config
        elif choice == 'Q':
            sys.exit(0)

class BunnyBotAI:
    def __init__(self, config: dict):
        self.config = config
        self.state = "MENU"
        self.ai_client = PuterClient() if AI_AVAILABLE else None
        self._get_resolution()
        
        # Sensor Regions (Legacy Fallback)
        self.left_roi = (int(self.h * 0.65), int(self.h * 0.75), int(self.w * 0.10), int(self.w * 0.45))
        self.right_roi = (int(self.h * 0.65), int(self.h * 0.75), int(self.w * 0.55), int(self.w * 0.90))

    def _adb_cmd(self, command: str) -> str:
        dev = f"-s {self.config['device_id']} " if self.config['device_id'] else ""
        return f"adb {dev}{command}"

    def _get_resolution(self):
        try:
            raw = subprocess.check_output(self._adb_cmd("shell wm size"), shell=True).decode()
            size = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size.split("x"))
        except:
            self.w, self.h = 1080, 2400 # Default fallback

    def get_frame_bytes(self):
        cmd = self._adb_cmd("exec-out screencap -p")
        return subprocess.check_output(cmd, shell=True)

    def ai_analyze(self, frame_bytes):
        """Ask Gemini what to do based on the current screen."""
        if not self.ai_client or not self.config["use_ai"]:
            return None

        # Convert to Base64 for the API
        b64_image = base64.b64encode(frame_bytes).decode('utf-8')
        
        prompt = (
            "You are a professional mobile game player bot. Look at this screen of 'Bunny Runner 3D'. "
            "If we are in a menu, output 'TAP [X] [Y]' where X and Y are screen coordinates to start or continue. "
            "If we are playing, look for the bunny. If there is a fence directly ahead, output 'MOVE LEFT' or 'MOVE RIGHT'. "
            "If an ad is showing, find the 'X' button and output 'TAP [X] [Y]'. "
            "Only output the command, nothing else."
        )

        try:
            # Using the Puter.js bridge to call Gemini
            response = self.ai_client.ai_chat(
                messages=[{"role": "user", "content": prompt}],
                options={"model": self.config["ai_model"]}
            )
            return response["response"]["result"]["message"]["content"]
        except Exception as e:
            return f"ERROR: {e}"

    def tap(self, x, y):
        os.system(self._adb_cmd(f"shell input tap {int(x)} {int(y)}"))

    def start_loop(self):
        print("🧠 AI Brain warming up...")
        while True:
            frame_bytes = self.get_frame_bytes()
            
            # 1. Ask AI for a strategic decision every 2 seconds (to save API limits)
            # and use fast pixel sensors for instant reflexes in between.
            decision = self.ai_analyze(frame_bytes)
            
            if decision:
                print(f"🤖 AI Decision: {decision}")
                if "TAP" in decision:
                    parts = decision.replace('[','').replace(']','').split()
                    try:
                        self.tap(int(parts[1]), int(parts[2]))
                    except: pass
                elif "MOVE LEFT" in decision:
                    self.tap(self.w * 0.2, self.h * 0.5)
                elif "MOVE RIGHT" in decision:
                    self.tap(self.w * 0.8, self.h * 0.5)

            # 2. Reflex Layer (Fast pixel checking)
            # [Insert the legacy sensor logic here for sub-second dodging]
            time.sleep(0.5)

if __name__ == "__main__":
    cfg = main_menu()
    bot = BunnyBotAI(cfg)
    bot.start_loop()
