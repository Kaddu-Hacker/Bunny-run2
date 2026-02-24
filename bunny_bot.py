#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         🐰  BunnyBot — Bunny Runner 3D  (Pure OpenCV)       ║
║         100% local  •  No AI  •  No internet required       ║
╚══════════════════════════════════════════════════════════════╝

HOW THE GAME WORKS:
  • The bunny runs on a winding 3D path that curves LEFT / RIGHT
  • Swipe left or right to steer
  • Collect carrots, avoid fences
  • Speed increases each level

HOW THIS BOT WORKS:
  Every ~100 ms the bot:
    1. Captures the screen via ADB
    2. Detects which way the path curves  (left/right pixel balance)
    3. Detects fences in danger zones     (template + colour)
    4. Detects game-over screen           (dark overlay heuristic)
    5. Sends the right ADB swipe command

  Zero API calls.  Zero internet.  Pure local OpenCV vision.

TEMPLATE FILES (put in the same folder as this script):
  template_carrot.png   — reference image of a carrot
  template_fence.png    — reference image of a fence
  template_rabbit.png   — reference image of the bunny

SETUP (Termux — run once):
  pkg update && pkg upgrade -y
  pkg install python android-tools python-numpy opencv-python git -y
  python bunny_bot.py
"""

import os
import sys
import time
import subprocess
import traceback

# Hard dependency — exit immediately with a helpful message if missing
try:
    import cv2
    import numpy as np
except ImportError:
    print("\n[FATAL] OpenCV / NumPy not found.")
    print("  Fix (Termux): pkg install python-numpy opencv-python -y")
    print("  Fix (Linux):  pip install opencv-python numpy")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  ★  CONFIGURATION  — all tuneable values in one place
# ═══════════════════════════════════════════════════════════════════════════════

CFG = {

    # ── ADB ──────────────────────────────────────────────────────────────────
    # Leave empty → bot auto-detects the first connected device.
    # Set to "192.168.x.x:PORT" to target a specific phone over Wi-Fi.
    "device": "",
    "adb_timeout": 8,             # seconds before killing a hung adb call

    # ── Game package ─────────────────────────────────────────────────────────
    # Run:  adb shell pm list packages | grep bunny
    # to verify this on your device.
    "game_package": "com.kwalee.bunnyrunner",

    # ── Template files (same folder as bunny_bot.py) ──────────────────────────
    "tmpl_carrot": "template_carrot.png",
    "tmpl_fence":  "template_fence.png",
    "tmpl_rabbit": "template_rabbit.png",

    # Match confidence threshold (0.0 loose → 1.0 strict).
    # Lower if templates aren't found; raise to stop false positives.
    "tmpl_threshold": 0.60,

    # ── Timing ───────────────────────────────────────────────────────────────
    "loop_fps":        10,    # main loop frames-per-second
    "startup_delay":    5,    # countdown seconds before bot goes live
    "swipe_ms":        80,    # ADB swipe gesture duration (ms)
    "swipe_px":       300,    # horizontal pixel distance per swipe
    "action_cooldown": 0.20,  # minimum seconds between consecutive swipes

    # ── Screen zones  (all values are fractions 0.0–1.0) ─────────────────────

    # LOOK-AHEAD STRIP  — the horizontal band where we measure path direction.
    # The bot compares path-coloured pixels on the left half vs right half
    # of this strip to determine which way the track is curving.
    "la_top":    0.30,   # top    edge of the strip
    "la_bottom": 0.55,   # bottom edge of the strip

    # DANGER ZONES — rectangles where we watch for incoming fences.
    "dz_left_x":  (0.05, 0.42),   # x range: left  danger zone
    "dz_right_x": (0.58, 0.95),   # x range: right danger zone
    "dz_y":       (0.28, 0.68),   # y range: shared for both zones

    # GAME-OVER ZONE — where retry/score UI appears after death
    "gameover_y": (0.58, 0.95),
    "gameover_x": (0.20, 0.80),

    # ── Path colour  (HSV) ────────────────────────────────────────────────────
    # The colour of the running track / ground surface.
    # Use Calibration (menu → C) to auto-detect the right values for your game.
    "path_hsv_lo": [8,  15, 130],
    "path_hsv_hi": [38, 110, 255],

    # Minimum fraction of lookahead strip that must be path-coloured before we
    # trust the direction signal (prevents acting on black/menu screens).
    "path_min_fill": 0.04,

    # Imbalance needed before we steer.
    # 0.12 → one side needs 12 percentage-points more path pixels than the other.
    # Raise (e.g. 0.18) to reduce jitter; lower (e.g. 0.08) for sharper curves.
    "path_deadband": 0.12,

    # ── Fence / obstacle colour  (HSV) ───────────────────────────────────────
    # Fences are typically bright white or very light grey.
    "fence_hsv_lo": [0,   0, 185],
    "fence_hsv_hi": [180, 45, 255],

    # Pixel count in a danger zone that triggers an emergency dodge.
    # Lower = more sensitive; higher = fewer false positives.
    "fence_px_threshold": 280,

    # ── Game-over detection ───────────────────────────────────────────────────
    # Triggered when BOTH conditions are true:
    #   1. >55% of the screen is very dark (the dim overlay)
    #   2. >400 bright pixels in the bottom zone (score / retry button)
    "gameover_dark_frac":   0.55,
    "gameover_dark_v_max":  60,
    "gameover_bright_px":   400,

    # ── Debug ─────────────────────────────────────────────────────────────────
    "debug": False,
    "debug_save_frames": False,   # saves annotated JPEGs to ./debug_frames/
}


# ═══════════════════════════════════════════════════════════════════════════════
#  ADB WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════

class ADB:
    def __init__(self, device: str = ""):
        self.device = device
        self._build_prefix()

    def _build_prefix(self):
        self._pfx = ["adb", "-s", self.device] if self.device else ["adb"]

    def _run(self, args: list, timeout: int = None):
        cmd = self._pfx + args
        t   = timeout or CFG["adb_timeout"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=t)
            return r.returncode, r.stdout
        except subprocess.TimeoutExpired:
            return -1, b""
        except FileNotFoundError:
            print("[FATAL] 'adb' not found.")
            print("  Fix: pkg install android-tools -y")
            sys.exit(1)

    # ── Device management ────────────────────────────────────────────────────

    def list_devices(self):
        _, out = self._run(["devices"])
        lines  = out.decode(errors="ignore").strip().splitlines()
        return [ln.split("\t")[0] for ln in lines[1:] if "\tdevice" in ln]

    def auto_connect(self) -> bool:
        devs = self.list_devices()
        if not devs:
            return False
        self.device = devs[0]
        self._build_prefix()
        print(f"[ADB] Auto-selected: {self.device}")
        return True

    def is_connected(self) -> bool:
        return bool(self.list_devices())

    # ── Screen capture ───────────────────────────────────────────────────────

    def screencap(self):
        """
        Capture current screen → BGR NumPy array.
        Tries three increasingly compatible methods.
        """
        # Method 1: exec-out (fastest — no temp file)
        rc, data = self._run(["exec-out", "screencap", "-p"], timeout=10)
        if rc == 0 and len(data) > 2000:
            img = _png_bytes_to_bgr(data)
            if img is not None:
                return img

        # Method 2: screencap to /sdcard then pull
        self._run(["shell", "screencap", "-p", "/sdcard/_bbot.png"])
        rc, _ = self._run(["pull", "/sdcard/_bbot.png", "/tmp/_bbot.png"])
        if rc == 0:
            img = cv2.imread("/tmp/_bbot.png")
            if img is not None:
                return img

        # Method 3: screencap to /data/local/tmp (no storage permission needed)
        self._run(["shell", "screencap", "-p", "/data/local/tmp/_bbot.png"])
        rc, _ = self._run(["pull", "/data/local/tmp/_bbot.png", "/tmp/_bbot2.png"])
        if rc == 0:
            img = cv2.imread("/tmp/_bbot2.png")
            if img is not None:
                return img

        return None

    # ── Input ────────────────────────────────────────────────────────────────

    def tap(self, x: int, y: int):
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1, y1, x2, y2, ms: int):
        self._run(["shell", "input", "swipe",
                   str(x1), str(y1), str(x2), str(y2), str(ms)])

    def swipe_left(self, w: int, h: int):
        cx = w // 2
        cy = int(h * 0.60)
        d  = CFG["swipe_px"] // 2
        self.swipe(cx + d, cy, cx - d, cy, CFG["swipe_ms"])

    def swipe_right(self, w: int, h: int):
        cx = w // 2
        cy = int(h * 0.60)
        d  = CFG["swipe_px"] // 2
        self.swipe(cx - d, cy, cx + d, cy, CFG["swipe_ms"])

    # ── Game lifecycle ───────────────────────────────────────────────────────

    def launch_game(self):
        pkg = CFG["game_package"]
        self._run(["shell", "monkey", "-p", pkg,
                   "-c", "android.intent.category.LAUNCHER", "1"])

    def force_stop(self):
        self._run(["shell", "am", "force-stop", CFG["game_package"]])

    def restart_game(self, reason: str = ""):
        label = f" ({reason})" if reason else ""
        print(f"[BOT] Restarting game{label}…")
        self.force_stop()
        time.sleep(1.5)
        self.launch_game()
        time.sleep(3.5)


def _png_bytes_to_bgr(data: bytes):
    """Decode raw PNG bytes (possibly with CRLF from ADB) to BGR array."""
    data = data.replace(b"\r\n", b"\n")
    buf  = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPLATE BANK
# ═══════════════════════════════════════════════════════════════════════════════

class TemplateBank:
    """
    Loads carrot / fence / rabbit reference images and builds a scale pyramid
    so matching works reliably across different phone screen resolutions.
    """

    # Scales to test during matching (covers most phone resolutions)
    SCALES = (0.35, 0.50, 0.70, 0.90, 1.00, 1.20, 1.50)

    def __init__(self):
        self._bank: dict = {}
        script_dir = os.path.dirname(os.path.abspath(__file__))

        specs = [
            ("carrot", CFG["tmpl_carrot"]),
            ("fence",  CFG["tmpl_fence"]),
            ("rabbit", CFG["tmpl_rabbit"]),
        ]

        for key, fname in specs:
            fpath = os.path.join(script_dir, fname)
            img   = cv2.imread(fpath, cv2.IMREAD_COLOR)
            if img is None:
                print(f"[TMPL] ⚠  Not found: {fpath}  — {key} matching disabled")
                continue
            h, w = img.shape[:2]
            pyramid = []
            for s in self.SCALES:
                nw = max(4, int(w * s))
                nh = max(4, int(h * s))
                pyramid.append(cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA))
            self._bank[key] = pyramid
            print(f"[TMPL] ✓  {fname}  ({w}×{h}px, {len(self.SCALES)} scales)")

    def find(self, frame, key: str, roi=None):
        """
        Search for template <key> inside <frame>.
        roi = (x1, y1, x2, y2) in pixels to restrict search area.
        Returns (found: bool, confidence: float, centre: (cx, cy))
        """
        if key not in self._bank or frame is None:
            return False, 0.0, (0, 0)

        search = frame
        ox, oy = 0, 0
        if roi:
            x1, y1, x2, y2 = roi
            search = frame[y1:y2, x1:x2]
            ox, oy = x1, y1

        sh, sw    = search.shape[:2]
        best_val  = 0.0
        best_loc  = (0, 0)
        best_size = (1, 1)

        for tmpl in self._bank[key]:
            th, tw = tmpl.shape[:2]
            if tw > sw or th > sh:
                continue
            try:
                res  = cv2.matchTemplate(search, tmpl, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > best_val:
                    best_val, best_loc, best_size = v, loc, (tw, th)
            except cv2.error:
                continue

        found = best_val >= CFG["tmpl_threshold"]
        cx    = ox + best_loc[0] + best_size[0] // 2
        cy    = oy + best_loc[1] + best_size[1] // 2
        return found, round(best_val, 3), (cx, cy)


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION ENGINE  — converts a frame into a game action
# ═══════════════════════════════════════════════════════════════════════════════

class Vision:
    """
    Decision priority (first match wins):
      1. Game-over overlay detected  →  RESTART
      2. Fence in left danger zone   →  RIGHT   (dodge away from it)
      3. Fence in right danger zone  →  LEFT    (dodge away from it)
      4. Path curves right           →  RIGHT
      5. Path curves left            →  LEFT
      6. Everything else             →  STRAIGHT
    """

    def __init__(self, bank: TemplateBank):
        self.bank = bank

    # ── Main entry ───────────────────────────────────────────────────────────

    def decide(self, frame):
        """Returns (action_str, debug_dict)."""
        h, w  = frame.shape[:2]
        dbg   = {"w": w, "h": h}

        # Priority 1 — game-over?
        if self._game_over(frame, w, h):
            dbg["reason"] = "GAME_OVER"
            return "RESTART", dbg

        # Priority 2 & 3 — fence / obstacle
        fence_action, fdebug = self._check_fences(frame, w, h)
        dbg.update(fdebug)
        if fence_action:
            dbg["reason"] = f"FENCE → {fence_action}"
            return fence_action, dbg

        # Priority 4 & 5 — path direction
        path_action, pdebug = self._check_path(frame, w, h)
        dbg.update(pdebug)
        dbg["reason"] = f"PATH → {path_action}"
        return path_action, dbg

    # ── Game-over detection ──────────────────────────────────────────────────

    def _game_over(self, frame, w: int, h: int) -> bool:
        """
        Two-signal heuristic:
          A) Most of the screen is very dark (dim overlay after death)
          B) Bright UI elements visible in the bottom-centre zone (retry button)
        Both must be true to avoid false positives.
        """
        hsv      = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        v_chan   = hsv[:, :, 2]

        # Signal A: dark overlay coverage
        dark_px  = int(np.count_nonzero(v_chan < CFG["gameover_dark_v_max"]))
        dark_frac = dark_px / max(v_chan.size, 1)
        if dark_frac < CFG["gameover_dark_frac"]:
            return False

        # Signal B: bright retry/score button in lower zone
        gy1 = int(CFG["gameover_y"][0] * h)
        gy2 = int(CFG["gameover_y"][1] * h)
        gx1 = int(CFG["gameover_x"][0] * w)
        gx2 = int(CFG["gameover_x"][1] * w)
        zone_v    = v_chan[gy1:gy2, gx1:gx2]
        bright_px = int(np.count_nonzero(zone_v > 200))

        return bright_px > CFG["gameover_bright_px"]

    # ── Fence detection ──────────────────────────────────────────────────────

    def _check_fences(self, frame, w: int, h: int):
        lo  = np.array(CFG["fence_hsv_lo"], dtype=np.uint8)
        hi  = np.array(CFG["fence_hsv_hi"], dtype=np.uint8)
        thr = CFG["fence_px_threshold"]

        lx1 = int(CFG["dz_left_x"][0]  * w);  lx2 = int(CFG["dz_left_x"][1]  * w)
        rx1 = int(CFG["dz_right_x"][0] * w);  rx2 = int(CFG["dz_right_x"][1] * w)
        zy1 = int(CFG["dz_y"][0] * h);         zy2 = int(CFG["dz_y"][1] * h)

        hsv        = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        left_mask  = cv2.inRange(hsv[zy1:zy2, lx1:lx2], lo, hi)
        right_mask = cv2.inRange(hsv[zy1:zy2, rx1:rx2], lo, hi)
        lc         = int(np.count_nonzero(left_mask))
        rc         = int(np.count_nonzero(right_mask))
        dbg        = {"fence_L": lc, "fence_R": rc}

        # Template match as a second signal (boosts confidence)
        lroi = (lx1, zy1, lx2, zy2)
        rroi = (rx1, zy1, rx2, zy2)
        t_left,  cl, _ = self.bank.find(frame, "fence", roi=lroi)
        t_right, cr, _ = self.bank.find(frame, "fence", roi=rroi)
        dbg["fence_tmpl_L"] = cl
        dbg["fence_tmpl_R"] = cr

        left_blocked  = (lc > thr) or t_left
        right_blocked = (rc > thr) or t_right

        if left_blocked and right_blocked:
            return ("RIGHT" if lc >= rc else "LEFT"), dbg
        if left_blocked:
            return "RIGHT", dbg
        if right_blocked:
            return "LEFT", dbg
        return None, dbg

    # ── Path direction detection ─────────────────────────────────────────────

    def _check_path(self, frame, w: int, h: int):
        """
        Isolate path-coloured pixels inside the look-ahead strip.
        Compare pixel count: left half vs right half.
        More pixels on the right → path curves right → swipe RIGHT.
        """
        y1    = int(CFG["la_top"]    * h)
        y2    = int(CFG["la_bottom"] * h)
        strip = frame[y1:y2, :]

        lo  = np.array(CFG["path_hsv_lo"], dtype=np.uint8)
        hi  = np.array(CFG["path_hsv_hi"], dtype=np.uint8)
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lo, hi)

        total       = mask.size
        total_path  = int(np.count_nonzero(mask))
        dbg         = {"path_fill": round(total_path / max(total, 1), 3)}

        # Not enough path visible — likely a menu or black loading screen
        if total_path < CFG["path_min_fill"] * total:
            return "STRAIGHT", dbg

        mid   = w // 2
        left  = int(np.count_nonzero(mask[:, :mid]))
        right = int(np.count_nonzero(mask[:, mid:]))
        dbg["path_L"] = left
        dbg["path_R"] = right

        denom = left + right
        if denom == 0:
            return "STRAIGHT", dbg

        db = CFG["path_deadband"]
        r_frac = right / denom

        if r_frac > 0.5 + db:
            return "RIGHT", dbg
        elif r_frac < 0.5 - db:
            return "LEFT", dbg
        else:
            return "STRAIGHT", dbg

    # ── Calibration helper ───────────────────────────────────────────────────

    def calibrate(self, frame):
        """
        Sample path colour from the lower-centre of a live in-game screenshot
        and print recommended HSV range values.
        """
        h, w  = frame.shape[:2]
        # Sample patch just below the bunny / directly on the path
        patch = frame[int(h * 0.72): int(h * 0.84),
                      int(w * 0.38): int(w * 0.62)]
        hsv   = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(float)
        med   = np.median(hsv, axis=0)
        lo    = np.clip(med - [15, 35, 50], 0, 255).astype(int).tolist()
        hi    = np.clip(med + [15, 50, 40], 0, 255).astype(int).tolist()

        print("\n─────────── PATH COLOUR CALIBRATION ────────────")
        print(f"  Median HSV:  H={med[0]:.1f}  S={med[1]:.1f}  V={med[2]:.1f}")
        print(f"  path_hsv_lo = {lo}")
        print(f"  path_hsv_hi = {hi}")
        print("  Paste these into CFG at the top of bunny_bot.py")
        print("────────────────────────────────────────────────\n")
        return lo, hi


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class BunnyBot:

    def __init__(self):
        self.adb    = ADB(CFG["device"])
        self.bank   = TemplateBank()
        self.vision = Vision(self.bank)
        self._reset_state()

    def _reset_state(self):
        self.frame_count       = 0
        self.start_time        = 0.0
        self.last_action       = "STRAIGHT"
        self.last_act_time     = 0.0
        self.consecutive_fails = 0
        self.screen_w          = 0
        self.screen_h          = 0

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup(self) -> bool:
        print("\n[BOT] Checking ADB connection…")

        if not CFG["device"]:
            if not self.adb.auto_connect():
                print(
                    "[ERROR] No device found.\n"
                    "  Steps:\n"
                    "    1. Enable Developer Options on your phone\n"
                    "    2. Turn on Wireless Debugging\n"
                    "    3. adb pair <IP>:<PAIR_PORT>\n"
                    "    4. adb connect <IP>:<CONN_PORT>"
                )
                return False
        else:
            if not self.adb.is_connected():
                print(f"[ERROR] Device '{CFG['device']}' not reachable.")
                return False

        print("[BOT] Testing screen capture…")
        frame = self.adb.screencap()
        if frame is None:
            print(
                "[ERROR] Screen capture failed.\n"
                "  Try: adb kill-server && adb connect <IP>:<PORT>"
            )
            return False

        h, w = frame.shape[:2]
        self.screen_w = w
        self.screen_h = h
        print(f"[BOT] Screen: {w}×{h}px  ✓")
        print("[BOT] Ready!\n")
        return True

    # ── Main loop ────────────────────────────────────────────────────────────

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

    # ── Single frame ─────────────────────────────────────────────────────────

    def _tick(self):
        self.frame_count += 1

        frame = self.adb.screencap()
        if frame is None:
            self.consecutive_fails += 1
            if self.consecutive_fails >= 10:
                print("[WARN] 10 capture failures — retrying ADB connection…")
                self.adb.auto_connect()
                self.consecutive_fails = 0
            return
        self.consecutive_fails = 0

        h, w = frame.shape[:2]
        self.screen_w = w
        self.screen_h = h

        action, dbg = self.vision.decide(frame)
        self._execute(action, w, h)

        if CFG["debug"]:
            fps = self.frame_count / max(time.time() - self.start_time, 1)
            pl  = dbg.get("path_L",   "-")
            pr  = dbg.get("path_R",   "-")
            fl  = dbg.get("fence_L",  "-")
            fr  = dbg.get("fence_R",  "-")
            rsn = dbg.get("reason",   "")
            print(f"[{self.frame_count:05d}] {action:<8}  {rsn:<32}"
                  f"  pathL/R={pl}/{pr}  fenceL/R={fl}/{fr}  {fps:.1f}fps")

        if CFG["debug_save_frames"]:
            self._save_debug(frame, action, dbg, w, h)

    # ── Execute action ───────────────────────────────────────────────────────

    def _execute(self, action: str, w: int, h: int):
        now = time.time()

        if action == "RESTART":
            print("[BOT] Game over — tapping to restart…")
            time.sleep(0.8)
            self.adb.tap(w // 2, int(h * 0.72))
            time.sleep(1.2)
            self.last_act_time = time.time()
            return

        # Cooldown guard — don't spam swipes
        if now - self.last_act_time < CFG["action_cooldown"]:
            return

        if action == "LEFT":
            self.adb.swipe_left(w, h)
            self.last_act_time = now
            self.last_action   = "LEFT"

        elif action == "RIGHT":
            self.adb.swipe_right(w, h)
            self.last_act_time = now
            self.last_action   = "RIGHT"

        # "STRAIGHT" → no input

    # ── Debug frame annotator ────────────────────────────────────────────────

    def _save_debug(self, frame, action: str, dbg: dict, w: int, h: int):
        vis = frame.copy()

        # Lookahead strip  (green)
        ly1 = int(CFG["la_top"]    * h)
        ly2 = int(CFG["la_bottom"] * h)
        cv2.rectangle(vis, (0, ly1), (w, ly2),     (0, 200, 0), 2)
        cv2.line(vis, (w // 2, ly1), (w // 2, ly2), (0, 255, 255), 1)

        # Danger zones  (red)
        lx1 = int(CFG["dz_left_x"][0]  * w);  lx2 = int(CFG["dz_left_x"][1]  * w)
        rx1 = int(CFG["dz_right_x"][0] * w);  rx2 = int(CFG["dz_right_x"][1] * w)
        zy1 = int(CFG["dz_y"][0] * h);         zy2 = int(CFG["dz_y"][1] * h)
        cv2.rectangle(vis, (lx1, zy1), (lx2, zy2), (0, 0, 220), 2)
        cv2.rectangle(vis, (rx1, zy1), (rx2, zy2), (0, 0, 220), 2)

        # Action label
        colour = {"LEFT": (0, 165, 255), "RIGHT": (0, 165, 255),
                  "RESTART": (0, 0, 255), "STRAIGHT": (0, 220, 0)}.get(action, (200, 200, 200))
        cv2.putText(vis, action, (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8, colour, 4)
        cv2.putText(vis, dbg.get("reason", ""), (20, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        cv2.imwrite(
            f"debug_frames/{self.frame_count:06d}_{action}.jpg",
            vis,
            [cv2.IMWRITE_JPEG_QUALITY, 65]
        )

    # ── Session stats ────────────────────────────────────────────────────────

    def print_stats(self):
        elapsed = time.time() - self.start_time
        fps = self.frame_count / max(elapsed, 1)
        print(f"\n[BOT] Stopped after {elapsed:.0f}s  |"
              f"  {self.frame_count} frames  |  avg {fps:.1f} fps")


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """\n╔══════════════════════════════════════════════════════════════╗
║         🐰  BunnyBot — Bunny Runner 3D  (Pure OpenCV)       ║
╚══════════════════════════════════════════════════════════════╝"""


def show_menu(bot):
    dev = CFG["device"] or "(auto-detect)"
    dbg = "ON" if CFG["debug"] else "OFF"
    sav = "ON" if CFG["debug_save_frames"] else "OFF"
    print(f"""
