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
import io
import threading
import struct
import socket

try:
    import av # type: ignore
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

try:
    import adbutils
    ADB_AVAILABLE = True
except ImportError:
    ADB_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
#  BunnyBot — Self-Learning AI Edition 🧠
# ─────────────────────────────────────────────────────────────────────────────

PACKAGE_NAME     = "com.bunny.runner3D.dg"
AI_CALL_INTERVAL = 1.5
LOOP_INTERVAL    = 0.08
CONFIG_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
KNOWLEDGE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_knowledge.json")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS = [
    "google/gemma-3-27b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-3-12b-it:free"
]
GOOGLE_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

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

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for index, model in enumerate(OPENROUTER_MODELS):
        if index > 0:
            print(f"🔄 Trying OpenRouter Fallback ({model})...")
            
        payload = {
            "model":       model,
            "max_tokens":  60,
            "temperature": 0.2,
            "messages":    [{"role": "user", "content": content}],
        }
        try:
            r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=10)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if index == 0:
                print(f"⚠️  OpenRouter Primary ({model}) failed: {e}")
            else:
                print(f"⚠️  OpenRouter Fallback ({model}) failed: {e}")
                
    return None

def _call_google(api_key: str, prompt: str, frame_b64: str | None = None) -> str | None:
    parts: list[dict] = []
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

def phase1_learn_game(cfg: dict, frame_bytes: bytes | None, kb: dict):
    if frame_bytes is None: return
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
    lines = result.splitlines()
    for line in lines:
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
        lines = result.splitlines()
        new_rules = [l[2:].strip() for l in lines if l.strip().startswith("- ")]
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
    return cfg  # Unreachable but satisfies linter

