import subprocess
import time
import os
import sys
import base64
import random
import json
import io

# ─────────────────────────────────────────────────────────────────────────────
#  BunnyBot — Gemini 3.1 Pro Edition 🧠
#  Primary AI  : OpenRouter → google/gemini-3.1-pro-preview (smarter moves)
#  Fallback AI : Google AI Studio → gemini-1.5-flash (free tier)
#  Control     : Wireless ADB (local or remote phone)
# ─────────────────────────────────────────────────────────────────────────────

# ── HARDCODED API KEYS ────────────────────────────────────────────────────────
OPENROUTER_API_KEY = "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"
OPENROUTER_MODEL   = "google/gemini-3.1-pro-preview"
GOOGLE_API_KEY     = "AIzaSyAA4YiJFrt0EaBg-0SpLTRv8xdrSUs5Vn4"
GOOGLE_MODEL       = "gemini-1.5-flash"

# ── BOT CONSTANTS ─────────────────────────────────────────────────────────────
PACKAGE_NAME     = "com.bunny.runner3D.dg"
AI_CALL_INTERVAL = 1.5     # Seconds between AI decisions
LOOP_INTERVAL    = 0.08    # Main loop tick (~12 fps)

# ── Optional heavy deps (pixel-reflex layer) ──────────────────────────────────
try:
    import cv2
    import numpy as np
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False

# ── OpenRouter (primary — gemini-3.1-pro-preview) ────────────────────────────
try:
    from openai import OpenAI as _OpenAI
    _openrouter_client = _OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    OPENROUTER_AVAILABLE = True
except ImportError:
    _openrouter_client   = None
    OPENROUTER_AVAILABLE = False

# ── Google AI Studio (fallback — gemini-1.5-flash) ───────────────────────────
try:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    _google_model    = genai.GenerativeModel(GOOGLE_MODEL)
    GOOGLE_AVAILABLE = True
except ImportError:
    _google_model    = None
    GOOGLE_AVAILABLE = False

AI_AVAILABLE = OPENROUTER_AVAILABLE or GOOGLE_AVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
#  GAME STATE MACHINE
#  The bot tracks what it believes the current game state is so it can send
#  contextual prompts and make better decisions.
# ─────────────────────────────────────────────────────────────────────────────
STATES = ["UNKNOWN", "MAIN_MENU", "LOADING", "PLAYING", "DEAD", "AD", "REWARD"]


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────────────────────────────────────

def main_menu():
    config = {
        "device_id":    "",
        "use_ai":       True,
        "tap_cooldown": 0.12,
    }

    while True:
        os.system("clear")
        primary  = "OpenRouter Gemini 3.1 Pro ✅" if OPENROUTER_AVAILABLE else "NOT INSTALLED ❌"
        fallback = "Google Gemini 1.5 Flash ✅"   if GOOGLE_AVAILABLE    else "NOT INSTALLED ❌"
        vision   = "OpenCV Reflex ✅"              if VISION_AVAILABLE    else "pkg not installed ⚠️"

        print("╔══════════════════════════════════════════════════════╗")
        print("║   🐰  BUNNY RUNNER 3D — AI BOT (Gemini 3.1 Pro)    ║")
        print("╠══════════════════════════════════════════════════════╣")
        print(f"║  Primary AI : {primary:<38}║")
        print(f"║  Fallback   : {fallback:<38}║")
        print(f"║  Vision     : {vision:<38}║")
        print(f"║  AI Mode    : {'ON ✅' if config['use_ai'] else 'OFF ❌':<38}║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  1. Set Target Device (IP:PORT or blank=local)      ║")
        print("║  2. Toggle AI Mode                                  ║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  S. START BOT          Q. QUIT                      ║")
        print("╚══════════════════════════════════════════════════════╝")

        if not AI_AVAILABLE:
            print("\n💡 pip install openai  OR  pip install google-generativeai")

        choice = input("\nSelect Option: ").strip().upper()
        if choice == "1":
            config["device_id"] = input("  Device IP:PORT (blank=local): ").strip()
        elif choice == "2":
            config["use_ai"] = not config["use_ai"]
        elif choice == "S":
            return config
        elif choice == "Q":
            sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
