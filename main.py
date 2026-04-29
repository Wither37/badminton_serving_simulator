"""主程式入口"""
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader, unlit_shader
import threading
import queue
import webbrowser

from utils.config import *
from utils.court import Court
from utils.ui import UIManager
from utils.return_solver import ReturnSolver
from utils.MQTTSimulator_menu import MQTTSimulator
from utils.BallFlight import BallFlight
from utils.html_menu_frontend import HtmlMenuFrontendServer
from utils.menu_frontend import RETURN_TARGET_PRESETS
from utils.menu_storage import (
    list_menus,
    load_menu,
    get_menu_drills_for_simulator,
    delete_menu,
    set_menu_return_policy,
)

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
        self.latest_landed_ball = None
        
        self.return_trails = []
        self.landing_markers = []

        self.precompute_in_progress = False
        self.precompute_menu_id = None
        self.precompute_drills = []
        self.precompute_returns = {}
        self.precompute_failures = {}
        self.precompute_index = 0
        self.precompute_hide_info_on_first_serve = False
        self.serve_start_cooldown = 0.0
        self.return_cam_yaw = 180.0
        self.return_cam_pitch = 0.0
        self.wait_for_player_home = False
        self.frontend_selected_menu_id = None
        self.frontend_selected_scope = "default"
        self.frontend_status = ""
        self.frontend_overlay_color = None
        self.frontend_window_color = None
        self.html_frontend_url = ""


def apply_view_mode():
    if 'player' not in globals():
        return

    camera.fov = CAMERA["fov"]

    if state.is_player_view == 0:
        player.enabled = True
        camera.parent = player.camera_pivot
        mouse.locked = True
    elif state.is_player_view == 1:
        player.enabled = False
        camera.parent = scene
        camera.position = _serve_machine_camera_position()
        state.return_cam_yaw = 0.0
        state.return_cam_pitch = 0.0
        camera.rotation = (state.return_cam_pitch, state.return_cam_yaw, 0)
        mouse.locked = True
    elif state.is_player_view == 2:
        player.enabled = False
        camera.parent = scene
        camera.position = (0, 2.5, 8.0)
        state.return_cam_yaw = 180.0
        state.return_cam_pitch = 0.0
        camera.rotation = (state.return_cam_pitch, state.return_cam_yaw, 0)
        mouse.locked = True
    elif state.is_player_view == 3:
        player.enabled = False
        camera.parent = scene
        mouse.locked = True


def _max_view_mode():
    return 3 if state.show_returns else 2


def _resolve_simulator_position_global(simulator_position=None):
    gx = SIMULATOR_DEFAULT_POSITION["x"]
    gy = SIMULATOR_DEFAULT_POSITION["y"]
    gz = SIMULATOR_DEFAULT_POSITION["z"]

    if isinstance(simulator_position, dict):
        try:
            if simulator_position.get('x') is not None:
                gx = float(simulator_position.get('x'))
            if simulator_position.get('y') is not None:
                gy = float(simulator_position.get('y'))
            if simulator_position.get('z') is not None:
                gz = float(simulator_position.get('z'))
        except Exception:
            pass

    return {'x': gx, 'y': gy, 'z': gz}


def _simulator_global_to_physics_start(simulator_position=None):
    # Global frame: X(width), Y(depth), Z(height)
    # Physics frame: x(depth), y(width), z(height)
    pos = _resolve_simulator_position_global(simulator_position)
    return pos['y'], pos['x'], pos['z']


def _set_serve_machine_marker_from_physics_start(start_x, start_y, start_z):
    # Ursina mapping: (world_x, world_y, world_z) = (physics_y, physics_z, physics_x)
    if 'serve_machine_marker' in globals() and serve_machine_marker is not None:
        serve_machine_marker.position = (start_y, start_z, start_x)
    if 'camera' in globals() and state.is_player_view == 1:
        camera.position = _serve_machine_camera_position(start_x, start_y, start_z)