# ─────────────────────────────────────────────────────────────────────────────
#  BOT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BunnyBotAI:
    def __init__(self, config: dict, kb: dict):
        self.w, self.h    = 0, 0
        self.config       = config
        self.kb           = kb
        self.game_state   = "UNKNOWN"
        self.recent_moves: list[str] = []
        self._last_ai_ts  = 0.0
        self._fail_streak = 0
        self.ai_available = bool(config.get("openrouter_key") or config.get("google_key"))
        self._ai_active   = False
        
        # Init ADB connection (fast socket access)
        self.adb_device = None
        if ADB_AVAILABLE:
            try:
                adbc = adbutils.AdbClient(host="127.0.0.1", port=5037)
                if self.config.get("device_id"):
                    self.adb_device = adbc.device(serial=self.config["device_id"])
                else:
                    self.adb_device = adbc.device()
                if self.adb_device:
                    print(f"✅ ADB connected via adbutils to: {self.adb_device.serial}")
            except Exception as e:
                print(f"⚠️  adbutils connection failed: {e}")

        self._get_resolution()
        
        # Init Scrcpy Stream Buffer
        self.latest_frame_bytes = None
        self._streaming = False
        if PYAV_AVAILABLE and self.adb_device:
            self.start_scrcpy_stream()
            
        # Try loading template images for OpenCV
        self.templates = {}
        for t_name in ["barrier", "car", "hole"]:
            t_path = os.path.join(os.path.dirname(__file__), f"template_{t_name}.png")
            if os.path.exists(t_path):
                self.templates[t_name] = cv2.imread(t_path, cv2.IMREAD_GRAYSCALE)
                
        self.left_roi  = (int(self.h*0.65), int(self.h*0.75), int(self.w*0.10), int(self.w*0.45))
        self.right_roi = (int(self.h*0.65), int(self.h*0.75), int(self.w*0.55), int(self.w*0.90))

    def start_scrcpy_stream(self):
        print("🚀 Booting PyAV Scrcpy Stream...")
        try:
            # Push server
            server_path = os.path.join(os.path.dirname(__file__), "scrcpy-server.jar")
            if os.path.exists(server_path):
                self.adb_device.sync.push(server_path, "/data/local/tmp/scrcpy-server.jar")
                # Forward port
                self.adb_device.forward("tcp:8081", "localabstract:scrcpy")
                
                # Start server in background
                def run_server():
                    cmd = "CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 2.4 tunnel_forward=true control=false cleanup=false"
                    self.adb_device.shell(cmd)
                threading.Thread(target=run_server, daemon=True).start()
                time.sleep(1) # wait for server bindings

                self._streaming = True
                threading.Thread(target=self._scrcpy_receiver_loop, daemon=True).start()
                print("✅ PyAV Scrcpy Stream Thread Started.")
            else:
                print("⚠️ scrcpy-server.jar not found, falling back to adbutils screenshots.")
        except Exception as e:
            print(f"⚠️ Scrcpy stream init failed: {e}")
            
    def _scrcpy_receiver_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", 8081))
            _ = s.recv(68) # Dummy read for device name
            
            codec = av.CodecContext.create('h264', 'r')
            while self._streaming:
                # Scrcpy protocol video header: pts (8 bytes) + packet size (4 bytes)
                header = s.recv(12)
                if len(header) < 12: break
                _, pkt_size = struct.unpack(">QI", header)
                
                pkt_data = bytearray()
                while len(pkt_data) < pkt_size:
                    chunk = s.recv(pkt_size - len(pkt_data))
                    if not chunk: break
                    pkt_data.extend(chunk)
                    
                packet = av.Packet(bytes(pkt_data))
                frames = codec.decode(packet)
                for frame in frames:
                    # Convert raw NV12 to BGR numpy array
                    img = frame.to_ndarray(format='bgr24')
                    # Encode to PNG bytes so pixel_reflex interface stays consistent
                    success, enc = cv2.imencode('.png', img)
                    if success:
                        self.latest_frame_bytes = enc.tobytes()
        except Exception as e:
            print(f"Scrcpy Stream Error: {e}")
        finally:
            s.close()
            self._streaming = False

    def _adb(self, cmd):
        dev = f"-s {self.config['device_id']} " if self.config.get('device_id') else ""
        return f"adb {dev}{cmd}"
        
    def _run(self, cmd): return subprocess.check_output(cmd, shell=True)

    def _get_resolution(self):
        try:
            if getattr(self, 'adb_device', None) and hasattr(self.adb_device, 'window_size'):
                info = self.adb_device.window_size()
                self.w, self.h = info.width, info.height
            else:
                raw = self._run(self._adb("shell wm size")).decode()
                self.w, self.h = map(int, raw.split(":")[-1].strip().split("x"))
        except Exception:
            self.w, self.h = 1080, 2400
    
    def get_frame(self) -> bytes | None:
        # 1. Extreme Speed Streaming
        if self._streaming and self.latest_frame_bytes:
            return self.latest_frame_bytes
            
        # 2. Fast grab using adbutils socket instead of subprocess
        if self.adb_device:
            img = self.adb_device.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
            
        # 3. Slow Subprocess Fallback
        try:
            return self._run(self._adb("exec-out screencap -p"))
        except:
            return None

    def tap(self, x, y):
        cx, cy = int(x)+random.randint(-8,8), int(y)+random.randint(-8,8)
        if self.adb_device:
            self.adb_device.click(cx, cy)
        else:
            os.system(self._adb(f"shell input tap {cx} {cy}"))
        time.sleep(self.config["tap_cooldown"] + random.uniform(0, 0.05))

    def move_left(self):
        y = self.h*0.5
        if self.adb_device:
            self.adb_device.swipe(int(self.w*.7), int(y), int(self.w*.3), int(y), 0.075)
        else:
            os.system(self._adb(f"shell input swipe {int(self.w*.7)} {int(y)} {int(self.w*.3)} {int(y)} 75"))
        time.sleep(0.13)

    def move_right(self):
        y = self.h*0.5
        if self.adb_device:
            self.adb_device.swipe(int(self.w*.3), int(y), int(self.w*.7), int(y), 0.075)
        else:
            os.system(self._adb(f"shell input swipe {int(self.w*.3)} {int(y)} {int(self.w*.7)} {int(y)} 75"))
        time.sleep(0.13)

    def jump(self):
        self.tap(self.w*0.5, self.h*0.35)

    def pixel_reflex(self, frame_bytes: bytes | None) -> str | None:
        if not VISION_AVAILABLE or frame_bytes is None: return None
        try:
            arr   = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: return None
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 1. Advanced Mode: Multi-Scale Template Matching
            action_found = None
            if self.templates:
                for t_name, t_img in self.templates.items():
                    if t_img is None: continue
                    # Multi-scale check: Horizon (small), Mid (normal), Danger (large)
                    scales = [0.75, 1.0, 1.25]
                    for scale in scales:
                        scaled_t = cv2.resize(t_img, (0,0), fx=scale, fy=scale)
                        res = cv2.matchTemplate(gray, scaled_t, cv2.TM_CCOEFF_NORMED)
                        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                        if max_val > 0.75:  # Confidence threshold
                            
                            x_center = max_loc[0] + (scaled_t.shape[1] // 2)
                            y_center = max_loc[1] + (scaled_t.shape[0] // 2)
                            
                            # Vector Tracking Logic (Time to Collision estimate)
                            if y_center > self.h * 0.4: # Only react if it's descending past horizon
                                if x_center < self.w * 0.4:
                                    action_found = "MOVE RIGHT" 
                                elif x_center > self.w * 0.6:
                                    action_found = "MOVE LEFT"  
                                else:
                                    action_found = "JUMP"       
                                return action_found

            # If no templates found, assume "No Road"
            # 2. Phase 2 Gemini Supervisor Recovery
            now = time.time()
            if action_found is None and (now - self._last_ai_ts) > 5.0 and self.ai_available:
                self._last_ai_ts = now
                if not getattr(self, '_ai_active', False):
                    self._ai_active = True
                    def _run_sup():
                        try:
                            p = (
                                "You are a supervisor AI for an endless runner bot. "
                                "The bot is stuck and not seeing any game obstacles. "
                                "Look at this screen. Are we in a menu? Is there an ad? "
                                "If you see a 'Play', 'Close', 'X', or 'Try Again' button, OUTPUT ONLY the coordinates as: TAP [x] [y]\n"
                                "If you see gameplay (we are just safely running), OUTPUT EXACTLY: NONE\n"
                                "If we died, OUTPUT EXACTLY: JUMP\n"
                            )
                            print("🧠 No road detected for 5s. Triggering Gemini Supervisor...")
                            res = call_ai(self.config, p, frame_bytes)
                            if res:
                                res = res.strip()
                                if "TAP" in res or "JUMP" in res:
                                    self.execute(res, "SUPERVISOR")
                        finally:
                            self._ai_active = False
                    threading.Thread(target=_run_sup, daemon=True).start()

            # 3. Fallback Mode: Basic Pixel Brightness (Lane detection)
            r1y1,r1y2,r1x1,r1x2 = self.left_roi
            r2y1,r2y2,r2x1,r2x2 = self.right_roi
            lc = int(np.sum(gray[r1y1:r1y2, r1x1:r1x2] > 215))
            rc = int(np.sum(gray[r2y1:r2y2, r2x1:r2x2] > 215))
            if lc > 350 and lc >= rc: return "MOVE RIGHT"
            elif rc > 350:            return "MOVE LEFT"
        except Exception as e:
            print(f"Reflex error: {e}")
        return None

    def ai_decide(self, frame_bytes: bytes | None) -> str | None:
        # User only wants AI to learn the game initially, then OpenCV to play it.
        # If we already have rules, the AI should stop interfering with the gameplay loop.
        if not self.config["use_ai"] or not self.ai_available or frame_bytes is None: return None
        if len(self.kb.get("rules", [])) > 0: return None
        
        now = time.time()
        if now - self._last_ai_ts < AI_CALL_INTERVAL: return None
        if getattr(self, '_ai_active', False): return None
        
        self._last_ai_ts = now
        self._ai_active = True
        
        def _run_ai():
            try:
                prompt = build_game_prompt(self.game_state, self.recent_moves, self.kb)
                result = call_ai(self.config, prompt, frame_bytes)
                if result: 
                    print(f"🤖 AI [{self.game_state}] → {result}")
                    self.execute(result, "AI")
            finally:
                self._ai_active = False
                
        threading.Thread(target=_run_ai, daemon=True).start()
        return None

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

                # Starts background learning thread if applicable
                self.ai_decide(frame)
                    
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
