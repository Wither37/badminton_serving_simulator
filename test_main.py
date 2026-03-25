"""主程式入口"""
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader
import threading
import queue

from config import *
from physics import simulate_trajectory
from court import Court
from ui import UIManager
from return_solver import ReturnSolver
from MQTTSimulator_menu import MQTTSimulator
from BallFlight import BallFlight
from menu_storage import list_menus, get_menu_payload, delete_menu

# Global state
class GameState:
    def __init__(self):
        self.active_balls = []          # 目前還在飛的球
        self.serve_timer = 0.0          # 固定間隔發球計時器
        self.serve_interval = 0.5       # 每幾秒發一球，可自行調整

        self.current_speed = 30.0
        self.current_yaw = 3.0
        self.current_pitch = 22.0
        
        self.show_trajectory = True
        self.is_player_view = True
        self.serve_mode = 0             # 0=auto, 1=manual
        self.menu_execution_queue = []  # queued menu ids to run in manual mode
        self.manual_menu_running = False
        self.menu_delete_mode = False
        self.show_returns = False
        self.current_return_view = '0'
        self.solutions_ready = False
        self.last_landing = None
        
        self.serve_trails = []
        self.return_trails = []
        self.landing_markers = []

state = GameState()


# App setup
app = Ursina()
Entity.default_shader = lit_with_shadows_shader

# Create scene
ui = UIManager()
court = Court()
ball = Entity(model='sphere', position=(0, RELEASE_HEIGHT, 0), color=color.yellow, scale=0.15)
solver = ReturnSolver(ball, ui, state)

ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

# Player
player = FirstPersonController(
    model='cube', collider='box', position=(0, 1, -2),
    origin_y=-0.5, jump_height=0, speed=8, color=color.orange
)
player.collider = BoxCollider(player, center=Vec3(0,1,0), size=Vec3(1,2,1))
player.visible = False

# Lighting
sun = DirectionalLight()
sun.look_at(Vec3(1, -1, 1))
Sky()

# def new_serve_traj():
#     # 開一條新軌跡(新的一球)
#     state.serve_trails.append([])

#     # 超過上限：刪最舊那條（destroy 它的所有點）
#     while len(state.serve_trails) > MAX_SERVE_TRAIL:
#         oldest = state.serve_trails.pop(0)
#         for e in oldest:
#             destroy(e)

# def reset_simulation(speed_mps, yaw_deg, pitch_deg, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):
#     """重置模擬"""
#     sim = simulate_trajectory(speed_mps, yaw_deg, pitch_deg, start_x=start_x, start_y=start_y, start_z=start_z)
#     state.trajectory_points = sim['points']
#     ball.position = (start_y, start_z, start_x)
#     ball.color = color.yellow
#     state.simulation_time = 0.0
#     state.trail_timer = 0.0
#     state.solutions_ready = False
#     state.simulation_type = 'serve'
#     new_serve_traj()  # Start a new serve trajectory
#     for e in state.return_trails:
#         destroy(e)
#     state.return_trails.clear(speed_mps, yaw_deg, pitch_deg, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT)

def create_ball(speed_mps, yaw_deg, pitch_deg, interval, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):
    ball = BallFlight(speed_mps, yaw_deg, pitch_deg, ui, simulator, state, interval, start_x, start_y, start_z)
    state.active_balls.append(ball)
    if len(state.active_balls) > MAX_SERVE_TRAIL:
                    state.active_balls[0].destroy()
                    state.active_balls.pop(0)
                    destroy(state.landing_markers[0])
                    state.landing_markers.pop(0)
                    ui.landings.pop(0)
                    ui.update_landing_text()


def clear_serve_queue():
    while not serve_queue.empty():
        try:
            serve_queue.get_nowait()
        except queue.Empty:
            break


def queue_menu_actions(menu_id):
    payload = get_menu_payload(menu_id)
    if not payload:
        return 0

    clear_serve_queue()
    drills = payload.get('menu', {}).get('drills', [])
    for drill in drills:
        params = drill.get('parameters', {})
        action_item = {
            'speed': params.get('speed', 30.0),
            'yaw': params.get('yaw', 0.0),
            'pitch': params.get('pitch', 20.0),
            'interval_ms': drill.get('interval', 1000)
        }
        serve_queue.put(action_item)

    return len(drills)

def update():
    """主更新迴圈"""

    # Process queue in auto mode or when a manual queued menu is running.
    if state.serve_mode == 0 or state.manual_menu_running:
        state.serve_timer += time.dt

        while state.serve_timer >= state.serve_interval:
            try:
                params = serve_queue.get_nowait()
                state.current_speed = params['speed']
                state.current_yaw = params['yaw']
                state.current_pitch = params['pitch']
                state.serve_timer -= state.serve_interval
                state.serve_interval = params['interval_ms'] / 1000.0  # Convert ms to seconds

                create_ball(
                    state.current_speed,
                    state.current_yaw,
                    state.current_pitch,
                    state.serve_interval
                )


            except queue.Empty:
                state.serve_timer = 0.0  # 沒有新球了，重置計時器
                state.serve_interval = 0.5  # 恢復預設間隔
                if state.manual_menu_running:
                    state.manual_menu_running = False
                    print("[App] Manual queued menu finished")
                break

    # 更新所有球
    for ball in state.active_balls:
        if ball.finished:
            continue
        ball.update()


