"""主程式入口"""
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader
import threading
import queue

from utils.config import *
from utils.court import Court
from ui import UIManager
from utils.return_solver import ReturnSolver
from utils.MQTTSimulator_menu import MQTTSimulator
from utils.BallFlight import BallFlight
from utils.menu_storage import list_menus, get_menu_payload, delete_menu

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
        self.is_player_view = 0
        self.serve_mode = 0             # 0=auto, 1=manual
        self.menu_execution_queue = []  # queued menu ids to run in manual mode
        self.manual_menu_running = False
        self.menu_delete_mode = False
        self.show_returns = False
        self.current_return_view = '0'
        self.latest_landed_ball = None
        
        self.return_trails = []
        self.landing_markers = []

        self.precompute_in_progress = False
        self.precompute_menu_id = None
        self.precompute_drills = []
        self.precompute_returns = {}
        self.precompute_index = 0
        self.precompute_hide_info_on_first_serve = False
        self.serve_start_cooldown = 0.0
        self.return_cam_yaw = 180.0
        self.return_cam_pitch = 0.0


def clear_trajectories_for_next_serve():
    # Keep balls/landings, but clear accumulated trajectory visuals.
    for b in state.active_balls:
        for e in b.trail_entities:
            destroy(e)
        b.trail_entities.clear()

    for e in state.return_trails:
        destroy(e)
    state.return_trails.clear()


def apply_view_mode():
    if 'player' not in globals():
        return

    if state.is_player_view == 0:
        player.enabled = True
        camera.parent = player.camera_pivot
        mouse.locked = True
    elif state.is_player_view == 1:
        player.enabled = False
        camera.parent = scene
        camera.position = (0, 1.8, -4.0)
        camera.rotation = (0, 0, 0)
        mouse.locked = False
    elif state.is_player_view == 2:
        player.enabled = False
        camera.parent = scene
        camera.position = (0, 1.7, 14)
        camera.rotation = (0, 180, 0)
        mouse.locked = False
    elif state.is_player_view == 3:
        player.enabled = False
        camera.parent = scene
        mouse.locked = True


def _max_view_mode():
    return 3 if state.show_returns else 2


def create_ball(speed_mps, yaw_deg, pitch_deg, interval, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT, precomputed_return=None, allow_runtime_return_solve=True):
    if state.show_returns:
        clear_trajectories_for_next_serve()

    ball = BallFlight(speed_mps, yaw_deg, pitch_deg, ui, simulator, state, interval, solver, start_x, start_y, start_z)
    state.active_balls.append(ball)
    solver.register_ball(ball, precomputed_return=precomputed_return, allow_runtime_solve=allow_runtime_return_solve)
    if len(state.active_balls) > MAX_SERVE_TRAIL:
        oldest = state.active_balls.pop(0)
        oldest.destroy()

        if state.latest_landed_ball is oldest:
            state.latest_landed_ball = None

        # A removed ball may still be in-flight, so landing artifacts may not exist yet.
        if oldest.finished:
            if state.landing_markers:
                destroy(state.landing_markers.pop(0))
            if ui.landings:
                ui.landings.pop(0)
                ui.update_landing_text()


def get_latest_landed_ball():
    current = state.latest_landed_ball
    if current in state.active_balls and current.finished:
        return current

    for ball in reversed(state.active_balls):
        if ball.finished:
            state.latest_landed_ball = ball
            return ball

    state.latest_landed_ball = None
    return None


def clear_serve_queue():
    while not serve_queue.empty():
        try:
            serve_queue.get_nowait()
        except queue.Empty:
            break


def clear_precompute_state():
    state.precompute_in_progress = False
    state.precompute_menu_id = None
    state.precompute_drills = []
    state.precompute_returns = {}
    state.precompute_index = 0
    state.precompute_hide_info_on_first_serve = False


def reset_before_menu_execution():
    # Prepare a clean scene for the next queued menu without changing current modes.
    for ball in state.active_balls:
        ball.destroy()
    state.active_balls.clear()

    for e in state.landing_markers:
        destroy(e)
    state.landing_markers.clear()

    ui.landings.clear()
    ui.update_landing_text()

    state.latest_landed_ball = None
    state.serve_timer = 0.0
    state.serve_interval = 0.5
    state.serve_start_cooldown = 0.0

    solver.clear_entities()
    clear_serve_queue()
    clear_precompute_state()