def _serve_machine_camera_position(start_x=None, start_y=None, start_z=None):
    if start_x is None or start_y is None or start_z is None:
        if 'serve_machine_marker' in globals() and serve_machine_marker is not None:
            machine_world = serve_machine_marker.position
        else:
            default_start_x, default_start_y, default_start_z = _simulator_global_to_physics_start()
            machine_world = Vec3(default_start_y, default_start_z, default_start_x)
    else:
        machine_world = Vec3(start_y, start_z, start_x)

    return Vec3(machine_world.x, machine_world.y, machine_world.z)


def create_ball(speed_mps, yaw_deg, pitch_deg, interval, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT, precomputed_return=None, allow_runtime_return_solve=True, return_policy=None):
    _set_serve_machine_marker_from_physics_start(start_x, start_y, start_z)
    ball = BallFlight(speed_mps, yaw_deg, pitch_deg, ui, simulator, state, interval, start_x, start_y, start_z)
    state.active_balls.append(ball)
    solver.register_ball(
        ball,
        precomputed_return=precomputed_return,
        allow_runtime_solve=allow_runtime_return_solve,
        return_policy=return_policy,
    )
    if len(state.active_balls) > SERVE_VISUAL["max_active_balls"]:
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
    state.precompute_failures = {}
    state.precompute_index = 0
    state.precompute_hide_info_on_first_serve = False
    state.wait_for_player_home = False


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
    state.wait_for_player_home = False

    solver.clear_entities()
    clear_serve_queue()
    clear_precompute_state()


def enqueue_menu_drills(drills, precomputed_map=None, precompute_locked=False):
    for idx, drill in enumerate(drills):
        params = drill.get('parameters', {})
        simulator_position = drill.get('simulator_position')
        failed_return = None
        if precompute_locked:
            failed_return = (precomputed_map or {}).get(idx) is None
        action_item = {
            'speed': params.get('speed', 30.0),
            'yaw': params.get('yaw', 0.0),
            'pitch': params.get('pitch', 20.0),
            'interval_ms': drill.get('interval', 1000),
            'return_plan': (precomputed_map or {}).get(idx),
            'return_policy': drill.get('simulator_return_policy'),
            'return_failed': failed_return,
            'return_failure_message': drill.get('return_failure_message'),
            'simulator_position': simulator_position,
            # In precompute mode, never do runtime solving during playback.
            'precompute_locked': precompute_locked,
        }
        serve_queue.put(action_item)


def start_menu_precompute(menu_id):
    drills = get_menu_drills_for_simulator(menu_id)
    if drills is None:
        return 0

    clear_serve_queue()
    if not drills:
        return 0

    clear_precompute_state()
    state.precompute_in_progress = True
    state.precompute_menu_id = menu_id
    state.precompute_drills = drills
    ui.update_return_info(f"Precomputing return trajectories... 0/{len(drills)}", visible=True)
    return len(drills)


def queue_menu_actions(menu_id, precompute_returns=False):
    drills = get_menu_drills_for_simulator(menu_id)
    if drills is None:
        return 0

    clear_serve_queue()

    # Immediate queueing path (no staged precompute)
    enqueue_menu_drills(drills, precomputed_map=None, precompute_locked=precompute_returns and state.show_returns)

    return len(drills)


def _return_policy_label(policy):
    if not isinstance(policy, dict):
        return "auto"

    profile = policy.get("profile") or "unknown"
    target = policy.get("target") or {}
    try:
        return f"{profile} to x={float(target.get('x')):.2f}, y={float(target.get('y')):.2f}"
    except (TypeError, ValueError):
        return str(profile)


def _return_failure_message(drill_index, drill, reason="no solution"):
    return f"Return failed: drill {drill_index + 1} {_return_policy_label(drill.get('simulator_return_policy'))} ({reason})"


def _default_return_policy(profile="clear"):
    target_options = _frontend_target_options(profile)
    first_target = next(iter(target_options.values()))
    return {"profile": profile, "target": dict(first_target)}


def _frontend_target_options(profile=None):
    if profile in RETURN_TARGET_PRESETS:
        return RETURN_TARGET_PRESETS[profile]
    return RETURN_TARGET_PRESETS["clear"]


