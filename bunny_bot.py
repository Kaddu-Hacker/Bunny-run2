#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v3 — Bunny Runner 3D  (Pure OpenCV)          ║
║      100% local  •  No AI  •  No internet required             ║
║      TWO backends: ADB subprocess  +  adbutils (Python)        ║
╚══════════════════════════════════════════════════════════════════╝

BACKENDS
────────
  BACKEND 1 — ADB subprocess  (no pip install needed)
    Uses the  adb  command-line binary.
    Install:  pkg install android-tools -y   (Termux)

  BACKEND 2 — adbutils  (pure Python, often more reliable)
    Talks DIRECTLY to the ADB daemon socket (port 5037).
    No adb binary calls. Faster screencap. Better error recovery.
    Install:  pip install adbutils --break-system-packages

  AUTO mode:  bot tries adbutils first, falls back to ADB subprocess.
  Force a specific backend from the menu (option B).

WHY adbutils IS OFTEN BETTER
─────────────────────────────
  • Talks to ADB daemon directly via TCP socket — no subprocess spawn
  • Handles PNG decoding internally (no CRLF corruption)
  • .screenshot() returns a PIL image — clean, reliable
  • .click(x, y) is a single socket call — faster than subprocess tap

GAME
────
  Bunny Runner 3D — tap LEFT side to go left, RIGHT side to go right.
  Collect carrots, dodge fences, survive as long as possible.

QUICK START (Termux)
────────────────────
  pkg update && pkg upgrade -y
  pkg install python android-tools python-numpy opencv-python -y
  pip install adbutils --break-system-packages      # recommended
  adb pair   <IP>:<PAIR_PORT>
  adb connect <IP>:<CONN_PORT>
  python bunny_bot.py
  → press 0 (diagnostics), then C (calibrate), then S (start)
