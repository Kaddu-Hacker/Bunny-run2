import subprocess
import time
import os
import sys
import base64
import json
import io
import random
from datetime import datetime
import requests

# ─────────────────────────────────────────────────────────────────────────────
#  BunnyBot — Self-Learning AI Edition 🧠
# ─────────────────────────────────────────────────────────────────────────────

PACKAGE_NAME     = "com.bunny.runner3D.dg"
AI_CALL_INTERVAL = 1.5
LOOP_INTERVAL    = 0.08
CONFIG_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
KNOWLEDGE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_knowledge.json")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MDL = "google/gemini-3.1-pro-preview"
GOOGLE_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

try:
    import cv2, numpy as np
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    default = {
        "openrouter_key": "",
        "google_key":     "",
        "active_ai":      "OPENROUTER", # "OPENROUTER" or "GOOGLE"
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
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
#  KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_KNOWLEDGE = {
    "game_summary":     "",
    "rules":            [],
    "state_hints":      {},
    "session_count":    0,
    "new_observations": [],
    "last_updated":     "",
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
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
#  AI CALLERS
# ─────────────────────────────────────────────────────────────────────────────

def _call_openrouter(api_key: str, prompt: str, frame_b64: str | None = None) -> str | None:
    content = []
    if frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{frame_b64}"}})
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": OPENROUTER_MDL,
        "max_tokens": 60,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  OpenRouter: {e}")
        return None

def _call_google(api_key: str, prompt: str, frame_b64: str | None = None) -> str | None:
    parts = []
    if frame_b64:
        parts.append({"inline_data": {"mime_type": "image/png", "data": frame_b64}})
    parts.append({"text": prompt})

    payload = {"contents": [{"parts": parts}]}
    url = f"{GOOGLE_URL}?key={api_key}"
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"⚠️  Google AI: {e}")
        return None

def call_ai(cfg: dict, prompt: str, frame_bytes: bytes | None = None) -> str | None:
    b64 = base64.b64encode(frame_bytes).decode() if frame_bytes else None
    
    # Try the specified active AI first
    if cfg.get("active_ai") == "OPENROUTER" and cfg.get("openrouter_key"):
        res = _call_openrouter(cfg["openrouter_key"], prompt, b64)
        if res: return res
        print("⚠️  OpenRouter failed, trying Google fallback...")
        if cfg.get("google_key"):
            return _call_google(cfg["google_key"], prompt, b64)

    elif cfg.get("active_ai") == "GOOGLE" and cfg.get("google_key"):
        res = _call_google(cfg["google_key"], prompt, b64)
        if res: return res
        print("⚠️  Google failed, trying OpenRouter fallback...")
        if cfg.get("openrouter_key"):
            return _call_openrouter(cfg["openrouter_key"], prompt, b64)
            
    # Fallback to whatever is available if active_ai is not set properly, or fallback from above failed
    if cfg.get("openrouter_key"): return _call_openrouter(cfg["openrouter_key"], prompt, b64)
    if cfg.get("google_key"): return _call_google(cfg["google_key"], prompt, b64)
    
    return None

# ─────────────────────────────────────────────────────────────────────────────
#  LEARNING SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def phase1_learn_game(cfg: dict, frame_bytes: bytes, kb: dict):
    print("\n🎓 First run — AI is learning the game from the screen...")
    prompt = (
        "You are analyzing a mobile game called 'Bunny Runner 3D'.\n"
        "From this screenshot, provide:\n"
        "SUMMARY: <one sentence describing the game>\n"
        "RULES:\n"
        "- <rule 1: what to do and when>\n"
        "- <rule 2>\n"
        "... (5 to 10 rules covering gameplay, menus, ads, death screen)\n\n"
        "Focus on what a bot needs to know to play. Output the EXACT format requested."
    )
    result = call_ai(cfg, prompt, frame_bytes)
    if not result:
        print("⚠️  Could not learn game — will retry next run.")
        return

    summary, rules = "", []
    for line in result.splitlines():
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[8:].strip()
        elif line.startswith("- "):
            rules.append(line[2:].strip())

    if summary: kb["game_summary"] = summary
    if rules:   kb["rules"] = rules
    save_knowledge(kb)
    if summary or rules:
        print(f"✅ Game learned! {len(rules)} rules saved.")

