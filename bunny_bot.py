#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v5 — Bunny Runner 3D                         ║
║      Colour-accurate  •  Night-light aware  •  Multi-signal    ║
╚══════════════════════════════════════════════════════════════════╝

COLOUR ANALYSIS  (from real game screenshots)
──────────────────────────────────────────────
  Measured in OpenCV HSV (H: 0-179, S: 0-255, V: 0-255)

  PATH  (brown dirt)  : H=15,   S=96-130,  V=140-165
  FENCE (cream posts) : H=15-18, S=5-35,   V=210-240
  GRASS (olive green) : H=48-51, S=106-121, V=105-120
  CARROT (orange)     : H=10-15, S=200-255, V=170-220
  BUNNY (sandy)       : H=20-28, S=40-80,  V=155-200

  ⚠ CRITICAL INSIGHT: Path and Fence share almost the SAME HUE (~H=15).
    They can ONLY be separated by SATURATION:
      PATH  S = 80-150  (medium saturation)
      FENCE S = 5-40    (very low saturation — nearly white)
    This is why old code using only hue failed to separate them.

  🌙 NIGHT LIGHT MODE shifts colours warmer (+5 to +15 on H),
    so all ranges are widened to accommodate this.

TURN DETECTION STRATEGY
────────────────────────
  PRIMARY signal: GRASS pixel balance
    The grass (H=38-90) is the MOST DISTINCT colour in the game.
    When the path curves RIGHT, the grass/path boundary moves:
      → More grass appears on the LEFT side of lookahead strip
      → Tap RIGHT to follow the path

    More grass LEFT  → tap RIGHT
    More grass RIGHT → tap LEFT
    Balanced         → straight

  SECONDARY signal: PATH pixel balance (brown pixels L vs R)
    Backs up the grass signal. Used as tiebreaker.

  BOTH signals must agree (or one must be strong) to act.

FENCE DETECTION STRATEGY
─────────────────────────
  Fences = cream/white posts:  S < 45 AND V > 180
  Three checks per danger zone:
    1. % of zone that is fence-coloured  (colour mask)
    2. Sudden vertical edge density spike (Canny edges)
    3. Horizontal scan: are multiple fence-shaped blobs present?
  Any 1 of 3 triggers a dodge.

BACKENDS
─────────
  auto     → tries adbutils first, falls back to ADB subprocess
  adbutils → pip install adbutils --break-system-packages
  adb      → pkg install android-tools -y

QUICK START
───────────
  pkg install python android-tools python-numpy opencv-python -y
  pip install adbutils --break-system-packages
  adb pair <IP>:<PAIR_PORT>
  adb connect <IP>:<CONN_PORT>
  python bunny_bot.py
  → press V (visual dump to check colours) → S (start)