def enqueue_menu_drills(drills, precomputed_map=None, precompute_locked=False):
    for idx, drill in enumerate(drills):
        params = drill.get('parameters', {})
        action_item = {
            'speed': params.get('speed', 30.0),
            'yaw': params.get('yaw', 0.0),
            'pitch': params.get('pitch', 20.0),
            'interval_ms': drill.get('interval', 1000),
            'return_plan': (precomputed_map or {}).get(idx),
            'precompute_locked': precompute_locked,
        }
        serve_queue.put(action_item)


def start_menu_precompute(menu_id):
    payload = get_menu_payload(menu_id)
    if not payload:
        return 0

    clear_serve_queue()
    drills = payload.get('menu', {}).get('drills', [])
    if not drills:
        return 0

    clear_precompute_state()
    state.precompute_in_progress = True
    state.precompute_menu_id = menu_id
    state.precompute_drills = drills
    ui.update_return_info(f"Precomputing return trajectories... 0/{len(drills)}", visible=True)
    return len(drills)


def queue_menu_actions(menu_id, precompute_returns=False):
    payload = get_menu_payload(menu_id)
    if not payload:
        return 0

    clear_serve_queue()
    drills = payload.get('menu', {}).get('drills', [])

    # Immediate queueing path (no staged precompute)
    enqueue_menu_drills(drills, precomputed_map=None, precompute_locked=precompute_returns and state.show_returns)

    return len(drills)