def phase3_consolidate(cfg: dict, kb: dict):
    obs = kb.get("new_observations", [])
    if not obs: return
    print(f"\n🧠 Consolidating {len(obs)} observations into knowledge base...")
    existing  = "\n".join(f"- {r}" for r in kb.get("rules", []))
    obs_text  = "\n".join(f"- {o}" for o in obs[-20:])
    prompt = (
        f"Game bot knowledge base for 'Bunny Runner 3D'.\n\n"
        f"Existing rules:\n{existing or '(none)'}\n\n"
        f"New session observations:\n{obs_text}\n\n"
        f"List any NEW rules not already covered. "
        f"Format: one rule per line starting with '- '. "
        f"If nothing new, output exactly: NONE"
    )
    result = call_ai(cfg, prompt)
    if result and result.strip().upper() != "NONE":
        new_rules = [l[2:].strip() for l in result.splitlines() if l.strip().startswith("- ")]
        if new_rules:
            kb["rules"].extend(new_rules)
            print(f"✅ Added {len(new_rules)} new rules to knowledge base!")
    kb["new_observations"] = []
    kb["session_count"]    = kb.get("session_count", 0) + 1
    save_knowledge(kb)

def build_game_prompt(game_state: str, recent_moves: list, kb: dict) -> str:
    rules   = "\n".join(f"  - {r}" for r in kb.get("rules", [])) or "  (still learning)"
    summary = kb.get("game_summary", "Bunny Runner 3D is an endless runner.")
    recent  = ", ".join(recent_moves[-4:]) if recent_moves else "none"
    hint    = kb.get("state_hints", {}).get(game_state, "")
    return (
        f"You are a bot playing: {summary}\n\n"
        f"Learned rules:\n{rules}\n\n"
        f"Current game state: {game_state}\n"
        f"{('Hint: ' + hint) if hint else ''}\n"
        f"Last 4 moves: {recent}\n\n"
        f"Look VERY CAREFULLY at this screenshot. Your job is to OUTPUT A COMMAND.\n"
        f"If you see a menu, play button, or retry/revive button, you MUST output 'TAP [x] [y]'.\n"
        f"If you see gameplay (the bunny running), look for obstacles. If there is a barrier, output 'MOVE LEFT', 'MOVE RIGHT' or 'JUMP'.\n"
        f"DO NOT OUTPUT 'NONE' unless you are 100% sure the bunny is currently running on a completely empty path with no menus on screen.\n\n"
        f"Choose the SINGLE BEST ACTION. Output EXACTLY ONE LINE from these choices:\n"
        f"  MOVE LEFT\n  MOVE RIGHT\n  JUMP\n  NONE\n  TAP [x] [y]\n\n"
        f"Do not include any explanation. Just the command."
    )

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────────────────────────────────────