"""

import os
import sys
import time
import subprocess
import traceback

# ── OpenCV / NumPy (hard dependency) ──────────────────────────────────────────
try:
    import cv2
    import numpy as np
except ImportError:
    print("\n[FATAL] OpenCV / NumPy not found.")
    print("  Fix (Termux): pkg install python-numpy opencv-python -y")
    print("  Fix (Linux):  pip install opencv-python numpy")
    sys.exit(1)

# ── adbutils (optional — soft dependency) ─────────────────────────────────────
try:
    import adbutils
    ADBUTILS_OK = True
except ImportError:
    ADBUTILS_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CFG = {

    # ── Device ───────────────────────────────────────────────────────────────
    "device":      "",     # blank = auto-detect; or "192.168.x.x:PORT"
    "adb_timeout": 12,     # seconds before killing a hung adb subprocess call

    # ── Backend ───────────────────────────────────────────────────────────────
    # "auto"     → try adbutils first, fall back to ADB subprocess
    # "adbutils" → force pure-Python adbutils
    # "adb"      → force ADB subprocess
    "backend": "auto",

    # Screencap method (ADB-subprocess backend only):
    # "auto" | "exec-out" | "local" | "pull"
    "screencap_method": "auto",

    # ── Game ─────────────────────────────────────────────────────────────────
    "game_package": "com.kwalee.bunnyrunner",

    # ── Templates (same folder as bunny_bot.py) ───────────────────────────────
    "tmpl_fence":     "template_fence.png",
    "tmpl_carrot":    "template_carrot.png",
    "tmpl_rabbit":    "template_rabbit.png",
    "tmpl_threshold": 0.60,

    # ── Timing ───────────────────────────────────────────────────────────────
    "loop_fps":        10,
    "startup_delay":    5,
    "action_cooldown": 0.18,

    # ── Tap positions (fractions 0.0–1.0) ────────────────────────────────────
    "tap_left_x":  0.25,
    "tap_right_x": 0.75,
    "tap_y":       0.60,

    # ── Look-ahead strip ──────────────────────────────────────────────────────
    "la_top":    0.30,
    "la_bottom": 0.55,

    # ── Danger zones ─────────────────────────────────────────────────────────
    "dz_left_x":  (0.03, 0.45),
    "dz_right_x": (0.55, 0.97),
    "dz_y":       (0.25, 0.70),

    # ── Game-over zone ────────────────────────────────────────────────────────
    "gameover_y": (0.55, 0.95),
    "gameover_x": (0.20, 0.80),

    # ── Path colour (HSV) — press C to auto-calibrate ─────────────────────────
    "path_hsv_lo":   [8,  15, 120],
    "path_hsv_hi":   [38, 120, 255],
    "path_min_fill": 0.04,
    "path_deadband": 0.12,

    # ── Fence colour (HSV) ────────────────────────────────────────────────────
    "fence_hsv_lo":       [0,   0, 180],
    "fence_hsv_hi":       [180, 50, 255],
    "fence_px_threshold": 250,

    # ── Game-over detection ───────────────────────────────────────────────────
    "gameover_dark_frac":  0.50,
    "gameover_dark_v_max": 65,
    "gameover_bright_px":  350,

    # ── Debug ─────────────────────────────────────────────────────────────────
    "debug":             False,
    "debug_save_frames": False,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 1 — ADB subprocess
# ═══════════════════════════════════════════════════════════════════════════════

class ADBSubprocessBackend:
    """
    Drives the  adb  command-line binary via subprocess.
    Three screencap fallback methods: exec-out / local-tmp / sdcard.
    """
    name = "adb-subprocess"

    def __init__(self, device: str = ""):
        self.device      = device.strip()
        self._pfx        = self._make_pfx()
        self._cap_method = CFG["screencap_method"]

    def _make_pfx(self):
        return ["adb", "-s", self.device] if self.device else ["adb"]

    def _run(self, args, timeout=None):
        cmd = self._pfx + args
        t   = timeout or CFG["adb_timeout"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=t)
            return r.returncode, r.stdout
        except subprocess.TimeoutExpired:
            print(f"[ADB] Timeout: {' '.join(args[:3])}")
            return -1, b""
        except FileNotFoundError:
            print("[ADB] 'adb' binary not found.")
            print("  Fix: pkg install android-tools -y")
            return -2, b""

    def list_devices(self):
        _, out = self._run(["devices"])
        lines  = out.decode(errors="ignore").strip().splitlines()
        return [ln.split("\t")[0] for ln in lines[1:] if "\tdevice" in ln]

    def auto_connect(self) -> bool:
        devs = self.list_devices()
        if not devs:
            return False
        self.device = devs[0]
        self._pfx   = self._make_pfx()
        print(f"[ADB] Auto-selected: {self.device}")
        return True

    def is_connected(self) -> bool:
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

    # ── Screencap ────────────────────────────────────────────────────────────

    def screencap(self):
        if self._cap_method == "exec-out":
            img = self._cap_exec_out()
            if img is not None:
                return img
            self._cap_method = "local"

        if self._cap_method in ("auto", "local"):
            img = self._cap_local_tmp()
            if img is not None:
                self._cap_method = "local"
                return img
            if self._cap_method == "auto":
                self._cap_method = "pull"

        if self._cap_method in ("auto", "pull"):
            img = self._cap_sdcard()
            if img is not None:
                self._cap_method = "pull"
                return img

        return self._cap_exec_out()

    def _cap_exec_out(self):
        rc, data = self._run(["exec-out", "screencap", "-p"], timeout=10)
        if rc != 0 or len(data) < 1000:
            return None
        return _decode_png(data)

    def _cap_local_tmp(self):
        self._run(["shell", "screencap", "-p", "/data/local/tmp/_bbot.png"], timeout=10)
        rc, _ = self._run(["pull", "/data/local/tmp/_bbot.png", "/tmp/_bbot_l.png"], timeout=10)
        return cv2.imread("/tmp/_bbot_l.png") if rc == 0 else None

    def _cap_sdcard(self):
        self._run(["shell", "screencap", "-p", "/sdcard/_bbot.png"], timeout=10)
        rc, _ = self._run(["pull", "/sdcard/_bbot.png", "/tmp/_bbot_s.png"], timeout=10)
        return cv2.imread("/tmp/_bbot_s.png") if rc == 0 else None

    def test_all_methods(self) -> bool:
        print("\n[ADB] Testing screencap methods…")
        tests = [("exec-out", self._cap_exec_out),
                 ("local-tmp", self._cap_local_tmp),
                 ("sdcard",    self._cap_sdcard)]
        chosen = None
        for label, fn in tests:
            try:
                img = fn()
                if img is not None:
                    h, w = img.shape[:2]
                    print(f"  ✓  {label:<12}  {w}×{h}px")
                    if chosen is None:
                        chosen = label
                else:
                    print(f"  ✗  {label:<12}  returned None")
            except Exception as e:
                print(f"  ✗  {label:<12}  error: {e}")

        if chosen:
            self._cap_method        = chosen
            CFG["screencap_method"] = chosen
            print(f"\n  → Using: {chosen}")
            return True

        print("\n  ✗ All ADB screencap methods failed.")
        print("  Fixes:")
        print("    • adb kill-server && adb connect <IP>:<PORT>")
        print("    • Phone → Developer Options → Revoke USB debugging → reconnect")
        print("    • Make sure 'adb devices' shows 'device' not 'unauthorized'")
        print("    • Try the adbutils backend (menu → B → adbutils)")
        return False

    # ── Input ────────────────────────────────────────────────────────────────

    def tap(self, x: int, y: int):
        self._run(["shell", "input", "tap", str(x), str(y)])

    def shell(self, cmd: str) -> str:
        _, out = self._run(["shell"] + cmd.split())
        return out.decode(errors="ignore").strip()

    def launch_game(self):
        self._run(["shell", "monkey", "-p", CFG["game_package"],
                   "-c", "android.intent.category.LAUNCHER", "1"])

    def force_stop(self):
        self._run(["shell", "am", "force-stop", CFG["game_package"]])


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 2 — adbutils  (pure Python)
# ═══════════════════════════════════════════════════════════════════════════════

class AdbUtilsBackend:
    """
    Pure-Python ADB backend using the  adbutils  library.
    Talks directly to the ADB server socket (127.0.0.1:5037).

    Install:  pip install adbutils --break-system-packages

    Key advantages over ADB subprocess:
      • No binary process spawning — single persistent TCP connection
      • .screenshot() returns PIL image with zero CRLF issues
      • .click(x, y) over socket — noticeably faster than subprocess tap
      • Better error messages and timeouts
    """
    name = "adbutils"

    def __init__(self, device: str = ""):
        self._serial    = device.strip()
        self._client    = None
        self._device    = None
        self._connected = False

    def _ensure_client(self):
        if self._client is None:
            self._client = adbutils.AdbClient(host="127.0.0.1", port=5037)

    def auto_connect(self) -> bool:
        try:
            self._ensure_client()
            devices = self._client.device_list()
            if not devices:
                return False
            if self._serial:
                match = next((d for d in devices if d.serial == self._serial), None)
                if match is None:
                    return False
                self._device = match
            else:
                self._device = devices[0]
                self._serial = self._device.serial
            self._connected = True
            print(f"[adbutils] Connected: {self._device.serial}")
            return True
        except Exception as e:
            print(f"[adbutils] auto_connect error: {e}")
            return False

    def is_connected(self) -> bool:
        if not self._connected or self._device is None:
            return False
        try:
            self._device.get_state()
            return True
        except Exception:
            self._connected = False
            return False

    def reconnect(self):
        print("[adbutils] Reconnecting…")
        self._connected = False
        self._device    = None
        time.sleep(1.0)
        self.auto_connect()

    # ── Screencap ────────────────────────────────────────────────────────────

    def screencap(self):
        if not self._connected or self._device is None:
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
            return arr[:, :, ::-1].copy()          # RGB → BGR
        except Exception as e:
            print(f"[adbutils] screencap error: {e}")
            return None

    # ── Input ────────────────────────────────────────────────────────────────

    def tap(self, x: int, y: int):
        try:
            self._device.click(x, y)
        except Exception as e:
            print(f"[adbutils] tap error: {e}")

    def shell(self, cmd: str) -> str:
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


# ═══════════════════════════════════════════════════════════════════════════════
#  DEVICE MANAGER  — backend selection + unified interface
# ═══════════════════════════════════════════════════════════════════════════════

class DeviceManager:
    """
    Selects the best available backend and exposes a unified API.
    auto mode: tries adbutils → falls back to ADB subprocess.
    """

    def __init__(self):
        self.backend = None
        self._adb    = ADBSubprocessBackend(CFG["device"])

    @property
    def backend_name(self) -> str:
        return self.backend.name if self.backend else "none"

    def setup(self) -> bool:
        choice = CFG["backend"]
        print(f"\n[BOT] Backend mode: {choice}")
        if choice == "adbutils":
            return self._try_adbutils()
        if choice == "adb":
            return self._try_adb()
        # auto
        if ADBUTILS_OK:
            print("[BOT] Trying adbutils…")
            if self._try_adbutils(silent_fail=True):
                return True
            print("[BOT] adbutils unavailable — falling back to ADB subprocess")
        else:
            print("[BOT] adbutils not installed — using ADB subprocess")
            print("  (Recommended: pip install adbutils --break-system-packages)")
        return self._try_adb()

    def _try_adbutils(self, silent_fail=False) -> bool:
        if not ADBUTILS_OK:
            if not silent_fail:
                print("[ERROR] adbutils not installed.")
                print("  Fix: pip install adbutils --break-system-packages")
            return False
        b = AdbUtilsBackend(CFG["device"])
        if not b.auto_connect():
            if not silent_fail:
                print("[ERROR] adbutils: no device found.")
                _print_connection_help()
            return False
        img = b.screencap()
        if img is None:
            if not silent_fail:
                print("[ERROR] adbutils connected but screencap failed.")
            return False
        h, w = img.shape[:2]
        print(f"[adbutils] ✓ screencap OK — {w}×{h}px")
        self.backend = b
        return True

    def _try_adb(self) -> bool:
        b = self._adb
        if not CFG["device"]:
            if not b.auto_connect():
                _print_connection_help()
                return False
        else:
            if not b.is_connected():
                print(f"[ERROR] ADB: '{CFG['device']}' not reachable.")
                return False
        ok = b.test_all_methods()
        if ok:
            self.backend = b
        return ok

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def run_diagnostics(self):
        print("\n" + "═"*56)
        print("  FULL BACKEND DIAGNOSTICS")
        print("═"*56)

        print("\n▶  BACKEND 1: adbutils (pure Python)")
        if not ADBUTILS_OK:
            print("   ✗ Not installed.")
            print("   Fix: pip install adbutils --break-system-packages")
        else:
            b = AdbUtilsBackend(CFG["device"])
            if b.auto_connect():
                img = b.screencap()
                if img is not None:
                    h, w = img.shape[:2]
                    print(f"   ✓ Screencap OK — {w}×{h}px")
                else:
                    print("   ✗ Connected but screencap returned None")
            else:
                print("   ✗ No device found")
                print("   (Is 'adb devices' showing a connected device?)")

        print("\n▶  BACKEND 2: ADB subprocess")
        b2 = self._adb
        if not CFG["device"]:
            b2.auto_connect()
        if not b2.is_connected():
            print("   ✗ No device found")
            _print_connection_help()
        else:
            print(f"   Device: {b2.device}")
            b2.test_all_methods()

        print("\n" + "─"*56)
        print("  Recommendation:")
        print("  • adbutils works? → use it (fastest, most reliable)")
        print("    menu B → adbutils")
        print("  • Only ADB subprocess works? → pick the method that ✓'d")
        print("    menu 9 → exec-out / local / pull")
        print("  • Nothing works? → fix ADB connection first")
        print("    adb kill-server && adb connect <IP>:<PORT>")
        print("═"*56 + "\n")

    # ── Unified API ──────────────────────────────────────────────────────────

    def screencap(self):
        return self.backend.screencap() if self.backend else None

    def tap(self, x: int, y: int):
        if self.backend:
            self.backend.tap(x, y)

    def tap_left(self, w: int, h: int):
        self.tap(int(w * CFG["tap_left_x"]), int(h * CFG["tap_y"]))

    def tap_right(self, w: int, h: int):
        self.tap(int(w * CFG["tap_right_x"]), int(h * CFG["tap_y"]))

    def shell(self, cmd: str) -> str:
        return self.backend.shell(cmd) if self.backend else ""

    def launch_game(self):
        if self.backend:
            self.backend.launch_game()

    def force_stop(self):
        if self.backend:
            self.backend.force_stop()

    def restart_game(self, reason=""):
        label = f" ({reason})" if reason else ""
        print(f"[BOT] Restarting game{label}…")
        self.force_stop()
        time.sleep(1.5)
        self.launch_game()
        time.sleep(4.0)

    def reconnect(self):
        if self.backend:
            self.backend.reconnect()


def _print_connection_help():
    print(
        "\n  No device found. Steps to connect:\n"
        "    1. Enable Developer Options on your phone\n"
        "    2. Turn on Wireless Debugging\n"
        "    3. adb pair <IP>:<PAIR_PORT>   ← enter the 6-digit pairing code\n"
        "    4. adb connect <IP>:<CONN_PORT> ← use port on main WD screen\n"
        "    5. adb devices                  ← must say 'device' not 'unauthorized'\n"
    )


def _decode_png(data: bytes):
    """Decode raw PNG bytes — handles CRLF corruption from adb exec-out."""
    clean = data.replace(b"\r\n", b"\n")
    buf   = np.frombuffer(clean, dtype=np.uint8)
    img   = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPLATE BANK
# ═══════════════════════════════════════════════════════════════════════════════

class TemplateBank:
    SCALES = (0.35, 0.50, 0.70, 0.90, 1.00, 1.20, 1.50)

    def __init__(self):
        self._bank = {}
        sd = os.path.dirname(os.path.abspath(__file__))
        for key, fname in [("fence",  CFG["tmpl_fence"]),
                           ("carrot", CFG["tmpl_carrot"]),
                           ("rabbit", CFG["tmpl_rabbit"])]:
            img = cv2.imread(os.path.join(sd, fname))
            if img is None:
                print(f"[TMPL] ⚠  {fname} not found — {key} matching disabled")
                continue
            h, w = img.shape[:2]
            self._bank[key] = [
                cv2.resize(img, (max(4, int(w*s)), max(4, int(h*s))),
                           interpolation=cv2.INTER_AREA)
                for s in self.SCALES
            ]
            print(f"[TMPL] ✓  {fname}  ({w}×{h}px)")

    def find(self, frame, key, roi=None):
        if key not in self._bank or frame is None:
            return False, 0.0, (0, 0)
        search, ox, oy = frame, 0, 0
        if roi:
            x1, y1, x2, y2 = roi
            search = frame[y1:y2, x1:x2]
            ox, oy = x1, y1
        sh, sw = search.shape[:2]
        bv, bl, bz = 0.0, (0,0), (1,1)
        for tmpl in self._bank[key]:
            th, tw = tmpl.shape[:2]
            if tw > sw or th > sh:
                continue
            try:
                _, v, _, loc = cv2.minMaxLoc(
                    cv2.matchTemplate(search, tmpl, cv2.TM_CCOEFF_NORMED))
                if v > bv:
                    bv, bl, bz = v, loc, (tw, th)
            except cv2.error:
                continue
        return bv >= CFG["tmpl_threshold"], round(bv, 3), \
               (ox + bl[0] + bz[0]//2, oy + bl[1] + bz[1]//2)


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class Vision:
    """
    Decision priority (first match wins):
      1. Game-over overlay   → RESTART
      2. Fence in LEFT zone  → RIGHT  (dodge away)
      3. Fence in RIGHT zone → LEFT   (dodge away)
      4. Path curves right   → RIGHT
      5. Path curves left    → LEFT
      6. Otherwise           → STRAIGHT
    """

    def __init__(self, bank: TemplateBank):
        self.bank = bank

    def decide(self, frame):
        h, w = frame.shape[:2]
        dbg  = {"w": w, "h": h}

        if self._game_over(frame, w, h):
            dbg["reason"] = "GAME_OVER"
            return "RESTART", dbg

        act, fd = self._check_fences(frame, w, h)
        dbg.update(fd)
        if act:
            dbg["reason"] = f"FENCE→{act}"
            return act, dbg

        act, pd = self._check_path(frame, w, h)
        dbg.update(pd)
        dbg["reason"] = f"PATH→{act}"
        return act, dbg

    def _game_over(self, frame, w, h):
        v    = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
        dark = int(np.count_nonzero(v < CFG["gameover_dark_v_max"]))
        if dark / max(v.size, 1) < CFG["gameover_dark_frac"]:
            return False
        gy1, gy2 = int(CFG["gameover_y"][0]*h), int(CFG["gameover_y"][1]*h)
        gx1, gx2 = int(CFG["gameover_x"][0]*w), int(CFG["gameover_x"][1]*w)
        return int(np.count_nonzero(v[gy1:gy2, gx1:gx2] > 200)) > CFG["gameover_bright_px"]

    def _check_fences(self, frame, w, h):
        lo  = np.array(CFG["fence_hsv_lo"], dtype=np.uint8)
        hi  = np.array(CFG["fence_hsv_hi"], dtype=np.uint8)
        thr = CFG["fence_px_threshold"]
        lx1, lx2 = int(CFG["dz_left_x"][0]*w),  int(CFG["dz_left_x"][1]*w)
        rx1, rx2 = int(CFG["dz_right_x"][0]*w), int(CFG["dz_right_x"][1]*w)
        zy1, zy2 = int(CFG["dz_y"][0]*h),        int(CFG["dz_y"][1]*h)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lc  = int(np.count_nonzero(cv2.inRange(hsv[zy1:zy2, lx1:lx2], lo, hi)))
        rc  = int(np.count_nonzero(cv2.inRange(hsv[zy1:zy2, rx1:rx2], lo, hi)))
        dbg = {"fence_L": lc, "fence_R": rc}
        tl, cl, _ = self.bank.find(frame, "fence", roi=(lx1, zy1, lx2, zy2))
        tr, cr, _ = self.bank.find(frame, "fence", roi=(rx1, zy1, rx2, zy2))
        dbg["fence_tmpl_L"], dbg["fence_tmpl_R"] = cl, cr
        lb, rb = (lc > thr) or tl, (rc > thr) or tr
        if lb and rb:
            return ("RIGHT" if lc >= rc else "LEFT"), dbg
        if lb:  return "RIGHT", dbg
        if rb:  return "LEFT",  dbg
        return None, dbg

    def _check_path(self, frame, w, h):
        y1, y2 = int(CFG["la_top"]*h), int(CFG["la_bottom"]*h)
        lo = np.array(CFG["path_hsv_lo"], dtype=np.uint8)
        hi = np.array(CFG["path_hsv_hi"], dtype=np.uint8)
        mask = cv2.inRange(cv2.cvtColor(frame[y1:y2, :], cv2.COLOR_BGR2HSV), lo, hi)
        total      = mask.size
        path_total = int(np.count_nonzero(mask))
        dbg        = {"path_fill": round(path_total / max(total, 1), 3)}
        if path_total < CFG["path_min_fill"] * total:
            return "STRAIGHT", dbg
        mid   = w // 2
        left  = int(np.count_nonzero(mask[:, :mid]))
        right = int(np.count_nonzero(mask[:, mid:]))
        dbg["path_L"], dbg["path_R"] = left, right
        denom = left + right
        if denom == 0:
            return "STRAIGHT", dbg
        r = right / denom
        db = CFG["path_deadband"]
        if r > 0.5 + db: return "RIGHT",    dbg
        if r < 0.5 - db: return "LEFT",     dbg
        return "STRAIGHT", dbg

    def calibrate(self, frame):
        h, w  = frame.shape[:2]
        patch = frame[int(h*0.70):int(h*0.85), int(w*0.35):int(w*0.65)]
        hsv   = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(float)
        med   = np.median(hsv, axis=0)
        lo    = np.clip(med - [18, 40, 55], 0, 255).astype(int).tolist()
        hi    = np.clip(med + [18, 55, 40], 0, 255).astype(int).tolist()
        print("\n─────────── PATH COLOUR CALIBRATION ────────────")
        print(f"  Median HSV : H={med[0]:.1f}  S={med[1]:.1f}  V={med[2]:.1f}")
        print(f"  path_hsv_lo = {lo}")
        print(f"  path_hsv_hi = {hi}")
        print("  Paste these into CFG at top of script to make permanent.")
        print("────────────────────────────────────────────────\n")
        return lo, hi


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class BunnyBot:

    def __init__(self):
        self.dm     = DeviceManager()
        self.bank   = TemplateBank()
        self.vision = Vision(self.bank)
        self._reset_state()

    def _reset_state(self):
        self.frame_count, self.start_time     = 0, 0.0
        self.last_action, self.last_act_time  = "STRAIGHT", 0.0
        self.consecutive_fails                = 0
        self.screen_w, self.screen_h          = 0, 0

    def setup(self) -> bool:
        ok = self.dm.setup()
        if ok:
            print(f"[BOT] Active backend: {self.dm.backend_name}  ✓")
            print("[BOT] Ready!\n")
        return ok

    def run(self):
        delay = CFG["startup_delay"]
        print(f"[BOT] Starting in {delay}s — SWITCH TO THE GAME NOW!")
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
            print(f"[WARN] Screencap fail #{self.consecutive_fails}")
            if self.consecutive_fails >= 5:
                print("[WARN] Reconnecting…")
                self.dm.reconnect()
                self.consecutive_fails = 0
            return
        self.consecutive_fails      = 0
        self.screen_w, self.screen_h = frame.shape[1], frame.shape[0]

        action, dbg = self.vision.decide(frame)
        self._execute(action, self.screen_w, self.screen_h)

        if CFG["debug"]:
            fps = self.frame_count / max(time.time() - self.start_time, 0.001)
            print(f"[{self.frame_count:05d}] {action:<8} | "
                  f"{dbg.get('reason',''):<28} | "
                  f"path={dbg.get('path_L','-')}/{dbg.get('path_R','-')} "
                  f"fence={dbg.get('fence_L','-')}/{dbg.get('fence_R','-')} | "
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
            self.last_act_time, self.last_action = now, "LEFT"
        elif action == "RIGHT":
            self.dm.tap_right(w, h)
            self.last_act_time, self.last_action = now, "RIGHT"

    def _save_debug(self, frame, action, dbg, w, h):
        vis  = frame.copy()
        ly1, ly2 = int(CFG["la_top"]*h),    int(CFG["la_bottom"]*h)
        lx1, lx2 = int(CFG["dz_left_x"][0]*w),  int(CFG["dz_left_x"][1]*w)
        rx1, rx2 = int(CFG["dz_right_x"][0]*w), int(CFG["dz_right_x"][1]*w)
        zy1, zy2 = int(CFG["dz_y"][0]*h),        int(CFG["dz_y"][1]*h)
        cv2.rectangle(vis, (0, ly1), (w, ly2),      (0,200,0), 2)
        cv2.line(vis, (w//2, ly1), (w//2, ly2),     (0,255,255), 1)
        cv2.rectangle(vis, (lx1, zy1), (lx2, zy2),  (0,0,220), 2)
        cv2.rectangle(vis, (rx1, zy1), (rx2, zy2),  (0,0,220), 2)
        cv2.circle(vis, (int(w*CFG["tap_left_x"]),  int(h*CFG["tap_y"])), 15, (255,128,0), 3)
        cv2.circle(vis, (int(w*CFG["tap_right_x"]), int(h*CFG["tap_y"])), 15, (255,128,0), 3)
        col = {"LEFT":(0,165,255),"RIGHT":(0,165,255),
               "RESTART":(0,0,255),"STRAIGHT":(0,220,0)}.get(action,(200,200,200))
        cv2.putText(vis, action, (20,60),  cv2.FONT_HERSHEY_SIMPLEX, 1.8, col, 4)
        cv2.putText(vis, dbg.get("reason",""), (20,105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255,255,255), 2)
        cv2.putText(vis, f"[{self.dm.backend_name}]", (20,140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180,180,180), 1)
        cv2.imwrite(f"debug_frames/{self.frame_count:06d}_{action}.jpg",
                    vis, [cv2.IMWRITE_JPEG_QUALITY, 65])

    def print_stats(self):
        elapsed = time.time() - self.start_time
        fps     = self.frame_count / max(elapsed, 1)
        print(f"\n[BOT] Stopped after {elapsed:.0f}s | "
              f"{self.frame_count} frames | avg {fps:.1f} fps | "
              f"backend: {self.dm.backend_name}")


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║      🐰  BunnyBot v3 — Bunny Runner 3D  (Pure OpenCV)          ║
║      Backends: adbutils (Python)  +  ADB subprocess            ║
╚══════════════════════════════════════════════════════════════════╝"""


