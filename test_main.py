"""主程式入口"""
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader
import threading
import queue
import time

from config import *
from physics import simulate_trajectory
from court import Court
from ui import UIManager
from return_solver import ReturnSolver
from MQTTSimulator_menu import MQTTSimulator

# Global state
class GameState:
    def __init__(self):
        self.trajectory_points = []
        self.simulation_time = 0.0
        self.simulation_type = None
        self.trail_timer = 0.0
        
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

def reset_simulation(speed_mps, yaw_deg, pitch_deg, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):
    """重置模擬"""
    sim = simulate_trajectory(speed_mps, yaw_deg, pitch_deg, start_x=start_x, start_y=start_y, start_z=start_z)
    state.trajectory_points = sim['points']
    ball.position = (start_y, start_z, start_x)
    ball.color = color.yellow
    state.simulation_time = 0.0
    state.trail_timer = 0.0
    state.solutions_ready = False
    state.simulation_type = 'serve'
    for e in state.return_trails:
        destroy(e)
    state.return_trails.clear()

def update():
    """主更新迴圈"""
    if not state.trajectory_points:  # No active simulation
        if state.auto_serve:
            try:
                params = serve_queue.get_nowait()
                state.current_speed = params['speed']
                state.current_yaw = params['yaw']
                state.current_pitch = params['pitch']
                reset_simulation(state.current_speed, state.current_yaw, state.current_pitch)
                # Reset everything on new serve
                state.last_landing = None
                for p in solver.return_presets:
                    p['solution'] = None
                solver.clear_entities()
                state.show_returns = False
                ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                                      state.show_returns, state.current_return_view)
            except queue.Empty:
                pass
        return

    # Advance simulation time
    state.simulation_time += time.dt

    # Find the current segment in pre-computed points
    for i in range(len(state.trajectory_points) - 1):
        curr_t = state.trajectory_points[i][6]
        next_t = state.trajectory_points[i + 1][6]
        if curr_t <= state.simulation_time < next_t:
            frac = (state.simulation_time - curr_t) / (next_t - curr_t)
            curr_pos = state.trajectory_points[i]
            next_pos = state.trajectory_points[i + 1]
            # Lerp position (x, y, z)
            x = curr_pos[0] + frac * (next_pos[0] - curr_pos[0])
            y = curr_pos[1] + frac * (next_pos[1] - curr_pos[1])
            z = curr_pos[2] + frac * (next_pos[2] - curr_pos[2])
            # Set ball position (Ursina: y, z, x)
            ball.position = (y, z, x)
            break
    else:
        # Beyond last point: Set to final landing and stop
        final_pos = state.trajectory_points[-1]
        ball.position = (final_pos[1], final_pos[2], final_pos[0])
        state.trajectory_points = []  # End simulation

    if state.show_trajectory:
        state.trail_timer += time.dt
        if state.trail_timer >= TRAIL_INTERVAL:
            trail = Entity(model='sphere', color=color.red, scale=0.03, position=ball.position)
            if state.simulation_type == 'return':
                state.return_trails.append(trail)
            elif state.simulation_type == 'serve':
                state.serve_trails.append(trail)
            state.trail_timer -= TRAIL_INTERVAL

    # Handle simulation end
    if not state.trajectory_points:
        if state.simulation_type == 'serve':
            ball.color = color.red
            print(f"Landed at (x={ball.z:.2f}, y={ball.x:.2f})")  # Ursina z = user's x, x = user's y

            state.last_landing = {'x': ball.z, 'y': ball.x}
            ui.landings.append({'pos': (ball.z, ball.x), 'params': (state.current_speed, state.current_yaw, state.current_pitch)})
            ui.update_landing_text()

            marker = Entity(model='sphere', scale=0.1, color=color.blue, position=(ball.x, 0.05, ball.z))
            state.landing_markers.append(marker)

            simulator.client.publish(simulator.status_topic, "serve=done")

            # === COMPUTE RETURN SOLUTIONS ONCE ===
            if not state.solutions_ready:
                solver.compute_solutions(state.last_landing, state.current_speed, state.current_yaw, state.current_pitch)
                state.solutions_ready = True

            # Auto-show if enabled
            state.current_return_view = '0'
            if state.show_returns:   
                solver.display_view(state.current_return_view, state.last_landing)
        elif state.simulation_type == 'return':
            ball.color = color.red
            # DO NOT compute solutions here!
        state.simulation_type = None

def input(key):
    """按鍵處理"""
    if key == 'q':
        application.quit()

    if key == 'r':
        for e in state.serve_trails + state.return_trails + state.landing_markers + solver.return_entities:
            destroy(e)
        state.serve_trails.clear()
        state.return_trails.clear()
        state.landing_markers.clear()
        solver.return_entities.clear()
        ui.landings.clear()
        ui.update_landing_text()
        ball.position = (0, RELEASE_HEIGHT, 0)
        ball.color = color.yellow
        state.trajectory_points = []
        state.simulation_time = 0.0
        state.last_landing = None
        for p in solver.return_presets:
            p['solution'] = None
        state.show_returns = False  
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                              state.show_returns, state.current_return_view)

    if key == 't':
        state.show_trajectory = not state.show_trajectory
        for e in state.serve_trails + state.return_trails:
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
        if not state.trajectory_points and not serve_queue.empty():
            params = serve_queue.get()
            state.current_speed = params['speed']
            state.current_yaw = params['yaw']
            state.current_pitch = params['pitch']
            reset_simulation(state.current_speed, state.current_yaw, state.current_pitch)
            # Reset returns
            state.last_landing = None
            for p in solver.return_presets:
                p['solution'] = None
            solver.clear_entities()
            state.show_returns = False  # Consistent with auto mode
            ui.update_instructions(state.show_trajectory, state.is_player_view, state.auto_serve, 
                                  state.show_returns, state.current_return_view)

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