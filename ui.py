"""UI 文字與顯示管理"""
from ursina import *

class UIManager:
    def __init__(self):
        self.landing_text = Text(
            position=window.top_left + Vec2(0.05, -0.05),
            text='',
            scale=1.0
        )
        
        self.instructions_text = Text(
            position=(0.80, -0.35),
            origin=(0.5, 0),
            scale=1.0
        )
        
        self.return_info_text = Text(
            position=(0.4, 0.4),
            scale=1.2,
            color=color.white,
            visible=False
        )
        
        self.menu_list_text = Text(
            position=window.top_right + Vec2(-0.05, -0.03),
            origin=(1, 0),
            text='',
            scale=0.8,
            visible=False
        )
        
        self.queue_list_text = Text(
            position=window.bottom_left + Vec2(0.15, 0.10),
            origin=(0, 0),
            text='',
            scale=0.8,
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
    
    def get_instructions_text(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns, current_return_view):
        """
        serve_mode: 0=auto, 1=manual
        """
        traj = "ON / off" if show_trajectory else "on / OFF"
        view_mode = "PLAYER / fixed" if is_player_view else "player / FIXED"
        
        if serve_mode == 0:
            serve_text = "AUTO / manual"
        else:
            serve_text = "auto / MANUAL"
        
        returns_mode = "ON / off" if show_returns else "on / OFF"
        view = "ALL" if current_return_view == '0' else (str(current_return_view) if str(current_return_view).isdigit() else "—")
        
        instructions = f"""Q: Quit
R: Reset
T: Toggle Trajectory ({traj})
V: Toggle View ({view_mode})
N: Toggle Serve Mode ({serve_text})
B: Toggle Returns ({returns_mode})
0-9: Show & Play Return ({view}) / Enqueue Menu (Manual)
Enter: Serve (Manual) / Run Next Queued Menu
X: Toggle Delete Menu Mode"""
        
        if serve_mode == 1:
            instructions += "\n[MANUAL MODE: MENU QUEUE ENABLED]"
            if menu_delete_mode:
                instructions += "\n[DELETE MODE: press 1-9 to delete menu]"
        
        return instructions
    
    def update_instructions(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns, current_return_view):
        self.instructions_text.text = self.get_instructions_text(show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns, current_return_view)

    def update_return_info(self, text, visible=True):
        self.return_info_text.text = text
        self.return_info_text.visible = visible

    def hide_return_info(self):
        self.return_info_text.visible = False
    
    def show_menu_list(self, menus):
        """Display list of available menus (top right)."""
        txt = "STORED MENUS:\n"
        if not menus:
            txt += "(none)"
        else:
            for i, menu in enumerate(menus[:9]):  # Show first 9 (keys 1-9)
                name = menu['menuName']
                if len(name) > 24:
                    name = f"{name[:21]}..."
                txt += f"{i+1}: {name}\n"
            if len(menus) > 9:
                txt += f"... +{len(menus)-9} more"
        
        self.menu_list_text.text = txt
        self.menu_list_text.visible = True
    
    def update_queue_list(self, queued_menu_ids):
        """Display queued menu IDs (bottom left) - show only first 3."""
        txt = "QUEUE:\n"
        if not queued_menu_ids:
            txt += "(empty)"
        else:
            for i, menu_id in enumerate(queued_menu_ids[:3]):
                txt += f"{i+1}. {menu_id}\n"
            if len(queued_menu_ids) > 3:
                txt += f"... +{len(queued_menu_ids)-3} more"
        
        self.queue_list_text.text = txt
        self.queue_list_text.visible = True
    
    def hide_menu_list(self):
        self.menu_list_text.visible = False
        self.queue_list_text.visible = False