def _target_label_for_policy(policy):
    target = (policy or {}).get("target")
    if not isinstance(target, dict):
        return "unset"

    try:
        tx = float(target.get("x"))
        ty = float(target.get("y"))
    except (TypeError, ValueError):
        return "custom"

    profile = (policy or {}).get("profile")
    for label, preset in _frontend_target_options(profile).items():
        if abs(tx - preset["x"]) < 0.02 and abs(ty - preset["y"]) < 0.02:
            return label
    return f"x={tx:.2f}, y={ty:.2f}"


def _policy_target_allowed(policy):
    target = (policy or {}).get("target")
    profile = (policy or {}).get("profile")
    if not isinstance(target, dict):
        return False

    try:
        tx = float(target.get("x"))
        ty = float(target.get("y"))
    except (TypeError, ValueError):
        return False

    for preset in _frontend_target_options(profile).values():
        if abs(tx - preset["x"]) < 0.02 and abs(ty - preset["y"]) < 0.02:
            return True
    return False


def _selected_menu():
    if not state.frontend_selected_menu_id:
        return None
    return load_menu(state.frontend_selected_menu_id)


def _selected_drills(menu):
    return ((menu.get("payload") or {}).get("menu") or {}).get("drills") or []


def _selected_scope_drill_index(menu):
    if state.frontend_selected_scope == "default":
        return None

    try:
        drill_index = int(state.frontend_selected_scope)
    except (TypeError, ValueError):
        state.frontend_selected_scope = "default"
        return None

    drills = _selected_drills(menu)
    if drill_index < 0 or drill_index >= len(drills):
        state.frontend_selected_scope = "default"
        return None
    return drill_index


def _selected_policy(menu):
    simulator_meta = menu.get("simulator") or {}
    default_policy = simulator_meta.get("default_return_policy")
    if not isinstance(default_policy, dict):
        default_policy = _default_return_policy()

    drill_index = _selected_scope_drill_index(menu)
    if drill_index is None:
        return default_policy

    overrides = simulator_meta.get("drill_overrides") or {}
    override = overrides.get(str(drill_index))
    if isinstance(override, dict) and isinstance(override.get("return_policy"), dict):
        return override.get("return_policy")
    return default_policy


def _queue_items_for_frontend():
    menu_name_by_id = {m["id"]: m["menuName"] for m in stored_menus}
    return [
        {
            "id": menu_id,
            "menuName": menu_name_by_id.get(menu_id, str(menu_id)),
        }
        for menu_id in state.menu_execution_queue
    ]


def refresh_frontend(status=None):
    global stored_menus

    if status is not None:
        state.frontend_status = status

    if stored_menus and not any(m["id"] == state.frontend_selected_menu_id for m in stored_menus):
        state.frontend_selected_menu_id = stored_menus[0]["id"]
        state.frontend_selected_scope = "default"
    elif not stored_menus:
        state.frontend_selected_menu_id = None
        state.frontend_selected_scope = "default"

    menu = _selected_menu()
    if menu:
        _selected_scope_drill_index(menu)


def reload_menus_for_frontend(status=None):
    global stored_menus
    stored_menus = list_menus()
    refresh_frontend(status=status)


def set_frontend_open(opened):
    reload_menus_for_frontend()
    if state.html_frontend_url:
        print(f"[Frontend] Browser frontend: {state.html_frontend_url}")
        webbrowser.open(state.html_frontend_url)


def ensure_manual_mode_for_frontend():
    global stored_menus

    if state.serve_mode == 1:
        return

    state.serve_mode = 1
    state.menu_delete_mode = False
    state.serve_start_cooldown = 0.0
    stored_menus = list_menus()
    ui.hide_menu_list()
    ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                          state.menu_delete_mode, state.show_returns)


def frontend_select_menu(menu_id):
    state.frontend_selected_menu_id = menu_id
    state.frontend_selected_scope = "default"
    refresh_frontend(status=f"Selected menu: {menu_id}")


def frontend_select_scope(scope):
    state.frontend_selected_scope = scope
    refresh_frontend()


def frontend_enqueue_selected():
    menu = _selected_menu()
    if not menu:
        refresh_frontend(status="No menu selected")
        return

    ensure_manual_mode_for_frontend()
    state.menu_execution_queue.append(menu["id"])
    refresh_frontend(status=f"Queued: {menu['menuName']}")