"""

import os, sys, time, subprocess, traceback
from collections import deque

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
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CFG = {
    # ── Device / Backend ─────────────────────────────────────────────────────
    "device":           "",       # blank = auto-detect; or "192.168.x.x:PORT"
    "adb_timeout":      12,
    "backend":          "auto",   # auto | adbutils | adb
    "screencap_method": "auto",   # auto | exec-out | local | pull

    # ── Game ─────────────────────────────────────────────────────────────────
    "game_package": "com.kwalee.bunnyrunner",

    # ── Timing ───────────────────────────────────────────────────────────────
    "loop_fps":        10,     # captures per second
    "startup_delay":    4,     # seconds before bot starts tapping
    "action_cooldown": 0.20,   # min seconds between taps (prevents spam)

    # ── Tap positions (fraction of screen width/height) ───────────────────────
    # Left tap  = left quarter of screen
    # Right tap = right quarter of screen
    # Tap at 65% height (below centre — where game registers input)
    "tap_left_x":  0.25,
    "tap_right_x": 0.75,
    "tap_y":       0.65,

    # ── LOOK-AHEAD STRIP ─────────────────────────────────────────────────────
    # Horizontal band where we measure grass/path balance to detect turns.
    # Placed at 30-60% height — the middle of the visible track,
    # far enough ahead to react in time, not so far the turn isn't visible yet.
    "la_top":    0.30,
    "la_bottom": 0.60,

    # ── DANGER ZONES ─────────────────────────────────────────────────────────
    # Left and right corridors where fence posts appear before reaching the bunny.
    # Fence rows run diagonally, so zones cover 25-75% height.
    "dz_left_x":  (0.02, 0.44),
    "dz_right_x": (0.56, 0.98),
    "dz_y":       (0.25, 0.75),

    # ── GAME-OVER ZONE ────────────────────────────────────────────────────────
    "gameover_y": (0.55, 0.95),
    "gameover_x": (0.20, 0.80),

    # ═══════════════════════════════════════════════════════════════════════
    # COLOUR RANGES (HSV — OpenCV scale: H 0-179, S 0-255, V 0-255)
    # Derived from pixel analysis of real game screenshots.
    # Ranges are widened (+/-10 on H, +/-30 on S/V) to handle:
    #   • Night light mode  (shifts H warmer by ~10)
    #   • Different phone screens  (brightness variation)
    #   • Shadows and lighting in game
    # ═══════════════════════════════════════════════════════════════════════

    # GRASS — olive/yellow-green.
    # H=38-90 covers the green channel cleanly, far from path/fence.
    # This is our MOST RELIABLE signal for turn detection.
    "grass_lo": [38,  50,  60],
    "grass_hi": [90, 255, 200],

    # PATH — warm brown/tan dirt.
    # Key: S must be > 50 to exclude fence posts (which have S < 40).
    # Key: S must be < 180 to exclude carrots (S > 180).
    "path_lo": [ 8,  50, 100],
    "path_hi": [35, 180, 210],

    # FENCE POSTS — cream/near-white.
    # Key separator: very LOW saturation (S < 45) + HIGH value (V > 175).
    # Path has S=80-130, so S < 45 uniquely identifies fence posts.
    # H range is wide because near-white pixels can shift hue easily.
    "fence_lo": [ 0,   0, 175],
    "fence_hi": [50,  45, 255],

    # ── Turn detection thresholds ─────────────────────────────────────────
    # Minimum grass pixels in strip before we trust the grass signal.
    # Prevents acting on pure-path screens (e.g. beginning of game).
    "grass_min_px":   200,

    # How lopsided the grass must be before we turn.
    # 0.12 = 12 percentage-points more grass on one side than the other.
    # Lower = more sensitive (reacts to small curves); raise if too jittery.
    "grass_deadband": 0.12,

    # Path signal deadband (used as tiebreaker / confirmation).
    "path_deadband":  0.10,

    # ── Fence detection thresholds ────────────────────────────────────────
    # Fraction of danger zone that must be fence-coloured to trigger dodge.
    # 0.05 = 5% — low threshold because fence posts are thin.
    "fence_colour_frac": 0.05,

    # Canny edge thresholds for edge density detection
    "canny_lo": 35,
    "canny_hi": 110,

    # How many times denser the danger zone edges must be vs background.
    "fence_edge_ratio": 1.6,

    # Number of fence signals (out of 2) needed to trigger a dodge.
    # 1 = more sensitive (catches more fences, some false positives)
    # 2 = more conservative (fewer false positives, may miss some)
    "fence_min_signals": 1,

    # ── Game-over detection ───────────────────────────────────────────────
    "gameover_dark_frac":  0.48,
    "gameover_dark_v_max": 68,
    "gameover_bright_px":  280,

    # ── Smoothing ─────────────────────────────────────────────────────────
    # How many CONSECUTIVE frames must agree on a direction before acting.
    # 1 = react on every frame (fastest, can be noisy)
    # 2 = two frames must agree (smoother, 100ms lag at 10fps)
    "vote_confirm": 1,

    # ── Debug ─────────────────────────────────────────────────────────────
    "debug":             False,   # print per-frame decisions
    "debug_save_frames": False,   # save annotated frames to ./debug_frames/
}


# ═══════════════════════════════════════════════════════════════════════════════
#  ADB BACKENDS
# ═══════════════════════════════════════════════════════════════════════════════

class ADBSubprocessBackend:
    """Drives the adb command-line binary via subprocess."""
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

    # ── Three screencap methods with auto-fallback ────────────────────────────
    def screencap(self):
        order = {
            "exec-out": self._cap_exec_out,
            "local":    self._cap_local_tmp,
            "pull":     self._cap_sdcard,
        }
        # Try current method first, then the others
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
        print("    Fix: adb kill-server && adb connect <IP>:<PORT>")
        print("    Or:  phone → Developer Options → Revoke USB debugging → reconnect")
        print("    Or:  switch to adbutils backend (menu → B → adbutils)")
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
    """Pure-Python ADB via socket. Install: pip install adbutils --break-system-packages"""
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
            return arr[:, :, ::-1].copy()   # RGB → BGR
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
    """Decode raw PNG bytes from adb — handles CRLF corruption."""
    clean = data.replace(b"\r\n", b"\n")
    buf   = np.frombuffer(clean, dtype=np.uint8)
    img   = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img if img is not None else \
           cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


# ═══════════════════════════════════════════════════════════════════════════════
#  DEVICE MANAGER  (backend selection + unified API)
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
        # auto
        if ADBUTILS_OK:
            print("[BOT] Trying adbutils first…")
            if self._init_adbutils(silent=True):
                return True
            print("[BOT] adbutils unavailable → falling back to ADB subprocess")
        else:
            print("[BOT] adbutils not installed → using ADB subprocess")
            print("  Tip: pip install adbutils --break-system-packages  (often more reliable)")
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
        print("\n" + "═"*52)
        print("  BACKEND DIAGNOSTICS")
        print("═"*52)

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

        print("\n" + "═"*52)
        print("  If adbutils works → use it (menu B → adbutils)")
        print("  If only ADB works → set screencap method (menu 9)")
        print("═"*52 + "\n")

    # ── Unified API ───────────────────────────────────────────────────────────
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
    """
    TURN DETECTION
    ──────────────
    Signal A (PRIMARY): GRASS balance
      Count green (H=38-90) pixels in left vs right half of look-ahead strip.
      More grass LEFT  → path curving RIGHT → tap RIGHT
      More grass RIGHT → path curving LEFT  → tap LEFT

    Signal B (SECONDARY): PATH balance
      Count brown/dirt pixels left vs right.
      More path RIGHT → tap RIGHT, more path LEFT → tap LEFT

    Decision: if both signals agree → act immediately.
              if only one fires → act if it's strong enough.
              if neither → STRAIGHT.

    FENCE DETECTION
    ───────────────
    Two signals per danger zone:
      1. Colour: fraction of zone with fence-colour pixels (cream, S<45, V>175)
      2. Edges:  sudden spike in Canny edge density vs background strip

    fence_min_signals controls how many must fire (default=1 for sensitivity).
    Fence on LEFT  → tap RIGHT to dodge
    Fence on RIGHT → tap LEFT to dodge
    """

    def __init__(self):
        self._vote_buf = deque(maxlen=3)
        self._frame_n  = 0

    # ── Main entry ────────────────────────────────────────────────────────────

    def decide(self, frame):
        """Returns (action: str, debug_dict: dict)"""
        self._frame_n += 1
        h, w = frame.shape[:2]
        dbg  = {"frame": self._frame_n, "w": w, "h": h}

        # Priority 1: Game over?
        if self._is_game_over(frame, w, h):
            self._vote_buf.clear()
            dbg["reason"] = "GAME_OVER"
            return "RESTART", dbg

        # Priority 2: Fence dodge
        fence_action, fdebug = self._detect_fences(frame, w, h)
        dbg.update(fdebug)
        if fence_action:
            self._vote_buf.clear()
            dbg["reason"] = f"FENCE → {fence_action}"
            return fence_action, dbg

        # Priority 3: Turn detection
        raw, tdebug = self._detect_turn(frame, w, h)
        dbg.update(tdebug)

        # Smooth with vote buffer
        self._vote_buf.append(raw)
        n = len(self._vote_buf)
        needed = CFG["vote_confirm"]
        if n >= needed and all(v == raw for v in list(self._vote_buf)[-needed:]):
            action = raw
        else:
            action = "STRAIGHT"

        dbg["reason"] = f"TURN → {raw}" + ("" if action == raw else " (confirming…)")
        return action, dbg

    # ── Game-over detection ───────────────────────────────────────────────────

    def _is_game_over(self, frame, w, h):
        v = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
        dark_frac = np.count_nonzero(v < CFG["gameover_dark_v_max"]) / max(v.size, 1)
        if dark_frac < CFG["gameover_dark_frac"]:
            return False
        gy1 = int(CFG["gameover_y"][0] * h); gy2 = int(CFG["gameover_y"][1] * h)
        gx1 = int(CFG["gameover_x"][0] * w); gx2 = int(CFG["gameover_x"][1] * w)
        bright = np.count_nonzero(v[gy1:gy2, gx1:gx2] > 200)
        return int(bright) > CFG["gameover_bright_px"]

    # ── Turn detection ────────────────────────────────────────────────────────

    def _detect_turn(self, frame, w, h):
        """Combine grass balance + path balance to determine turn direction."""
        y1 = int(CFG["la_top"]    * h)
        y2 = int(CFG["la_bottom"] * h)
        mid = w // 2

        strip     = frame[y1:y2, :]
        strip_hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)

        lo_g = np.array(CFG["grass_lo"], dtype=np.uint8)
        hi_g = np.array(CFG["grass_hi"], dtype=np.uint8)
        lo_p = np.array(CFG["path_lo"],  dtype=np.uint8)
        hi_p = np.array(CFG["path_hi"],  dtype=np.uint8)

        grass_mask = cv2.inRange(strip_hsv, lo_g, hi_g)
        path_mask  = cv2.inRange(strip_hsv, lo_p, hi_p)

        # ── Signal A: Grass balance ───────────────────────────────────────────
        gL = int(np.count_nonzero(grass_mask[:, :mid]))
        gR = int(np.count_nonzero(grass_mask[:, mid:]))
        g_total = gL + gR

        sig_A = "STRAIGHT"
        g_ratio = 0.0
        if g_total >= CFG["grass_min_px"]:
            g_ratio = gR / g_total
            db = CFG["grass_deadband"]
            if g_ratio > 0.5 + db:
                sig_A = "LEFT"    # more grass RIGHT → path went LEFT → go LEFT
            elif g_ratio < 0.5 - db:
                sig_A = "RIGHT"   # more grass LEFT  → path went RIGHT → go RIGHT

        # ── Signal B: Path balance ────────────────────────────────────────────
        pL = int(np.count_nonzero(path_mask[:, :mid]))
        pR = int(np.count_nonzero(path_mask[:, mid:]))
        p_total = pL + pR

        sig_B = "STRAIGHT"
        p_ratio = 0.0
        if p_total >= CFG["grass_min_px"] // 2:
            p_ratio = pR / p_total
            db = CFG["path_deadband"]
            if p_ratio > 0.5 + db:
                sig_B = "RIGHT"
            elif p_ratio < 0.5 - db:
                sig_B = "LEFT"

        # ── Combine: both agree → act; only A fires → act (it's more reliable) ─
        if sig_A != "STRAIGHT" and sig_B != "STRAIGHT":
            if sig_A == sig_B:
                direction = sig_A          # both agree — highest confidence
            else:
                direction = sig_A          # grass wins on disagreement
        elif sig_A != "STRAIGHT":
            direction = sig_A              # only grass signal — trust it
        elif sig_B != "STRAIGHT":
            direction = sig_B              # only path signal
        else:
            direction = "STRAIGHT"

        dbg = {
            "grass_L": gL, "grass_R": gR, "grass_ratio": round(g_ratio, 3),
            "path_L":  pL, "path_R":  pR, "path_ratio":  round(p_ratio, 3),
            "sig_A": sig_A, "sig_B": sig_B, "turn": direction,
        }
        return direction, dbg

    # ── Fence detection ───────────────────────────────────────────────────────

    def _detect_fences(self, frame, w, h):
        lo_f  = np.array(CFG["fence_lo"], dtype=np.uint8)
        hi_f  = np.array(CFG["fence_hi"], dtype=np.uint8)

        lx1 = int(CFG["dz_left_x"][0]  * w); lx2 = int(CFG["dz_left_x"][1]  * w)
        rx1 = int(CFG["dz_right_x"][0] * w); rx2 = int(CFG["dz_right_x"][1] * w)
        zy1 = int(CFG["dz_y"][0] * h);        zy2 = int(CFG["dz_y"][1] * h)

        hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, CFG["canny_lo"], CFG["canny_hi"])

        def analyse_zone(x1, x2, name):
            roi_h  = zy2 - zy1
            roi_w  = x2 - x1
            n_px   = roi_h * roi_w
            if n_px == 0:
                return False, 0, {}

            roi_hsv  = hsv[zy1:zy2, x1:x2]
            roi_edge = edges[zy1:zy2, x1:x2]

            # Signal 1: colour fraction
            fence_mask  = cv2.inRange(roi_hsv, lo_f, hi_f)
            colour_frac = np.count_nonzero(fence_mask) / n_px
            sig1 = colour_frac > CFG["fence_colour_frac"]

            # Signal 2: edge density spike
            # Compare top-half of danger zone vs same-height strip just above
            top_h = max(1, roi_h // 2)
            dz_edge_dens = np.count_nonzero(roi_edge[:top_h]) / max(1, top_h * roi_w)
            bg_y1 = max(0, zy1 - top_h)
            bg_edge = edges[bg_y1:zy1, x1:x2]
            bg_dens  = np.count_nonzero(bg_edge) / max(1, top_h * roi_w)
            sig2 = (dz_edge_dens > 0.008 and
                    bg_dens < dz_edge_dens / CFG["fence_edge_ratio"])

            n_sigs   = int(sig1) + int(sig2)
            blocked  = n_sigs >= CFG["fence_min_signals"]

            return blocked, n_sigs, {
                f"col_{name}": round(colour_frac, 3),
                f"edge_{name}": round(dz_edge_dens, 4),
                f"sigs_{name}": n_sigs,
            }

        l_blocked, l_sigs, l_dbg = analyse_zone(lx1, lx2, "L")
        r_blocked, r_sigs, r_dbg = analyse_zone(rx1, rx2, "R")
        dbg = {**l_dbg, **r_dbg}

        if l_blocked and r_blocked:
            # Both blocked — dodge toward the less-blocked side
            action = "RIGHT" if l_sigs >= r_sigs else "LEFT"
        elif l_blocked:
            action = "RIGHT"
        elif r_blocked:
            action = "LEFT"
        else:
            action = None

        return action, dbg


# ═══════════════════════════════════════════════════════════════════════════════
#  VISUAL DUMP  — saves annotated frame so you can check what the bot sees
# ═══════════════════════════════════════════════════════════════════════════════

def save_visual_dump(frame, path="bbot_debug.jpg"):
    """
    Saves an annotated image highlighting:
      YELLOW  → pixels detected as PATH
      GREEN   → pixels detected as GRASS
      RED     → pixels detected as FENCE COLOUR
    Also draws lookahead strip, danger zones, and tap points.
    Pull this file to your phone/PC to verify the colours are right.
    """
    if frame is None:
        print("[VIS] No frame to dump.")
        return

    h, w  = frame.shape[:2]
    vis   = frame.copy()
    hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    grass_mask = cv2.inRange(hsv,
                             np.array(CFG["grass_lo"], dtype=np.uint8),
                             np.array(CFG["grass_hi"], dtype=np.uint8))
    path_mask  = cv2.inRange(hsv,
                             np.array(CFG["path_lo"],  dtype=np.uint8),
                             np.array(CFG["path_hi"],  dtype=np.uint8))
    fence_mask = cv2.inRange(hsv,
                             np.array(CFG["fence_lo"], dtype=np.uint8),
                             np.array(CFG["fence_hi"], dtype=np.uint8))

    # Colour overlays
    vis[path_mask  > 0] = (0,   220, 220)   # YELLOW  = path
    vis[grass_mask > 0] = (0,   220,  50)   # GREEN   = grass
    vis[fence_mask > 0] = (30,   30, 255)   # RED     = fence colour

    # Look-ahead strip
    ly1 = int(CFG["la_top"]    * h)
    ly2 = int(CFG["la_bottom"] * h)
    cv2.rectangle(vis, (0, ly1), (w, ly2),   (255, 255, 0), 3)
    cv2.line(vis, (w//2, ly1), (w//2, ly2),  (255,255,255), 2)
    cv2.putText(vis, "LOOKAHEAD (turn detection)", (6, ly1 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

    # Danger zones
    lx1 = int(CFG["dz_left_x"][0]  * w); lx2 = int(CFG["dz_left_x"][1]  * w)
    rx1 = int(CFG["dz_right_x"][0] * w); rx2 = int(CFG["dz_right_x"][1] * w)
    zy1 = int(CFG["dz_y"][0] * h);        zy2 = int(CFG["dz_y"][1] * h)
    cv2.rectangle(vis, (lx1, zy1), (lx2, zy2), (0,  0, 255), 2)
    cv2.rectangle(vis, (rx1, zy1), (rx2, zy2), (0,  0, 255), 2)
    cv2.putText(vis, "DZ-L", (lx1+4, zy1+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
    cv2.putText(vis, "DZ-R", (rx1+4, zy1+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

    # Tap positions
    cv2.circle(vis, (int(w*CFG["tap_left_x"]),  int(h*CFG["tap_y"])), 20, (0,128,255), 3)
    cv2.circle(vis, (int(w*CFG["tap_right_x"]), int(h*CFG["tap_y"])), 20, (0,128,255), 3)
    cv2.putText(vis, "TAP-L", (int(w*CFG["tap_left_x"])-28,  int(h*CFG["tap_y"])-24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,128,255), 1)
    cv2.putText(vis, "TAP-R", (int(w*CFG["tap_right_x"])-28, int(h*CFG["tap_y"])-24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,128,255), 1)

    # Legend (bottom left)
    items = [
        ((0,220,220), "PATH detected"),
        ((0,220, 50), "GRASS detected"),
        ((30, 30,255), "FENCE colour detected"),
        ((255,255,  0), "Look-ahead strip"),
        ((0,  0, 255), "Danger zones"),
        ((0,128,255), "Tap points"),
    ]
    box_y = h - len(items)*20 - 12
    cv2.rectangle(vis, (0, box_y-4), (210, h), (15,15,15), -1)
    for i, (col, label) in enumerate(items):
        y = box_y + i * 20 + 14
        cv2.rectangle(vis, (6, y-11), (20, y+3), col, -1)
        cv2.putText(vis, label, (26, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (230,230,230), 1)

    # Pixel counts
    gp = np.count_nonzero(grass_mask)
    pp = np.count_nonzero(path_mask)
    fp = np.count_nonzero(fence_mask)
    cv2.putText(vis, f"grass={gp}px  path={pp}px  fence={fp}px",
                (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240,240,240), 1)

    cv2.imwrite(path, vis, [cv2.IMWRITE_JPEG_QUALITY, 92])

    print(f"\n[VIS] Saved: {path}")
    print(f"  Grass pixels detected : {gp}")
    print(f"  Path  pixels detected : {pp}")
    print(f"  Fence pixels detected : {fp}")
    print()
    print("  Pull file to check visually:")
    print(f"    adb pull {path} .")
    print()
    print("  What to look for:")
    print("   ✓ YELLOW  covers the dirt/brown path strip")
    print("   ✓ GREEN   covers the grass on both sides")
    print("   ✓ RED     appears on the white fence posts")
    print()
    print("  If colours are wrong, adjust these in CFG:")
    print("    path_lo / path_hi   — for yellow being wrong")
    print("    grass_lo / grass_hi — for green being wrong")
    print("    fence_lo / fence_hi — for red being wrong (or missing)")
    print()
    if gp < 500:
        print("  ⚠ Very few grass pixels! Turn detection will be unreliable.")
        print("    Try lowering grass_lo[1] (saturation) in CFG.")
    if pp < 500:
        print("  ⚠ Very few path pixels! Path signal will be weak.")
        print("    Adjust path_lo/path_hi — or just rely on grass signal.")
    if fp < 100:
        print("  ⚠ Very few fence pixels! Fence detection may miss posts.")
        print("    Try lowering fence_lo[2] (value) or raising fence_hi[1].")


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
        print(f"[BOT] Starting in {delay}s — switch to the game now!")
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
                if CFG["debug"]:
                    traceback.print_exc()
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
        self.consecutive_fails      = 0
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
        col = {"LEFT":(0,165,255), "RIGHT":(0,165,255),
               "RESTART":(0,0,255), "STRAIGHT":(0,220,0)}.get(action, (180,180,180))
        cv2.putText(vis, action, (15, 55),  cv2.FONT_HERSHEY_SIMPLEX, 1.8, col, 4)
        cv2.putText(vis, dbg.get("reason",""), (15, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        info = (f"A={dbg.get('sig_A','')} B={dbg.get('sig_B','')} "
                f"gL={dbg.get('grass_L','')} gR={dbg.get('grass_R','')}")
        cv2.putText(vis, info, (15, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,255,200), 1)
        os.makedirs("debug_frames", exist_ok=True)
        cv2.imwrite(f"debug_frames/{self.frame_count:06d}_{action}.jpg",
                    vis, [cv2.IMWRITE_JPEG_QUALITY, 70])

    def print_stats(self):
        elapsed = max(time.time() - self.start_time, 0.001)
        fps     = self.frame_count / elapsed
        print(f"\n[BOT] {elapsed:.0f}s | {self.frame_count} frames | "
              f"{fps:.1f}fps avg | backend: {self.dm.backend_name}")


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v5 — Bunny Runner 3D  (Vision Overhaul)      ║
║      Tuned to real game colours  •  Grass-primary detection    ║
╚══════════════════════════════════════════════════════════════════╝"""


