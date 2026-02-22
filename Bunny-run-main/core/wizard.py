import json
import os
import time

class Wizard:
    def __init__(self, config_path="/sdcard/bunny_runner.json"):
        self.config_path = config_path

    def save_config(self, config_data):
        """Saves configuration to a JSON file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            return True
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            return False

    def load_config(self):
        """Loads configuration from a JSON file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    print("⚠️ Config file is not a dictionary")
            except Exception as e:
                print(f"❌ Error loading config: {e}")
        return None

    def passive_path_gatherer(self, detector, capture_func):
        """
        Passive Learning: Samples the path many times and picks the most frequent color.
        Mirroring the Lua 'Passive Calibration' logic.
        """
        color_votes = {}
        samples_needed = 30
        collected = 0
        
        print("🕒 Learning Path... Just play normally!")
        
        while collected < samples_needed:
            screen = capture_func()
            if screen is not None:
                h, w = screen.shape[:2]
                # Sample center path
                pixel = screen[int(h * 0.7), int(w / 2)]
                # Convert BGR to Hex for easier voting
                color_hex = (int(pixel[2]) << 16) | (int(pixel[1]) << 8) | int(pixel[0])
                
                # Ignore pure black or pure white
                if color_hex != 0x000000 and color_hex != 0xFFFFFF:
                    color_votes[color_hex] = color_votes.get(color_hex, 0) + 1
                    collected += 1
            time.sleep(0.15)
            
        # Find the most frequent color (Mode)
        if not color_votes:
            return 0x8D6E63 # Default brown path
            
        winner = max(color_votes, key=color_votes.get)
        print(f"✅ Calibration Successful! Path color: {hex(winner)}")
        return winner

    def get_default_config(self):
        return {
            "path_color": 0x8D6E63,
            "rx": 540,
            "ry": 1800,
            "detectionHeight": 65,
            "tolerance": 5000,
            "refractoryMs": 200,
            "appIconX": 540,
            "appIconY": 450,
            "autoReset": True,
            "rootMode": True
        }
