#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   🐰  BunnyBot v7 — Bunny Runner 3D                                ║
║   Auto-Calibration  •  Adaptive Self-Tuning  •  Guided Controls    ║
╚══════════════════════════════════════════════════════════════════════╝

HOW THE BOT WORKS (read this once!)
─────────────────────────────────────
  Every 1/FPS seconds the bot:
    1. Takes a screenshot of your phone via ADB
    2. Converts it to HSV colour space
    3. Looks at a horizontal "lookahead strip" (middle of screen)
    4. Counts GREEN (grass) pixels on the LEFT half vs RIGHT half
       → More grass on LEFT  = path curves RIGHT → tap RIGHT
       → More grass on RIGHT = path curves LEFT  → tap LEFT
    5. Also checks LEFT/RIGHT danger zones for CREAM fence posts
       → Fence on LEFT  = dodge RIGHT
       → Fence on RIGHT = dodge LEFT
    6. If game-over screen detected → auto-tap retry

COLOUR ANALYSIS (from your screenshots)
─────────────────────────────────────────
  HSV scale: H=0-179, S=0-255, V=0-255

  GRASS  (olive green) : H=38-90,  S=50-255, V=60-200
  PATH   (brown dirt)  : H=8-35,   S=50-180, V=100-210
  FENCE  (cream/white) : H=0-50,   S=0-45,   V=175-255
  CARROT (orange)      : H=5-20,   S=200-255,V=150-230

  ⚠ Path & Fence share the same HUE (~H=15). Separated ONLY by saturation:
    PATH  S=80-150 (medium)   FENCE S=5-40 (near-white, very low)

  🌙 Night light shifts all H values warmer by +5 to +15