┌──────────────────────────────────────────────────┐
│  Device          : {dev:<30}│
│  Loop FPS        : {CFG['loop_fps']:<30}│
│  Swipe           : {CFG['swipe_ms']}ms  /  {CFG['swipe_px']}px{"":<17}│
│  Action cooldown : {CFG['action_cooldown']}s{"":<27}│
│  Debug log       : {dbg:<30}│
│  Save frames     : {sav:<30}│
├──────────────────────────────────────────────────┤
│  1  Set target device (blank = auto)             │
│  2  Change loop FPS              (default 10)    │
│  3  Change swipe speed / distance                │
│  4  Change action cooldown       (default 0.20s) │
│  5  Toggle debug logging                         │
│  6  Toggle save debug frames                     │
│  7  Change game package name                     │
│  8  Adjust fence pixel threshold (default 280)   │
│  9  Adjust path deadband         (default 12%)   │
│                                                  │
│  C  Calibrate path colour from live screen       │
│  S  START the bot                                │
│  Q  Quit                                         │
└──────────────────────────────────────────────────┘""")


def menu():
    print(BANNER)
    bot = BunnyBot()

    while True:
        show_menu(bot)
        c = input("  Option: ").strip().lower()

        if c == "1":
            v = input("  Device IP:PORT (blank = auto): ").strip()
            CFG["device"] = v
            bot.adb = ADB(v)

        elif c == "2":
            try:
                v = int(input(f"  FPS 1–30 [current {CFG['loop_fps']}]: "))
                CFG["loop_fps"] = max(1, min(30, v))
            except ValueError:
                print("  Not a valid number.")

        elif c == "3":
            try:
                ms = int(input(f"  Swipe duration ms [current {CFG['swipe_ms']}]: "))
                px = int(input(f"  Swipe distance px [current {CFG['swipe_px']}]: "))
                CFG["swipe_ms"] = max(20, ms)
                CFG["swipe_px"] = max(50, px)
            except ValueError:
                print("  Not valid numbers.")

        elif c == "4":
            try:
                v = float(input(f"  Cooldown seconds [current {CFG['action_cooldown']}]: "))
                CFG["action_cooldown"] = max(0.05, v)
            except ValueError:
                print("  Not a valid number.")

        elif c == "5":
            CFG["debug"] = not CFG["debug"]
            print(f"  Debug logging: {'ON' if CFG['debug'] else 'OFF'}")

        elif c == "6":
            CFG["debug_save_frames"] = not CFG["debug_save_frames"]
            print(f"  Frame saving: {'ON' if CFG['debug_save_frames'] else 'OFF'}")

        elif c == "7":
            v = input(f"  Package [current: {CFG['game_package']}]: ").strip()
            if v:
                CFG["game_package"] = v

        elif c == "8":
            try:
                v = int(input(f"  Fence threshold [current {CFG['fence_px_threshold']}]: "))
                CFG["fence_px_threshold"] = max(10, v)
            except ValueError:
                print("  Not a valid number.")

        elif c == "9":
            try:
                v = float(input(f"  Deadband % 1–49 [current {CFG['path_deadband']*100:.0f}]: "))
                CFG["path_deadband"] = max(0.01, min(0.49, v / 100))
            except ValueError:
                print("  Not a valid number.")

        elif c == "c":
            print("  Setting up — open the game to a running screen first…")
            if not bot.setup():
                print("  Fix device connection first.")
                continue
            frame = bot.adb.screencap()
            if frame is not None:
                lo, hi = bot.vision.calibrate(frame)
                if input("  Apply these values now? [y/N]: ").strip().lower() == "y":
                    CFG["path_hsv_lo"] = lo
                    CFG["path_hsv_hi"] = hi
                    print("  ✓ Path colour updated for this session.")
                    print("    (Copy them into CFG in the script to make permanent.)")
            else:
                print("  Screen capture failed.")

        elif c == "s":
            if not bot.setup():
                print("\n  Fix the issues above and try again.\n")
                continue
            try:
                bot.run()
            except KeyboardInterrupt:
                pass
            finally:
                bot.print_stats()
            bot._reset_state()   # allow re-running without restarting script

        elif c == "q":
            print("  Bye! 🐰\n")
            sys.exit(0)

        else:
            print("  Unknown option.")


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Pass device as CLI arg:  python bunny_bot.py 192.168.1.10:38765
    if len(sys.argv) > 1 and ":" in sys.argv[1]:
        CFG["device"] = sys.argv[1]
        print(f"[CLI] Device: {CFG['device']}")
    menu()