def input(key):
    """按鍵處理"""
    global stored_menus

    if key == 'q':
        application.quit()

    if key == 'r':
        for ball in state.active_balls:
            ball.destroy()
        state.active_balls.clear()

        for e in state.landing_markers:
            destroy(e)
        state.landing_markers.clear()

        for trail in state.serve_trails:
            for e in trail:
                destroy(e)
        state.serve_trails.clear()

        ui.landings.clear()
        ui.update_landing_text()

        state.serve_timer = 0.0
        state.serve_interval = 0.5
        state.manual_menu_running = False
        state.menu_delete_mode = False
        state.menu_execution_queue.clear()
        clear_serve_queue()
        if state.serve_mode == 1:
            ui.show_menu_list(stored_menus)
            ui.update_queue_list(state.menu_execution_queue)
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                              state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 't':
        state.show_trajectory = not state.show_trajectory
        for ball in state.active_balls:
            for e in ball.trail_entities:
                e.visible = state.show_trajectory
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 'v':
        state.is_player_view = not state.is_player_view
        if state.is_player_view:
            player.enabled = True
            camera.parent = player.camera_pivot
        else:
            player.enabled = False
            camera.parent = scene
            camera.position = (0, 1.8, -4.0)
            camera.rotation = (0, 0, 0)
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 'n':
        # Cycle through serve modes: auto -> manual -> auto
        state.serve_mode = (state.serve_mode + 1) % 2
        state.menu_delete_mode = False
        
        if state.serve_mode == 1:  # Manual mode
            stored_menus = list_menus()
            ui.show_menu_list(stored_menus)
            ui.update_queue_list(state.menu_execution_queue)
        else:
            ui.hide_menu_list()
        
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                              state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 'x' and state.serve_mode == 1:
        state.menu_delete_mode = not state.menu_delete_mode
        mode_label = "ON" if state.menu_delete_mode else "OFF"
        print(f"[App] Menu delete mode: {mode_label}")
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                              state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 'enter':
        if state.serve_mode == 1:  # Manual mode
            if state.manual_menu_running:
                print("[App] A queued menu is already running")
            elif state.menu_execution_queue:
                next_menu_id = state.menu_execution_queue.pop(0)
                drill_count = queue_menu_actions(next_menu_id)
                if drill_count > 0:
                    state.manual_menu_running = True
                    state.serve_timer = state.serve_interval
                    print(f"[App] Executing queued menu {next_menu_id} ({drill_count} actions)")
                else:
                    print(f"[App] Menu {next_menu_id} has no playable drills")
                ui.show_menu_list(stored_menus)
                ui.update_queue_list(state.menu_execution_queue)
            elif not serve_queue.empty():
                params = serve_queue.get()
                state.current_speed = params['speed']
                state.current_yaw = params['yaw']
                state.current_pitch = params['pitch']
                state.serve_interval = params['interval_ms'] / 1000.0  # Convert ms to seconds
                create_ball(
                    state.current_speed,
                    state.current_yaw,
                    state.current_pitch,
                    state.serve_interval
                )
            else:
                print("[App] No queued menu. Press 1-9 to enqueue a menu.")

    if key == 'b':
        state.show_returns = not state.show_returns
        if state.show_returns and state.solutions_ready:
            solver.display_view('0', state.last_landing)
        else:
            solver.clear_entities()
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

    # === RETURN VIEW / MENU QUEUE KEYS: 0-9 ===
    if key in '0123456789':
        if state.serve_mode == 1 and not (state.show_returns and state.solutions_ready):
            menu_index = int(key) - 1
            if 0 <= menu_index < len(stored_menus):
                selected_menu = stored_menus[menu_index]
                menu_id = selected_menu['id']
                if state.menu_delete_mode:
                    if delete_menu(menu_id):
                        # Remove deleted menu id from pending execution queue.
                        state.menu_execution_queue = [mid for mid in state.menu_execution_queue if mid != menu_id]
                        stored_menus = list_menus()
                        print(f"[App] Deleted menu {menu_index+1}: {selected_menu['menuName']} (id={menu_id})")
                    else:
                        print(f"[App] Failed to delete menu id={menu_id}")
                else:
                    state.menu_execution_queue.append(menu_id)
                    print(f"[App] Enqueued menu {menu_index+1}: {selected_menu['menuName']} (id={menu_id})")
                ui.show_menu_list(stored_menus)
                ui.update_queue_list(state.menu_execution_queue)
        elif state.show_returns and state.solutions_ready:  # Return view mode
            solver.display_view(key, state.last_landing)
            state.current_return_view = key
            ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                                  state.menu_delete_mode, state.show_returns, state.current_return_view)

# Initialize menu storage
stored_menus = list_menus()
print(f"[App] Loaded {len(stored_menus)} stored menus")

# MQTT setup
serve_queue = queue.Queue()
simulator = MQTTSimulator(command_topic='Badminton_simulator', status_topic='abcde12345', serve_queue=serve_queue)
mqtt_thread = threading.Thread(target=simulator.start, daemon=True)
mqtt_thread.start()

# Run
app.run()