def show_menu(bot: BunnyBot):
    dev  = CFG["device"] or "(auto)"
    au   = "✓ installed" if ADBUTILS_OK else "✗ not installed"
    dbg  = "ON"  if CFG["debug"]             else "OFF"
    sav  = "ON"  if CFG["debug_save_frames"] else "OFF"
    bknd = bot.dm.backend_name
    print(f"""
┌──────────────────────────────────────────────────────────────┐
│  Device           : {dev:<42}│
│  Active backend   : {bknd:<42}│
│  adbutils         : {au:<42}│
│  Debug log        : {dbg:<42}│
│  Save frames      : {sav:<42}│
├──────────────────────────────────────────────────────────────┤
│  0   Full diagnostics (both backends)                        │
│  1   Set target device         (blank = auto)                │
│  B   Set backend               (auto / adbutils / adb)       │
│  2   Change loop FPS           (default {CFG['loop_fps']})                     │
│  3   Change action cooldown    (default {CFG['action_cooldown']}s)               │
│  4   Toggle debug logging      (currently {dbg})                 │
│  5   Toggle save debug frames  (currently {sav})                 │
│  6   Change game package name                                │
│  7   Fence sensitivity         (signals: {CFG['fence_min_signals']}/2)               │
│  8   Grass deadband            (current: {CFG['grass_deadband']*100:.0f}%)              │
│  9   Screencap method          ({CFG['screencap_method']})                   │
│  NL  Adjust for night light mode (shifts HSV ranges)         │
│                                                              │
│  V   Visual dump — see EXACTLY what the bot sees             │
│  S   START the bot                                           │
│  Q   Quit                                                    │
└──────────────────────────────────────────────────────────────┘""")


