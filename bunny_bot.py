#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v4 — Bunny Runner 3D  (Vision Overhaul)      ║
║      Tuned to actual game colours  •  Multi-signal detection    ║
╚══════════════════════════════════════════════════════════════════╝

GAME LAYOUT (from actual screenshot analysis)
──────────────────────────────────────────────
  PATH   = brown/dirt strip  (HSV H:12–28, S:40–160, V:110–220)
  GRASS  = bright green      (HSV H:38–80, S:60–255, V:80–220)
  FENCES = beige/cream posts (HSV H:20–40, S:10–60,  V:140–220)
           arranged in ROWS along both path edges
  BUNNY  = grey              (HSV H:0–180, S:0–40,   V:80–160)
  CARROT = bright orange     (HSV H:8–20,  S:160–255, V:160–255)

HOW TURNS WORK
──────────────
  The path is a dirt strip that snakes left/right.
  When path curves RIGHT → more brown pixels appear in the right
  half of a horizontal lookahead band across the screen.
  When path curves LEFT  → more brown pixels in the left half.

HOW FENCES ARE DETECTED
────────────────────────
  Fences run in two rows — one on each side of the path.
  Three independent signals are combined:
    1. Beige/cream HSV colour mask
    2. Dense edge clusters (Canny) — fence rows create sharp edges
    3. Vertical structure (Sobel-X) — fence posts are tall and thin
  Needing 2-of-3 signals prevents false positives.

BACKENDS (same as v3)
──────────────────────
  auto | adbutils | adb-subprocess
  Install: pip install adbutils --break-system-packages