def show_menu(bot: BunnyBot):
    dev    = CFG["device"] or "(auto-detect)"
    bknd   = CFG["backend"]
    active = bot.dm.backend_name
    au_ok  = "✓  installed" if ADBUTILS_OK else "✗  not installed"
    dbg    = "ON" if CFG["debug"]             else "OFF"
    sav    = "ON" if CFG["debug_save_frames"] else "OFF"
    print(f"""
┌──────────────────────────────────────────────────────────┐
│  Device              : {dev:<34}│
│  Backend mode        : {bknd:<34}│
│  Active backend      : {active:<34}│
│  adbutils            : {au_ok:<34}│
│  Loop FPS            : {CFG['loop_fps']:<34}│
│  Action cooldown     : {CFG['action_cooldown']}s{"":<31}│
│  Debug log           : {dbg:<34}│
│  Save frames         : {sav:<34}│
├──────────────────────────────────────────────────────────┤
│  0  Run full diagnostics  (start here!)                  │
│  1  Set target device     (blank = auto)                 │
│  B  Set backend           (auto / adbutils / adb)        │
│  2  Change loop FPS       (default 10)                   │
│  3  Change action cooldown (default 0.18s)               │
│  4  Toggle debug logging                                 │
│  5  Toggle save debug frames                             │
│  6  Change game package name                             │
│  7  Adjust fence sensitivity  (default 250px)            │
│  8  Adjust path deadband      (default 12%)              │
│  9  Set ADB screencap method  (auto/exec-out/local/pull) │
│                                                          │
│  C  Calibrate path colour from live screen               │
│  S  START the bot                                        │
│  Q  Quit                                                 │
└──────────────────────────────────────────────────────────┘""")