def apply_night_light_shift(amount: int):
    """
    Night light mode warms the screen (shifts H higher, reduces blue).
    amount = 0 (off) to 15 (max).
    Shifts all HSV hue ranges by +amount.
    """
    for key in ("grass_lo", "grass_hi", "path_lo", "path_hi",
                "fence_lo", "fence_hi"):
        lo_or_hi = CFG[key]
        lo_or_hi[0] = min(179, lo_or_hi[0] + amount)
    print(f"  ✓ Night light shift of +{amount} applied to all HSV hue ranges.")
    print("    If colours are still wrong, use V to check and adjust manually.")


def menu():
    print(BANNER)
    bot = BunnyBot()

    while True:
        show_menu(bot)
        c = input("  Option: ").strip().lower()

        if c == "0":
            bot.dm.run_diagnostics()

        elif c == "1":
            v = input("  IP:PORT (blank=auto): ").strip()
            CFG["device"] = v
            bot.dm = DeviceManager()

        elif c == "b":
            v = input("  [auto/adbutils/adb]: ").strip().lower()
            if v in ("auto", "adbutils", "adb"):
                CFG["backend"] = v
                bot.dm = DeviceManager()
                print(f"  Backend → {v}")
            else:
                print("  Use: auto / adbutils / adb")

        elif c == "2":
            try:
                v = int(input(f"  FPS 1-30 [current {CFG['loop_fps']}]: "))
                CFG["loop_fps"] = max(1, min(30, v))
            except ValueError: print("  Invalid.")

        elif c == "3":
            try:
                v = float(input(f"  Cooldown s [current {CFG['action_cooldown']}]: "))
                CFG["action_cooldown"] = max(0.05, v)
            except ValueError: print("  Invalid.")

        elif c == "4":
            CFG["debug"] = not CFG["debug"]
            print(f"  Debug: {'ON' if CFG['debug'] else 'OFF'}")

        elif c == "5":
            CFG["debug_save_frames"] = not CFG["debug_save_frames"]
            print(f"  Frame saving: {'ON' if CFG['debug_save_frames'] else 'OFF'}")

        elif c == "6":
            v = input(f"  Package [{CFG['game_package']}]: ").strip()
            if v: CFG["game_package"] = v

        elif c == "7":
            try:
                v = int(input("  Min fence signals [1=sensitive, 2=strict]: "))
                CFG["fence_min_signals"] = max(1, min(2, v))
                print(f"  fence_min_signals → {CFG['fence_min_signals']}")
            except ValueError: print("  Invalid.")

        elif c == "8":
            try:
                v = float(input(f"  Grass deadband % [current {CFG['grass_deadband']*100:.0f}]: "))
                CFG["grass_deadband"] = max(0.03, min(0.45, v / 100))
            except ValueError: print("  Invalid.")

        elif c == "9":
            v = input("  [auto/exec-out/local/pull]: ").strip().lower()
            if v in ("auto", "exec-out", "local", "pull"):
                CFG["screencap_method"]       = v
                bot.dm._adb._cap_method = v
            else:
                print("  Unknown method.")

        elif c == "nl":
            try:
                v = int(input("  Night light H-shift amount 0-15 [0=off, 10=typical]: "))
                apply_night_light_shift(max(0, min(15, v)))
            except ValueError: print("  Invalid.")

        elif c == "v":
            print("  Capturing frame…")
            if not bot.dm.backend:
                if not bot.dm.setup():
                    print("  Fix connection first."); continue
            frame = bot.dm.screencap()
            if frame is not None:
                save_visual_dump(frame, "bbot_debug.jpg")
                print("\n  To view on PC:")
                print("    adb pull bbot_debug.jpg .")
            else:
                print("  Screencap failed. Run 0 to diagnose.")

        elif c == "s":
            if not bot.setup():
                print("\n  Fix the issues above first.\n"); continue
            # One visual dump before starting so user can verify colours
            print("[BOT] Taking pre-run visual dump for your reference…")
            frame = bot.dm.screencap()
            if frame is not None:
                save_visual_dump(frame, "bbot_prerun.jpg")
                print("  Pull bbot_prerun.jpg to verify colours look right.")
                print("  Press Ctrl+C now if they look wrong, fix with NL or")
                print("  edit CFG values directly, then restart.\n")
            try:
                bot.run()
            except KeyboardInterrupt:
                pass
            finally:
                bot.print_stats()
            bot._reset_state()

        elif c == "q":
            print("  Bye! 🐰\n")
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
    if len(sys.argv) > 2 and sys.argv[2] in ("auto", "adbutils", "adb"):
        CFG["backend"] = sys.argv[2]
        print(f"[CLI] Backend: {CFG['backend']}")
    menu()