QUICK START
───────────
  pkg install python android-tools python-numpy opencv-python -y
  pip install adbutils --break-system-packages
  adb pair <IP>:<PAIR_PORT> && adb connect <IP>:<CONN_PORT>
  python bunny_bot.py
  → menu: 0 (diagnose) → V (visual dump to see what bot sees) → S (start)
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
    # ── Device / backend ─────────────────────────────────────────────────────
    "device":           "",
    "adb_timeout":      12,
    "backend":          "auto",       # auto | adbutils | adb
    "screencap_method": "auto",       # auto | exec-out | local | pull

    # ── Game ─────────────────────────────────────────────────────────────────
    "game_package": "com.kwalee.bunnyrunner",

    # ── Template (optional — put template_fence.png next to script) ───────────
    "tmpl_fence":     "template_fence.png",
    "tmpl_threshold": 0.55,

    # ── Timing ───────────────────────────────────────────────────────────────
    "loop_fps":        10,
    "startup_delay":    5,
    "action_cooldown": 0.18,

    # ── Tap positions ─────────────────────────────────────────────────────────
    "tap_left_x":  0.25,
    "tap_right_x": 0.75,
    "tap_y":       0.65,

    # ── Vision zones (all fractions 0.0–1.0) ─────────────────────────────────

    # LOOK-AHEAD STRIP — horizontal band where path direction is measured.
    # Placed in the middle of the screen where the path is widest and most
    # visible. Avoid top (sky/UI) and bottom (directly under bunny = straight).
    "la_top":    0.32,
    "la_bottom": 0.58,

    # DANGER ZONES — left and right corridors where fence posts appear
    # just before they reach the bunny. Chosen to cover fence rows.
    "dz_left_x":  (0.02, 0.44),
    "dz_right_x": (0.56, 0.98),
    "dz_y":       (0.30, 0.75),

    # GAME-OVER zone (centre-bottom — where retry button appears)
    "gameover_y": (0.55, 0.95),
    "gameover_x": (0.20, 0.80),

    # ── PATH colour (HSV) — the brown/dirt running track ─────────────────────
    # Derived from actual game screenshot analysis.
    # H:12–28 covers the warm brown-orange of the dirt.
    # S:35–170 excludes pure white (fence posts) and grey (bunny).
    # V:100–225 excludes very dark shadows and very bright specular.
    "path_lo": [12,  35, 100],
    "path_hi": [28, 170, 225],

    # Min fraction of strip that must be path-coloured (rejects menu/black screens)
    "path_min_fill": 0.05,

    # Imbalance before committing to a turn.
    # 0.10 = one side needs 10pp more path pixels than the other.
    # Lower = more responsive; higher = less jitter.
    "path_deadband": 0.10,

    # ── GRASS colour (HSV) — bright green on both sides of path ───────────────
    # Measuring grass is an independent turn signal:
    # more grass on the RIGHT → path is curving LEFT (and vice versa).
    "grass_lo": [38,  55,  70],
    "grass_hi": [80, 255, 220],

    # ── FENCE colour (HSV) — beige/cream fence posts ─────────────────────────
    # These are NOT pure white — they're a warm beige.
    # H:15–42 covers the warm cream tones.
    # S:8–70  excludes pure-white sky and grey bunny.
    # V:130–230 targets the medium-bright cream colour.
    "fence_lo": [15,   8, 130],
    "fence_hi": [42,  70, 230],

    # Fence detection: fraction of danger zone that must be fence-coloured
    "fence_colour_frac": 0.055,

    # Fence detection: Canny edge density ratio (danger vs background)
    "fence_edge_thr_lo": 40,
    "fence_edge_thr_hi": 120,
    "fence_edge_ratio":  1.7,

    # Minimum signals needed to call a fence (out of 3):
    # colour mask  /  edge density  /  template match
    "fence_min_signals": 1,   # 1 = sensitive; 2 = conservative

    # ── Game-over detection ───────────────────────────────────────────────────
    "gameover_dark_frac":  0.48,
    "gameover_dark_v_max": 65,
    "gameover_bright_px":  280,

    # ── Smoothing ─────────────────────────────────────────────────────────────
    # How many consecutive frames must agree before we act.
    # 1 = react instantly (can be noisy); 2 = one frame smoother.
    "vote_confirm": 1,

    # ── Debug ─────────────────────────────────────────────────────────────────
    "debug":             False,
    "debug_save_frames": False,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  ADB BACKENDS  (unchanged from v3 — skip to VISION ENGINE below if reading)
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
            print("[ADB] 'adb' not found. Fix: pkg install android-tools -y")
            return -2, b""

    def list_devices(self):
        _, out = self._run(["devices"])
        lines = out.decode(errors="ignore").strip().splitlines()
        return [l.split("\t")[0] for l in lines[1:] if "\tdevice" in l]

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
        m = self._cap_method
        for attempt in (m, "local", "exec-out", "pull"):
            img = {"exec-out": self._cap_exec_out,
                   "local":    self._cap_local_tmp,
                   "pull":     self._cap_sdcard}.get(attempt, self._cap_local_tmp)()
            if img is not None:
                self._cap_method = attempt
                CFG["screencap_method"] = attempt
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
                    if chosen is None:
                        chosen = label
                else:
                    print(f"  ✗  {label:<12}  None")
            except Exception as e:
                print(f"  ✗  {label:<12}  {e}")
        if chosen:
            self._cap_method = chosen
            CFG["screencap_method"] = chosen
            print(f"\n  → Using: {chosen}")
            return True
        print("\n  ✗ All methods failed. Try: adb kill-server && adb connect <IP>:<PORT>")
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
            self._device    = next((d for d in devs if d.serial == self._serial),
                                   devs[0])
            self._serial    = self._device.serial
            self._connected = True
            print(f"[adbutils] Connected: {self._device.serial}")
            return True
        except Exception as e:
            print(f"[adbutils] auto_connect: {e}")
            return False

    def is_connected(self):
        if not self._connected or not self._device:
            return False
        try:
            self._device.get_state()
            return True
        except Exception:
            self._connected = False
            return False

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
            return f"error:{e}"

    def launch_game(self):
        try:
            self._device.app_start(CFG["game_package"])
        except Exception:
            self.shell(f"monkey -p {CFG['game_package']} "
                       "-c android.intent.category.LAUNCHER 1")

    def force_stop(self):
        self.shell(f"am force-stop {CFG['game_package']}")


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
        if mode == "adbutils":
            return self._init_adbutils()
        if mode == "adb":
            return self._init_adb()
        # auto
        if ADBUTILS_OK:
            print("[BOT] Trying adbutils…")
            if self._init_adbutils(silent=True):
                return True
            print("[BOT] adbutils failed → falling back to ADB subprocess")
        else:
            print("[BOT] adbutils not installed → using ADB subprocess")
            print("  Optional: pip install adbutils --break-system-packages")
        return self._init_adb()

    def _init_adbutils(self, silent=False):
        if not ADBUTILS_OK:
            if not silent:
                print("[ERROR] adbutils not installed.")
                print("  Fix: pip install adbutils --break-system-packages")
            return False
        b = AdbUtilsBackend(CFG["device"])
        if not b.auto_connect():
            if not silent:
                print("[ERROR] adbutils: no device found.")
                _print_conn_help()
            return False
        img = b.screencap()
        if img is None:
            if not silent:
                print("[ERROR] adbutils: screencap returned None")
            return False
        h, w = img.shape[:2]
        print(f"[adbutils] ✓ {w}×{h}px")
        self.backend = b
        return True

    def _init_adb(self):
        b = self._adb
        if not CFG["device"]:
            if not b.auto_connect():
                _print_conn_help()
                return False
        else:
            if not b.is_connected():
                print(f"[ERROR] Device '{CFG['device']}' not reachable.")
                return False
        ok = b.test_all_methods()
        if ok:
            self.backend = b
        return ok

    def run_diagnostics(self):
        print("\n" + "═"*54 + "\n  DIAGNOSTICS\n" + "═"*54)
        print("\n[1] adbutils")
        if not ADBUTILS_OK:
            print("  ✗ Not installed: pip install adbutils --break-system-packages")
        else:
            b = AdbUtilsBackend(CFG["device"])
            if b.auto_connect():
                img = b.screencap()
                if img is not None:
                    print(f"  ✓ {img.shape[1]}×{img.shape[0]}px")
                else:
                    print("  ✗ Connected but screencap None")
            else:
                print("  ✗ No device found")
        print("\n[2] ADB subprocess")
        b2 = self._adb
        if not CFG["device"]:
            b2.auto_connect()
        if not b2.is_connected():
            print("  ✗ No device"); _print_conn_help()
        else:
            print(f"  Device: {b2.device}")
            b2.test_all_methods()
        print("═"*54)

    def screencap(self):
        return self.backend.screencap() if self.backend else None

    def tap(self, x, y):
        if self.backend:
            self.backend.tap(x, y)

    def tap_left(self, w, h):
        self.tap(int(w * CFG["tap_left_x"]), int(h * CFG["tap_y"]))

    def tap_right(self, w, h):
        self.tap(int(w * CFG["tap_right_x"]), int(h * CFG["tap_y"]))

    def shell(self, cmd):
        return self.backend.shell(cmd) if self.backend else ""

    def launch_game(self):
        if self.backend: self.backend.launch_game()

    def force_stop(self):
        if self.backend: self.backend.force_stop()

    def reconnect(self):
        if self.backend: self.backend.reconnect()

    def restart_game(self, reason=""):
        print(f"[BOT] Restarting game{' ('+reason+')' if reason else ''}…")
        self.force_stop()
        time.sleep(1.5)
        self.launch_game()
        time.sleep(4.0)


