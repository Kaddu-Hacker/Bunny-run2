from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView

class Dashboard(BoxLayout):
    def __init__(self, config, on_run, on_calibrate, on_scan, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 10
        self.spacing = 10
        self.config = config
        self.on_run = on_run
        self.on_calibrate = on_calibrate
        self.on_scan = on_scan
        self.build_ui()

    def build_ui(self):
        self.clear_widgets()
        
        # Header / Status
        mode = "ROOT" if self.config.get("rootMode") else "HUMAN"
        status_text = f"--- SETUP STATUS ---\nMode: {mode}\nAuto-Reset: {self.config.get('autoReset')}\nPath: {hex(self.config.get('path_color', 0))}"
        self.add_widget(Label(text=status_text, size_hint_y=None, height=100))

        # Action Buttons
        btn_layout = BoxLayout(orientation='vertical', spacing=5)
        
        run_btn = Button(text="🚀 RUN BOT", background_color=(0, 0.7, 1, 1))
        run_btn.bind(on_press=self.on_run)
        btn_layout.add_widget(run_btn)

        cal_btn = Button(text="🎨 Step 1: Calibrate Path")
        cal_btn.bind(on_press=self.on_calibrate)
        btn_layout.add_widget(cal_btn)

        scan_btn = Button(text="🤖 Auto-Scan UI Elements")
        scan_btn.bind(on_press=self.on_scan)
        btn_layout.add_widget(scan_btn)

        mode_btn = Button(text=f"🔄 Switch Mode [{mode}]")
        mode_btn.bind(on_press=self.toggle_mode)
        btn_layout.add_widget(mode_btn)

        tut_btn = Button(text="📖 View Tutorial")
        tut_btn.bind(on_press=self.show_tutorial)
        btn_layout.add_widget(tut_btn)

        self.add_widget(btn_layout)

    def toggle_mode(self, instance):
        self.config["rootMode"] = not self.config.get("rootMode")
        self.build_ui()

    def show_tutorial(self, instance):
        content = Label(text="""
📖 GHOST RESET GUIDE:
• This bot uses the "Ghost" method to bypass ads.
• When you Win or Lose, the app automatically restarts.
• This ensures 0 ads and infinite loops!

💡 QUICK START:
1. Calibrate Path Color while playing.
2. Toggle Ghost Reset to ON.
3. Click 'RUN BOT'.
""", halign='center')
        popup = Popup(title='Tutorial', content=content, size_hint=(0.9, 0.6))
        popup.open()
