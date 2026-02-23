import subprocess
import time
import os
import sys
import base64
import json
import io
import random
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
#  BunnyBot — Self-Learning AI Edition 🧠
#  Keys     : Loaded from config.json (never hardcoded)
#  Primary  : OpenRouter → google/gemini-3.1-pro-preview
#  Fallback : Google AI Studio → gemini-1.5-flash
#  Learning : game_knowledge.json — grows with every session
# ─────────────────────────────────────────────────────────────────────────────

PACKAGE_NAME     = "com.bunny.runner3D.dg"
AI_CALL_INTERVAL = 1.5
LOOP_INTERVAL    = 0.08
CONFIG_FILE      = os.path.join(os.path.dirname(__file__), "config.json")
KNOWLEDGE_FILE   = os.path.join(os.path.dirname(__file__), "game_knowledge.json")

# ── Optional heavy deps ───────────────────────────────────────────────────────
try:
    import cv2, numpy as np
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG — persisted to config.json
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    default = {
        "openrouter_key": "",
        "google_key":     "",
        "device_id":      "",
        "use_ai":         True,
        "tap_cooldown":   0.12,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            saved = json.load(open(CONFIG_FILE, encoding="utf-8"))
            default.update(saved)
        except Exception:
            pass
    return default


def save_config(cfg: dict):
    try:
        json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)
    except Exception as e:
        print(f"⚠️  Could not save config: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  KNOWLEDGE BASE — persisted to game_knowledge.json
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_KNOWLEDGE = {
    "game_summary":    "",
    "rules":           [],
    "state_hints":     {},
    "session_count":   0,
    "new_observations": [],
    "last_updated":    "",
}


def load_knowledge() -> dict:
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            return json.load(open(KNOWLEDGE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return dict(DEFAULT_KNOWLEDGE)


def save_knowledge(kb: dict):
    kb["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        json.dump(kb, open(KNOWLEDGE_FILE, "w", encoding="utf-8"), indent=2)
    except Exception as e:
        print(f"⚠️  Could not save knowledge: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  AI CLIENTS — built from config keys at runtime
# ─────────────────────────────────────────────────────────────────────────────

def build_clients(cfg: dict):
    """
    Returns (openrouter_client | None, google_model | None).
    Builds clients from whatever keys are in config.
    """
    or_client, g_model = None, None

    if cfg.get("openrouter_key"):
        try:
            from openai import OpenAI
            or_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=cfg["openrouter_key"],
            )
        except ImportError:
            print("⚠️  openai package not installed. Run: pip install openai")

    if cfg.get("google_key"):
        try:
            import google.generativeai as genai
            genai.configure(api_key=cfg["google_key"])
            g_model = genai.GenerativeModel("gemini-1.5-flash")
        except ImportError:
            print("⚠️  google-generativeai not installed. Run: pip install google-generativeai")

    return or_client, g_model


# ─────────────────────────────────────────────────────────────────────────────
#  AI CALLS
# ─────────────────────────────────────────────────────────────────────────────

def _call_ai(or_client, g_model, messages_openai: list, text_only: bool = False) -> str | None:
    """
    Try OpenRouter first, then Google fallback.
    messages_openai: OpenAI-format message list.
    text_only: if True, send only the text parts (no image) to Google fallback.
    """
    # OpenRouter
    if or_client:
        try:
            resp = or_client.chat.completions.create(
                model="google/gemini-3.1-pro-preview",
                messages=messages_openai,
                max_tokens=200,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"⚠️  OpenRouter: {e}")

    # Google fallback
    if g_model:
        try:
            # Extract text prompt
            text = ""
            b64_data = None
            for m in messages_openai:
                if isinstance(m.get("content"), list):
                    for part in m["content"]:
                        if part.get("type") == "text":
                            text += part["text"]
                        elif part.get("type") == "image_url":
                            url = part["image_url"]["url"]
                            if url.startswith("data:image"):
                                b64_data = url.split(",", 1)[1]
                elif isinstance(m.get("content"), str):
                    text += m["content"]

            if b64_data and not text_only:
                try:
                    import PIL.Image
                    img = PIL.Image.open(io.BytesIO(base64.b64decode(b64_data)))
                    resp = g_model.generate_content([text, img])
                except Exception:
                    resp = g_model.generate_content([
                        {"role": "user", "parts": [
                            {"text": text},
                            {"inline_data": {"mime_type": "image/png", "data": b64_data}}
                        ]}
                    ])
            else:
                resp = g_model.generate_content(text)
            return resp.text.strip()
        except Exception as e:
            print(f"⚠️  Google AI: {e}")

    return None


def _vision_message(frame_bytes: bytes, prompt: str) -> list:
    b64 = base64.b64encode(frame_bytes).decode()
    return [{"role": "user", "content": [
        {"type": "text",      "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}]


def _text_message(prompt: str) -> list:
    return [{"role": "user", "content": prompt}]


# ─────────────────────────────────────────────────────────────────────────────
#  LEARNING SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def phase1_learn_game(or_client, g_model, frame_bytes: bytes, kb: dict):
    """
    Phase 1: Run ONCE if we have no game summary.
    Ask AI to explain the game from a screenshot.
    """
    print("\n🎓 First run — AI is learning the game from the screen...")
    prompt = (
        "You are analyzing a mobile game called 'Bunny Runner 3D'.\n"
        "From this screenshot, explain:\n"
        "1. The game objective and how it is played (1-2 sentences)\n"
        "2. What visual elements appear (bunny, lanes, fences, buttons, ads, score)\n"
        "3. List 5-10 specific rules/strategies a bot should follow to survive and "
        "   handle every screen state (menus, ads, death screens, gameplay)\n\n"
        "Format your answer as:\n"
        "SUMMARY: <one sentence>\n"
        "RULES:\n- rule 1\n- rule 2\n..."
    )
    msgs = _vision_message(frame_bytes, prompt)
    result = _call_ai(or_client, g_model, msgs)
    if not result:
        print("⚠️  Could not learn game — will try again next run.")
        return

    # Parse result
    summary = ""
    rules   = []
    for line in result.splitlines():
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[8:].strip()
        elif line.startswith("- "):
            rules.append(line[2:].strip())

    if summary:
        kb["game_summary"] = summary
    if rules:
        kb["rules"] = rules

    print(f"✅ Learned {len(rules)} rules about the game!")
    save_knowledge(kb)


def phase3_consolidate(or_client, g_model, kb: dict):
    """
    Phase 3: After session ends, send new observations to AI and extract new rules.
    """
    observations = kb.get("new_observations", [])
    if not observations:
        return

    print(f"\n🧠 Consolidating {len(observations)} new observations into knowledge base...")
    obs_text = "\n".join(f"- {o}" for o in observations[-20:])  # Cap at 20
    existing = "\n".join(f"- {r}" for r in kb.get("rules", []))

    prompt = (
        f"You are updating a game bot's knowledge base for 'Bunny Runner 3D'.\n\n"
        f"Existing rules:\n{existing}\n\n"
        f"New observations from this session:\n{obs_text}\n\n"
        f"Extract any NEW rules not already covered above. "
        f"Write ONLY new rules, one per line, starting with '- '. "
        f"If no new rules, output NONE."
    )
    result = _call_ai(or_client, g_model, _text_message(prompt), text_only=True)
    if not result or result.strip().upper() == "NONE":
        print("✅ No new rules to add.")
    else:
        new_rules = [l[2:].strip() for l in result.splitlines() if l.strip().startswith("- ")]
        if new_rules:
            kb["rules"].extend(new_rules)
            print(f"✅ Added {len(new_rules)} new rules to knowledge base!")

    # Clear observations for next session
    kb["new_observations"] = []
    kb["session_count"]    = kb.get("session_count", 0) + 1
    save_knowledge(kb)


def build_game_prompt(game_state: str, recent_moves: list, kb: dict) -> str:
    """Build a context-rich prompt using the knowledge base."""
    rules_text = "\n".join(f"  - {r}" for r in kb.get("rules", []))
    summary    = kb.get("game_summary", "Bunny Runner 3D is an endless runner game.")
    recent     = ", ".join(recent_moves[-4:]) if recent_moves else "none"
    hint       = kb.get("state_hints", {}).get(game_state, "")

    return f"""You are a bot playing '{summary}'

Learned rules:
{rules_text if rules_text else '  (none yet — still learning)'}

Current state: {game_state}
{f'Hint for this state: {hint}' if hint else ''}
Last 4 moves: {recent}

Looking at this screenshot, decide the SINGLE best action RIGHT NOW.

Output EXACTLY one line — nothing else:
  MOVE LEFT          ← swipe left (dodge right-side obstacle)
  MOVE RIGHT         ← swipe right (dodge left-side obstacle)
  JUMP               ← jump over gap/obstacle
  NONE               ← path is clear, no action needed
  TAP [x] [y]        ← tap a button (replace x y with pixel coords)

Only output NONE if you are absolutely sure the path ahead is clear."""


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN MENU (with API key config)
# ─────────────────────────────────────────────────────────────────────────────

def main_menu(cfg: dict, kb: dict) -> dict:
    while True:
        os.system("clear")
        has_or  = bool(cfg.get("openrouter_key"))
        has_g   = bool(cfg.get("google_key"))
        has_kb  = bool(kb.get("game_summary"))
        sessions = kb.get("session_count", 0)
        rules    = len(kb.get("rules", []))

        def key_status(key): return "SET ✅" if key else "NOT SET ❌"

        print("╔══════════════════════════════════════════════════════╗")
        print("║   🐰  BUNNY RUNNER 3D — SELF-LEARNING AI BOT        ║")
        print("╠══════════════════════════════════════════════════════╣")
        print(f"║  📡 OpenRouter Key : {key_status(has_or):<33}║")
        print(f"║  🔑 Google AI Key  : {key_status(has_g):<33}║")
        print(f"║  🧠 Knowledge      : {(str(rules)+' rules, '+str(sessions)+' sessions'):<33}║")
        print(f"║  👁  Vision Reflex : {'OpenCV ✅' if VISION_AVAILABLE else 'pkg not installed ⚠️':<33}║")
        print(f"║  🤖 AI Mode        : {'ON ✅' if cfg['use_ai'] else 'OFF ❌':<33}║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  1. Set OpenRouter API Key                          ║")
        print("║  2. Set Google AI Studio Key                        ║")
        print("║  3. Set Target Device (IP:PORT or blank=local)      ║")
        print("║  4. Toggle AI Mode                                  ║")
        print("║  5. Clear Knowledge Base (reset learning)           ║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  S. START BOT          Q. QUIT                      ║")
        print("╚══════════════════════════════════════════════════════╝")

        if not has_or and not has_g:
            print("\n⚠️  No API keys set. Go to option 1 or 2 first.")

        choice = input("\nSelect Option: ").strip().upper()

        if choice == "1":
            k = input("  Paste OpenRouter API Key (or Enter to clear): ").strip()
            cfg["openrouter_key"] = k
            save_config(cfg)
            print("  ✅ Saved." if k else "  ✅ Cleared.")
            time.sleep(1)
        elif choice == "2":
            k = input("  Paste Google AI Studio Key (or Enter to clear): ").strip()
            cfg["google_key"] = k
            save_config(cfg)
            print("  ✅ Saved." if k else "  ✅ Cleared.")
            time.sleep(1)
        elif choice == "3":
            cfg["device_id"] = input("  Device IP:PORT (blank=local): ").strip()
            save_config(cfg)
        elif choice == "4":
            cfg["use_ai"] = not cfg["use_ai"]
            save_config(cfg)
        elif choice == "5":
            confirm = input("  Reset all game knowledge? (yes/no): ").strip().lower()
            if confirm == "yes":
                kb.update(DEFAULT_KNOWLEDGE)
                save_knowledge(kb)
                print("  ✅ Knowledge base cleared.")
                time.sleep(1)
        elif choice == "S":
            return cfg
        elif choice == "Q":
            sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
#  BOT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BunnyBotAI:
    def __init__(self, config: dict, kb: dict):
        self.config        = config
        self.kb            = kb
        self.game_state    = "UNKNOWN"
        self.recent_moves: list[str] = []
        self._last_ai_ts   = 0.0
        self._fail_streak  = 0

        self.or_client, self.g_model = build_clients(config)
        self.ai_available = bool(self.or_client or self.g_model)

        self._get_resolution()
        self.left_roi  = (int(self.h*0.65), int(self.h*0.75),
                          int(self.w*0.10), int(self.w*0.45))
        self.right_roi = (int(self.h*0.65), int(self.h*0.75),
                          int(self.w*0.55), int(self.w*0.90))

    # ── ADB ───────────────────────────────────────────────────────────────────

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

    # ── Actions ───────────────────────────────────────────────────────────────

    def tap(self, x: float, y: float):
        jx = int(x) + random.randint(-8, 8)
        jy = int(y) + random.randint(-8, 8)
        os.system(self._adb(f"shell input tap {jx} {jy}"))
        time.sleep(self.config["tap_cooldown"] + random.uniform(0, 0.05))

    def swipe(self, x1, y1, x2, y2, ms=75):
        os.system(self._adb(
            f"shell input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {ms}"
        ))
        time.sleep(0.12 + random.uniform(0, 0.04))

    def move_left(self):
        y = self.h * 0.5
        self.swipe(self.w*0.70, y, self.w*0.30, y)

    def move_right(self):
        y = self.h * 0.5
        self.swipe(self.w*0.30, y, self.w*0.70, y)

    def jump(self):
        self.tap(self.w * 0.5, self.h * 0.35)

    def restart_game(self):
        print("🔄 Restarting game (ad-skip)...")
        os.system(self._adb(f"shell am force-stop {PACKAGE_NAME}"))
        time.sleep(1.5)
        os.system(self._adb(
            f"shell monkey -p {PACKAGE_NAME} -c android.intent.category.LAUNCHER 1"
        ))
        time.sleep(3)
        self.game_state = "LOADING"

    # ── Pixel Reflex (fast, no API) ───────────────────────────────────────────

    def pixel_reflex(self, frame_bytes: bytes) -> str | None:
        if not VISION_AVAILABLE or self.game_state != "PLAYING":
            return None
        try:
            arr   = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return None
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            WHITE, THRESH = 215, 350
            r1y1,r1y2,r1x1,r1x2 = self.left_roi
            r2y1,r2y2,r2x1,r2x2 = self.right_roi
            lc = int(np.sum(gray[r1y1:r1y2, r1x1:r1x2] > WHITE))
            rc = int(np.sum(gray[r2y1:r2y2, r2x1:r2x2] > WHITE))
            if lc > THRESH and lc >= rc:
                return "MOVE RIGHT"
            elif rc > THRESH:
                return "MOVE LEFT"
        except Exception:
            pass
        return None

    # ── AI Decision ───────────────────────────────────────────────────────────

    def ai_decide(self, frame_bytes: bytes) -> str | None:
        if not self.config["use_ai"] or not self.ai_available:
            return None
        now = time.time()
        if now - self._last_ai_ts < AI_CALL_INTERVAL:
            return None
        self._last_ai_ts = now

        prompt = build_game_prompt(self.game_state, self.recent_moves, self.kb)
        msgs   = _vision_message(frame_bytes, prompt)
        result = _call_ai(self.or_client, self.g_model, msgs)
        if result:
            print(f"🤖 AI [{self.game_state}] → {result}")
        return result

    # ── Execute ───────────────────────────────────────────────────────────────

    def _update_state(self, cmd: str):
        if "TAP" in cmd and self.game_state in ("DEAD","MAIN_MENU","REWARD","UNKNOWN","LOADING"):
            self.game_state = "LOADING"
        elif any(x in cmd for x in ("MOVE","JUMP")):
            self.game_state = "PLAYING"

    def execute(self, command: str, source: str = "AI"):
        cmd = command.upper().strip()
        if not cmd or cmd == "NONE":
            return

        self.recent_moves.append(cmd)
        if len(self.recent_moves) > 10:
            self.recent_moves.pop(0)
        self._update_state(cmd)

        # Log to knowledge base as observation
        obs = f"[{self.game_state}] {source} said '{cmd}'"
        self.kb.setdefault("new_observations", []).append(obs)

        if   "MOVE LEFT"  in cmd: self.move_left()
        elif "MOVE RIGHT" in cmd: self.move_right()
        elif "JUMP"       in cmd: self.jump()
        elif cmd.startswith("TAP"):
            parts = cmd.replace("[","").replace("]","").split()
            try:
                self.tap(float(parts[1]), float(parts[2]))
            except (IndexError, ValueError):
                self.tap(self.w*0.5, self.h*0.5)

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def start_loop(self):
        print("\n🧠 BunnyBot Self-Learning starting... Switch to the game!")
        for i in range(5, 0, -1):
            print(f"   Starting in {i}s...", end="\r", flush=True)
            time.sleep(1)
        print("\n🚀 Live! (Ctrl+C to stop)\n")

        # Phase 1: Learn game on first run
        if self.ai_available and not self.kb.get("game_summary"):
            try:
                frame = self.get_frame()
                phase1_learn_game(self.or_client, self.g_model, frame, self.kb)
            except Exception as e:
                print(f"⚠️  Could not capture for learning: {e}")

        try:
            while True:
                # Capture
                try:
                    frame = self.get_frame()
                    self._fail_streak = 0
                except Exception as e:
                    self._fail_streak += 1
                    print(f"⚠️  Capture fail ({self._fail_streak}): {e}")
                    if self._fail_streak >= 3:
                        print("❌ ADB connection lost.")
                        break
                    time.sleep(1)
                    continue

                # AI decision (rate-limited, uses knowledge base context)
                ai_cmd = self.ai_decide(frame)
                if ai_cmd:
                    self.execute(ai_cmd, source="AI")
                    time.sleep(LOOP_INTERVAL)
                    continue

                # Pixel reflex (instant, no API)
                reflex = self.pixel_reflex(frame)
                if reflex:
                    print(f"⚡ Reflex → {reflex}")
                    self.execute(reflex, source="Reflex")

                time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user.")

        finally:
            # Phase 3: Consolidate what was learned this session
            if self.ai_available and self.kb.get("new_observations"):
                phase3_consolidate(self.or_client, self.g_model, self.kb)
            else:
                # Still save session count even if no AI
                self.kb["session_count"] = self.kb.get("session_count", 0) + 1
                self.kb["new_observations"] = []
                save_knowledge(self.kb)


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_config()
    kb  = load_knowledge()
    cfg = main_menu(cfg, kb)
    bot = BunnyBotAI(cfg, kb)
    bot.start_loop()