def frontend_delete_selected():
    global stored_menus

    menu = _selected_menu()
    if not menu:
        refresh_frontend(status="No menu selected")
        return

    menu_id = menu["id"]
    menu_name = menu["menuName"]
    if delete_menu(menu_id):
        state.menu_execution_queue = [mid for mid in state.menu_execution_queue if mid != menu_id]
        stored_menus = list_menus()
        refresh_frontend(status=f"Deleted: {menu_name}")
    else:
        refresh_frontend(status=f"Delete failed: {menu_id}")


def frontend_clear_queue():
    state.menu_execution_queue.clear()
    clear_serve_queue()
    state.manual_menu_running = False
    refresh_frontend(status="Queue cleared")


def frontend_update_policy(profile=None, target_label=None):
    menu = _selected_menu()
    if not menu:
        refresh_frontend(status="No menu selected")
        return

    current = dict(_selected_policy(menu) or _default_return_policy())
    current["profile"] = profile or current.get("profile") or "clear"
    if target_label:
        target_options = _frontend_target_options(current["profile"])
        if target_label not in target_options:
            refresh_frontend(status=f"Target is not available for {current['profile']}")
            return
        current["target"] = dict(target_options[target_label])
    elif not _policy_target_allowed(current):
        current["target"] = _default_return_policy(current["profile"])["target"]

    drill_index = _selected_scope_drill_index(menu)
    ok = set_menu_return_policy(menu["id"], current, drill_index=drill_index)
    scope_label = "default" if drill_index is None else f"drill {drill_index + 1}"
    reload_menus_for_frontend(
        status=f"Saved {scope_label} return policy" if ok else "Failed to save return policy"
    )


def html_update_policy(menu_id, scope, profile, target_label):
    global stored_menus

    menu = load_menu(menu_id)
    if not menu:
        state.frontend_status = "No menu selected"
        return

    target_options = _frontend_target_options(profile)
    if target_label not in target_options:
        state.frontend_status = f"Target is not available for {profile}"
        return

    drill_index = None
    if scope != "default":
        try:
            drill_index = int(scope)
        except (TypeError, ValueError):
            state.frontend_status = "Invalid drill scope"
            return

    ok = set_menu_return_policy(
        menu_id,
        {"profile": profile, "target": dict(target_options[target_label])},
        drill_index=drill_index,
    )
    stored_menus = list_menus()
    scope_label = "default" if drill_index is None else f"drill {drill_index + 1}"
    state.frontend_status = f"Saved {scope_label} return policy" if ok else "Failed to save return policy"


def get_html_frontend_state():
    menu_items = []
    for meta in list_menus():
        full = load_menu(meta["id"]) or {}
        payload = full.get("payload") or {}
        drills = (payload.get("menu") or {}).get("drills") or []
        item = dict(meta)
        item["drill_count"] = len(drills) if isinstance(drills, list) else 0
        item["simulator"] = full.get("simulator") or {}
        menu_items.append(item)

    menu_name_by_id = {m["id"]: m["menuName"] for m in menu_items}
    return {
        "menus": menu_items,
        "queue": [
            {"id": menu_id, "menuName": menu_name_by_id.get(menu_id, str(menu_id))}
            for menu_id in state.menu_execution_queue
        ],
        "targets": RETURN_TARGET_PRESETS,
        "manual_menu_running": state.manual_menu_running,
        "precompute_in_progress": state.precompute_in_progress,
        "status": state.frontend_status,
    }


def process_html_frontend_commands():
    global stored_menus

    if "html_frontend_commands" not in globals():
        return

    processed = 0
    while processed < 8:
        try:
            command = html_frontend_commands.get_nowait()
        except queue.Empty:
            break

        action = command.get("action")
        menu_id = command.get("menu_id")

        if action == "enqueue":
            menu = load_menu(menu_id)
            if menu:
                ensure_manual_mode_for_frontend()
                state.menu_execution_queue.append(menu_id)
                state.frontend_status = f"Queued: {menu.get('menuName', menu_id)}"
            else:
                state.frontend_status = "Menu not found"
        elif action == "delete":
            if delete_menu(menu_id):
                state.menu_execution_queue = [mid for mid in state.menu_execution_queue if mid != menu_id]
                stored_menus = list_menus()
                state.frontend_status = f"Deleted: {menu_id}"
            else:
                state.frontend_status = f"Delete failed: {menu_id}"
        elif action == "clear_queue":
            state.menu_execution_queue.clear()
            clear_serve_queue()
            state.manual_menu_running = False
            state.frontend_status = "Queue cleared"
        elif action == "set_policy":
            html_update_policy(
                menu_id=menu_id,
                scope=command.get("scope", "default"),
                profile=command.get("profile", "clear"),
                target_label=command.get("target_label", ""),
            )
        else:
            state.frontend_status = f"Unknown action: {action}"

        processed += 1