def main_menu(cfg: dict, kb: dict) -> dict:
    while True:
        os.system("clear")
        def ks(k): return "SET ✅" if k else "NOT SET ❌"
        sessions = kb.get("session_count", 0)
        rules    = len(kb.get("rules", []))
        
        active_ai_str = "OpenRouter" if cfg.get("active_ai") == "OPENROUTER" else "Google AI Studio"

        print("╔══════════════════════════════════════════════════════╗")
        print("║   🐰  BUNNY RUNNER 3D — SELF-LEARNING AI BOT        ║")
        print("╠══════════════════════════════════════════════════════╣")
        print(f"║  📡 OpenRouter Key : {ks(cfg.get('openrouter_key')):<33}║")
        print(f"║  🔑 Google AI Key  : {ks(cfg.get('google_key')):<33}║")
        print(f"║  ⭐ Active AI      : {active_ai_str:<33}║")
        print(f"║  🧠 Knowledge      : {(str(rules)+' rules, '+str(sessions)+' sessions'):<33}║")
        print(f"║  👁  Vision Reflex : {'OpenCV ✅' if VISION_AVAILABLE else 'pkg not installed ⚠️':<33}║")
        print(f"║  🤖 AI Mode        : {'ON ✅' if cfg['use_ai'] else 'OFF ❌':<33}║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  1. Set OpenRouter API Key                          ║")
        print("║  2. Set Google AI Studio Key                        ║")
        print("║  3. Select Active AI Method (Toggle)                ║")
        print("║  4. Set Target Device (IP:PORT or blank=local)      ║")
        print("║  5. Toggle AI Mode                                  ║")
        print("║  6. Clear Knowledge Base (reset learning)           ║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  S. START BOT          Q. QUIT                      ║")
        print("╚══════════════════════════════════════════════════════╝")

        choice = input("\nSelect Option: ").strip().upper()
        if choice == "1":
            k = input("  Paste OpenRouter key (Enter to clear): ").strip()
            cfg["openrouter_key"] = k; save_config(cfg)
            print("  ✅ Saved." if k else "  ✅ Cleared."); time.sleep(1)
        elif choice == "2":
            k = input("  Paste Google AI Studio key (Enter to clear): ").strip()
            cfg["google_key"] = k; save_config(cfg)
            print("  ✅ Saved." if k else "  ✅ Cleared."); time.sleep(1)
        elif choice == "3":
            if cfg.get("active_ai") == "OPENROUTER":
                cfg["active_ai"] = "GOOGLE"
            else:
                cfg["active_ai"] = "OPENROUTER"
            save_config(cfg)
            print(f"  ✅ Active AI changed to {cfg['active_ai']}."); time.sleep(1)
        elif choice == "4":
            cfg["device_id"] = input("  Device IP:PORT (blank=local): ").strip()
            save_config(cfg)
        elif choice == "5":
            cfg["use_ai"] = not cfg["use_ai"]; save_config(cfg)
        elif choice == "6":
            if input("  Reset all knowledge? (yes/no): ").strip().lower() == "yes":
                kb.update(DEFAULT_KNOWLEDGE); save_knowledge(kb)
                print("  ✅ Knowledge base cleared."); time.sleep(1)
        elif choice == "S":
            return cfg
        elif choice == "Q":
            sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
