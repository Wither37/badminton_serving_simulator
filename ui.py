"""UI 文字與顯示管理"""
from ursina import *

class UIManager:
    def __init__(self):
        self.landing_text = Text(
            position=window.top_left + Vec2(0.05, -0.05),
            text='',
            scale=1.0,
            background=True
        )
        
        self.instructions_text = Text(
            position=(0.78, -0.2),
            origin=(0.5, 0),
            scale=1.0
        )
        
        self.return_info_text = Text(
            position=(0.4, 0.4),
            scale=1.2,
            color=color.white,
            visible=False
        )
        
        self.landings = []
    
    def update_landing_text(self):
        txt = "Landings:\n"
        for i, ld in enumerate(self.landings):
            pos = ld['pos']
            params = ld['params']
            txt += f"{i+1}: Pos ({pos[0]:.2f}, {pos[1]:.2f}), Speed={params[0]}, Yaw={params[1]}, Pitch={params[2]}\n"
        self.landing_text.text = txt
    
    def get_instructions_text(self, show_trajectory, is_player_view, auto_serve, show_returns, current_return_view):
        traj = "ON / off" if show_trajectory else "on / OFF"
        view_mode = "PLAYER / fixed" if is_player_view else "player / FIXED"
        serve_mode = "AUTO / manual" if auto_serve else "auto / MANUAL"
        returns_mode = "ON / off" if show_returns else "on / OFF"
        view = "ALL" if current_return_view == '0' else (str(current_return_view) if str(current_return_view).isdigit() else "—")
        return f"""Q: Quit
R: Reset
T: Toggle Trajectory ({traj})
V: Toggle View ({view_mode})
M: Toggle Serve Mode ({serve_mode})
B: Toggle Returns ({returns_mode})
0-9: Show & Play Return ({view})
Enter: Serve (Manual)"""
    
    def update_instructions(self, *args):
        self.instructions_text.text = self.get_instructions_text(*args)

    def update_return_info(self, text, visible=True):
        self.return_info_text.text = text
        self.return_info_text.visible = visible

    def hide_return_info(self):
        self.return_info_text.visible = False