#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   🐰  BunnyBot v6 — Bunny Runner 3D                                ║
║   Persistent Settings  •  Guided Tuning  •  Granular Controls      ║
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

import os, sys, time, subprocess, traceback, json, tempfile
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
    "night_light_shift",
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
    "path_lo":  [ 8, 110,  80],  # brown dirt  (lower bound)
    "path_hi":  [35, 255, 235],  # brown dirt  (upper bound)
    "fence_lo": [ 0,   0, 175],  # cream white (lower bound)
    "fence_hi": [50, 110, 255],  # cream white (upper bound)

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
    "night_light_shift": 0,      # cumulative H shift applied so far
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
        tmp = os.path.join(tempfile.gettempdir(), "_bbot_l.png")
        rc, _ = self._run(["pull", "/data/local/tmp/_bbot.png", tmp], timeout=10)
        return cv2.imread(tmp) if rc == 0 else None

    def _cap_sdcard(self):
        self._run(["shell", "screencap", "-p", "/sdcard/_bbot.png"], timeout=10)
        tmp = os.path.join(tempfile.gettempdir(), "_bbot_s.png")
        rc, _ = self._run(["pull", "/sdcard/_bbot.png", tmp], timeout=10)
        return cv2.imread(tmp) if rc == 0 else None

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
        self.dm     = DeviceManager()
        self.vision = Vision()
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

    _top()
    _line("🐰  BunnyBot v6 — Bunny Runner 3D")
    _line("Settings auto-save on every change • Delete bunnybot_settings.json to full reset")
    _sep()
    _line(f"Device      : {dev}")
    _line(f"Backend     : {bknd}   │  adbutils: {au}")
    _line(f"Night light : {nl}   │  FPS: {fps}   │  Cooldown: {cool}s   │  Debug: {dbg}")
    _line(f"Settings    : {saved}")
    _divider()


def show_main_menu(bot):
    show_status(bot)
    _line("MAIN MENU — choose a category or action")
    _sep()
    _line("  C   ► Colour Tuning          (grass, path, fence, night light)")
    _line("  T   ► Timing & Speed         (FPS, cooldown, reaction speed)")
    _line("  R   ► Reaction Sensitivity   (turn sharpness, fence strictness)")
    _line("  Z   ► Zone Positions         (lookahead, danger zones, tap spots)")
    _line("  D   ► Device & Connection    (ADB, backend, screencap method)")
    _line("  X   ► Reset Options          (reset specific groups or factory reset)")
    _sep()
    _line("  V   ► Visual Dump            (see what the bot sees — do this first!)")
    _line("  0   ► Full Diagnostics       (test ADB connection + screencap)")
    _line("  S   ► START BOT              (launches the bot)")
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
        _line("  A   ► Auto-calibrate colours from current frame (recommended)")
        _line("        Learns HSV ranges for *your* device + night light automatically")
        _line("  V   ► Visual dump (check current colours)")
        _line("  B   ► Back to main menu")
        _bot()

        c = input("  Option: ").strip().lower()

        if c == "b": break

        elif c == "nl":
            print("\n  Night light H-shift")
            print("  0  = off (normal screen)")
            print("  +8 = typical warm/night light on many phones")
            print("  -8 = if your night light shifts greens toward YELLOW (H decreases)")
            print("  ±15 = maximum shift")
            print("  This RESETS colours to defaults, then applies this shift.")
            old = CFG["night_light_shift"]
            try:
                v = int(input(f"  Amount -15..+15 [currently applied: {old:+d}]: "))
                v = max(-15, min(15, v))
                # Reset all colours to defaults first, then apply fresh shift
                for key in ("grass_lo","grass_hi","path_lo","path_hi","fence_lo","fence_hi"):
                    CFG[key] = list(_DEFAULTS[key])
                CFG["night_light_shift"] = 0
                if v != 0:
                    _apply_nl_shift(v)
                else:
                    print("  ✓ Night light OFF — colours reset to default")
                _autosave()
            except ValueError: print("  Invalid.")

        elif c in ("g1","g2","g3","p1","p2","p3","f1","f2","f3"):
            _edit_colour(c)

        elif c == "a":
            _auto_colour_calibrate(bot)

        elif c == "v":
            _do_visual_dump(bot)

        else:
            print("  Unknown option.")


def _apply_nl_shift(amount):
    for key in ("grass_lo","grass_hi","path_lo","path_hi","fence_lo","fence_hi"):
        CFG[key][0] = max(0, min(179, CFG[key][0] + amount))
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