#  AI CALLER
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(game_state: str, recent_moves: list[str]) -> str:
    recent = ", ".join(recent_moves[-4:]) if recent_moves else "none"
    return f"""You are an expert Bunny Runner 3D mobile game bot.

Current game state: {game_state}
Your last 4 moves: {recent}

Looking at this screenshot, decide the SINGLE best action to take RIGHT NOW.

Rules:
- MAIN_MENU / LOADING: Find and tap the best button (Play, Continue, Tap to Start, etc.)
  → Output: TAP [x] [y]
  
- PLAYING: The bunny runs forward automatically. Your ONLY job is to dodge obstacles.
  * Fences, walls or barriers ahead → MOVE LEFT or MOVE RIGHT (choose the clearest lane)
  * Gap or chasm → JUMP
  * Nothing in the way → do nothing (output: NONE)
  * Avoid repeating the same move if the last 2 moves were identical (it means you're stuck)
  
- DEAD (score/retry screen visible): Tap the best revival/retry button
  → Output: TAP [x] [y]
  
- AD (advertisement visible): Tap the skip/close/X button
  → Output: TAP [x] [y]
  
- REWARD (claim screen visible): Tap the claim/collect button
  → Output: TAP [x] [y]

Output EXACTLY one line — the action only, nothing else:
  MOVE LEFT
  MOVE RIGHT
  JUMP
  NONE
  TAP [x] [y]  ← replace x and y with actual pixel coordinates
"""


def _image_message(frame_bytes: bytes, prompt: str) -> list:
    """Build an OpenRouter / OpenAI-compatible vision message."""
    b64 = base64.b64encode(frame_bytes).decode()
    return [
        {
            "role": "user",
            "content": [
                {"type": "text",       "text": prompt},
                {"type": "image_url",  "image_url": {
                    "url": f"data:image/png;base64,{b64}"
                }},
            ],
        }
    ]


