import cv2
import time
import os
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.clock import Clock
from core.vision import BunnyVision
from core.controller import AndroidController
from core.wizard import Wizard
from core.vision_auto import VisionAuto
from core.permissions import Permissions
from ui.dashboard import Dashboard

class BunnyRoot(FloatLayout):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        # Dashboard is a child of the FloatLayout
        self.dashboard = Dashboard(
            config=self.app.config_data,
            on_run=self.app.start_bot,
            on_calibrate=self.app.calibrate_path,
            on_scan=self.app.scan_ui,
            size_hint=(1, 0.4), # Occupy bottom 40% of screen
            pos_hint={'x': 0, 'y': 0}
        )
        self.add_widget(self.dashboard)

class BunnyBotApp(App):
    def build(self):
        self.config_data = Wizard().load_config() or Wizard().get_default_config()
        self.vision = BunnyVision() # New Vision Class
        self.controller = AndroidController()
        self.running = False
        
        # Root is now a FloatLayout
        self.root_widget = BunnyRoot(self)
        return self.root_widget

    def start_bot(self, instance):
        if not self.running:
            self.running = True
            print("🚀 Bot started (Clock scheduled)")
            # Schedule vision check every 0.5 seconds
            self.bot_event = Clock.schedule_interval(self.bot_loop, 0.5)
        else:
            self.running = False
            print("🛑 Bot stopped")
            if hasattr(self, 'bot_event'):
                self.bot_event.cancel()

    def calibrate_path(self, instance):
        # Calibration usually needs a thread as it might be blocking or long-running
        # For now, keeping it simple or off-thread if possible, but threading is safer for heavy tasks
        import threading
        threading.Thread(target=self._do_calibrate, daemon=True).start()

    def _do_calibrate(self):
        new_color = Wizard().passive_path_gatherer(self.vision, self.capture_screen)
        self.config_data["path_color"] = new_color
        Wizard().save_config(self.config_data)

    def scan_ui(self, instance):
        import threading
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        VisionAuto().auto_locate(self.capture_screen)

    def capture_screen(self):
        """Native screen capture integration"""
        # Note: screencap is slow. 
        # In a real optimized scenario, we'd use a faster method, 
        # but for this refactor we keep it simple as requested.
        try:
            res = os.system("screencap -p /sdcard/screen.png")
            if res != 0:
                print("⚠️ screencap command failed")
                return None
            img = cv2.imread("/sdcard/screen.png")
            if img is None:
                print("⚠️ cv2.imread failed to read /sdcard/screen.png")
            return img
        except Exception as e:
            print(f"❌ capture_screen error: {e}")
            return None

    def bot_loop(self, dt):
        """
        Main Loop called by Clock every 0.5s.
        dt: delta time (required by Clock)
        """
        if not self.running:
            return

        screen = self.capture_screen()
        if screen is not None:
            # New get_current_state method
            state, coords = self.vision.get_current_state(screen)
            
            if state == "start": # Mapped from starting_btn
                print(f"Found START at {coords}")
                self.controller.tap(coords[0], coords[1])
            
            elif state == "win" or state == "end": # Mapped from winning/ending_btn
                print(f"Found END/WIN at {coords}")
                self.controller.swipe_to_close()
                self.controller.relaunch_game()
                # Pause the clock for a bit to let game reload? 
                # With Clock, we just skip checks if we used time.sleep, but here we can't sleep the main thread.
                # ideally we count frames. For now, simple logic acts immediately.
            
            elif state == "IN_GAME":
                # Only check pathing if we are definitely playing
                edges = self.vision.find_path_edge(screen)
                # Logic using Canny edges...
                pass

if __name__ == "__main__":
    BunnyBotApp().run()