def frontend_toggle_returns():
    ensure_manual_mode_for_frontend()
    state.show_returns = not state.show_returns
    solver.set_enabled(state.show_returns)
    if not state.show_returns:
        solver.clear_entities()
        if state.is_player_view == 3:
            state.is_player_view = 2
            apply_view_mode()
    else:
        if state.is_player_view > _max_view_mode():
            state.is_player_view = 2
        apply_view_mode()
    ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                          state.menu_delete_mode, state.show_returns)
    refresh_frontend(status="Dynamic returns: ON" if state.show_returns else "Dynamic returns: OFF")


def run_next_manual_item():
    ensure_manual_mode_for_frontend()

    if state.precompute_in_progress:
        print("[App] Precompute is running. Please wait.")
        refresh_frontend(status="Precompute is running")
        return
    if state.manual_menu_running:
        print("[App] A queued menu is already running")
        refresh_frontend(status="A queued menu is already running")
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
                refresh_frontend(status=f"Precomputing menu: {next_menu_id}")
            else:
                state.manual_menu_running = True
                state.serve_timer = state.serve_interval
                print(f"[App] Executing queued menu {next_menu_id} ({drill_count} actions)")
                refresh_frontend(status=f"Executing menu: {next_menu_id}")
        else:
            print(f"[App] Menu {next_menu_id} has no playable drills")
            refresh_frontend(status=f"No playable drills: {next_menu_id}")
    elif not serve_queue.empty():
        params = serve_queue.get()
        state.current_speed = params['speed']
        state.current_yaw = params['yaw']
        state.current_pitch = params['pitch']
        state.serve_interval = params['interval_ms'] / 1000.0
        start_x, start_y, start_z = _simulator_global_to_physics_start(params.get('simulator_position'))
        create_ball(
            state.current_speed,
            state.current_yaw,
            state.current_pitch,
            state.serve_interval,
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            precomputed_return=params.get('return_plan'),
            allow_runtime_return_solve=not params.get('precompute_locked', False),
            return_policy=params.get('return_policy'),
        )
        if params.get('return_failed') and params.get('return_failure_message'):
            ui.update_return_info(params.get('return_failure_message'), visible=True)
        refresh_frontend(status="Served one queued action")
    else:
        print("[App] No queued menu. Press Esc to open frontend and enqueue a menu.")
        refresh_frontend(status="No queued menu")