def auto_calibrate_colours(frame, sample_n=30000, k=5):
    """
    Auto-calibrate HSV ranges for grass/path/fence from ONE screenshot.

    This is a lightweight "learning" step:
      - samples pixels in a central ROI (ignores UI + black bars)
      - clusters colours with k-means in HSV space
      - picks 3 clusters: grass (highest H), fence (highest V), path (lowest V)
      - builds HSV ranges from robust percentiles (+ safety padding)

    Returns a dict with new ranges, or None if it couldn't find stable clusters.
    """
    if frame is None:
        return None

    h, w = frame.shape[:2]

    # Central ROI: avoid top UI + bottom overlays.
    y1 = int(0.18 * h); y2 = int(0.95 * h)
    x1 = int(0.05 * w); x2 = int(0.95 * w)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    px  = hsv.reshape(-1, 3).astype(np.float32)

    # Drop near-black pixels (letterboxing / status bars) — they ruin k-means.
    px = px[px[:, 2] > 40]
    if px.shape[0] < 2000:
        return None

    n = min(sample_n, px.shape[0])
    idx = np.random.choice(px.shape[0], size=n, replace=False)
    sample = px[idx]

    # K-means clustering
    k = int(max(3, min(8, k)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 0.5)
    _ret, labels, centers = cv2.kmeans(
        sample, k, None, criteria, 6, cv2.KMEANS_PP_CENTERS
    )
    labels  = labels.flatten()
    centers = centers.astype(np.float32)

    clusters = []
    for i in range(k):
        pts = sample[labels == i]
        if pts.shape[0] < 200:
            continue
        p5  = np.percentile(pts, 5,  axis=0)
        p95 = np.percentile(pts, 95, axis=0)
        clusters.append({
            "idx": int(i),
            "n": int(pts.shape[0]),
            "center": centers[i],
            "p5": p5,
            "p95": p95
        })

    if len(clusters) < 3:
        return None

    # ── Cluster selection (simple + surprisingly robust for this game) ──
    fence = max(clusters, key=lambda c: float(c["center"][2]))  # brightest = fence
    rem   = [c for c in clusters if c["idx"] != fence["idx"]]
    grass = max(rem, key=lambda c: float(c["center"][0]))       # greenest = grass
    rem2  = [c for c in rem if c["idx"] != grass["idx"]]
    if not rem2:
        return None
    path  = min(rem2, key=lambda c: float(c["center"][2]))      # darkest leftover = path

    def mk_range(c, h_pad, s_pad, v_pad):
        lo = [
            int(max(0,   c["p5"][0]  - h_pad)),
            int(max(0,   c["p5"][1]  - s_pad)),
            int(max(0,   c["p5"][2]  - v_pad)),
        ]
        hi = [
            int(min(179, c["p95"][0] + h_pad)),
            int(min(255, c["p95"][1] + s_pad)),
            int(min(255, c["p95"][2] + v_pad)),
        ]
        # Ensure ordering
        for j in range(3):
            if lo[j] > hi[j]:
                lo[j], hi[j] = hi[j], lo[j]
        return lo, hi

    g_lo, g_hi = mk_range(grass, h_pad=10, s_pad=60, v_pad=60)
    p_lo, p_hi = mk_range(path,  h_pad=10, s_pad=60, v_pad=60)
    f_lo, f_hi = mk_range(fence, h_pad=12, s_pad=50, v_pad=40)

    # Guardrails (prevents silly ranges that make everything match)
    f_lo[2] = max(f_lo[2], 150)     # fence must be bright
    f_hi[1] = min(f_hi[1], 180)     # fence saturation must stay "not too saturated"

    # Force path saturation ABOVE fence saturation to prevent fence bleed.
    p_lo[1] = max(p_lo[1], min(255, f_hi[1] + 10))
    p_hi[1] = 255

    # Grass should not be grey/white
    g_lo[1] = max(g_lo[1], 40)

    return {
        "grass": (g_lo, g_hi),
        "path":  (p_lo, p_hi),
        "fence": (f_lo, f_hi),
        "roi":   (x1, y1, x2, y2),
        "picked": {
            "grass_center": [float(x) for x in grass["center"]],
            "path_center":  [float(x) for x in path["center"]],
            "fence_center": [float(x) for x in fence["center"]],
        }
    }


def _auto_colour_calibrate(bot):
    print("\n  ▶ Auto-calibrating colours from a live screenshot…")
    if not bot.dm.backend:
        if not bot.dm.setup():
            print("  Fix connection first."); return
    frame = bot.dm.screencap()
    if frame is None:
        print("  Screencap failed. Go to Device menu → Full diagnostics."); return

    res = auto_calibrate_colours(frame)
    if not res:
        print("  ✗ Auto-calibration failed (not enough stable colours detected).")
        print("    Try again when you're *in-game* and the camera is stable.")
        return

    (g_lo, g_hi) = res["grass"]
    (p_lo, p_hi) = res["path"]
    (f_lo, f_hi) = res["fence"]

    CFG["grass_lo"], CFG["grass_hi"] = g_lo, g_hi
    CFG["path_lo"],  CFG["path_hi"]  = p_lo, p_hi
    CFG["fence_lo"], CFG["fence_hi"] = f_lo, f_hi

    # This replaces manual night-light shifting.
    CFG["night_light_shift"] = 0

    _autosave()

    print("  ✓ Updated HSV ranges (learned):")
    print(f"    grass_lo={CFG['grass_lo']}  grass_hi={CFG['grass_hi']}")
    print(f"    path_lo ={CFG['path_lo']}   path_hi ={CFG['path_hi']}")
    print(f"    fence_lo={CFG['fence_lo']}  fence_hi={CFG['fence_hi']}")
    print(f"    picked centres (H,S,V): {res['picked']}")

    # Save a visual dump so you can SEE what it learned.
    save_visual_dump(frame, "bbot_autocal.jpg")
    print("  ✓ Saved bbot_autocal.jpg (pull it and confirm colours look right)\n")
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
║   🐰  BunnyBot v6 — Bunny Runner 3D                                ║
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

        if c == "c":
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