def ai_decide(frame_bytes: bytes, game_state: str, recent_moves: list[str]) -> str | None:
    """
    Call AI (OpenRouter first, Google fallback) and get a game command.
    Returns a command string or None on failure.
    """
    prompt = _build_prompt(game_state, recent_moves)

    # ── Try OpenRouter (Gemini 3.1 Pro) ──────────────────────────────────────
    if OPENROUTER_AVAILABLE:
        try:
            messages = _image_message(frame_bytes, prompt)
            response = _openrouter_client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=messages,
                max_tokens=50,
                temperature=0.2,   # Low temp = consistent, deterministic moves
            )
            result = response.choices[0].message.content.strip().upper()
            print(f"🤖 Gemini 3.1 Pro → {result}")
            return result
        except Exception as e:
            print(f"⚠️  OpenRouter error: {e} — trying fallback...")

    # ── Try Google AI Studio (Gemini 1.5 Flash) ───────────────────────────────
    if GOOGLE_AVAILABLE and _google_model:
        try:
            img = None
            try:
                import PIL.Image
                img = PIL.Image.open(io.BytesIO(frame_bytes))
            except Exception:
                pass

            if img:
                response = _google_model.generate_content([prompt, img])
            else:
                b64 = base64.b64encode(frame_bytes).decode()
                response = _google_model.generate_content([
                    {"role": "user", "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": b64}}
                    ]}
                ])
            result = response.text.strip().upper()
            print(f"🔁 Gemini Flash fallback → {result}")
            return result
        except Exception as e:
            print(f"⚠️  Google AI error: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
#  BOT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BunnyBotAI:
    def __init__(self, config: dict):
        self.config       = config
        self.game_state   = "UNKNOWN"
        self.recent_moves: list[str] = []
        self._last_ai_ts  = 0.0
        self._last_tap_ts = 0.0
        self._fail_streak = 0

        self._get_resolution()
        self.left_roi  = (int(self.h*0.65), int(self.h*0.75),
                          int(self.w*0.10), int(self.w*0.45))
        self.right_roi = (int(self.h*0.65), int(self.h*0.75),
                          int(self.w*0.55), int(self.w*0.90))

    # ── ADB ────────────────────────────────────────────────────────────────────

    def _adb(self, cmd: str) -> str:
        dev = f"-s {self.config['device_id']} " if self.config["device_id"] else ""
        return f"adb {dev}{cmd}"

    def _run(self, cmd: str) -> bytes:
        return subprocess.check_output(cmd, shell=True)

    def _get_resolution(self):
        try:
            raw  = self._run(self._adb("shell wm size")).decode()
            size = raw.split(":")[-1].strip()
            self.w, self.h = map(int, size.split("x"))
        except Exception:
            self.w, self.h = 1080, 2400

    def get_frame(self) -> bytes:
        return self._run(self._adb("exec-out screencap -p"))

    # ── Actions ────────────────────────────────────────────────────────────────

    def tap(self, x: float, y: float):
        """Tap with slight human-like random offset."""
        jx = int(x) + random.randint(-8, 8)
        jy = int(y) + random.randint(-8, 8)
        os.system(self._adb(f"shell input tap {jx} {jy}"))
        time.sleep(self.config["tap_cooldown"] + random.uniform(0, 0.05))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 80):
        """Swipe gesture for lane changes."""
        os.system(self._adb(
            f"shell input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}"
        ))
        time.sleep(0.12 + random.uniform(0, 0.04))

    def move_left(self):
        mid_y = self.h * 0.5
        self.swipe(self.w*0.70, mid_y, self.w*0.30, mid_y, 70)

    def move_right(self):
        mid_y = self.h * 0.5
        self.swipe(self.w*0.30, mid_y, self.w*0.70, mid_y, 70)

    def jump(self):
        self.tap(self.w * 0.5, self.h * 0.35)

    def restart_game(self):
        print("🔄 Restarting game to skip ad...")
        os.system(self._adb(f"shell am force-stop {PACKAGE_NAME}"))
        time.sleep(1.5)
        os.system(self._adb(
            f"shell monkey -p {PACKAGE_NAME} -c android.intent.category.LAUNCHER 1"
        ))
        time.sleep(3)
        self.game_state = "LOADING"

    # ── Pixel Reflex ───────────────────────────────────────────────────────────

    def pixel_reflex(self, frame_bytes: bytes) -> str | None:
        """
        Fast pixel-based fence detection using OpenCV.
        Only active while PLAYING. Runs every frame.
        """
        if not VISION_AVAILABLE or self.game_state != "PLAYING":
            return None
        try:
            arr   = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return None
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            r1y1, r1y2, r1x1, r1x2 = self.left_roi
            r2y1, r2y2, r2x1, r2x2 = self.right_roi
            WHITE = 215
            THRESH = 350
            left_cnt  = int(np.sum(gray[r1y1:r1y2, r1x1:r1x2] > WHITE))
            right_cnt = int(np.sum(gray[r2y1:r2y2, r2x1:r2x2] > WHITE))

            if left_cnt > THRESH and left_cnt >= right_cnt:
                return "MOVE RIGHT"
            elif right_cnt > THRESH:
                return "MOVE LEFT"
        except Exception:
            pass
        return None

    # ── State Inference ────────────────────────────────────────────────────────

    def _infer_state_from_command(self, cmd: str):
        """Loosely update game state based on what the AI tells us."""
        if "TAP" in cmd:
            # If we were dead/on a menu and tapped, assume we're now loading
            if self.game_state in ("DEAD", "MAIN_MENU", "REWARD", "UNKNOWN"):
                self.game_state = "LOADING"
        elif "MOVE" in cmd or "JUMP" in cmd:
            self.game_state = "PLAYING"

    # ── Execute ────────────────────────────────────────────────────────────────

    def execute(self, command: str):
        cmd = command.upper().strip()
        if not cmd or cmd == "NONE":
            return

        self.recent_moves.append(cmd)
        if len(self.recent_moves) > 10:
            self.recent_moves.pop(0)

        self._infer_state_from_command(cmd)

        if "MOVE LEFT"  in cmd: self.move_left()
        elif "MOVE RIGHT" in cmd: self.move_right()
        elif "JUMP"       in cmd: self.jump()
        elif cmd.startswith("TAP"):
            parts = cmd.replace("[","").replace("]","").split()
            try:
                self.tap(float(parts[1]), float(parts[2]))
            except (IndexError, ValueError):
                # Tap center as safe fallback
                self.tap(self.w * 0.5, self.h * 0.5)

    # ── Main Loop ──────────────────────────────────────────────────────────────

    def start_loop(self):
        print("\n🧠 BunnyBot (Gemini 3.1 Pro) starting up...")
        for i in range(5, 0, -1):
            print(f"   Launching in {i}s...", end="\r", flush=True)
            time.sleep(1)
        print("\n🚀 Bot is LIVE!  Press Ctrl+C to stop.\n")

        while True:
            # ── Capture frame ─────────────────────────────────────────────────
            try:
                frame = self.get_frame()
                self._fail_streak = 0
            except Exception as e:
                self._fail_streak += 1
                print(f"⚠️  Capture fail ({self._fail_streak}): {e}")
                if self._fail_streak >= 3:
                    print("❌ 3 consecutive failures. Check ADB connection.")
                    break
                time.sleep(1)
                continue

            # ── AI strategic decision ─────────────────────────────────────────
            now = time.time()
            if self.config["use_ai"] and AI_AVAILABLE:
                if now - self._last_ai_ts >= AI_CALL_INTERVAL:
                    self._last_ai_ts = now
                    decision = ai_decide(frame, self.game_state, self.recent_moves)
                    if decision:
                        self.execute(decision)
                        # After an AI decision, skip reflex for 0.3s (avoid conflicts)
                        time.sleep(LOOP_INTERVAL)
                        continue

            # ── Pixel reflex (instant obstacle dodge, no API) ─────────────────
            reflex = self.pixel_reflex(frame)
            if reflex:
                print(f"⚡ Reflex → {reflex}")
                self.execute(reflex)

            time.sleep(LOOP_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = main_menu()
    bot = BunnyBotAI(cfg)
    bot.start_loop()