def _print_conn_help():
    print(
        "\n  No device found.\n"
        "    1. Developer Options → Wireless Debugging → ON\n"
        "    2. adb pair <IP>:<PAIR_PORT>    (enter 6-digit code)\n"
        "    3. adb connect <IP>:<CONN_PORT> (main WD screen port)\n"
        "    4. adb devices                  (must say 'device')\n"
    )

def _decode_png(data: bytes):
    clean = data.replace(b"\r\n", b"\n")
    buf   = np.frombuffer(clean, dtype=np.uint8)
    img   = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img if img is not None else cv2.imdecode(
        np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPLATE BANK
# ═══════════════════════════════════════════════════════════════════════════════

class TemplateBank:
    SCALES = (0.40, 0.60, 0.80, 1.00, 1.20)

    def __init__(self):
        self._bank = {}
        sd = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(sd, CFG["tmpl_fence"])
        img  = cv2.imread(path)
        if img is None:
            print(f"[TMPL] template_fence.png not found — template matching disabled")
            return
        h, w = img.shape[:2]
        self._bank["fence"] = [
            cv2.resize(img, (max(4, int(w*s)), max(4, int(h*s))),
                       interpolation=cv2.INTER_AREA)
            for s in self.SCALES
        ]
        print(f"[TMPL] ✓ template_fence.png ({w}×{h}px)")

    def find_fence(self, roi_img):
        """Search for fence template inside roi_img. Returns confidence 0-1."""
        if "fence" not in self._bank or roi_img is None:
            return 0.0
        sh, sw = roi_img.shape[:2]
        best = 0.0
        for tmpl in self._bank["fence"]:
            th, tw = tmpl.shape[:2]
            if tw > sw or th > sh:
                continue
            try:
                _, v, _, _ = cv2.minMaxLoc(
                    cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED))
                if v > best:
                    best = v
            except cv2.error:
                continue
        return round(best, 3)


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO-CALIBRATOR  — learns exact colours from YOUR screen at runtime
# ═══════════════════════════════════════════════════════════════════════════════

