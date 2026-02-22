import cv2
import numpy as np
import os

class BunnyVision:
    def __init__(self, templates_dir="templates/"):
        self.templates_dir = templates_dir
        self.templates = {}
        self.load_templates()

    def load_templates(self):
        """Loads all .png images from the templates directory."""
        if not os.path.exists(self.templates_dir):
            print(f"⚠️ Warning: Templates directory '{self.templates_dir}' not found.")
            return

        for f in os.listdir(self.templates_dir):
            if f.endswith(".png"):
                path = os.path.join(self.templates_dir, f)
                # Load in grayscale (0) for performance
                img = cv2.imread(path, 0)
                if img is not None:
                    # Key is filename without extension (e.g., 'starting_btn')
                    key = os.path.splitext(f)[0]
                    self.templates[key] = img
                    print(f"✅ Loaded template: {key}")
                else:
                    print(f"❌ Failed to load: {path}")

    def find_match(self, screen_gray, template_key, threshold=0.85):
        """
        Returns (x, y) center coordinates if match found, else None.
        args:
            screen_gray: Grayscale screenshot
            template_key: Key in self.templates dictionary
            threshold: Confidence threshold (default 0.85)
        """
        template = self.templates.get(template_key)
        if template is None:
            return None

        # The Magic: Match Template
        # TM_CCOEFF_NORMED is robust against lighting differences
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        if max_val >= threshold:
            # Calculate center of the found button
            h, w = template.shape
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return (center_x, center_y)
        
        return None

    def get_current_state(self, screenshot):
        """
        Determines the current game screen based on visible templates.
        Returns: (state_name, coordinates) or ("IN_GAME", None)
        """
        if screenshot is None or not self.templates:
            return "IN_GAME", None

        try:
            # Convert screen to grayscale once
            screen_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

            # Check for known states
            # Priority checks
            if "starting_btn" in self.templates:
                match = self.find_match(screen_gray, "starting_btn")
                if match:
                    return "start", match

            if "winning_btn" in self.templates:
                match = self.find_match(screen_gray, "winning_btn")
                if match:
                    return "win", match

            if "ending_btn" in self.templates:
                match = self.find_match(screen_gray, "ending_btn")
                if match:
                    return "end", match
                    
            if "try_again" in self.templates: # Fallback if user kept old name
                 match = self.find_match(screen_gray, "try_again")
                 if match:
                     return "end", match
        except Exception as e:
            print(f"❌ Error in get_current_state: {e}")

        return "IN_GAME", None
        
    def find_path_edge(self, screenshot):
        """Uses Canny Edge Detection to find the white fences."""
        # Convert to grayscale
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        # Apply Canny Edge Detection
        # Thresh 50-150 is a good baseline for bright white fences
        edges = cv2.Canny(gray, 50, 150)
        return edges