SETTINGS ARE SAVED to bunnybot_settings.json automatically.
Delete that file to fully reset to factory defaults.
"""

import os, sys, time, subprocess, traceback, json
from collections import deque
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("\n[FATAL] OpenCV / NumPy not found.")
    print("  Termux: pkg install python-numpy opencv-python -y")
    sys.exit(1)

try:
    import adbutils
    ADBUTILS_OK = True
except ImportError:
    ADBUTILS_OK = False

# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

SETTINGS_FILE = Path("bunnybot_settings.json")

# All keys that get saved to disk (internal/runtime keys excluded)
SAVEABLE_KEYS = {
    "device", "backend", "screencap_method", "game_package",
    "loop_fps", "startup_delay", "action_cooldown",
    "tap_left_x", "tap_right_x", "tap_y",
    "la_top", "la_bottom",
    "dz_left_x", "dz_right_x", "dz_y",
    "gameover_y", "gameover_x",
    "grass_lo", "grass_hi",
    "path_lo",  "path_hi",
    "fence_lo", "fence_hi",
    "grass_min_px", "grass_deadband", "path_deadband",
    "fence_colour_frac", "canny_lo", "canny_hi",
    "fence_edge_ratio", "fence_min_signals",
    "gameover_dark_frac", "gameover_dark_v_max", "gameover_bright_px",
    "vote_confirm", "debug", "debug_save_frames",
    "night_light_shift", "adaptive_tuning",
}

def save_settings(cfg):
    data = {}
    for k in SAVEABLE_KEYS:
        if k in cfg:
            v = cfg[k]
            # tuples → list for JSON
            if isinstance(v, tuple):
                v = list(v)
            data[k] = v
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"  ⚠ Could not save: {e}")
        return False

def load_settings(cfg):
    if not SETTINGS_FILE.exists():
        return False
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        count = 0
        for k, v in data.items():
            if k in SAVEABLE_KEYS and k in cfg:
                # restore tuples that are stored as lists
                if isinstance(cfg[k], tuple) and isinstance(v, list):
                    cfg[k] = tuple(v)
                else:
                    cfg[k] = v
                count += 1
        return count
    except Exception as e:
        print(f"  ⚠ Could not load settings: {e}")
        return False

def reset_one(cfg, defaults, key):
    """Reset a single key to factory default."""
    if key in defaults:
        cfg[key] = defaults[key]
        return True
    return False

def reset_group(cfg, defaults, keys):
    """Reset a group of keys."""
    for k in keys:
        reset_one(cfg, defaults, k)

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    # Connection
    "device":           "",
    "adb_timeout":      12,
    "backend":          "auto",
    "screencap_method": "auto",
    "game_package":     "com.kwalee.bunnyrunner",

    # Timing — affects how fast/responsive the bot is
    "loop_fps":        10,       # how many frames analysed per second
    "startup_delay":    4,       # seconds before bot activates after pressing S
    "action_cooldown": 0.20,     # min gap between taps in seconds

    # Tap positions (fraction 0.0-1.0 of screen width/height)
    "tap_left_x":  0.25,         # X position for left tap  (25% from left)
    "tap_right_x": 0.75,         # X position for right tap (75% from left)
    "tap_y":       0.65,         # Y position for all taps  (65% from top)

    # Lookahead strip — the horizontal band analysed for turn detection
    "la_top":    0.30,           # strip starts at 30% from top
    "la_bottom": 0.60,           # strip ends   at 60% from top

    # Danger zones — areas scanned for incoming fence posts
    "dz_left_x":  (0.02, 0.44), # left zone:  2% to 44% width
    "dz_right_x": (0.56, 0.98), # right zone: 56% to 98% width
    "dz_y":       (0.25, 0.75), # both zones: 25% to 75% height

    # Game-over zone
    "gameover_y": (0.55, 0.95),
    "gameover_x": (0.20, 0.80),

    # Colour ranges [H, S, V] — OpenCV HSV scale
    "grass_lo": [38,  50,  60],  # olive green (lower bound)
    "grass_hi": [90, 255, 200],  # olive green (upper bound)
    "path_lo":  [ 8,  50, 100],  # brown dirt  (lower bound)
    "path_hi":  [35, 180, 210],  # brown dirt  (upper bound)
    "fence_lo": [ 0,   0, 175],  # cream white (lower bound)
    "fence_hi": [50,  45, 255],  # cream white (upper bound)

    # Turn detection sensitivity
    "grass_min_px":   200,       # minimum grass pixels before trusting signal
    "grass_deadband": 0.12,      # imbalance needed to trigger turn (12%)
    "path_deadband":  0.10,      # same for path signal (backup)

    # Fence detection sensitivity
    "fence_colour_frac": 0.05,   # 5% of zone must be fence colour
    "canny_lo":          35,     # edge detection lower threshold
    "canny_hi":          110,    # edge detection upper threshold
    "fence_edge_ratio":  1.6,    # how much denser zone edges vs background
    "fence_min_signals": 1,      # how many signals (1=sensitive, 2=strict)

    # Game-over detection
    "gameover_dark_frac":  0.48,
    "gameover_dark_v_max": 68,
    "gameover_bright_px":  280,

    # Smoothing
    "vote_confirm": 1,           # frames that must agree before acting

    # Debug
    "debug":             False,
    "debug_save_frames": False,

    # Night light tracking
    "night_light_shift": 0,

    # Adaptive self-tuning
    "adaptive_tuning": True,     # auto-adjust deadbands based on performance
}

# Working config — copy of defaults, then overridden by saved file
CFG = dict(_DEFAULTS)
for k, v in _DEFAULTS.items():
    if isinstance(v, list):
        CFG[k] = list(v)
    elif isinstance(v, tuple):
        CFG[k] = tuple(v)
    else:
        CFG[k] = v

_loaded = load_settings(CFG)


# ═══════════════════════════════════════════════════════════════════════════════
#  ADB BACKENDS
# ═══════════════════════════════════════════════════════════════════════════════

class ADBSubprocessBackend:
    name = "adb-subprocess"

    def __init__(self, device=""):
        self.device      = device.strip()
        self._pfx        = self._make_pfx()
        self._cap_method = CFG["screencap_method"]

    def _make_pfx(self):
        return ["adb", "-s", self.device] if self.device else ["adb"]

    def _run(self, args, timeout=None):
        cmd = self._pfx + args
        try:
            r = subprocess.run(cmd, capture_output=True,
                               timeout=timeout or CFG["adb_timeout"])
            return r.returncode, r.stdout
        except subprocess.TimeoutExpired:
            return -1, b""
        except FileNotFoundError:
            print("[ADB] 'adb' not found — pkg install android-tools -y")
            return -2, b""

    def list_devices(self):
        _, out = self._run(["devices"])
        return [l.split("\t")[0]
                for l in out.decode(errors="ignore").strip().splitlines()[1:]
                if "\tdevice" in l]

    def auto_connect(self):
        devs = self.list_devices()
        if not devs:
            return False
        self.device = devs[0]
        self._pfx   = self._make_pfx()
        print(f"[ADB] Auto-selected: {self.device}")
        return True

    def is_connected(self):
        return bool(self.list_devices())

    def reconnect(self):
        print("[ADB] kill-server + reconnect…")
        subprocess.run(["adb", "kill-server"],  capture_output=True, timeout=8)
        time.sleep(1.5)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=8)
        time.sleep(1.0)
        if self.device:
            subprocess.run(["adb", "connect", self.device],
                           capture_output=True, timeout=8)
            time.sleep(1.0)

    def screencap(self):
        order = {
            "exec-out": self._cap_exec_out,
            "local":    self._cap_local_tmp,
            "pull":     self._cap_sdcard,
        }
        methods = [self._cap_method] + [m for m in order if m != self._cap_method]
        for method in methods:
            fn  = order.get(method, self._cap_local_tmp)
            img = fn()
            if img is not None:
                if method != self._cap_method:
                    print(f"[ADB] Switched screencap method → {method}")
                    self._cap_method        = method
                    CFG["screencap_method"] = method
                return img
        return None

    def _cap_exec_out(self):
        rc, data = self._run(["exec-out", "screencap", "-p"], timeout=10)
        return _decode_png(data) if rc == 0 and len(data) > 1000 else None

    def _cap_local_tmp(self):
        self._run(["shell", "screencap", "-p", "/data/local/tmp/_bbot.png"], timeout=10)
        rc, _ = self._run(["pull", "/data/local/tmp/_bbot.png", "/tmp/_bbot_l.png"], timeout=10)
        return cv2.imread("/tmp/_bbot_l.png") if rc == 0 else None

    def _cap_sdcard(self):
        self._run(["shell", "screencap", "-p", "/sdcard/_bbot.png"], timeout=10)
        rc, _ = self._run(["pull", "/sdcard/_bbot.png", "/tmp/_bbot_s.png"], timeout=10)
        return cv2.imread("/tmp/_bbot_s.png") if rc == 0 else None

    def test_all_methods(self):
        print("\n[ADB] Testing screencap methods…")
        chosen = None
        for label, fn in [("exec-out", self._cap_exec_out),
                          ("local-tmp", self._cap_local_tmp),
                          ("sdcard",    self._cap_sdcard)]:
            try:
                img = fn()
                if img is not None:
                    h, w = img.shape[:2]
                    print(f"  ✓  {label:<12}  {w}×{h}px")
                    chosen = chosen or label
                else:
                    print(f"  ✗  {label:<12}  returned None")
            except Exception as e:
                print(f"  ✗  {label:<12}  error: {e}")
        if chosen:
            self._cap_method        = chosen
            CFG["screencap_method"] = chosen
            print(f"\n  → Using: {chosen}")
            return True
        print("\n  ✗ All screencap methods failed.")
        print("    adb kill-server && adb connect <IP>:<PORT>")
        return False

    def tap(self, x, y):
        self._run(["shell", "input", "tap", str(x), str(y)])

    def shell(self, cmd):
        _, out = self._run(["shell"] + cmd.split())
        return out.decode(errors="ignore").strip()

    def launch_game(self):
        self._run(["shell", "monkey", "-p", CFG["game_package"],
                   "-c", "android.intent.category.LAUNCHER", "1"])

    def force_stop(self):
        self._run(["shell", "am", "force-stop", CFG["game_package"]])


class AdbUtilsBackend:
    name = "adbutils"

    def __init__(self, device=""):
        self._serial    = device.strip()
        self._client    = None
        self._device    = None
        self._connected = False

    def auto_connect(self):
        try:
            if self._client is None:
                self._client = adbutils.AdbClient(host="127.0.0.1", port=5037)
            devs = self._client.device_list()
            if not devs:
                return False
            self._device    = next((d for d in devs if d.serial == self._serial), devs[0])
            self._serial    = self._device.serial
            self._connected = True
            print(f"[adbutils] Connected: {self._device.serial}")
            return True
        except Exception as e:
            print(f"[adbutils] connect failed: {e}")
            return False

    def is_connected(self):
        if not self._connected or not self._device:
            return False
        try:
            self._device.get_state(); return True
        except Exception:
            self._connected = False; return False

    def reconnect(self):
        self._connected = False
        self._device    = None
        time.sleep(1.0)
        self.auto_connect()

    def screencap(self):
        if not self._connected or not self._device:
            return None
        try:
            pil = self._device.screenshot()
            if pil is None:
                return None
            arr = np.array(pil)
            if arr.ndim == 2:
                return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            if arr.shape[2] == 4:
                return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            return arr[:, :, ::-1].copy()
        except Exception as e:
            print(f"[adbutils] screencap: {e}")
            return None

    def tap(self, x, y):
        try:
            self._device.click(x, y)
        except Exception as e:
            print(f"[adbutils] tap: {e}")

    def shell(self, cmd):
        try:
            return self._device.shell(cmd)
        except Exception as e:
            return f"error: {e}"

    def launch_game(self):
        try:
            self._device.app_start(CFG["game_package"])
        except Exception:
            self.shell(f"monkey -p {CFG['game_package']} "
                       "-c android.intent.category.LAUNCHER 1")

    def force_stop(self):
        self.shell(f"am force-stop {CFG['game_package']}")


def _decode_png(data: bytes):
    clean = data.replace(b"\r\n", b"\n")
    buf   = np.frombuffer(clean, dtype=np.uint8)
    img   = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img if img is not None else \
           cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


# ═══════════════════════════════════════════════════════════════════════════════
#  DEVICE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class DeviceManager:
    def __init__(self):
        self.backend = None
        self._adb    = ADBSubprocessBackend(CFG["device"])

    @property
    def backend_name(self):
        return self.backend.name if self.backend else "none"

    def setup(self):
        mode = CFG["backend"]
        print(f"\n[BOT] Backend mode: {mode}")
        if mode == "adbutils":  return self._init_adbutils()
        if mode == "adb":       return self._init_adb()
        if ADBUTILS_OK:
            print("[BOT] Trying adbutils first…")
            if self._init_adbutils(silent=True):
                return True
            print("[BOT] adbutils unavailable → falling back to ADB subprocess")
        else:
            print("[BOT] adbutils not installed → using ADB subprocess")
        return self._init_adb()

    def _init_adbutils(self, silent=False):
        if not ADBUTILS_OK:
            if not silent:
                print("[ERROR] adbutils not installed.")
                print("  Fix: pip install adbutils --break-system-packages")
            return False
        b = AdbUtilsBackend(CFG["device"])
        if not b.auto_connect():
            if not silent: print("[ERROR] adbutils: no device."); _conn_help()
            return False
        img = b.screencap()
        if img is None:
            if not silent: print("[ERROR] adbutils: screencap returned None")
            return False
        print(f"[adbutils] ✓ {img.shape[1]}×{img.shape[0]}px")
        self.backend = b
        return True

    def _init_adb(self):
        b = self._adb
        if not CFG["device"]:
            if not b.auto_connect(): _conn_help(); return False
        else:
            if not b.is_connected():
                print(f"[ERROR] Device '{CFG['device']}' not reachable."); return False
        if not b.test_all_methods(): return False
        self.backend = b
        return True

    def run_diagnostics(self):
        print("\n" + "═"*56)
        print("  BACKEND DIAGNOSTICS")
        print("═"*56)
        print("\n▶ adbutils (pure Python — recommended)")
        if not ADBUTILS_OK:
            print("  ✗ Not installed")
            print("    Fix: pip install adbutils --break-system-packages")
        else:
            b = AdbUtilsBackend(CFG["device"])
            if b.auto_connect():
                img = b.screencap()
                if img is not None:
                    print(f"  ✓ Screencap OK  {img.shape[1]}×{img.shape[0]}px")
                else:
                    print("  ✗ Connected but screencap returned None")
            else:
                print("  ✗ No device found")
        print("\n▶ ADB subprocess")
        b2 = self._adb
        if not CFG["device"]: b2.auto_connect()
        if not b2.is_connected():
            print("  ✗ No device found"); _conn_help()
        else:
            print(f"  Device: {b2.device}")
            b2.test_all_methods()
        print("\n" + "═"*56 + "\n")

    def screencap(self): return self.backend.screencap() if self.backend else None
    def tap(self, x, y):
        if self.backend: self.backend.tap(x, y)
    def tap_left(self, w, h):
        self.tap(int(w * CFG["tap_left_x"]), int(h * CFG["tap_y"]))
    def tap_right(self, w, h):
        self.tap(int(w * CFG["tap_right_x"]), int(h * CFG["tap_y"]))
    def shell(self, cmd): return self.backend.shell(cmd) if self.backend else ""
    def launch_game(self):
        if self.backend: self.backend.launch_game()
    def force_stop(self):
        if self.backend: self.backend.force_stop()
    def reconnect(self):
        if self.backend: self.backend.reconnect()
    def restart_game(self, reason=""):
        print(f"[BOT] Restarting{' ('+reason+')' if reason else ''}…")
        self.force_stop(); time.sleep(1.5)
        self.launch_game(); time.sleep(4.0)


def _conn_help():
    print(
        "\n  No device found. Steps:\n"
        "    1. Developer Options → Wireless Debugging → ON\n"
        "    2. adb pair <IP>:<PAIR_PORT>    ← enter 6-digit code\n"
        "    3. adb connect <IP>:<CONN_PORT> ← main WD screen port\n"
        "    4. adb devices                  ← must say 'device'\n"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class Vision:
    def __init__(self):
        self._vote_buf = deque(maxlen=3)
        self._frame_n  = 0

    def decide(self, frame):
        self._frame_n += 1
        h, w = frame.shape[:2]
        dbg  = {"frame": self._frame_n, "w": w, "h": h}

        if self._is_game_over(frame, w, h):
            self._vote_buf.clear()
            dbg["reason"] = "GAME_OVER"
            return "RESTART", dbg

        fence_action, fdebug = self._detect_fences(frame, w, h)
        dbg.update(fdebug)
        if fence_action:
            self._vote_buf.clear()
            dbg["reason"] = f"FENCE → {fence_action}"
            return fence_action, dbg

        raw, tdebug = self._detect_turn(frame, w, h)
        dbg.update(tdebug)

        self._vote_buf.append(raw)
        n = len(self._vote_buf)
        needed = CFG["vote_confirm"]
        if n >= needed and all(v == raw for v in list(self._vote_buf)[-needed:]):
            action = raw
        else:
            action = "STRAIGHT"

        dbg["reason"] = f"TURN → {raw}" + ("" if action == raw else " (wait…)")
        return action, dbg

    def _is_game_over(self, frame, w, h):
        v = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
        dark_frac = np.count_nonzero(v < CFG["gameover_dark_v_max"]) / max(v.size, 1)
        if dark_frac < CFG["gameover_dark_frac"]:
            return False
        gy1 = int(CFG["gameover_y"][0] * h); gy2 = int(CFG["gameover_y"][1] * h)
        gx1 = int(CFG["gameover_x"][0] * w); gx2 = int(CFG["gameover_x"][1] * w)
        bright = np.count_nonzero(v[gy1:gy2, gx1:gx2] > 200)
        return int(bright) > CFG["gameover_bright_px"]

    def _detect_turn(self, frame, w, h):
        y1  = int(CFG["la_top"]    * h)
        y2  = int(CFG["la_bottom"] * h)
        mid = w // 2

        strip     = frame[y1:y2, :]
        strip_hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)

        lo_g = np.array(CFG["grass_lo"], dtype=np.uint8)
        hi_g = np.array(CFG["grass_hi"], dtype=np.uint8)
        lo_p = np.array(CFG["path_lo"],  dtype=np.uint8)
        hi_p = np.array(CFG["path_hi"],  dtype=np.uint8)

        grass_mask = cv2.inRange(strip_hsv, lo_g, hi_g)
        path_mask  = cv2.inRange(strip_hsv, lo_p, hi_p)

        gL = int(np.count_nonzero(grass_mask[:, :mid]))
        gR = int(np.count_nonzero(grass_mask[:, mid:]))
        g_total = gL + gR

        sig_A   = "STRAIGHT"
        g_ratio = 0.0
        if g_total >= CFG["grass_min_px"]:
            g_ratio = gR / g_total
            db = CFG["grass_deadband"]
            if g_ratio > 0.5 + db:
                sig_A = "LEFT"
            elif g_ratio < 0.5 - db:
                sig_A = "RIGHT"

        pL = int(np.count_nonzero(path_mask[:, :mid]))
        pR = int(np.count_nonzero(path_mask[:, mid:]))
        p_total = pL + pR

        sig_B   = "STRAIGHT"
        p_ratio = 0.0
        if p_total >= CFG["grass_min_px"] // 2:
            p_ratio = pR / p_total
            db = CFG["path_deadband"]
            if p_ratio > 0.5 + db:
                sig_B = "RIGHT"
            elif p_ratio < 0.5 - db:
                sig_B = "LEFT"

        if sig_A != "STRAIGHT" and sig_B != "STRAIGHT":
            direction = sig_A   # grass wins on conflict
        elif sig_A != "STRAIGHT":
            direction = sig_A
        elif sig_B != "STRAIGHT":
            direction = sig_B
        else:
            direction = "STRAIGHT"

        return direction, {
            "grass_L": gL, "grass_R": gR, "grass_ratio": round(g_ratio, 3),
            "path_L":  pL, "path_R":  pR, "path_ratio":  round(p_ratio, 3),
            "sig_A": sig_A, "sig_B": sig_B, "turn": direction,
        }

    def _detect_fences(self, frame, w, h):
        lo_f = np.array(CFG["fence_lo"], dtype=np.uint8)
        hi_f = np.array(CFG["fence_hi"], dtype=np.uint8)

        lx1 = int(CFG["dz_left_x"][0]  * w); lx2 = int(CFG["dz_left_x"][1]  * w)
        rx1 = int(CFG["dz_right_x"][0] * w); rx2 = int(CFG["dz_right_x"][1] * w)
        zy1 = int(CFG["dz_y"][0] * h);        zy2 = int(CFG["dz_y"][1] * h)

        hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, CFG["canny_lo"], CFG["canny_hi"])

        def analyse_zone(x1, x2, name):
            roi_h = zy2 - zy1
            roi_w = x2 - x1
            n_px  = roi_h * roi_w
            if n_px == 0:
                return False, 0, {}
            roi_hsv  = hsv[zy1:zy2, x1:x2]
            roi_edge = edges[zy1:zy2, x1:x2]

            fence_mask  = cv2.inRange(roi_hsv, lo_f, hi_f)
            colour_frac = np.count_nonzero(fence_mask) / n_px
            sig1 = colour_frac > CFG["fence_colour_frac"]

            top_h = max(1, roi_h // 2)
            dz_dens = np.count_nonzero(roi_edge[:top_h]) / max(1, top_h * roi_w)
            bg_y1   = max(0, zy1 - top_h)
            bg_dens = np.count_nonzero(edges[bg_y1:zy1, x1:x2]) / max(1, top_h * roi_w)
            sig2 = (dz_dens > 0.008 and bg_dens < dz_dens / CFG["fence_edge_ratio"])

            n_sigs  = int(sig1) + int(sig2)
            blocked = n_sigs >= CFG["fence_min_signals"]
            return blocked, n_sigs, {
                f"col_{name}":  round(colour_frac, 3),
                f"edge_{name}": round(dz_dens, 4),
                f"sigs_{name}": n_sigs,
            }

        l_blocked, l_sigs, l_dbg = analyse_zone(lx1, lx2, "L")
        r_blocked, r_sigs, r_dbg = analyse_zone(rx1, rx2, "R")
        dbg = {**l_dbg, **r_dbg}

        if l_blocked and r_blocked:
            action = "RIGHT" if l_sigs >= r_sigs else "LEFT"
        elif l_blocked:
            action = "RIGHT"
        elif r_blocked:
            action = "LEFT"
        else:
            action = None

        return action, dbg


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO CALIBRATOR
#  Samples a real gameplay screenshot and sets colour ranges automatically.
#  Strategy:
#    - Divides the lookahead strip into left-edge / centre / right-edge bands
#    - Left & right edges are almost always GRASS in normal gameplay
#    - Centre is almost always PATH
#    - Top-left/right corners of danger zones contain FENCE when posts are present
#    - Fits HSV ranges around the median colours found ± tolerance
# ═══════════════════════════════════════════════════════════════════════════════

class AutoCalibrator:
    # Tolerance added around sampled median values
    H_TOL = 14   # ±14 hue units
    S_TOL = 55   # ±55 saturation units
    V_TOL = 55   # ±55 value units

    def calibrate(self, frame):
        """
        Analyse a gameplay frame and return updated colour ranges.
        Returns dict of updated CFG keys, or None if frame looks wrong.
        """
        h, w = frame.shape[:2]
        hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ── Sample regions ────────────────────────────────────────────────────
        # Lookahead strip bounds
        ly1 = int(CFG["la_top"]    * h)
        ly2 = int(CFG["la_bottom"] * h)
        strip_h = ly2 - ly1

        # Grass: left 15% and right 15% of lookahead strip
        grass_left  = hsv[ly1:ly2,  :int(w*0.15)]
        grass_right = hsv[ly1:ly2,   int(w*0.85):]
        grass_pixels = np.vstack([
            grass_left.reshape(-1, 3),
            grass_right.reshape(-1, 3)
        ])

        # Path: centre 20% of lookahead strip, bottom half of strip
        cx1 = int(w * 0.40); cx2 = int(w * 0.60)
        path_pixels = hsv[ly1 + strip_h//2 : ly2, cx1:cx2].reshape(-1, 3)

        # Fence: sample top rows of both danger zones
        lx1 = int(CFG["dz_left_x"][0]  * w); lx2 = int(CFG["dz_left_x"][1]  * w)
        rx1 = int(CFG["dz_right_x"][0] * w); rx2 = int(CFG["dz_right_x"][1] * w)
        zy1 = int(CFG["dz_y"][0] * h)
        fence_h = max(1, int(0.08 * h))   # top 8% of danger zone
        fence_left  = hsv[zy1:zy1+fence_h,  lx1:lx2].reshape(-1, 3)
        fence_right = hsv[zy1:zy1+fence_h,  rx1:rx2].reshape(-1, 3)
        fence_pixels = np.vstack([fence_left, fence_right])

        results = {}
        log     = []

        # ── Fit grass ─────────────────────────────────────────────────────────
        g_ok, g_lo, g_hi, g_msg = self._fit(grass_pixels, "grass",
            h_range=(25, 100), s_min=30, v_min=40,
            label="green/olive")
        if g_ok:
            results["grass_lo"] = g_lo
            results["grass_hi"] = g_hi
        log.append(("GRASS", g_ok, g_msg))

        # ── Fit path ──────────────────────────────────────────────────────────
        p_ok, p_lo, p_hi, p_msg = self._fit(path_pixels, "path",
            h_range=(5, 40), s_min=30, v_min=60,
            label="brown/tan",
            s_hi_cap=190)   # cap S max so fence doesn't bleed in
        if p_ok:
            results["path_lo"] = p_lo
            results["path_hi"] = p_hi
        log.append(("PATH", p_ok, p_msg))

        # ── Fit fence (only if bright near-white pixels found) ───────────────
        # Fence is near-white so filter for high-V, low-S pixels first
        bright_mask = (fence_pixels[:, 1] < 80) & (fence_pixels[:, 2] > 140)
        fence_bright = fence_pixels[bright_mask]
        if len(fence_bright) > 50:
            f_ok, f_lo, f_hi, f_msg = self._fit(fence_bright, "fence",
                h_range=(0, 60), s_min=0, v_min=130,
                label="cream/white",
                s_hi_cap=70)
            if f_ok:
                # Fence: keep S max LOW (it's the key separator from path)
                f_hi[1] = min(f_hi[1], 70)
                results["fence_lo"] = f_lo
                results["fence_hi"] = f_hi
            log.append(("FENCE", f_ok, f_msg))
        else:
            log.append(("FENCE", False,
                "No bright near-white pixels found in danger zones. "
                "Try calibrating when fence posts are visible."))

        return results, log

    def _fit(self, pixels, name, h_range, s_min, v_min,
             label="", s_hi_cap=255):
        """
        Filter pixels to expected hue range, then fit min/max ± tolerance.
        Returns (success, lo_array, hi_array, message).
        """
        if len(pixels) == 0:
            return False, None, None, "No pixels sampled"

        # Filter to plausible hue range for this element
        h_arr = pixels[:, 0].astype(int)
        s_arr = pixels[:, 1].astype(int)
        v_arr = pixels[:, 2].astype(int)

        mask = (
            (h_arr >= h_range[0]) & (h_arr <= h_range[1]) &
            (s_arr >= s_min) &
            (v_arr >= v_min)
        )
        filt = pixels[mask]

        if len(filt) < 30:
            return False, None, None, (
                f"Only {len(filt)} matching pixels — "
                f"expected {label} but this region looks wrong. "
                "Is the game paused or showing menus?"
            )

        # Use percentile-based fitting to ignore outliers
        h_med = int(np.percentile(filt[:, 0], 50))
        s_med = int(np.percentile(filt[:, 1], 50))
        v_med = int(np.percentile(filt[:, 2], 50))

        # 10th/90th percentile for the actual range, then add tolerance
        h_lo = max(0,   int(np.percentile(filt[:,0], 10)) - self.H_TOL)
        h_hi = min(179, int(np.percentile(filt[:,0], 90)) + self.H_TOL)
        s_lo = max(0,   int(np.percentile(filt[:,1], 10)) - self.S_TOL)
        s_hi = min(255, int(np.percentile(filt[:,1], 90)) + self.S_TOL)
        v_lo = max(0,   int(np.percentile(filt[:,2], 10)) - self.V_TOL)
        v_hi = min(255, int(np.percentile(filt[:,2], 90)) + self.V_TOL)

        # Apply caps
        s_hi = min(s_hi, s_hi_cap)

        lo = [h_lo, s_lo, v_lo]
        hi = [h_hi, s_hi, v_hi]

        msg = (f"Median HSV=({h_med},{s_med},{v_med})  "
               f"Range H:{h_lo}-{h_hi} S:{s_lo}-{s_hi} V:{v_lo}-{v_hi}  "
               f"from {len(filt)} pixels")
        return True, lo, hi, msg


# ═══════════════════════════════════════════════════════════════════════════════
#  ADAPTIVE TUNER
#  Watches bot performance in real-time and nudges settings automatically.
#
#  What it tracks every 60-frame window:
#    - turn_rate:   how often the bot is turning vs going straight
#      → too high (>40%) = deadband too LOW → raise it (phantom turns)
#      → too low  (< 5%) = deadband too HIGH → lower it (missing turns)
#    - zigzag_rate: how often direction flips L→R→L in 3 frames
#      → high = noisy signal, raise deadband or vote_confirm
#    - death_rate:  game-over events per minute
#      → rising fast = something is very wrong, try lowering fence threshold
#    - fence_trigger_rate: how often fence dodge fires
#      → very high = false positives, raise fence_colour_frac
#      → zero while dying = not catching fences, lower fence_colour_frac
#
#  Adjustments are small and logged so you can see what it changed.
#  You can disable adaptive tuning from the menu.
# ═══════════════════════════════════════════════════════════════════════════════

class AdaptiveTuner:
    WINDOW     = 60     # frames per evaluation window
    MAX_NUDGE  = 3      # max adjustments per window (prevents wild swings)

    # How aggressively to nudge — fraction of current value
    DEADBAND_STEP   = 0.01   # 1 percentage point per nudge
    FENCE_FRAC_STEP = 0.005

    # Thresholds that trigger nudges
    TURN_RATE_HIGH  = 0.40   # >40% turns = too sensitive
    TURN_RATE_LOW   = 0.04   # <4%  turns = too sluggish
    ZIGZAG_HIGH     = 0.15   # >15% zigzags = noisy
    FENCE_HIGH      = 0.25   # >25% fence triggers = likely false positives
    FENCE_LOW_DEATH = 0.02   # <2% fence but dying = missing fences

    def __init__(self, enabled=True):
        self.enabled       = enabled
        self._actions      = deque(maxlen=self.WINDOW)
        self._fence_events = deque(maxlen=self.WINDOW)
        self._deaths       = deque(maxlen=10)
        self._nudge_count  = 0
        self._window_count = 0
        self.log           = deque(maxlen=50)   # last 50 tuning decisions
        self._last_eval    = 0

    def record(self, action, fence_triggered, is_death):
        """Call once per frame with the bot's decision."""
        if not self.enabled:
            return
        self._actions.append(action)
        self._fence_events.append(1 if fence_triggered else 0)
        if is_death:
            self._deaths.append(time.time())

        self._window_count += 1
        if self._window_count >= self.WINDOW:
            self._window_count = 0
            self._nudge_count  = 0
            self._evaluate()

    def _evaluate(self):
        """Analyse the window and apply nudges."""
        n = len(self._actions)
        if n < 20:
            return

        actions_list = list(self._actions)

        # ── Turn rate ─────────────────────────────────────────────────────────
        turns = sum(1 for a in actions_list if a in ("LEFT","RIGHT"))
        turn_rate = turns / n

        # ── Zigzag rate: L→R or R→L within 3 consecutive frames ──────────────
        zigzags = 0
        for i in range(2, len(actions_list)):
            a, b, c = actions_list[i-2], actions_list[i-1], actions_list[i]
            if ((a == "LEFT"  and c == "RIGHT") or
                (a == "RIGHT" and c == "LEFT")) and b in ("LEFT","RIGHT"):
                zigzags += 1
        zigzag_rate = zigzags / max(n - 2, 1)

        # ── Fence trigger rate ────────────────────────────────────────────────
        fence_rate = sum(self._fence_events) / max(len(self._fence_events), 1)

        # ── Recent deaths (last 2 minutes) ────────────────────────────────────
        now = time.time()
        recent_deaths = sum(1 for t in self._deaths if now - t < 120)

        nudges = []

        # ── Apply nudges ──────────────────────────────────────────────────────

        # 1. Too many phantom turns / zigzagging → raise deadband
        if turn_rate > self.TURN_RATE_HIGH and self._nudge_count < self.MAX_NUDGE:
            old = CFG["grass_deadband"]
            CFG["grass_deadband"] = min(0.40, old + self.DEADBAND_STEP)
            nudges.append(f"turn_rate={turn_rate:.0%} HIGH → grass_deadband "
                          f"{old:.2f}→{CFG['grass_deadband']:.2f}")
            self._nudge_count += 1

        if zigzag_rate > self.ZIGZAG_HIGH and self._nudge_count < self.MAX_NUDGE:
            old = CFG["grass_deadband"]
            CFG["grass_deadband"] = min(0.40, old + self.DEADBAND_STEP)
            nudges.append(f"zigzag={zigzag_rate:.0%} HIGH → grass_deadband "
                          f"{old:.2f}→{CFG['grass_deadband']:.2f}")
            self._nudge_count += 1
            # Also raise vote_confirm if still low
            if CFG["vote_confirm"] < 2:
                CFG["vote_confirm"] = 2
                nudges.append("zigzag HIGH → vote_confirm 1→2")

        # 2. Barely turning at all → lower deadband
        if (turn_rate < self.TURN_RATE_LOW and
                CFG["grass_deadband"] > 0.06 and
                self._nudge_count < self.MAX_NUDGE):
            old = CFG["grass_deadband"]
            CFG["grass_deadband"] = max(0.06, old - self.DEADBAND_STEP)
            nudges.append(f"turn_rate={turn_rate:.0%} LOW → grass_deadband "
                          f"{old:.2f}→{CFG['grass_deadband']:.2f}")
            self._nudge_count += 1

        # 3. Too many fence triggers (likely false positives) → raise threshold
        if fence_rate > self.FENCE_HIGH and self._nudge_count < self.MAX_NUDGE:
            old = CFG["fence_colour_frac"]
            CFG["fence_colour_frac"] = min(0.25, old + self.FENCE_FRAC_STEP)
            nudges.append(f"fence_rate={fence_rate:.0%} HIGH → fence_colour_frac "
                          f"{old:.3f}→{CFG['fence_colour_frac']:.3f}")
            self._nudge_count += 1

        # 4. Dying repeatedly but fence barely triggering → lower threshold
        if (recent_deaths >= 3 and
                fence_rate < self.FENCE_LOW_DEATH and
                CFG["fence_colour_frac"] > 0.02 and
                self._nudge_count < self.MAX_NUDGE):
            old = CFG["fence_colour_frac"]
            CFG["fence_colour_frac"] = max(0.02, old - self.FENCE_FRAC_STEP)
            nudges.append(f"deaths={recent_deaths} + fence_rate low → fence_colour_frac "
                          f"{old:.3f}→{CFG['fence_colour_frac']:.3f}")
            self._nudge_count += 1

        # ── Log results ───────────────────────────────────────────────────────
        summary = (f"[ADAPT] turns={turn_rate:.0%} zigzag={zigzag_rate:.0%} "
                   f"fence={fence_rate:.0%} deaths={recent_deaths}")
        if nudges:
            for n_msg in nudges:
                entry = f"{summary} | nudge: {n_msg}"
                self.log.append(entry)
                print(f"\n  🔧 {entry}")
            save_settings(CFG)   # persist the auto-nudges
        else:
            self.log.append(summary + " | no change")

    def show_log(self):
        if not self.log:
            print("  No adaptive tuning events yet.")
            return
        print(f"\n  Last {len(self.log)} adaptive tuning events:")
        for entry in self.log:
            print(f"    {entry}")