#  BOT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BunnyBotAI:
    def __init__(self, config: dict, kb: dict):
        self.config       = config
        self.kb           = kb
        self.game_state   = "UNKNOWN"
        self.recent_moves: list[str] = []
        self._last_ai_ts  = 0.0
        self._fail_streak = 0
        self.ai_available = bool(config.get("openrouter_key") or config.get("google_key"))
        self._get_resolution()
        self.left_roi  = (int(self.h*0.65), int(self.h*0.75), int(self.w*0.10), int(self.w*0.45))
        self.right_roi = (int(self.h*0.65), int(self.h*0.75), int(self.w*0.55), int(self.w*0.90))

    def _adb(self, cmd): return f"adb {('-s '+self.config['device_id']+' ') if self.config.get('device_id') else ''}{cmd}"
    def _run(self, cmd): return subprocess.check_output(cmd, shell=True)

    def _get_resolution(self):
        try:
            raw = self._run(self._adb("shell wm size")).decode()
            self.w, self.h = map(int, raw.split(":")[-1].strip().split("x"))
        except Exception:
            self.w, self.h = 1080, 2400

    def get_frame(self) -> bytes:
        return self._run(self._adb("exec-out screencap -p"))

    def tap(self, x, y):
        os.system(self._adb(f"shell input tap {int(x)+random.randint(-8,8)} {int(y)+random.randint(-8,8)}"))
        time.sleep(self.config["tap_cooldown"] + random.uniform(0, 0.05))

    def move_left(self):
        y = self.h*0.5
        os.system(self._adb(f"shell input swipe {int(self.w*.7)} {int(y)} {int(self.w*.3)} {int(y)} 75"))
        time.sleep(0.13)

    def move_right(self):
        y = self.h*0.5
        os.system(self._adb(f"shell input swipe {int(self.w*.3)} {int(y)} {int(self.w*.7)} {int(y)} 75"))
        time.sleep(0.13)

    def jump(self):
        self.tap(self.w*0.5, self.h*0.35)

    def pixel_reflex(self, frame_bytes: bytes) -> str | None:
        if not VISION_AVAILABLE or self.game_state != "PLAYING": return None
        try:
            arr   = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: return None
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            r1y1,r1y2,r1x1,r1x2 = self.left_roi
            r2y1,r2y2,r2x1,r2x2 = self.right_roi
            lc = int(np.sum(gray[r1y1:r1y2, r1x1:r1x2] > 215))
            rc = int(np.sum(gray[r2y1:r2y2, r2x1:r2x2] > 215))
            if lc > 350 and lc >= rc: return "MOVE RIGHT"
            elif rc > 350:            return "MOVE LEFT"
        except Exception: pass
        return None

    def ai_decide(self, frame_bytes: bytes) -> str | None:
        if not self.config["use_ai"] or not self.ai_available: return None
        now = time.time()
        if now - self._last_ai_ts < AI_CALL_INTERVAL: return None
        self._last_ai_ts = now
        prompt = build_game_prompt(self.game_state, self.recent_moves, self.kb)
        result = call_ai(self.config, prompt, frame_bytes)
        if result: print(f"🤖 AI [{self.game_state}] → {result}")
        return result

    def execute(self, command: str, source: str = "AI"):
        cmd = command.upper().strip()
        if not cmd or cmd == "NONE": return
        self.recent_moves.append(cmd)
        if len(self.recent_moves) > 10: self.recent_moves.pop(0)

        # Update game state heuristic based on command
        if "TAP" in cmd and self.game_state in ("DEAD","MAIN_MENU","REWARD","UNKNOWN","LOADING"):
            self.game_state = "LOADING"
        elif "MOVE" in cmd or "JUMP" in cmd:
            self.game_state = "PLAYING"

        # Force state updates to prevent "UNKNOWN" lock
        if self.game_state == "UNKNOWN" and cmd != "NONE":
             self.game_state = "MAIN_MENU" if "TAP" in cmd else "PLAYING"

        self.kb.setdefault("new_observations", []).append(f"[{self.game_state}] {source}→{cmd}")
        
        if   "MOVE LEFT"  in cmd: self.move_left()
        elif "MOVE RIGHT" in cmd: self.move_right()
        elif "JUMP"       in cmd: self.jump()
        elif cmd.startswith("TAP"):
            parts = cmd.replace("[","").replace("]","").split()
            try:    self.tap(float(parts[1]), float(parts[2]))
            except: self.tap(self.w*0.5, self.h*0.5)

    def start_loop(self):
        print(f"\n🧠 BunnyBot starting up! Active AI: {self.config.get('active_ai', 'OPENROUTER')}")
        print("   Switch to the game now!")
        for i in range(5, 0, -1):
            print(f"   Starting in {i}s...", end="\r", flush=True)
            time.sleep(1)
        print("\n🚀 Live! (Ctrl+C to stop)\n")

        if self.ai_available and not self.kb.get("game_summary"):
            try: phase1_learn_game(self.config, self.get_frame(), self.kb)
            except Exception as e: print(f"⚠️  Phase 1 skipped: {e}")

        try:
            while True:
                try:
                    frame = self.get_frame()
                    self._fail_streak = 0
                except Exception as e:
                    self._fail_streak += 1
                    print(f"⚠️  Capture fail: {e}")
                    if self._fail_streak >= 3: break
                    time.sleep(1); continue

                ai_cmd = self.ai_decide(frame)
                if ai_cmd:
                    self.execute(ai_cmd, "AI")
                    time.sleep(LOOP_INTERVAL)
                    continue

                reflex = self.pixel_reflex(frame)
                if reflex:
                    print(f"⚡ Reflex → {reflex}")
                    self.execute(reflex, "Reflex")

                time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            print("\n\n🛑 Stopped.")
        finally:
            if self.ai_available and self.kb.get("new_observations"):
                phase3_consolidate(self.config, self.kb)
            else:
                self.kb["session_count"] = self.kb.get("session_count", 0) + 1
                self.kb["new_observations"] = []
                save_knowledge(self.kb)

if __name__ == "__main__":
    cfg = load_config()
    kb  = load_knowledge()
    cfg = main_menu(cfg, kb)
    BunnyBotAI(cfg, kb).start_loop()
