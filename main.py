import os
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.utils import platform

class BunnyRoot(FloatLayout):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        # Dashboard is a child of the FloatLayout
        from ui.dashboard import Dashboard
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
        """Main entry point - all initialization happens here"""
        try:
            # 1. VERIFY PATHS FIRST - Critical for Android
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            template_path = os.path.join(self.script_dir, 'templates', 'starting_btn.png')
            
            if not os.path.exists(template_path):
                error_msg = f"CRITICAL ERROR: Missing templates at {template_path}"
                print(f"❌ {error_msg}")
                return Label(text=error_msg, halign='center')
            
            print("✅ Templates directory verified")
            
            # 2. Import heavy modules inside build() for Android compatibility
            try:
                from core.wizard import Wizard
                from core.vision import BunnyVision
                from core.controller import AndroidController
            except ImportError as e:
                error_msg = f"Import Error: {e}"
                print(f"❌ {error_msg}")
                return Label(text=error_msg, halign='center')
            
            # 3. Initialize core components
            self.config_data = Wizard().load_config() or Wizard().get_default_config()
            self.vision = BunnyVision()
            self.controller = AndroidController()
            self.running = False
            
            print("✅ Core components initialized")
            
            # 4. Build UI
            self.root_widget = BunnyRoot(self)
            return self.root_widget
            
        except Exception as e:
            # Crash log for debugging
            error_msg = f"Fatal Error: {str(e)}"
            print(f"❌ {error_msg}")
            try:
                with open("/sdcard/bunnybot_crash.log", "w") as f:
                    f.write(error_msg)
                    import traceback
                    f.write("\n" + traceback.format_exc())
            except:
                pass
            return Label(text=error_msg, halign='center')

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
        # Calibration in a separate thread to avoid blocking
        import threading
        threading.Thread(target=self._do_calibrate, daemon=True).start()

    def _do_calibrate(self):
        from core.wizard import Wizard
        new_color = Wizard().passive_path_gatherer(self.vision, self.capture_screen)
        self.config_data["path_color"] = new_color
        Wizard().save_config(self.config_data)

    def scan_ui(self, instance):
        import threading
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        from core.vision_auto import VisionAuto
        VisionAuto().auto_locate(self.capture_screen)

    def capture_screen(self):
        """Native screen capture integration"""
        try:
            import cv2
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
            # Get current state using vision system
            state, coords = self.vision.get_current_state(screen)
            
            if state == "start": # Mapped from starting_btn
                print(f"Found START at {coords}")
                self.controller.tap(coords[0], coords[1])
            
            elif state == "win" or state == "end": # Mapped from winning/ending_btn
                print(f"Found END/WIN at {coords}")
                self.controller.swipe_to_close()
                self.controller.relaunch_game()
            
            elif state == "IN_GAME":
                # Only check pathing if we are definitely playing
                edges = self.vision.find_path_edge(screen)
                # Logic using Canny edges (future implementation)
                pass

if __name__ == "__main__":
    try:
        BunnyBotApp().run()
    except Exception as e:
        # Final crash handler
        print(f"❌ App crashed: {e}")
        try:
            with open("/sdcard/bunnybot_crash.log", "w") as f:
                import traceback
                f.write(str(e) + "\n" + traceback.format_exc())
        except:
            pass
