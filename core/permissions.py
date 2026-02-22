import os

class Permissions:
    @staticmethod
    def request_accessibility():
        """
        Launches the Android Accessibility Settings page directly.
        Mirroring the Lua 'requestAccessibility' logic.
        """
        print("🛡️ NON-ROOT SETUP Required.")
        # Launch the Android Accessibility Settings page
        os.system("am start -a android.settings.ACCESSIBILITY_SETTINGS")
        
        instructions = """
📢 ATTENTION:
1. Find 'BunnyBot' or 'Downloaded Apps'.
2. If it's greyed out, click the 3 dots (top right) and select 'Allow Restricted Settings'.
3. Enable the toggle.
4. Return to the app and press START!
"""
        print(instructions)
        return instructions