def update():
    """主更新迴圈"""
    if state.is_player_view == 3 and state.show_returns:
        state.return_cam_yaw += mouse.velocity[0] * RETURN_CAMERA_SENSITIVITY
        state.return_cam_pitch -= mouse.velocity[1] * RETURN_CAMERA_SENSITIVITY
        state.return_cam_pitch = max(RETURN_CAMERA_PITCH_MIN, min(RETURN_CAMERA_PITCH_MAX, state.return_cam_pitch))

        rp = solver.return_player.position
        camera.parent = scene
        camera.position = (rp.x, RETURN_CAMERA_HEIGHT, rp.z)
        camera.rotation = (state.return_cam_pitch, state.return_cam_yaw, 0)

    if state.precompute_in_progress:
        total = len(state.precompute_drills)
        batch_size = 1

        for _ in range(batch_size):
            if state.precompute_index >= total:
                break

            drill = state.precompute_drills[state.precompute_index]
            params = drill.get('parameters', {})
            state.precompute_returns[state.precompute_index] = solver.precompute_return_for_serve(
                speed_mps=params.get('speed', 30.0),
                yaw_deg=params.get('yaw', 0.0),
                pitch_deg=params.get('pitch', 20.0),
                start_x=0.0,
                start_y=0.0,
                start_z=RELEASE_HEIGHT,
            )
            state.precompute_index += 1

        ui.update_return_info(f"Precomputing return trajectories... {state.precompute_index}/{total}", visible=True)

        if state.precompute_index >= total:
            valid_count = sum(1 for v in state.precompute_returns.values() if v is not None)
            ui.update_return_info(f"Precompute done: {valid_count}/{total} returns ready", visible=True)
            finished_menu_id = state.precompute_menu_id
            enqueue_menu_drills(
                state.precompute_drills,
                precomputed_map=state.precompute_returns,
                precompute_locked=True,
            )
            state.manual_menu_running = True
            state.serve_timer = state.serve_interval
            state.serve_start_cooldown = PRECOMPUTE_SERVE_WARMUP
            print(f"[App] Executing queued menu {finished_menu_id} ({total} actions)")
            clear_precompute_state()
            state.precompute_hide_info_on_first_serve = True

    # Process queue in auto mode or when a manual queued menu is running.
    if state.serve_mode == 0 or state.manual_menu_running:
        if state.serve_start_cooldown > 0.0:
            state.serve_start_cooldown = max(0.0, state.serve_start_cooldown - time.dt)

        hold_for_return = state.manual_menu_running and state.show_returns and solver.has_outstanding_return()
        hold_for_warmup = state.serve_start_cooldown > 0.0
        if hold_for_return:
            # In manual return mode, serve strictly one rally at a time.
            pass

        state.serve_timer += time.dt
        max_carry = max(state.serve_interval * 2.0, 0.25)
        if state.serve_timer > max_carry:
            state.serve_timer = max_carry

        serves_spawned = 0
        max_serves_per_frame = 1

        while (not hold_for_return) and (not hold_for_warmup) and state.serve_timer >= state.serve_interval and serves_spawned < max_serves_per_frame:
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
                    state.serve_interval,
                    precomputed_return=params.get('return_plan'),
                    allow_runtime_return_solve=not params.get('precompute_locked', False)
                )
                if state.precompute_hide_info_on_first_serve:
                    ui.hide_return_info()
                    state.precompute_hide_info_on_first_serve = False
                serves_spawned += 1


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

    # 更新回球動畫（單一回球播放）
    solver.update_animation()


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

        ui.landings.clear()
        ui.update_landing_text()

        state.serve_timer = 0.0
        state.serve_interval = 0.5
        state.serve_start_cooldown = 0.0
        state.manual_menu_running = False
        state.menu_delete_mode = False
        state.menu_execution_queue.clear()
        state.latest_landed_ball = None
        state.show_returns = False
        state.current_return_view = '0'
        clear_precompute_state()
        solver.set_enabled(False)
        solver.clear_entities()
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
        state.is_player_view = (state.is_player_view + 1) % (_max_view_mode() + 1)
        if state.is_player_view == 3:
            state.return_cam_yaw = camera.rotation_y
            state.return_cam_pitch = camera.rotation_x
        apply_view_mode()
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

    if key == 'n':
        # Cycle through serve modes: auto -> manual -> auto
        state.serve_mode = (state.serve_mode + 1) % 2
        state.menu_delete_mode = False
        state.serve_start_cooldown = 0.0
        if state.precompute_in_progress:
            clear_precompute_state()

        # Dynamic returns are available in manual mode only.
        if state.serve_mode == 0 and state.show_returns:
            state.show_returns = False
            solver.set_enabled(False)
            solver.clear_entities()
            state.current_return_view = '0'

        if state.is_player_view > _max_view_mode():
            state.is_player_view = 2
            apply_view_mode()
        
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
            if state.precompute_in_progress:
                print("[App] Precompute is running. Please wait.")
                return
            if state.manual_menu_running:
                print("[App] A queued menu is already running")
            elif state.menu_execution_queue:
                next_menu_id = state.menu_execution_queue.pop(0)
                reset_before_menu_execution()
                if state.show_returns:
                    drill_count = start_menu_precompute(next_menu_id)
                else:
                    drill_count = queue_menu_actions(next_menu_id, precompute_returns=False)
                if drill_count > 0:
                    if state.show_returns:
                        print(f"[App] Precomputing menu {next_menu_id} ({drill_count} actions)")
                    else:
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
                    state.serve_interval,
                    precomputed_return=params.get('return_plan'),
                    allow_runtime_return_solve=not params.get('precompute_locked', False)
                )
            else:
                print("[App] No queued menu. Press 1-9 to enqueue a menu.")

    if key == 'b':
        if state.serve_mode != 1:
            print("[App] Dynamic returns are available in MANUAL mode only.")
            if state.show_returns:
                state.show_returns = False
                solver.set_enabled(False)
                solver.clear_entities()
                state.current_return_view = '0'
            ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                          state.menu_delete_mode, state.show_returns, state.current_return_view)
            return

        state.show_returns = not state.show_returns
        solver.set_enabled(state.show_returns)
        if not state.show_returns:
            solver.clear_entities()
            state.current_return_view = '0'
            if state.is_player_view == 3:
                state.is_player_view = 2
                apply_view_mode()
        else:
            # Ensure new return-follow view mode is available immediately.
            if state.is_player_view > _max_view_mode():
                state.is_player_view = 2
            apply_view_mode()
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns, state.current_return_view)

    # === RETURN VIEW / MENU QUEUE KEYS: 0-9 ===
    if key in '0123456789':
        if state.serve_mode == 1:
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
        elif state.show_returns:
            # Keep numeric keys reserved for future return-debug controls.
            pass

if __name__ == '__main__':
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

    apply_view_mode()

    # Lighting
    sun = DirectionalLight()
    sun.look_at(Vec3(1, -1, 1))
    Sky()

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