def update():
    """主更新迴圈"""
    process_html_frontend_commands()

    if state.is_player_view in (1, 2) or (state.is_player_view == 3 and state.show_returns):
        state.return_cam_yaw += mouse.velocity[0] * RETURN_CAMERA["sensitivity"]
        state.return_cam_pitch -= mouse.velocity[1] * RETURN_CAMERA["sensitivity"]
        state.return_cam_pitch = max(RETURN_CAMERA["pitch_min"], min(RETURN_CAMERA["pitch_max"], state.return_cam_pitch))

        camera.parent = scene
        if state.is_player_view == 1:
            camera.position = _serve_machine_camera_position()
        elif state.is_player_view == 3:
            rp = solver.return_player.position
            camera.position = (rp.x, RETURN_CAMERA["height"], rp.z)
        camera.rotation = (state.return_cam_pitch, state.return_cam_yaw, 0)

    if state.precompute_in_progress:
        total = len(state.precompute_drills)
        batch_size = 1

        for _ in range(batch_size):
            if state.precompute_index >= total:
                break

            drill = state.precompute_drills[state.precompute_index]
            params = drill.get('parameters', {})
            start_x, start_y, start_z = _simulator_global_to_physics_start(drill.get('simulator_position'))
            result = solver.precompute_return_for_serve(
                speed_mps=params.get('speed', 30.0),
                yaw_deg=params.get('yaw', 0.0),
                pitch_deg=params.get('pitch', 20.0),
                start_x=start_x,
                start_y=start_y,
                start_z=start_z,
                return_policy=drill.get('simulator_return_policy'),
            )
            state.precompute_returns[state.precompute_index] = result
            if result is None:
                message = _return_failure_message(state.precompute_index, drill)
                state.precompute_failures[state.precompute_index] = message
                drill['return_failure_message'] = message
                ui.update_return_info(message, visible=True)
            state.precompute_index += 1

        if not state.precompute_failures:
            ui.update_return_info(f"Precomputing return trajectories... {state.precompute_index}/{total}", visible=True)

        if state.precompute_index >= total:
            valid_count = sum(1 for v in state.precompute_returns.values() if v is not None)
            no_solution_count = total - valid_count
            failure_text = ""
            if state.precompute_failures:
                first_failure = next(iter(state.precompute_failures.values()))
                failure_text = f"\n{first_failure}"
            ui.update_return_info(
                f"Precompute done: {valid_count}/{total} ready, {no_solution_count} skipped{failure_text}",
                visible=True,
            )
            finished_menu_id = state.precompute_menu_id
            enqueue_menu_drills(
                state.precompute_drills,
                precomputed_map=state.precompute_returns,
                precompute_locked=True,
            )
            state.manual_menu_running = True
            state.serve_timer = state.serve_interval
            state.serve_start_cooldown = RETURN_RUNTIME["precompute_serve_warmup"]
            print(f"[App] Executing queued menu {finished_menu_id} ({total} actions)")
            clear_precompute_state()
            state.precompute_hide_info_on_first_serve = True

    # Process queue in auto mode or when a manual queued menu is running.
    if state.serve_mode == 0 or state.manual_menu_running:
        if state.serve_start_cooldown > 0.0:
            state.serve_start_cooldown = max(0.0, state.serve_start_cooldown - time.dt)

        hold_for_warmup = state.serve_start_cooldown > 0.0
        active_serve_in_flight = any(not b.finished for b in state.active_balls)
        strict_player_return_gate = state.manual_menu_running and state.show_returns and RETURN_PLAYER["block_on_recover"]

        if strict_player_return_gate:
            # Strict rally sequence in return mode:
            # serve -> wait return cycle -> player back home -> next serve.
            if state.wait_for_player_home:
                if solver.consume_player_returned_home_pulse() and not hold_for_warmup:
                    state.wait_for_player_home = False
                    if serve_queue.empty():
                        state.serve_timer = 0.0
                        state.serve_interval = 0.5
                        if state.manual_menu_running:
                            state.manual_menu_running = False
                            print("[App] Manual queued menu finished")
                    else:
                        state.serve_timer = state.serve_interval
            elif not active_serve_in_flight:
                state.serve_timer += time.dt
        else:
            state.serve_timer += time.dt

        max_carry = max(state.serve_interval * 2.0, 0.25)
        if state.serve_timer > max_carry:
            state.serve_timer = max_carry

        serves_spawned = 0
        max_serves_per_frame = 1

        while (not hold_for_warmup) and state.serve_timer >= state.serve_interval and serves_spawned < max_serves_per_frame:
            try:
                if strict_player_return_gate:
                    if active_serve_in_flight or state.wait_for_player_home:
                        break

                params = serve_queue.get_nowait()
                state.current_speed = params['speed']
                state.current_yaw = params['yaw']
                state.current_pitch = params['pitch']
                state.serve_timer -= state.serve_interval
                state.serve_interval = params['interval_ms'] / 1000.0  # Convert ms to seconds
                start_x, start_y, start_z = _simulator_global_to_physics_start(params.get('simulator_position'))

                create_ball(
                    state.current_speed,
                    state.current_yaw,
                    state.current_pitch,
                    state.serve_interval,
                    start_x=start_x,
                    start_y=start_y,
                    start_z=start_z,
                    precomputed_return=params.get('return_plan'),
                    allow_runtime_return_solve=not params.get('precompute_locked', False),
                    return_policy=params.get('return_policy'),
                )
                if params.get('return_failed') and params.get('return_failure_message'):
                    ui.update_return_info(params.get('return_failure_message'), visible=True)
                if state.precompute_hide_info_on_first_serve:
                    if not params.get('return_failed'):
                        ui.hide_return_info()
                    state.precompute_hide_info_on_first_serve = False

                if strict_player_return_gate:
                    # If this serve has a planned return, block until player reaches home.
                    # If no solution exists, fallback is menu interval timing.
                    state.wait_for_player_home = params.get('return_plan') is not None

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
        ball.update()

    # 更新回球動畫（單一回球播放）
    solver.update_animation()


