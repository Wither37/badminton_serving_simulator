"""UI 文字與顯示管理"""
from ursina import *

class UIManager:
    def __init__(self):
        self.instructions_text = Text(
            position=(window.aspect_ratio / 2 - 0.05, 0.5 - 0.05),
            origin=(0.5, 0.5),
            scale=0.72,
            color=color.black,
            parent=camera.ui,
        )
        self.menu_status = "Idle"
    
    def get_instructions_text(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns):
        """
        serve_mode: 0=auto, 1=manual
        """
        view_labels = ["Free", "Machine", "Player", "Return Cam"]
        view_mode = view_labels[is_player_view] if 0 <= is_player_view < len(view_labels) else "Unknown"
        enter_text = "Serve / Run queued" if serve_mode == 1 else "Serve"
        return f"""Q: Quit
V: View ({view_mode})
Esc: Frontend
Enter: {enter_text}

Menu: {self.menu_status}"""
    
    def update_instructions(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns):
        self.instructions_text.text = self.get_instructions_text(show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns)

    def update_return_info(self, text, visible=True):
        if visible and text:
            print(f"[ReturnInfo] {text}")

    def hide_return_info(self):
        pass
