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
        self.auto_serve = True
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

ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                      state.show_returns, state.current_return_view)

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

def update():
    """主更新迴圈"""

    # 固定每 N 秒自動發一球，不管場上還有沒有球
    if state.auto_serve:
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
                if len(state.active_balls) > MAX_SERVE_TRAIL:
                    state.active_balls[0].destroy()
                    state.active_balls.pop(0)
                    destroy(state.landing_markers[0])
                    state.landing_markers.pop(0)
                    ui.landings.pop(0)
                    ui.update_landing_text()


            except queue.Empty:
                state.serve_timer = 0.0  # 沒有新球了，重置計時器
                state.serve_interval = 0.5  # 恢復預設間隔
                break

    # 更新所有球
    for ball in state.active_balls:
        if ball.finished:
            continue
        ball.update()


def input(key):
    """按鍵處理"""
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
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

    if key == 't':
        state.show_trajectory = not state.show_trajectory
        for ball in state.active_balls:
            for e in ball.trail_entities:
                e.visible = state.show_trajectory
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

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
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

    if key == 'm':
        state.auto_serve = not state.auto_serve
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

    if key == 'enter' and not state.auto_serve:
        if not serve_queue.empty():
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

    if key == 'b':
        state.show_returns = not state.show_returns
        if state.show_returns and state.solutions_ready:
            solver.display_view('0', state.last_landing)
        else:
            solver.clear_entities()
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

    # === RETURN VIEW KEYS: 0-9 ===
    if key in '0123456789' and state.show_returns and state.solutions_ready:
        solver.display_view(key, state.last_landing)
        state.current_return_view = key
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

# MQTT setup
serve_queue = queue.Queue()
simulator = MQTTSimulator(command_topic='Badminton_simulator', status_topic='abcde12345', serve_queue=serve_queue)
mqtt_thread = threading.Thread(target=simulator.start, daemon=True)
mqtt_thread.start()

# Run
app.run()