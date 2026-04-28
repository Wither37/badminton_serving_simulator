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
            position=window.top_left + Vec2(0.05, -0.15),
            scale=1.0,
            color=color.white,
            visible=False
        )

        self.menu_list_text = Text(
            position=window.top_right + Vec2(-0.04, -0.10),
            origin=(1, 0),
            text='',
            scale=0.82,
            visible=False,
        )

        self.queue_list_text = Text(
            position=window.top_right + Vec2(-0.04, -0.28),
            origin=(1, 0),
            text='',
            scale=0.82,
            visible=False,
        )
        
        self.landings = []
    
    def update_landing_text(self):
        txt = "Landings:\n"
        for i, ld in enumerate(self.landings):
            pos = ld['pos']
            params = ld['params']
            txt += f"{i+1}: Pos ({pos[0]:.2f}, {pos[1]:.2f}), Speed={params[0]}, Yaw={params[1]}, Pitch={params[2]}\n"
        self.landing_text.text = txt
    
    def get_instructions_text(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns):
        """
        serve_mode: 0=auto, 1=manual
        """
        traj = "ON / off" if show_trajectory else "on / OFF"
        if show_returns:
            if is_player_view == 0:
                view_mode = "FREE / serve machine / player / return-cam"
            elif is_player_view == 1:
                view_mode = "free / SERVE MACHINE / player / return-cam"
            elif is_player_view == 2:
                view_mode = "free / serve machine / PLAYER / return-cam"
            else:
                view_mode = "free / serve machine / player / RETURN-CAM"
        else:
            if is_player_view == 0:
                view_mode = "FREE / serve machine / player"
            elif is_player_view == 1:
                view_mode = "free / SERVE MACHINE / player"
            else:
                view_mode = "free / serve machine / PLAYER"

        if serve_mode == 0:
            serve_text = "AUTO / manual"
        else:
            serve_text = "auto / MANUAL"
        
        returns_mode = "ON / off" if show_returns else "on / OFF"
        instructions = f"""Q: Quit
R: Reset
T: Toggle Trajectory ({traj})
V: Toggle View ({view_mode})
N: Toggle Serve Mode ({serve_text})
    B: Toggle Dynamic Returns ({returns_mode}) [Manual only]
    0-9: Enqueue Menu (Manual)
Enter: Serve (Manual) / Run Next Queued Menu
X: Toggle Delete Menu Mode"""
        
        if serve_mode == 1:
            instructions += "\n[MANUAL MODE: MENU QUEUE ENABLED]"
            if menu_delete_mode:
                instructions += "\n[DELETE MODE: press 1-9 to delete menu]"
        
        return instructions
    
    def update_instructions(self, show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns):
        self.instructions_text.text = self.get_instructions_text(show_trajectory, is_player_view, serve_mode, menu_delete_mode, show_returns)

    def update_return_info(self, text, visible=True):
        self.return_info_text.text = text
        self.return_info_text.visible = visible

    def hide_return_info(self):
        self.return_info_text.visible = False
    
    def show_menu_list(self, menus):
        """Display list of available menus (right panel)."""
        txt = "AVAILABLE MENUS\n"
        txt += "----------------\n"
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
        """Display queued menu IDs in right panel (under available menu list)."""
        txt = "EXECUTION QUEUE\n"
        txt += "---------------\n"
        if not queued_menu_ids:
            txt += "(empty)"
        else:
            for i, menu_id in enumerate(queued_menu_ids[:5]):
                label = str(menu_id)
                if len(label) > 26:
                    label = f"{label[:23]}..."
                txt += f"{i+1}. {label}\n"
            if len(queued_menu_ids) > 5:
                txt += f"... +{len(queued_menu_ids)-5} more"
        
        self.queue_list_text.text = txt
        self.queue_list_text.visible = True
    
    def hide_menu_list(self):
        self.menu_list_text.visible = False
        self.queue_list_text.visible = False