def input(key):
    """按鍵處理"""
    global stored_menus

    if key == 'escape':
        set_frontend_open(True)
        return

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
        clear_precompute_state()
        solver.set_enabled(False)
        solver.clear_entities()
        clear_serve_queue()
        ui.hide_menu_list()
        refresh_frontend(status="Reset complete")
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                              state.menu_delete_mode, state.show_returns)

    if key == 't':
        state.show_trajectory = not state.show_trajectory
        for ball in state.active_balls:
            for e in ball.trail_entities:
                e.visible = state.show_trajectory
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns)

    if key == 'v':
        state.is_player_view = (state.is_player_view + 1) % (_max_view_mode() + 1)
        if state.is_player_view == 3:
            state.return_cam_yaw = camera.rotation_y
            state.return_cam_pitch = camera.rotation_x
        apply_view_mode()
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                      state.menu_delete_mode, state.show_returns)

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

        if state.is_player_view > _max_view_mode():
            state.is_player_view = 2
            apply_view_mode()
        
        if state.serve_mode == 1:  # Manual mode
            stored_menus = list_menus()
            ui.hide_menu_list()
        else:
            ui.hide_menu_list()
        refresh_frontend()
        
        ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                              state.menu_delete_mode, state.show_returns)

    if key == 'enter':
        if state.serve_mode == 1:  # Manual mode
            run_next_manual_item()

    if key == 'b':
        if state.serve_mode != 1:
            print("[App] Dynamic returns are available in MANUAL mode only.")
            if state.show_returns:
                state.show_returns = False
                solver.set_enabled(False)
                solver.clear_entities()
            ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                          state.menu_delete_mode, state.show_returns)
            refresh_frontend(status="Switch to manual mode for dynamic returns")
            return

        frontend_toggle_returns()

if __name__ == '__main__':
    state = GameState()

    # App setup
    app = Ursina(icon='', size=(1280, 720))
    Entity.default_shader = lit_with_shadows_shader

    # Create scene
    ui = UIManager()
    court = Court()
    serve_machine_marker = Entity(
        model='cube',
        position=(
            SIMULATOR_DEFAULT_POSITION["x"],
            SIMULATOR_DEFAULT_POSITION["z"],
            SIMULATOR_DEFAULT_POSITION["y"],
        ),
        color=color.black,
        # Manual tune point for marker size:
        # change this scale tuple directly to resize the box.
        scale=(0.28, 0.20, 0.28),
        shader=unlit_shader,
    )
    solver = ReturnSolver(serve_machine_marker, ui, state)

    ui.update_instructions(state.show_trajectory, state.is_player_view, state.serve_mode,
                          state.menu_delete_mode, state.show_returns)

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
    if stored_menus:
        state.frontend_selected_menu_id = stored_menus[0]["id"]
    refresh_frontend(status=f"Loaded {len(stored_menus)} menus")

    html_frontend_commands = queue.Queue()
    html_frontend = HtmlMenuFrontendServer(get_html_frontend_state, html_frontend_commands)
    state.html_frontend_url = html_frontend.start()
    print(f"[Frontend] HTML frontend ready: {state.html_frontend_url}")

    # MQTT setup
    serve_queue = queue.Queue()
    simulator = MQTTSimulator(command_topic='Badminton_simulator', status_topic='abcde12345', serve_queue=serve_queue)
    mqtt_thread = threading.Thread(target=simulator.start, daemon=True)
    mqtt_thread.start()

    # Run
    app.run()