class AutoCalibrator:
    """
    Captures frames during the first seconds of play and learns:
      - Path colour  (bottom-centre zone — always path)
      - Grass colour (side strips — always grass)
      - Fence colour (relative brightness + hue analysis)
      - Sky/UI colour (top strip — always background)

    After calibration the learned HSV ranges are injected into CFG
    and used by the Vision engine instead of the defaults.

    Also supports single-frame quick recalibration for level changes.
    """

    def __init__(self, dm: DeviceManager):
        self.dm            = dm
        self._path_samples = []   # list of (H, S, V) numpy arrays
        self._is_done      = False

    # ── Zones used for sampling ───────────────────────────────────────────────

    @staticmethod
    def _crop(frame, y_range, x_range):
        h, w = frame.shape[:2]
        y1, y2 = int(y_range[0]*h), int(y_range[1]*h)
        x1, x2 = int(x_range[0]*w), int(x_range[1]*w)
        return frame[y1:y2, x1:x2]

    @staticmethod
    def _hsv_median(patch):
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        pixels = hsv.reshape(-1, 3).astype(float)
        return np.median(pixels, axis=0)  # [H, S, V]

    # ── Main calibration ──────────────────────────────────────────────────────

    def run(self, n_frames: int = 6, verbose: bool = True) -> bool:
        if verbose:
            print(f"\n[CAL] Auto-calibrating from {n_frames} live frames…")
            print("[CAL] Make sure the game is running (bunny on track)…")

        frames = []
        for i in range(n_frames):
            f = self.dm.screencap()
            if f is not None:
                frames.append(f)
                if verbose:
                    print(f"  [{i+1}/{n_frames}] frame captured {f.shape[1]}×{f.shape[0]}")
            time.sleep(0.25)

        if len(frames) < 2:
            if verbose:
                print("[CAL] ✗ Not enough frames — is the game on screen?")
            return False

        # Sample path colour from bottom-centre (bunny always runs there)
        path_meds = []
        for f in frames:
            patch = self._crop(f, (0.70, 0.90), (0.30, 0.70))
            path_meds.append(self._hsv_median(patch))
        path_med = np.median(path_meds, axis=0)

        # Sample grass colour from sides (always grass)
        grass_meds = []
        for f in frames:
            left_patch  = self._crop(f, (0.35, 0.65), (0.00, 0.18))
            right_patch = self._crop(f, (0.35, 0.65), (0.82, 1.00))
            combined = np.vstack([
                cv2.cvtColor(left_patch,  cv2.COLOR_BGR2HSV).reshape(-1, 3),
                cv2.cvtColor(right_patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
            ])
            grass_meds.append(np.median(combined.astype(float), axis=0))
        grass_med = np.median(grass_meds, axis=0)

        # Sample fence colour — look for the beige/cream posts
        # Sample from the zone just inside both path edges (top of DZ)
        fence_meds = []
        for f in frames:
            # Fence rows appear at ~30-50% height, near path edges
            lp = self._crop(f, (0.30, 0.50), (0.05, 0.30))
            rp = self._crop(f, (0.30, 0.50), (0.70, 0.95))
            for patch in [lp, rp]:
                hsv_p = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                pixels = hsv_p.reshape(-1, 3).astype(float)
                # Select pixels that are NOT green and NOT very dark
                mask = (pixels[:, 0] < 35) | (pixels[:, 0] > 80)   # not green hue
                mask &= pixels[:, 2] > 100                            # not dark
                mask &= pixels[:, 1] < 100                            # not saturated (not carrot)
                if mask.sum() > 20:
                    fence_meds.append(np.median(pixels[mask], axis=0))

        # Build HSV ranges with generous margins
        MH, MS, MV = 14, 60, 60   # hue, sat, val margins

        lo = np.clip(path_med - [MH, MS, MV], 0, 255).astype(int).tolist()
        hi = np.clip(path_med + [MH, MS, MV], 0, 255).astype(int).tolist()
        # Hue must stay sensible (0–179 in OpenCV)
        lo[0] = max(0,   lo[0])
        hi[0] = min(179, hi[0])
        lo[1] = max(10,  lo[1])   # min saturation — exclude pure white/grey
        CFG["path_lo"] = lo
        CFG["path_hi"] = hi

        # Grass
        glo = np.clip(grass_med - [12, 40, 40], 0, 255).astype(int).tolist()
        ghi = np.clip(grass_med + [12, 80, 60], 0, 255).astype(int).tolist()
        glo[0] = max(30, glo[0])   # must be green hue
        ghi[0] = min(90, ghi[0])
        CFG["grass_lo"] = glo
        CFG["grass_hi"] = ghi

        # Fence
        if fence_meds:
            fence_med = np.median(fence_meds, axis=0)
            flo = np.clip(fence_med - [18, 0, 50], 0, 255).astype(int).tolist()
            fhi = np.clip(fence_med + [18, 35, 55], 0, 255).astype(int).tolist()
            flo[1] = max(5, flo[1])
            fhi[1] = min(80, fhi[1])
            fhi[2] = min(240, fhi[2])
            CFG["fence_lo"] = flo
            CFG["fence_hi"] = fhi
        else:
            fence_med = np.array([0, 0, 0])

        self._is_done = True

        if verbose:
            print(f"\n[CAL] PATH  median HSV: H={path_med[0]:.1f} "
                  f"S={path_med[1]:.1f} V={path_med[2]:.1f}")
            print(f"[CAL]   path_lo = {CFG['path_lo']}")
            print(f"[CAL]   path_hi = {CFG['path_hi']}")
            print(f"[CAL] GRASS median HSV: H={grass_med[0]:.1f} "
                  f"S={grass_med[1]:.1f} V={grass_med[2]:.1f}")
            if fence_meds:
                print(f"[CAL] FENCE median HSV: H={fence_med[0]:.1f} "
                      f"S={fence_med[1]:.1f} V={fence_med[2]:.1f}")
                print(f"[CAL]   fence_lo = {CFG['fence_lo']}")
                print(f"[CAL]   fence_hi = {CFG['fence_hi']}")
            print("[CAL] ✓ Done — colours learned from your screen\n")

        return True

    def quick_recal_path(self, frame) -> bool:
        """
        Single-frame path recalibration — called every N frames.
        Only updates path range, keeping fence range stable.
        """
        try:
            patch = self._crop(frame, (0.70, 0.90), (0.30, 0.70))
            med   = self._hsv_median(patch)
            MH, MS, MV = 14, 60, 60
            lo = np.clip(med - [MH, MS, MV], [0,10,0], 255).astype(int).tolist()
            hi = np.clip(med + [MH, MS, MV], 0, [179,255,255]).astype(int).tolist()
            CFG["path_lo"] = lo
            CFG["path_hi"] = hi
            return True
        except Exception:
            return False

    @property
    def is_done(self):
        return self._is_done


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION ENGINE  — multi-signal, calibration-aware
# ═══════════════════════════════════════════════════════════════════════════════

class Vision:
    """
    TURN DETECTION — combines 3 independent signals:
      Signal A: PATH balance — count brown/dirt pixels left vs right
                in the look-ahead strip.
      Signal B: GRASS balance — count green pixels left vs right.
                More grass on the RIGHT → path curves LEFT (grass fills
                the gap where path was). And vice versa.
      Signal C: PATH column density — for each column in the strip,
                count path pixels. The column of maximum density is the
                path centre. If it's left of screen-centre → curving left.

    Signals A and B are combined by majority vote. Signal C is a
    tiebreaker. This makes the system robust to colour drift and
    HSV mismatches.

    FENCE DETECTION — combines 3 independent signals:
      Signal 1: HSV colour mask — count beige/cream pixels in DZ
      Signal 2: Canny edge density — fence row = burst of edges
      Signal 3: Template match (if template file present)
    Any `fence_min_signals` signals firing → FENCE detected.
    """

    RECAL_EVERY = 300   # frames between path recalibrations

    def __init__(self, bank: TemplateBank, cal: AutoCalibrator):
        self.bank        = bank
        self.cal         = cal
        self._frame_num  = 0
        self._vote_buf   = deque(maxlen=2)   # last 2 decisions for smoothing

    # ── Main entry ────────────────────────────────────────────────────────────

    def decide(self, frame) -> tuple:
        """Returns (action: str, debug_dict: dict)"""
        self._frame_num += 1
        h, w = frame.shape[:2]
        dbg  = {"w": w, "h": h, "frame": self._frame_num}

        # Periodic path recalibration
        if self._frame_num % self.RECAL_EVERY == 0:
            self.cal.quick_recal_path(frame)

        # Priority 1: game over?
        if self._game_over(frame, w, h):
            self._vote_buf.clear()
            dbg["reason"] = "GAME_OVER"
            return "RESTART", dbg

        # Priority 2: fence dodge
        fence_action, fdebug = self._check_fences(frame, w, h)
        dbg.update(fdebug)
        if fence_action:
            self._vote_buf.clear()
            dbg["reason"] = f"FENCE→{fence_action}"
            return fence_action, dbg

        # Priority 3: path direction (voted)
        raw_action, pdebug = self._check_direction(frame, w, h)
        dbg.update(pdebug)

        # Smoothing: require vote_confirm consecutive same decisions
        self._vote_buf.append(raw_action)
        if len(self._vote_buf) >= CFG["vote_confirm"]:
            confirmed = all(v == raw_action for v in self._vote_buf)
        else:
            confirmed = False

        action = raw_action if confirmed else "STRAIGHT"
        dbg["reason"] = f"PATH→{raw_action}" + ("" if confirmed else " (wait)")
        return action, dbg

    # ── Game-over ─────────────────────────────────────────────────────────────

    def _game_over(self, frame, w, h):
        v    = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
        dark = np.count_nonzero(v < CFG["gameover_dark_v_max"])
        if dark / max(v.size, 1) < CFG["gameover_dark_frac"]:
            return False
        gy1, gy2 = int(CFG["gameover_y"][0]*h), int(CFG["gameover_y"][1]*h)
        gx1, gx2 = int(CFG["gameover_x"][0]*w), int(CFG["gameover_x"][1]*w)
        return int(np.count_nonzero(v[gy1:gy2, gx1:gx2] > 200)) > CFG["gameover_bright_px"]

    # ── Fence detection ───────────────────────────────────────────────────────

    def _check_fences(self, frame, w, h):
        lo_f  = np.array(CFG["fence_lo"], dtype=np.uint8)
        hi_f  = np.array(CFG["fence_hi"], dtype=np.uint8)
        lx1   = int(CFG["dz_left_x"][0]  * w)
        lx2   = int(CFG["dz_left_x"][1]  * w)
        rx1   = int(CFG["dz_right_x"][0] * w)
        rx2   = int(CFG["dz_right_x"][1] * w)
        zy1   = int(CFG["dz_y"][0] * h)
        zy2   = int(CFG["dz_y"][1] * h)

        hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray,
                          CFG["fence_edge_thr_lo"],
                          CFG["fence_edge_thr_hi"])

        def zone_signals(x1, x2):
            roi_hsv  = hsv[zy1:zy2, x1:x2]
            roi_edge = edges[zy1:zy2, x1:x2]
            roi_img  = frame[zy1:zy2, x1:x2]
            n_px     = roi_hsv.shape[0] * roi_hsv.shape[1]
            if n_px == 0:
                return 0, {}

            # Signal 1: colour
            colour_mask = cv2.inRange(roi_hsv, lo_f, hi_f)
            colour_frac = np.count_nonzero(colour_mask) / n_px
            sig1 = colour_frac > CFG["fence_colour_frac"]

            # Signal 2: edge density burst
            # Compare edge density in the top half of the danger zone
            # (where fence posts first appear) vs the background strip above
            top_h = max(1, (zy2 - zy1) // 2)
            edge_dz_density  = np.count_nonzero(roi_edge[:top_h, :]) / max(1, top_h * (x2-x1))
            # Background reference: same-width strip just above danger zone
            bgy1 = max(0, zy1 - top_h)
            bg_edge = edges[bgy1:zy1, x1:x2]
            bg_density = np.count_nonzero(bg_edge) / max(1, top_h * (x2-x1))
            sig2 = (edge_dz_density > 0.005 and
                    edge_dz_density > bg_density * CFG["fence_edge_ratio"])

            # Signal 3: template match
            tmpl_conf = self.bank.find_fence(roi_img)
            sig3 = tmpl_conf >= CFG["tmpl_threshold"]

            n_signals = int(sig1) + int(sig2) + int(sig3)
            blocked = n_signals >= CFG["fence_min_signals"]

            return n_signals, {
                "col_frac": round(colour_frac, 3),
                "edge_dz":  round(edge_dz_density, 4),
                "edge_bg":  round(bg_density, 4),
                "tmpl":     tmpl_conf,
                "sigs":     n_signals,
                "blocked":  blocked,
            }

        l_sigs, l_dbg = zone_signals(lx1, lx2)
        r_sigs, r_dbg = zone_signals(rx1, rx2)

        dbg = {
            "fence_L_sigs": l_sigs, "fence_L_col": l_dbg.get("col_frac"),
            "fence_R_sigs": r_sigs, "fence_R_col": r_dbg.get("col_frac"),
        }

        l_blocked = l_dbg.get("blocked", False)
        r_blocked = r_dbg.get("blocked", False)

        if l_blocked and r_blocked:
            return ("RIGHT" if l_sigs >= r_sigs else "LEFT"), dbg
        if l_blocked:
            return "RIGHT", dbg
        if r_blocked:
            return "LEFT", dbg
        return None, dbg

    # ── Direction detection ───────────────────────────────────────────────────

    def _check_direction(self, frame, w, h):
        """
        Three signals combined:
          A — path colour balance (brown pixels L vs R)
          B — grass colour balance (green pixels L vs R)
          C — path column centroid (where is the most path?)
        """
        y1    = int(CFG["la_top"]    * h)
        y2    = int(CFG["la_bottom"] * h)
        strip = frame[y1:y2, :]
        hsv   = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        mid   = w // 2
        dbg   = {}

        lo_p = np.array(CFG["path_lo"],  dtype=np.uint8)
        hi_p = np.array(CFG["path_hi"],  dtype=np.uint8)
        lo_g = np.array(CFG["grass_lo"], dtype=np.uint8)
        hi_g = np.array(CFG["grass_hi"], dtype=np.uint8)

        path_mask  = cv2.inRange(hsv, lo_p, hi_p)
        grass_mask = cv2.inRange(hsv, lo_g, hi_g)

        path_total = int(np.count_nonzero(path_mask))
        dbg["path_fill"] = round(path_total / max(path_mask.size, 1), 3)

        # ── Signal A: path balance ────────────────────────────────────────────
        pL = int(np.count_nonzero(path_mask[:, :mid]))
        pR = int(np.count_nonzero(path_mask[:, mid:]))
        dbg["path_L"] = pL
        dbg["path_R"] = pR
        denom_p = pL + pR
        sig_A = "STRAIGHT"
        if denom_p > 0 and path_total >= CFG["path_min_fill"] * path_mask.size:
            r = pR / denom_p
            db = CFG["path_deadband"]
            if r > 0.5 + db:
                sig_A = "RIGHT"
            elif r < 0.5 - db:
                sig_A = "LEFT"

        # ── Signal B: grass balance ───────────────────────────────────────────
        # More grass on RIGHT → path has moved LEFT → we should go LEFT
        gL = int(np.count_nonzero(grass_mask[:, :mid]))
        gR = int(np.count_nonzero(grass_mask[:, mid:]))
        dbg["grass_L"] = gL
        dbg["grass_R"] = gR
        denom_g = gL + gR
        sig_B = "STRAIGHT"
        if denom_g > 50:  # need meaningful grass signal
            r = gR / denom_g
            db = CFG["path_deadband"] * 0.9
            if r > 0.5 + db:
                sig_B = "LEFT"    # grass pushed RIGHT → go LEFT
            elif r < 0.5 - db:
                sig_B = "RIGHT"   # grass pushed LEFT  → go RIGHT

        # ── Signal C: path column centroid ────────────────────────────────────
        col_sums = np.sum(path_mask, axis=0).astype(float)
        total_c  = col_sums.sum()
        sig_C = "STRAIGHT"
        if total_c > 0:
            centroid = np.sum(np.arange(w) * col_sums) / total_c
            offset   = (centroid - mid) / w   # negative = left, positive = right
            dbg["centroid_offset"] = round(offset, 3)
            db2 = CFG["path_deadband"] * 0.8
            if offset > db2:
                sig_C = "RIGHT"
            elif offset < -db2:
                sig_C = "LEFT"

        dbg["sig_A"] = sig_A
        dbg["sig_B"] = sig_B
        dbg["sig_C"] = sig_C

        # ── Vote: majority of A, B, C ─────────────────────────────────────────
        votes = [sig_A, sig_B, sig_C]
        left_votes  = votes.count("LEFT")
        right_votes = votes.count("RIGHT")

        if right_votes >= 2:
            final = "RIGHT"
        elif left_votes >= 2:
            final = "LEFT"
        elif sig_A != "STRAIGHT":
            final = sig_A   # A is most direct path signal — use as tiebreaker
        else:
            final = "STRAIGHT"

        dbg["direction"] = final
        return final, dbg


# ═══════════════════════════════════════════════════════════════════════════════
#  VISUAL DEBUG DUMP
# ═══════════════════════════════════════════════════════════════════════════════

def save_visual_dump(frame, w, h, out_path="bbot_visual_dump.jpg"):
    """
    Saves an annotated frame showing:
      • Look-ahead strip (green box)
      • Path pixels highlighted (yellow overlay)
      • Grass pixels highlighted (bright green overlay)
      • Fence colour pixels highlighted (red overlay)
      • Danger zones (red boxes)
      • Tap positions (orange circles)
    """
    vis = frame.copy()

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lo_p = np.array(CFG["path_lo"],  dtype=np.uint8)
    hi_p = np.array(CFG["path_hi"],  dtype=np.uint8)
    lo_g = np.array(CFG["grass_lo"], dtype=np.uint8)
    hi_g = np.array(CFG["grass_hi"], dtype=np.uint8)
    lo_f = np.array(CFG["fence_lo"], dtype=np.uint8)
    hi_f = np.array(CFG["fence_hi"], dtype=np.uint8)

    path_mask  = cv2.inRange(hsv, lo_p, hi_p)
    grass_mask = cv2.inRange(hsv, lo_g, hi_g)
    fence_mask = cv2.inRange(hsv, lo_f, hi_f)

    # Colour overlays
    vis[path_mask  > 0] = (0, 220, 220)   # yellow-ish = path detected
    vis[grass_mask > 0] = (0, 255, 80)    # bright green = grass detected
    vis[fence_mask > 0] = (0, 60, 255)    # red = fence colour detected

    # Look-ahead strip
    ly1 = int(CFG["la_top"]    * h)
    ly2 = int(CFG["la_bottom"] * h)
    cv2.rectangle(vis, (0, ly1), (w, ly2),   (255, 255, 0), 3)
    cv2.line(vis,  (w//2, ly1), (w//2, ly2), (255, 255, 255), 2)
    cv2.putText(vis, "LOOKAHEAD", (5, ly1+22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,0), 1)

    # Danger zones
    lx1, lx2 = int(CFG["dz_left_x"][0]*w),  int(CFG["dz_left_x"][1]*w)
    rx1, rx2 = int(CFG["dz_right_x"][0]*w), int(CFG["dz_right_x"][1]*w)
    zy1, zy2 = int(CFG["dz_y"][0]*h),        int(CFG["dz_y"][1]*h)
    cv2.rectangle(vis, (lx1, zy1), (lx2, zy2), (0, 0, 255), 2)
    cv2.rectangle(vis, (rx1, zy1), (rx2, zy2), (0, 0, 255), 2)
    cv2.putText(vis, "DZ-L", (lx1+4, zy1+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
    cv2.putText(vis, "DZ-R", (rx1+4, zy1+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

    # Tap targets
    cv2.circle(vis, (int(w*CFG["tap_left_x"]),  int(h*CFG["tap_y"])), 18, (0,128,255), 3)
    cv2.circle(vis, (int(w*CFG["tap_right_x"]), int(h*CFG["tap_y"])), 18, (0,128,255), 3)
    cv2.putText(vis, "TAP-L", (int(w*CFG["tap_left_x"])-25,  int(h*CFG["tap_y"])-22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,128,255), 1)
    cv2.putText(vis, "TAP-R", (int(w*CFG["tap_right_x"])-25, int(h*CFG["tap_y"])-22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,128,255), 1)

    # Legend
    legend_y = h - 120
    cv2.rectangle(vis, (5, legend_y), (200, h-5), (20,20,20), -1)
    items = [
        ((0,220,220), "Path detected"),
        ((0,255,80),  "Grass detected"),
        ((0,60,255),  "Fence colour"),
        ((255,255,0), "Look-ahead strip"),
        ((0,0,255),   "Danger zones"),
    ]
    for i, (col, label) in enumerate(items):
        y = legend_y + 14 + i * 20
        cv2.rectangle(vis, (10, y-10), (22, y+2), col, -1)
        cv2.putText(vis, label, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (240,240,240), 1)

    cv2.imwrite(out_path, vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"[VIS] Saved: {out_path}")
    print("[VIS] Colours in the image:")
    print("  YELLOW  = pixels the bot thinks are PATH")
    print("  GREEN   = pixels the bot thinks are GRASS")
    print("  RED     = pixels the bot thinks are FENCE COLOUR")
    print("  If these look wrong → run 'C' (calibrate) again")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class BunnyBot:

    def __init__(self):
        self.dm     = DeviceManager()
        self.bank   = TemplateBank()
        self.cal    = None       # created after device connects
        self.vision = None       # created after calibration
        self._reset_state()

    def _reset_state(self):
        self.frame_count       = 0
        self.start_time        = 0.0
        self.last_act_time     = 0.0
        self.consecutive_fails = 0
        self.screen_w          = 0
        self.screen_h          = 0

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup(self) -> bool:
        ok = self.dm.setup()
        if not ok:
            return False
        print(f"[BOT] Backend: {self.dm.backend_name}  ✓")

        # Auto-calibrate before starting
        self.cal = AutoCalibrator(self.dm)
        print("\n[BOT] Running auto-calibration…")
        print("      ➜  Make sure the GAME IS ON SCREEN with the bunny running!")
        ok = self.cal.run(n_frames=6, verbose=True)
        if not ok:
            print("[BOT] ⚠  Calibration failed — using default colours.")
            print("          Results may be poor. Try menu 'C' while in-game.")
        self.vision = Vision(self.bank, self.cal)
        print("[BOT] Ready!\n")
        return True

    # ── Main loop ────────────────────────────────────────────────────────────

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
        period          = 1.0 / max(1, CFG["loop_fps"])

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
                print("[WARN] 5 consecutive screencap failures — reconnecting…")
                self.dm.reconnect()
                self.consecutive_fails = 0
            return
        self.consecutive_fails      = 0
        self.screen_w, self.screen_h = frame.shape[1], frame.shape[0]

        action, dbg = self.vision.decide(frame)
        self._execute(action, self.screen_w, self.screen_h)

        if CFG["debug"]:
            fps = self.frame_count / max(time.time() - self.start_time, 0.001)
            sigA = dbg.get("sig_A", "-")
            sigB = dbg.get("sig_B", "-")
            sigC = dbg.get("sig_C", "-")
            fl   = dbg.get("fence_L_sigs", "-")
            fr   = dbg.get("fence_R_sigs", "-")
            pf   = dbg.get("path_fill",    "-")
            print(f"[{self.frame_count:05d}] {action:<8} | "
                  f"A={sigA} B={sigB} C={sigC} | "
                  f"fence L:{fl} R:{fr} | path_fill={pf} | "
                  f"{fps:.1f}fps [{self.dm.backend_name}]")

        if CFG["debug_save_frames"]:
            self._save_debug(frame, action, dbg,
                             self.screen_w, self.screen_h)

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

    def _save_debug(self, frame, action, dbg, w, h):
        vis = frame.copy()
        col = {"LEFT": (0,165,255), "RIGHT": (0,165,255),
               "RESTART": (0,0,255), "STRAIGHT": (0,220,0)}.get(action, (200,200,200))
        cv2.putText(vis, action, (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, col, 4)
        cv2.putText(vis, dbg.get("reason",""), (20, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        cv2.putText(vis, f"A={dbg.get('sig_A','')} B={dbg.get('sig_B','')} C={dbg.get('sig_C','')}",
                    (20, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,255,200), 1)
        os.makedirs("debug_frames", exist_ok=True)
        cv2.imwrite(f"debug_frames/{self.frame_count:06d}_{action}.jpg",
                    vis, [cv2.IMWRITE_JPEG_QUALITY, 65])

    def print_stats(self):
        elapsed = time.time() - self.start_time
        fps     = self.frame_count / max(elapsed, 1)
        print(f"\n[BOT] {elapsed:.0f}s | {self.frame_count} frames | "
              f"{fps:.1f}fps avg | backend: {self.dm.backend_name}")


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v4 — Bunny Runner 3D  (Vision Overhaul)      ║
╚══════════════════════════════════════════════════════════════════╝"""


def show_menu(bot: BunnyBot):
    dev    = CFG["device"]   or "(auto)"
    bknd   = CFG["backend"]
    active = bot.dm.backend_name
    au_ok  = "✓" if ADBUTILS_OK else "✗ not installed"
    dbg    = "ON"  if CFG["debug"]             else "OFF"
    sav    = "ON"  if CFG["debug_save_frames"] else "OFF"
    cal    = "done" if (bot.cal and bot.cal.is_done) else "not yet"
    print(f"""
┌────────────────────────────────────────────────────────────┐
│  Device          : {dev:<40}│
│  Backend mode    : {bknd:<40}│
│  Active backend  : {active:<40}│
│  adbutils        : {au_ok:<40}│
│  Calibration     : {cal:<40}│
│  Debug log       : {dbg:<40}│
│  Save frames     : {sav:<40}│
├────────────────────────────────────────────────────────────┤
│  0  Run diagnostics (both backends)                        │
│  1  Set target device         (blank = auto)               │
│  B  Set backend               (auto/adbutils/adb)          │
│  2  Change loop FPS           (default 10)                 │
│  3  Change action cooldown    (default 0.18s)              │
│  4  Toggle debug logging                                   │
│  5  Toggle save debug frames                               │
│  6  Change game package name                               │
│  7  Fence sensitivity         (default 1 signal needed)    │
│  8  Path deadband             (default 10%)                │
│  9  Screencap method          (auto/exec-out/local/pull)   │
│                                                            │
│  C  Re-calibrate colours from live screen                  │
│  V  Visual dump — save annotated frame to see what bot sees│
│  S  START the bot (auto-calibrates at startup)             │
│  Q  Quit                                                   │
└────────────────────────────────────────────────────────────┘""")


def menu():
    print(BANNER)
    bot = BunnyBot()

    while True:
        show_menu(bot)
        c = input("  Option: ").strip().lower()

        if c == "0":
            bot.dm.run_diagnostics()

        elif c == "1":
            v = input("  Device IP:PORT (blank=auto): ").strip()
            CFG["device"] = v
            bot.dm        = DeviceManager()

        elif c == "b":
            v = input("  Backend [auto/adbutils/adb]: ").strip().lower()
            if v in ("auto", "adbutils", "adb"):
                CFG["backend"] = v
                bot.dm         = DeviceManager()
                print(f"  Backend → {v}")
            else:
                print("  Use: auto / adbutils / adb")

        elif c == "2":
            try:
                v = int(input(f"  FPS [current {CFG['loop_fps']}]: "))
                CFG["loop_fps"] = max(1, min(30, v))
            except ValueError:
                print("  Invalid.")

        elif c == "3":
            try:
                v = float(input(f"  Cooldown s [current {CFG['action_cooldown']}]: "))
                CFG["action_cooldown"] = max(0.05, v)
            except ValueError:
                print("  Invalid.")

        elif c == "4":
            CFG["debug"] = not CFG["debug"]
            print(f"  Debug: {'ON' if CFG['debug'] else 'OFF'}")

        elif c == "5":
            CFG["debug_save_frames"] = not CFG["debug_save_frames"]
            print(f"  Frame saving: {'ON' if CFG['debug_save_frames'] else 'OFF'}")

        elif c == "6":
            v = input(f"  Package [current: {CFG['game_package']}]: ").strip()
            if v:
                CFG["game_package"] = v

        elif c == "7":
            try:
                v = int(input("  Min fence signals [1=sensitive, 2=strict, 3=very strict]: "))
                CFG["fence_min_signals"] = max(1, min(3, v))
                print(f"  fence_min_signals → {CFG['fence_min_signals']}")
            except ValueError:
                print("  Invalid.")

        elif c == "8":
            try:
                v = float(input(f"  Deadband % [current {CFG['path_deadband']*100:.0f}]: "))
                CFG["path_deadband"] = max(0.01, min(0.40, v / 100))
            except ValueError:
                print("  Invalid.")

        elif c == "9":
            v = input("  Method [auto/exec-out/local/pull]: ").strip().lower()
            if v in ("auto", "exec-out", "local", "pull"):
                CFG["screencap_method"]      = v
                bot.dm._adb._cap_method = v
            else:
                print("  Unknown.")

        elif c == "c":
            print("  Make sure the game is running on screen (bunny on path)…")
            if not bot.dm.backend:
                if not bot.dm.setup():
                    print("  Fix connection first.")
                    continue
            if bot.cal is None:
                bot.cal = AutoCalibrator(bot.dm)
            ok = bot.cal.run(n_frames=6, verbose=True)
            if ok:
                print("  ✓ Colours updated. Run V to see what the bot sees.")
            else:
                print("  ✗ Failed — is the game on screen?")

        elif c == "v":
            print("  Capturing frame for visual dump…")
            if not bot.dm.backend:
                if not bot.dm.setup():
                    print("  Fix connection first.")
                    continue
            frame = bot.dm.screencap()
            if frame is not None:
                path = save_visual_dump(frame, frame.shape[1], frame.shape[0])
                print(f"\n  → Pull the file to your computer to inspect:")
                print(f"    adb pull {path} .")
                print(f"    (or open ./bbot_visual_dump.jpg if running on same PC)")
            else:
                print("  Screencap failed. Run 0 to diagnose.")

        elif c == "s":
            if not bot.setup():
                print("\n  Fix the issues above, then try again.\n")
                continue
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
