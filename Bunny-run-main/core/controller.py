import os
import time
import subprocess
from typing import Optional, Any

class AndroidController:
    def __init__(self, package_name="com.bunny.runner3D.dg"):
        self.package_name = package_name
        self.shell: Optional[subprocess.Popen[str]] = None
        
        # Cleanup old shell if needed
        old_shell = getattr(self, 'shell', None)
        if old_shell is not None:
            try:
                old_shell.kill()
            except Exception:
                pass

        # Start a persistent shell process
        try:
            self.shell = subprocess.Popen(
                ['sh'],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )
        except FileNotFoundError:
            print("⚠️ 'sh' not found. Fallback to os.system will fail significantly.")
            # Create a dummy object or handle gracefully if running on Windows without sh
            self.shell = None

    def _run_cmd(self, cmd):
        """Writes a command to the persistent shell's stdin."""
        # Retry loop to handle shell restarts
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                # 1. Check if shell exists and is running
                shell = self.shell
                if shell is None or shell.poll() is not None:
                    self.__init__(self.package_name)
                    shell = self.shell
                
                if shell is None:
                    raise BrokenPipeError("Shell not available")
                
                stdin = shell.stdin
                if stdin is None:
                    raise BrokenPipeError("Shell stdin is not available")

                # 3. Write command
                stdin.write(cmd + "\n")
                stdin.flush()
                return # Success

            except (BrokenPipeError, AttributeError, OSError) as e:
                print(f"⚠️ Shell error (attempt {attempt}): {e}")
                if attempt < max_retries:
                    # Force restart before retry
                    self.__init__(self.package_name)
                else:
                    print(f"❌ Command dropped: {cmd}")

    def tap(self, x, y):
        """Native tap via persistent shell."""
        self._run_cmd(f"input tap {x} {y}")

    def swipe(self, x1, y1, x2, y2, duration=400):
        """Native swipe via persistent shell."""
        self._run_cmd(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    def swipe_to_close(self):
        """The 'Human' method to kill the app and bypass ads."""
        print("🚫 Ad-Dodge Reset triggered!")
        
        # Kernel-level Force Stop
        self._run_cmd(f"am force-stop {self.package_name}")
        time.sleep(1.0)
        
        # Fallback to gestured clearing if force-stop is restricted
        self._run_cmd("input keyevent 187") # Open Recents
        time.sleep(1.0)
        self.swipe(540, 1200, 540, 200, 400) # Swipe Card
        time.sleep(0.5)

        # Go Home
        self._run_cmd("input keyevent 3")
        time.sleep(0.5)

    def relaunch_game(self):
        """Restarts the game from the launcher using the monkey tool."""
        print(f"🚀 Relaunching {self.package_name}...")
        self._run_cmd(f"monkey -p {self.package_name} 1")