def menu():
    print(BANNER)
    bot = BunnyBot()

    while True:
        show_menu(bot)
        c = input("  Option: ").strip().lower()

        if c == "0":
            bot.dm.run_diagnostics()

        elif c == "1":
            v = input("  Device IP:PORT (blank = auto): ").strip()
            CFG["device"] = v
            bot.dm        = DeviceManager()

        elif c == "b":
            v = input("  Backend [auto / adbutils / adb]: ").strip().lower()
            if v in ("auto", "adbutils", "adb"):
                CFG["backend"] = v
                bot.dm         = DeviceManager()
                print(f"  Backend → {v}")
            else:
                print("  Unknown. Use: auto / adbutils / adb")

        elif c == "2":
            try:
                v = int(input(f"  FPS 1–30 [current {CFG['loop_fps']}]: "))
                CFG["loop_fps"] = max(1, min(30, v))
            except ValueError:
                print("  Not a valid number.")

        elif c == "3":
            try:
                v = float(input(f"  Cooldown s [current {CFG['action_cooldown']}]: "))
                CFG["action_cooldown"] = max(0.05, v)
            except ValueError:
                print("  Not a valid number.")

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
                v = int(input(f"  Fence px threshold [current {CFG['fence_px_threshold']}]: "))
                CFG["fence_px_threshold"] = max(10, v)
            except ValueError:
                print("  Not a valid number.")

        elif c == "8":
            try:
                v = float(input(f"  Deadband % 1–49 [current {CFG['path_deadband']*100:.0f}]: "))
                CFG["path_deadband"] = max(0.01, min(0.49, v / 100))
            except ValueError:
                print("  Not a valid number.")

        elif c == "9":
            v = input("  Screencap method [auto/exec-out/local/pull]: ").strip().lower()
            if v in ("auto", "exec-out", "local", "pull"):
                CFG["screencap_method"]   = v
                bot.dm._adb._cap_method  = v
            else:
                print("  Unknown method.")

        elif c == "c":
            print("  Get the game to an active RUNNING screen first…")
            if not bot.dm.backend:
                if not bot.dm.setup():
                    print("  Fix device connection first.")
                    continue
            frame = bot.dm.screencap()
            if frame is not None:
                lo, hi = bot.vision.calibrate(frame)
                if input("  Apply? [y/N]: ").strip().lower() == "y":
                    CFG["path_hsv_lo"] = lo
                    CFG["path_hsv_hi"] = hi
                    print("  ✓ Path colour updated.")
            else:
                print("  Screencap failed. Run option 0 to diagnose.")

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
    # Optional CLI args:
    #   python bunny_bot.py 192.168.1.7:34679
    #   python bunny_bot.py 192.168.1.7:34679 adbutils
    if len(sys.argv) > 1 and ":" in sys.argv[1]:
        CFG["device"] = sys.argv[1]
        print(f"[CLI] Device: {CFG['device']}")
    if len(sys.argv) > 2 and sys.argv[2] in ("auto", "adbutils", "adb"):
        CFG["backend"] = sys.argv[2]
        print(f"[CLI] Backend: {CFG['backend']}")
    menu()