# ═══════════════════════════════════════════════════════════════════════════════
#  VISUAL DUMP
# ═══════════════════════════════════════════════════════════════════════════════

def save_visual_dump(frame, path="bbot_debug.jpg"):
    if frame is None:
        print("[VIS] No frame to dump.")
        return

    h, w = frame.shape[:2]
    vis  = frame.copy()
    hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    grass_mask = cv2.inRange(hsv, np.array(CFG["grass_lo"], dtype=np.uint8),
                                  np.array(CFG["grass_hi"], dtype=np.uint8))
    path_mask  = cv2.inRange(hsv, np.array(CFG["path_lo"],  dtype=np.uint8),
                                  np.array(CFG["path_hi"],  dtype=np.uint8))
    fence_mask = cv2.inRange(hsv, np.array(CFG["fence_lo"], dtype=np.uint8),
                                  np.array(CFG["fence_hi"], dtype=np.uint8))

    vis[path_mask  > 0] = (0,   220, 220)   # yellow = path
    vis[grass_mask > 0] = (0,   220,  50)   # green  = grass
    vis[fence_mask > 0] = (30,   30, 255)   # red    = fence

    ly1 = int(CFG["la_top"]    * h)
    ly2 = int(CFG["la_bottom"] * h)
    cv2.rectangle(vis, (0, ly1), (w, ly2), (255, 255, 0), 3)
    cv2.line(vis, (w//2, ly1), (w//2, ly2), (255,255,255), 2)
    cv2.putText(vis, "LOOKAHEAD", (6, ly1+22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 2)

    lx1 = int(CFG["dz_left_x"][0]*w);  lx2 = int(CFG["dz_left_x"][1]*w)
    rx1 = int(CFG["dz_right_x"][0]*w); rx2 = int(CFG["dz_right_x"][1]*w)
    zy1 = int(CFG["dz_y"][0]*h);        zy2 = int(CFG["dz_y"][1]*h)
    cv2.rectangle(vis, (lx1, zy1), (lx2, zy2), (0, 0, 255), 2)
    cv2.rectangle(vis, (rx1, zy1), (rx2, zy2), (0, 0, 255), 2)
    cv2.putText(vis, "DZ-L", (lx1+4, zy1+20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,255), 1)
    cv2.putText(vis, "DZ-R", (rx1+4, zy1+20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,255), 1)

    cv2.circle(vis, (int(w*CFG["tap_left_x"]),  int(h*CFG["tap_y"])), 22, (0,128,255), 3)
    cv2.circle(vis, (int(w*CFG["tap_right_x"]), int(h*CFG["tap_y"])), 22, (0,128,255), 3)
    cv2.putText(vis, "TAP-L", (int(w*CFG["tap_left_x"])-30,  int(h*CFG["tap_y"])-26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,128,255), 1)
    cv2.putText(vis, "TAP-R", (int(w*CFG["tap_right_x"])-30, int(h*CFG["tap_y"])-26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,128,255), 1)

    gp = int(np.count_nonzero(grass_mask))
    pp = int(np.count_nonzero(path_mask))
    fp = int(np.count_nonzero(fence_mask))

    items = [
        ((0,220,220), f"PATH  {pp}px"),
        ((0,220, 50), f"GRASS {gp}px"),
        ((30, 30,255), f"FENCE {fp}px"),
        ((255,255,  0), "Lookahead"),
        ((0,  0, 255), "Danger zones"),
        ((0,128,255),  "Tap points"),
    ]
    box_y = h - len(items)*22 - 12
    cv2.rectangle(vis, (0, box_y-4), (190, h), (15,15,15), -1)
    for i, (col, label) in enumerate(items):
        y = box_y + i*22 + 16
        cv2.rectangle(vis, (6, y-13), (22, y+3), col, -1)
        cv2.putText(vis, label, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230,230,230), 1)

    cv2.imwrite(path, vis, [cv2.IMWRITE_JPEG_QUALITY, 92])

    print(f"\n  ✅ Saved: {path}")
    print(f"  Grass pixels : {gp}  {'⚠ LOW — raise grass_hi[1] (S max)' if gp < 500 else '✓'}")
    print(f"  Path  pixels : {pp}  {'⚠ LOW — widen path ranges'         if pp < 500 else '✓'}")
    print(f"  Fence pixels : {fp}  {'⚠ LOW — raise fence_hi[1] (S max)' if fp < 100 else '✓'}")
    print()
    print("  Colours in image:")
    print("   YELLOW = path detected   GREEN = grass detected   RED = fence detected")
    print("   BLUE box = lookahead strip   RED box = danger zones")
    print()
    print("  Pull to PC:  adb pull bbot_debug.jpg .")
    print()
    if gp < 500:
        print("  ⚠ Grass fix: menu → C → Colour Ranges → grass_hi S → raise to 255")
    if fp < 100:
        print("  ⚠ Fence fix: menu → C → Colour Ranges → fence_hi S → raise slightly")


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class BunnyBot:
    def __init__(self):
        self.dm      = DeviceManager()
        self.vision  = Vision()
        self.tuner   = AdaptiveTuner(enabled=CFG.get("adaptive_tuning", True))
        self.calibr  = AutoCalibrator()
        self._reset_state()

    def _reset_state(self):
        self.frame_count       = 0
        self.start_time        = 0.0
        self.last_act_time     = 0.0
        self.consecutive_fails = 0
        self.screen_w          = 0
        self.screen_h          = 0

    def setup(self) -> bool:
        ok = self.dm.setup()
        if ok:
            print(f"[BOT] Backend: {self.dm.backend_name}  ✓")
            print("[BOT] Ready!\n")
        return ok

    def run(self):
        delay = CFG["startup_delay"]
        print(f"\n[BOT] Starting in {delay}s — switch to the game now!")
        for i in range(delay, 0, -1):
            print(f"  {i}…", end="\r", flush=True)
            time.sleep(1)
        print("[BOT] 🐰  GO!  (Ctrl+C to stop)\n")

        if CFG["debug_save_frames"]:
            os.makedirs("debug_frames", exist_ok=True)

        self.start_time = time.time()
        period = 1.0 / max(1, CFG["loop_fps"])

        while True:
            t0 = time.time()
            try:
                self._tick()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[WARN] Tick error: {e}")
                if CFG["debug"]: traceback.print_exc()
                time.sleep(0.3)
            spare = period - (time.time() - t0)
            if spare > 0:
                time.sleep(spare)

    def _tick(self):
        self.frame_count += 1
        frame = self.dm.screencap()

        if frame is None:
            self.consecutive_fails += 1
            if self.consecutive_fails >= 5:
                print("[WARN] 5 consecutive screencap failures → reconnecting…")
                self.dm.reconnect()
                self.consecutive_fails = 0
            return
        self.consecutive_fails       = 0
        self.screen_w, self.screen_h = frame.shape[1], frame.shape[0]

        action, dbg = self.vision.decide(frame)
        is_death        = (action == "RESTART")
        fence_triggered = bool(dbg.get("sigs_L", 0) or dbg.get("sigs_R", 0))
        self.tuner.record(action, fence_triggered, is_death)
        self._execute(action, self.screen_w, self.screen_h)

        if CFG["debug"]:
            fps = self.frame_count / max(time.time() - self.start_time, 0.001)
            print(
                f"[{self.frame_count:05d}] {action:<8} | "
                f"{dbg.get('reason',''):<30} | "
                f"A={dbg.get('sig_A','-')} B={dbg.get('sig_B','-')} | "
                f"gL={dbg.get('grass_L','-')} gR={dbg.get('grass_R','-')} | "
                f"fL={dbg.get('sigs_L','-')} fR={dbg.get('sigs_R','-')} | "
                f"{fps:.1f}fps"
            )

        if CFG["debug_save_frames"]:
            self._save_debug_frame(frame, action, dbg, self.screen_w, self.screen_h)

    def _execute(self, action: str, w: int, h: int):
        now = time.time()

        if action == "RESTART":
            print("[BOT] 💀 Game over — tapping retry…")
            time.sleep(0.8)
            self.dm.tap(w // 2, int(h * 0.75))
            time.sleep(1.5)
            self.last_act_time = time.time()
            return

        if now - self.last_act_time < CFG["action_cooldown"]:
            return

        if action == "LEFT":
            self.dm.tap_left(w, h)
            self.last_act_time = now
        elif action == "RIGHT":
            self.dm.tap_right(w, h)
            self.last_act_time = now

    def _save_debug_frame(self, frame, action, dbg, w, h):
        vis = frame.copy()
        col = {"LEFT":(0,165,255),"RIGHT":(0,165,255),
               "RESTART":(0,0,255),"STRAIGHT":(0,220,0)}.get(action,(180,180,180))
        cv2.putText(vis, action, (15,55), cv2.FONT_HERSHEY_SIMPLEX, 1.8, col, 4)
        cv2.putText(vis, dbg.get("reason",""), (15,100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        os.makedirs("debug_frames", exist_ok=True)
        cv2.imwrite(f"debug_frames/{self.frame_count:06d}_{action}.jpg",
                    vis, [cv2.IMWRITE_JPEG_QUALITY, 70])

    def print_stats(self):
        elapsed = max(time.time() - self.start_time, 0.001)
        fps     = self.frame_count / elapsed
        print(f"\n[BOT] Ran for {elapsed:.0f}s | {self.frame_count} frames | "
              f"{fps:.1f}fps avg | backend: {self.dm.backend_name}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MENU SYSTEM — Clean, Categorised, Informative
# ═══════════════════════════════════════════════════════════════════════════════

W = 66  # menu width

def _line(text="", pad=True):
    if text == "":
        print("║" + " "*(W-2) + "║")
        return
    inner = W - 4
    print("║  " + text.ljust(inner)[:inner] + "  ║")

def _divider(label=""):
    if label:
        side = (W - len(label) - 4) // 2
        print("╠" + "─"*side + "  " + label + "  " + "─"*(W-side-len(label)-4) + "╣")
    else:
        print("╠" + "═"*(W-2) + "╣")

def _top():
    print("╔" + "═"*(W-2) + "╗")

def _bot():
    print("╚" + "═"*(W-2) + "╝")

def _sep():
    print("╠" + "─"*(W-2) + "╣")

def show_status(bot):
    dev   = CFG["device"] or "(auto-detect)"
    bknd  = bot.dm.backend_name
    au    = "✓ installed" if ADBUTILS_OK else "✗ not installed  pip install adbutils"
    saved = "✓ Saved" if SETTINGS_FILE.exists() else "✗ Not saved yet"
    nl    = f"+{CFG['night_light_shift']}" if CFG['night_light_shift'] else "OFF"
    fps   = CFG['loop_fps']
    cool  = CFG['action_cooldown']
    dbg   = "ON" if CFG["debug"] else "OFF"
    adapt = "ON ✓" if CFG.get("adaptive_tuning", True) else "OFF"

    _top()
    _line("🐰  BunnyBot v7 — Bunny Runner 3D")
    _line("Settings auto-save on every change • Delete bunnybot_settings.json to full reset")
    _sep()
    _line(f"Device      : {dev}")
    _line(f"Backend     : {bknd}   │  adbutils: {au}")
    _line(f"Night light : {nl}   │  FPS: {fps}   │  Cooldown: {cool}s   │  Debug: {dbg}")
    _line(f"Adaptive    : {adapt}   │  Settings: {saved}")
    _divider()


def show_main_menu(bot):
    show_status(bot)
    _line("MAIN MENU — choose a category or action")
    _sep()
    _line("  A   ► AUTO CALIBRATE ★        (auto-detect colours from screenshot!)")
    _line("  K   ► Adaptive Self-Tuning    (bot adjusts itself while running)")
    _sep()
    _line("  C   ► Colour Tuning           (manual: grass, path, fence, night light)")
    _line("  T   ► Timing & Speed          (FPS, cooldown, reaction speed)")
    _line("  R   ► Reaction Sensitivity    (turn sharpness, fence strictness)")
    _line("  Z   ► Zone Positions          (lookahead, danger zones, tap spots)")
    _line("  D   ► Device & Connection     (ADB, backend, screencap method)")
    _line("  X   ► Reset Options           (reset specific groups or factory reset)")
    _sep()
    _line("  V   ► Visual Dump             (see what the bot sees — do this first!)")
    _line("  0   ► Full Diagnostics        (test ADB connection + screencap)")
    _line("  S   ► START BOT               (launches the bot)")
    _line("  Q   ► Quit")
    _bot()


# ─────────────────── COLOUR TUNING SUBMENU ───────────────────

def menu_colours(bot):
    while True:
        nl = CFG["night_light_shift"]
        _top()
        _line("COLOUR TUNING")
        _line("Use 'V' (visual dump) to see which colours are detected.")
        _line("YELLOW=path  GREEN=grass  RED=fence  on the debug image.")
        _sep()
        _line("NIGHT LIGHT (do this FIRST if you use night light mode)")
        _line(f"  NL  ► Apply night light H-shift    current: +{nl}")
        _line("        Night light warms colours → shifts Hue +5 to +15")
        _line("        Effect: fixes washed-out colour detection")
        _line("        Start with NL=8, check with V, adjust if needed")
        _sep()
        _line("GRASS COLOUR  (olive green — most important for turn detection)")
        _line(f"  G1  ► H min/max  [{CFG['grass_lo'][0]}, {CFG['grass_hi'][0]}]")
        _line("        Lower H-min if grass appears orange/red on V dump")
        _line("        Raise H-max if sky/other greens trigger false turns")
        _line(f"  G2  ► S min/max  [{CFG['grass_lo'][1]}, {CFG['grass_hi'][1]}]")
        _line("        Lower S-min if too few green pixels (grass not detected)")
        _line(f"  G3  ► V min/max  [{CFG['grass_lo'][2]}, {CFG['grass_hi'][2]}]")
        _line("        Lower V-min if grass appears dark/shadowed")
        _sep()
        _line("PATH COLOUR  (brown dirt — backup signal for turns)")
        _line(f"  P1  ► H min/max  [{CFG['path_lo'][0]}, {CFG['path_hi'][0]}]")
        _line(f"  P2  ► S min/max  [{CFG['path_lo'][1]}, {CFG['path_hi'][1]}]")
        _line("        KEEP S-min above 45! Below that = fence pixels bleed in")
        _line(f"  P3  ► V min/max  [{CFG['path_lo'][2]}, {CFG['path_hi'][2]}]")
        _sep()
        _line("FENCE COLOUR  (cream/white posts — obstacle avoidance)")
        _line(f"  F1  ► H min/max  [{CFG['fence_lo'][0]}, {CFG['fence_hi'][0]}]")
        _line(f"  F2  ► S max      [{CFG['fence_hi'][1]}]  (keep LOW — fence is near-white)")
        _line("        Raise S-max if fence posts are not detected (red on V)")
        _line("        Don't raise above 80 or path pixels bleed in")
        _line(f"  F3  ► V min      [{CFG['fence_lo'][2]}]  (keep HIGH — fence is bright)")
        _sep()
        _line("  V   ► Visual dump (check current colours)")
        _line("  B   ► Back to main menu")
        _bot()

        c = input("  Option: ").strip().lower()

        if c == "b": break

        elif c == "nl":
            print("\n  Night light H-shift")
            print("  0 = off (normal screen)")
            print("  8 = typical night light")
            print("  15 = maximum (very warm/orange screen)")
            print("  ⚠ This ADDS to current shift. Use 0 to fully reset first.")
            old = CFG["night_light_shift"]
            try:
                v = int(input(f"  Amount 0-15 [currently applied: +{old}]: "))
                v = max(0, min(15, v))
                # Reset all colours to defaults first, then apply fresh shift
                for key in ("grass_lo","grass_hi","path_lo","path_hi","fence_lo","fence_hi"):
                    CFG[key] = list(_DEFAULTS[key])
                CFG["night_light_shift"] = 0
                if v > 0:
                    _apply_nl_shift(v)
                else:
                    print("  ✓ Night light OFF — colours reset to default")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c in ("g1","g2","g3","p1","p2","p3","f1","f2","f3"):
            _edit_colour(c)

        elif c == "v":
            _do_visual_dump(bot)

        else:
            print("  Unknown option.")


def _apply_nl_shift(amount):
    for key in ("grass_lo","grass_hi","path_lo","path_hi","fence_lo","fence_hi"):
        CFG[key][0] = min(179, CFG[key][0] + amount)
    CFG["night_light_shift"] = amount
    print(f"  ✓ Night light +{amount} applied to all H ranges")


def _edit_colour(code):
    """Generic HSV range editor."""
    mapping = {
        "g1": ("grass", 0, "H (hue)"),
        "g2": ("grass", 1, "S (saturation)"),
        "g3": ("grass", 2, "V (brightness)"),
        "p1": ("path",  0, "H (hue)"),
        "p2": ("path",  1, "S (saturation)"),
        "p3": ("path",  2, "V (brightness)"),
        "f1": ("fence", 0, "H (hue)"),
        "f2": ("fence", 1, "S (saturation)"),
        "f3": ("fence", 2, "V (brightness)"),
    }
    name, idx, label = mapping[code]
    lo_key = f"{name}_lo"
    hi_key = f"{name}_hi"
    lo_cur = CFG[lo_key][idx]
    hi_cur = CFG[hi_key][idx]

    print(f"\n  {name.upper()} — {label}")
    print(f"  Current range: {lo_cur} to {hi_cur}  (0-255 scale)")

    if name == "fence" and idx == 1:
        print("  ⚠ For fence saturation: only edit the MAX (hi). Keep min at 0.")
        try:
            v = int(input(f"  New S max [current {hi_cur}, default {_DEFAULTS[hi_key][idx]}]: "))
            CFG[hi_key][idx] = max(0, min(255, v))
            print(f"  ✓ fence_hi S → {CFG[hi_key][idx]}")
            _autosave()
        except ValueError: print("  Invalid.")
        return

    try:
        lo_new = int(input(f"  New min [{lo_cur}] (enter to keep): ") or lo_cur)
        hi_new = int(input(f"  New max [{hi_cur}] (enter to keep): ") or hi_cur)
        lo_new = max(0, min(255, lo_new))
        hi_new = max(0, min(255, hi_new))
        if lo_new > hi_new:
            print("  ⚠ Min must be ≤ max — swapping.")
            lo_new, hi_new = hi_new, lo_new
        CFG[lo_key][idx] = lo_new
        CFG[hi_key][idx] = hi_new
        print(f"  ✓ {lo_key}[{idx}]={lo_new}  {hi_key}[{idx}]={hi_new}")
        _autosave()
    except ValueError:
        print("  Invalid.")


# ─────────────────── TIMING SUBMENU ───────────────────

def menu_timing(bot):
    while True:
        _top()
        _line("TIMING & SPEED")
        _sep()
        _line(f"  1   ► Loop FPS            current: {CFG['loop_fps']}")
        _line("        How many screenshots per second the bot takes.")
        _line("        Higher = faster reaction, higher CPU/battery use.")
        _line("        🐢 Too low (< 8): misses fast turns")
        _line("        🐇 10-15: sweet spot   20+: very aggressive")
        _sep()
        _line(f"  2   ► Action cooldown      current: {CFG['action_cooldown']}s")
        _line("        Minimum time between two taps.")
        _line("        🐢 Too high (> 0.4): can't handle rapid back-to-back turns")
        _line("        🐇 Too low (< 0.1): spammy taps, rabbit zigzags")
        _line("        Rabbit going too fast? Raise to 0.25-0.35")
        _line("        Missing turns? Lower to 0.10-0.15")
        _sep()
        _line(f"  3   ► Startup delay        current: {CFG['startup_delay']}s")
        _line("        Seconds after pressing S before the bot activates.")
        _line("        Gives you time to switch to the game.")
        _sep()
        _line(f"  4   ► Frame confirmation   current: {CFG['vote_confirm']} frame(s)")
        _line("        How many consecutive frames must agree before turning.")
        _line("        1 = instant reaction (can be twitchy on bad screenshots)")
        _line("        2 = smoother but ~100ms slower at 10fps")
        _line("        Rabbit zigzagging randomly? Raise to 2")
        _sep()
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "1":
            try:
                v = int(input(f"  FPS 1-30 [current {CFG['loop_fps']}]: "))
                CFG["loop_fps"] = max(1, min(30, v))
                print(f"  ✓ loop_fps → {CFG['loop_fps']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "2":
            try:
                v = float(input(f"  Cooldown seconds [current {CFG['action_cooldown']}]: "))
                CFG["action_cooldown"] = max(0.05, min(2.0, v))
                print(f"  ✓ action_cooldown → {CFG['action_cooldown']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "3":
            try:
                v = int(input(f"  Startup delay seconds [current {CFG['startup_delay']}]: "))
                CFG["startup_delay"] = max(1, min(30, v))
                print(f"  ✓ startup_delay → {CFG['startup_delay']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "4":
            try:
                v = int(input(f"  Frame confirmation 1-3 [current {CFG['vote_confirm']}]: "))
                CFG["vote_confirm"] = max(1, min(3, v))
                print(f"  ✓ vote_confirm → {CFG['vote_confirm']}")
                _autosave()
            except ValueError: print("  Invalid.")

        else:
            print("  Unknown option.")


# ─────────────────── REACTION SENSITIVITY SUBMENU ───────────────────

def menu_reaction(bot):
    while True:
        gdb = int(CFG['grass_deadband']*100)
        pdb = int(CFG['path_deadband']*100)
        _top()
        _line("REACTION SENSITIVITY")
        _line("These control HOW MUCH the scene must change before the bot turns.")
        _sep()
        _line("TURN DETECTION")
        _line(f"  1   ► Grass deadband       current: {gdb}%")
        _line("        How lopsided grass must be (L vs R) before turning.")
        _line("        🐢 Too high (> 20%): misses gentle turns, turns late")
        _line("        🐇 Too low  (< 8%):  phantom turns on straight paths")
        _line("        Recommended: 10-15%  │  Jittery? Raise it.")
        _sep()
        _line(f"  2   ► Path deadband         current: {pdb}%")
        _line("        Same concept but for the dirt path signal (backup).")
        _line("        Usually keep 2-3% below grass deadband.")
        _sep()
        _line(f"  3   ► Min grass pixels      current: {CFG['grass_min_px']}")
        _line("        Minimum grass pixels needed before trusting the signal.")
        _line("        Low on grass in frame? Lower this (try 100).")
        _line("        False turns at game start? Raise this (try 400).")
        _sep()
        _line("FENCE DETECTION")
        _line(f"  4   ► Fence signals needed  current: {CFG['fence_min_signals']}/2")
        _line("        1 = trigger on ANY fence signal (more sensitive)")
        _line("        2 = need BOTH signals to agree (fewer false dodges)")
        _line("        Bumping into fences? Set to 1")
        _line("        Dodging when no fence? Set to 2")
        _sep()
        _line(f"  5   ► Fence colour fraction current: {CFG['fence_colour_frac']:.3f}")
        _line("        % of danger zone that must be fence-coloured.")
        _line("        Lower = catches thin/partial fence views")
        _line("        0.03 = very sensitive   0.08 = less sensitive")
        _sep()
        _line(f"  6   ► Fence edge ratio      current: {CFG['fence_edge_ratio']}")
        _line("        How much more edges the fence zone needs vs background.")
        _line("        Lower = more fence dodges   Higher = fewer, stricter")
        _sep()
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "1":
            try:
                v = float(input(f"  Grass deadband % [current {gdb}]: "))
                CFG["grass_deadband"] = max(3, min(45, v)) / 100
                print(f"  ✓ grass_deadband → {CFG['grass_deadband']:.2f} ({v:.0f}%)")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "2":
            try:
                v = float(input(f"  Path deadband % [current {pdb}]: "))
                CFG["path_deadband"] = max(3, min(45, v)) / 100
                print(f"  ✓ path_deadband → {CFG['path_deadband']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "3":
            try:
                v = int(input(f"  Min grass pixels [current {CFG['grass_min_px']}]: "))
                CFG["grass_min_px"] = max(50, min(2000, v))
                print(f"  ✓ grass_min_px → {CFG['grass_min_px']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "4":
            try:
                v = int(input("  Fence signals needed [1 or 2]: "))
                CFG["fence_min_signals"] = max(1, min(2, v))
                print(f"  ✓ fence_min_signals → {CFG['fence_min_signals']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "5":
            try:
                v = float(input(f"  Fence colour fraction [current {CFG['fence_colour_frac']}]: "))
                CFG["fence_colour_frac"] = max(0.01, min(0.30, v))
                print(f"  ✓ fence_colour_frac → {CFG['fence_colour_frac']:.3f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "6":
            try:
                v = float(input(f"  Fence edge ratio [current {CFG['fence_edge_ratio']}]: "))
                CFG["fence_edge_ratio"] = max(1.0, min(5.0, v))
                print(f"  ✓ fence_edge_ratio → {CFG['fence_edge_ratio']}")
                _autosave()
            except ValueError: print("  Invalid.")

        else:
            print("  Unknown option.")


# ─────────────────── ZONE POSITIONS SUBMENU ───────────────────

def menu_zones(bot):
    while True:
        _top()
        _line("ZONE POSITIONS  (all values are 0.0-1.0 fraction of screen)")
        _sep()
        _line("LOOKAHEAD STRIP  (horizontal band analysed for turns)")
        _line(f"  L1  ► Top edge      current: {CFG['la_top']:.2f}  ({int(CFG['la_top']*100)}% from top)")
        _line(f"  L2  ► Bottom edge   current: {CFG['la_bottom']:.2f}  ({int(CFG['la_bottom']*100)}% from top)")
        _line("        Too far up? Bot sees the horizon not the path → late turns")
        _line("        Too far down? Bot sees behind itself → misses upcoming turns")
        _sep()
        _line("TAP POSITIONS  (where taps are sent on screen)")
        _line(f"  T1  ► Left tap X    current: {CFG['tap_left_x']:.2f}  ({int(CFG['tap_left_x']*100)}% from left)")
        _line(f"  T2  ► Right tap X   current: {CFG['tap_right_x']:.2f}  ({int(CFG['tap_right_x']*100)}% from left)")
        _line(f"  T3  ► Tap Y         current: {CFG['tap_y']:.2f}  ({int(CFG['tap_y']*100)}% from top)")
        _line("        Taps not registering? Adjust Y — try 0.5 to 0.8")
        _sep()
        _line("DANGER ZONES  (areas scanned for fence posts)")
        _line(f"  D1  ► Left zone X   current: {CFG['dz_left_x'][0]:.2f} to {CFG['dz_left_x'][1]:.2f}")
        _line(f"  D2  ► Right zone X  current: {CFG['dz_right_x'][0]:.2f} to {CFG['dz_right_x'][1]:.2f}")
        _line(f"  D3  ► Zone height   current: {CFG['dz_y'][0]:.2f} to {CFG['dz_y'][1]:.2f}")
        _line("        Use V (visual dump) to see red DZ boxes — adjust if wrong")
        _sep()
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "l1":
            try:
                v = float(input(f"  la_top [current {CFG['la_top']}]: "))
                CFG["la_top"] = max(0.0, min(CFG["la_bottom"]-0.05, v))
                print(f"  ✓ la_top → {CFG['la_top']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "l2":
            try:
                v = float(input(f"  la_bottom [current {CFG['la_bottom']}]: "))
                CFG["la_bottom"] = max(CFG["la_top"]+0.05, min(1.0, v))
                print(f"  ✓ la_bottom → {CFG['la_bottom']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "t1":
            try:
                v = float(input(f"  tap_left_x [current {CFG['tap_left_x']}]: "))
                CFG["tap_left_x"] = max(0.0, min(0.49, v))
                print(f"  ✓ tap_left_x → {CFG['tap_left_x']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "t2":
            try:
                v = float(input(f"  tap_right_x [current {CFG['tap_right_x']}]: "))
                CFG["tap_right_x"] = max(0.51, min(1.0, v))
                print(f"  ✓ tap_right_x → {CFG['tap_right_x']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "t3":
            try:
                v = float(input(f"  tap_y [current {CFG['tap_y']}]: "))
                CFG["tap_y"] = max(0.0, min(1.0, v))
                print(f"  ✓ tap_y → {CFG['tap_y']:.2f}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "d1":
            try:
                a = float(input(f"  dz_left_x start [current {CFG['dz_left_x'][0]}]: "))
                b_v = float(input(f"  dz_left_x end   [current {CFG['dz_left_x'][1]}]: "))
                CFG["dz_left_x"] = (max(0,min(1,a)), max(0,min(1,b_v)))
                print(f"  ✓ dz_left_x → {CFG['dz_left_x']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "d2":
            try:
                a = float(input(f"  dz_right_x start [current {CFG['dz_right_x'][0]}]: "))
                b_v = float(input(f"  dz_right_x end   [current {CFG['dz_right_x'][1]}]: "))
                CFG["dz_right_x"] = (max(0,min(1,a)), max(0,min(1,b_v)))
                print(f"  ✓ dz_right_x → {CFG['dz_right_x']}")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c == "d3":
            try:
                a = float(input(f"  dz_y top    [current {CFG['dz_y'][0]}]: "))
                b_v = float(input(f"  dz_y bottom [current {CFG['dz_y'][1]}]: "))
                CFG["dz_y"] = (max(0,min(1,a)), max(0,min(1,b_v)))
                print(f"  ✓ dz_y → {CFG['dz_y']}")
                _autosave()
            except ValueError: print("  Invalid.")

        else:
            print("  Unknown option.")


# ─────────────────── DEVICE SUBMENU ───────────────────

def menu_device(bot):
    while True:
        _top()
        _line("DEVICE & CONNECTION")
        _sep()
        _line(f"  1   ► Set device IP:PORT   current: {CFG['device'] or '(auto)'}")
        _line("        Leave blank to auto-detect any connected device.")
        _line(f"  2   ► Set backend           current: {CFG['backend']}")
        _line("        auto = try adbutils then adb subprocess")
        _line("        adbutils = pure Python, most reliable")
        _line("        adb = requires adb binary installed")
        _line(f"  3   ► Screencap method      current: {CFG['screencap_method']}")
        _line("        auto tries all methods. Change if screencap fails.")
        _line("  4   ► Set game package name")
        _line(f"        current: {CFG['game_package']}")
        _line("  5   ► Toggle debug logging")
        _line(f"        current: {'ON' if CFG['debug'] else 'OFF'}")
        _line("        Shows per-frame decisions in terminal while running")
        _line("  6   ► Toggle save debug frames")
        _line(f"        current: {'ON' if CFG['debug_save_frames'] else 'OFF'}")
        _line("        Saves annotated JPGs to ./debug_frames/ (uses disk space)")
        _sep()
        _line("  0   ► Full diagnostics (test all backends + screencap methods)")
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "1":
            v = input("  IP:PORT (blank=auto): ").strip()
            CFG["device"] = v
            bot.dm = DeviceManager()
            print(f"  ✓ device → '{v or 'auto'}'")
            _autosave()

        elif c == "2":
            v = input("  [auto/adbutils/adb]: ").strip().lower()
            if v in ("auto","adbutils","adb"):
                CFG["backend"] = v
                bot.dm = DeviceManager()
                print(f"  ✓ backend → {v}")
                _autosave()
            else: print("  Invalid.")

        elif c == "3":
            v = input("  [auto/exec-out/local/pull]: ").strip().lower()
            if v in ("auto","exec-out","local","pull"):
                CFG["screencap_method"] = v
                bot.dm._adb._cap_method = v
                print(f"  ✓ screencap_method → {v}")
                _autosave()
            else: print("  Invalid.")

        elif c == "4":
            v = input(f"  Package [{CFG['game_package']}]: ").strip()
            if v:
                CFG["game_package"] = v
                print(f"  ✓ game_package → {v}")
                _autosave()

        elif c == "5":
            CFG["debug"] = not CFG["debug"]
            print(f"  ✓ debug → {'ON' if CFG['debug'] else 'OFF'}")
            _autosave()

        elif c == "6":
            CFG["debug_save_frames"] = not CFG["debug_save_frames"]
            print(f"  ✓ debug_save_frames → {'ON' if CFG['debug_save_frames'] else 'OFF'}")
            _autosave()

        elif c == "0":
            bot.dm.run_diagnostics()

        else: print("  Unknown option.")


# ─────────────────── RESET SUBMENU ───────────────────

def menu_reset():
    while True:
        _top()
        _line("RESET OPTIONS")
        _line("Resets individual groups without touching other settings.")
        _sep()
        _line("  1   ► Reset COLOURS only    (grass/path/fence + night light)")
        _line("  2   ► Reset TIMING only     (FPS, cooldown, delay, vote_confirm)")
        _line("  3   ► Reset SENSITIVITY only (deadbands, fence thresholds)")
        _line("  4   ► Reset ZONES only      (lookahead, danger zones, tap spots)")
        _sep()
        _line("  9   ► FULL FACTORY RESET    (resets EVERYTHING)")
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "1":
            confirm = input("  Reset colours to defaults? [y/N]: ").strip().lower()
            if confirm == "y":
                reset_group(CFG, _DEFAULTS, [
                    "grass_lo","grass_hi","path_lo","path_hi",
                    "fence_lo","fence_hi","night_light_shift"
                ])
                print("  ✓ Colours reset.")
                _autosave()

        elif c == "2":
            confirm = input("  Reset timing to defaults? [y/N]: ").strip().lower()
            if confirm == "y":
                reset_group(CFG, _DEFAULTS, [
                    "loop_fps","startup_delay","action_cooldown","vote_confirm"
                ])
                print("  ✓ Timing reset.")
                _autosave()

        elif c == "3":
            confirm = input("  Reset sensitivity to defaults? [y/N]: ").strip().lower()
            if confirm == "y":
                reset_group(CFG, _DEFAULTS, [
                    "grass_min_px","grass_deadband","path_deadband",
                    "fence_colour_frac","canny_lo","canny_hi",
                    "fence_edge_ratio","fence_min_signals",
                ])
                print("  ✓ Sensitivity reset.")
                _autosave()

        elif c == "4":
            confirm = input("  Reset zones to defaults? [y/N]: ").strip().lower()
            if confirm == "y":
                reset_group(CFG, _DEFAULTS, [
                    "la_top","la_bottom",
                    "dz_left_x","dz_right_x","dz_y",
                    "tap_left_x","tap_right_x","tap_y",
                ])
                print("  ✓ Zones reset.")
                _autosave()

        elif c == "9":
            confirm = input("  FULL RESET — are you sure? Type YES: ").strip()
            if confirm == "YES":
                for k, v in _DEFAULTS.items():
                    if isinstance(v, list): CFG[k] = list(v)
                    elif isinstance(v, tuple): CFG[k] = tuple(v)
                    else: CFG[k] = v
                if SETTINGS_FILE.exists():
                    SETTINGS_FILE.unlink()
                print("  ✓ Full factory reset complete. Settings file deleted.")

        else:
            print("  Unknown option.")


def menu_autocal(bot):
    """Auto-calibration menu — samples live screenshot to set colour ranges."""
    _top()
    _line("AUTO CALIBRATION")
    _line("The bot will take a screenshot and analyse your game's actual colours.")
    _line("For best results:")
    _line("  • Be IN the game, actively running (not paused/menus)")
    _line("  • Make sure you can see grass on BOTH sides of the path")
    _line("  • Night light ON? Turn it on before calibrating")
    _sep()
    _line("  1   ► Run auto-calibration now")
    _line("  2   ► Run calibration + apply if all colours found")
    _line("  V   ► Visual dump after calibration (to verify)")
    _line("  B   ► Back")
    _bot()

    while True:
        c = input("  Option: ").strip().lower()
        if c == "b":
            return

        elif c in ("1", "2"):
            if not bot.dm.backend:
                if not bot.dm.setup():
                    print("  Fix connection first.")
                    continue

            print("\n  📸 Capturing screenshot…")
            frame = bot.dm.screencap()
            if frame is None:
                print("  ✗ Screenshot failed. Go to Device → Full Diagnostics.")
                continue

            print("  🔬 Analysing colours…\n")
            results, log = bot.calibr.calibrate(frame)

            # Show what was found
            print("  ┌─ Calibration Results ─────────────────────────────────┐")
            all_ok = True
            for element, ok, msg in log:
                status = "✓" if ok else "✗"
                print(f"  │  {status} {element:<6} {msg}")
                if not ok:
                    all_ok = False
            print("  └───────────────────────────────────────────────────────┘")

            if not results:
                print("\n  ✗ No colours could be detected.")
                print("    Make sure the game is running and the path/grass is visible.")
                continue

            # Show proposed changes
            print("\n  Proposed changes:")
            for key, val in results.items():
                old = CFG.get(key, "?")
                print(f"    {key:<12} : {old}  →  {val}")

            if c == "2" or (c == "1" and all_ok):
                if not all_ok:
                    ans = input("\n  Some elements not found. Apply partial results? [y/N]: ").strip().lower()
                    if ans != "y":
                        print("  Cancelled.")
                        continue

                # Apply results
                for key, val in results.items():
                    CFG[key] = val

                # Reset night light shift since we recalibrated
                CFG["night_light_shift"] = 0

                _autosave()
                print("\n  ✅ Colour ranges updated and saved!")
                print("  Press V to run a visual dump and verify the colours look correct.")

            elif c == "1":
                ans = input("\n  Apply these changes? [y/N]: ").strip().lower()
                if ans == "y":
                    for key, val in results.items():
                        CFG[key] = val
                    CFG["night_light_shift"] = 0
                    _autosave()
                    print("  ✅ Applied and saved!")
                else:
                    print("  Not applied.")

        elif c == "v":
            _do_visual_dump(bot)

        else:
            print("  Unknown option.")


def menu_adaptive(bot):
    """Adaptive tuner settings and log viewer."""
    while True:
        enabled = bot.tuner.enabled
        _top()
        _line("ADAPTIVE SELF-TUNING")
        _line("Watches the bot's performance and auto-adjusts settings every 60 frames.")
        _sep()
        _line("WHAT IT ADJUSTS:")
        _line("  • Grass deadband  — turns too often/rarely?")
        _line("    Too many phantom turns → raises deadband (less sensitive)")
        _line("    Never turning         → lowers deadband (more sensitive)")
        _line("  • Vote confirm    — zigzagging back and forth?")
        _line("    Raises to 2 if zigzag rate is too high")
        _line("  • Fence threshold — missing or falsely dodging fences?")
        _line("    Deaths + low fence triggers → lowers threshold")
        _line("    Too many fence triggers     → raises threshold")
        _sep()
        _line(f"  1   ► Toggle adaptive tuning   current: {'ENABLED ✓' if enabled else 'DISABLED ✗'}")
        _line(f"  2   ► View tuning log          ({len(bot.tuner.log)} events recorded)")
        _line(f"  3   ► Reset tuner memory       (clears performance history)")
        _sep()
        _line("TUNING AGGRESSIVENESS (how fast it nudges):")
        _line(f"  4   ► Deadband step size       current: {bot.tuner.DEADBAND_STEP*100:.1f}% per nudge")
        _line("        Smaller = slower/gentler   Larger = faster but risky")
        _line(f"  5   ► Max nudges per window     current: {bot.tuner.MAX_NUDGE}")
        _line("        Higher = adapts faster   Lower = more conservative")
        _sep()
        _line("  B   ► Back")
        _bot()

        c = input("  Option: ").strip().lower()
        if c == "b": break

        elif c == "1":
            bot.tuner.enabled = not bot.tuner.enabled
            CFG["adaptive_tuning"] = bot.tuner.enabled
            state = "ENABLED" if bot.tuner.enabled else "DISABLED"
            print(f"  ✓ Adaptive tuning → {state}")
            _autosave()

        elif c == "2":
            bot.tuner.show_log()

        elif c == "3":
            bot.tuner._actions.clear()
            bot.tuner._fence_events.clear()
            bot.tuner._deaths.clear()
            bot.tuner.log.clear()
            bot.tuner._window_count = 0
            print("  ✓ Tuner memory cleared.")

        elif c == "4":
            try:
                v = float(input(f"  Step size % [current {bot.tuner.DEADBAND_STEP*100:.1f}]: "))
                bot.tuner.DEADBAND_STEP = max(0.005, min(0.05, v/100))
                print(f"  ✓ Deadband step → {bot.tuner.DEADBAND_STEP*100:.1f}%")
            except ValueError: print("  Invalid.")

        elif c == "5":
            try:
                v = int(input(f"  Max nudges per window [current {bot.tuner.MAX_NUDGE}]: "))
                bot.tuner.MAX_NUDGE = max(1, min(10, v))
                print(f"  ✓ Max nudges → {bot.tuner.MAX_NUDGE}")
            except ValueError: print("  Invalid.")

        else:
            print("  Unknown option.")


# ─────────────────── HELPERS ───────────────────

def _autosave():
    """Save settings silently after every change."""
    save_settings(CFG)


def _do_visual_dump(bot):
    print("  Capturing frame…")
    if not bot.dm.backend:
        if not bot.dm.setup():
            print("  Fix connection first."); return
    frame = bot.dm.screencap()
    if frame is not None:
        save_visual_dump(frame, "bbot_debug.jpg")
        print("\n  Pull to your PC:  adb pull bbot_debug.jpg .")
    else:
        print("  Screencap failed. Go to Device menu → Full diagnostics.")


def apply_night_light_shift(amount: int):
    for key in ("grass_lo","grass_hi","path_lo","path_hi","fence_lo","fence_hi"):
        lo_or_hi = CFG[key]
        lo_or_hi[0] = min(179, lo_or_hi[0] + amount)
    print(f"  ✓ Night light shift of +{amount} applied to all HSV hue ranges.")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN MENU LOOP
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════════════════╗
║   🐰  BunnyBot v7 — Bunny Runner 3D                                ║
║   Persistent Settings • Guided Tuning • Granular Controls          ║
╚══════════════════════════════════════════════════════════════════════╝"""


def menu():
    print(BANNER)

    if _loaded:
        print(f"  ✅ Settings loaded from {SETTINGS_FILE}\n")
    else:
        print("  ℹ  No saved settings found — using factory defaults.\n")

    bot = BunnyBot()

    while True:
        show_main_menu(bot)
        c = input("  Option: ").strip().lower()

        if c == "a":
            menu_autocal(bot)

        elif c == "k":
            menu_adaptive(bot)

        elif c == "c":
            menu_colours(bot)

        elif c == "t":
            menu_timing(bot)

        elif c == "r":
            menu_reaction(bot)

        elif c == "z":
            menu_zones(bot)

        elif c == "d":
            menu_device(bot)

        elif c == "x":
            menu_reset()

        elif c == "v":
            _do_visual_dump(bot)

        elif c == "0":
            bot.dm.run_diagnostics()

        elif c == "s":
            if not bot.setup():
                print("\n  Fix the connection issues above first.\n")
                continue
            print("[BOT] Taking pre-run visual dump…")
            frame = bot.dm.screencap()
            if frame is not None:
                save_visual_dump(frame, "bbot_prerun.jpg")
                print("  Pull bbot_prerun.jpg to verify colours look correct.")
                print("  If wrong, go back → C → adjust colours → try again.\n")
            try:
                bot.run()
            except KeyboardInterrupt:
                pass
            finally:
                bot.print_stats()
            bot._reset_state()

        elif c == "q":
            save_settings(CFG)
            print("  Settings saved. Bye! 🐰\n")
            sys.exit(0)

        else:
            print("  Unknown option.")


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1 and ":" in sys.argv[1]:
        CFG["device"] = sys.argv[1]
        print(f"[CLI] Device: {CFG['device']}")
    if len(sys.argv) > 2 and sys.argv[2] in ("auto","adbutils","adb"):
        CFG["backend"] = sys.argv[2]
        print(f"[CLI] Backend: {CFG['backend']}")
    menu()
