class VisionAuto:
    def __init__(self):
        # DNA of UI buttons for auto-scanning
        self.PATTERNS = {
            "START_BTN": {"color": 0x2196F3, "label": "Play Button"},    # Blue
            "WIN_NEXT":  {"color": 0xFFAA00, "label": "Next Button"},    # Orange
            "ENDING_RE": {"color": 0xFF4444, "label": "Try Again"},     # Red/Pink
            "LOSE_NO":   {"color": 0x8BC34A, "label": "Continue Button"} # Green
        }

    def auto_locate(self, capture_func):
        """
        Scans the screen along the vertical center axis to find button locations.
        Mirroring the Lua 'autoLocate' logic.
        """
        screen = capture_func()
        if screen is None:
            return {}
            
        h, w = screen.shape[:2]
        center_x = w // 2
        found = {}
        
        print("🔍 Auto-Scanning UI Elements...")

        # Scan vertical center from 70% to 95% of screen height
        for y in range(int(h * 0.7), int(h * 0.95), 10):
            pixel = screen[y, center_x] # BGR
            # Convert BGR to Hex
            color_hex = (int(pixel[2]) << 16) | (int(pixel[1]) << 8) | int(pixel[0])
            
            for key, pattern in self.PATTERNS.items():
                if key not in found:
                    # Check color with tolerance (absolute difference sum)
                    target = pattern["color"]
                    tr, tg, tb = (target >> 16) & 0xFF, (target >> 8) & 0xFF, target & 0xFF
                    pr, pg, pb = (color_hex >> 16) & 0xFF, (color_hex >> 8) & 0xFF, color_hex & 0xFF
                    
                    if (abs(tr - pr) + abs(tg - pg) + abs(tb - pb)) < 40:
                        found[key] = {"x": center_x, "y": y}
                        print(f"✅ Found {pattern['label']} at ({center_x}, {y})")
        
        return found
