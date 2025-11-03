from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader
from math import cos, sin, radians, sqrt, inf, atan2, degrees
import threading
import queue
import paho.mqtt.client as mqtt
import json
import time

# ----- 1) 尺寸常數 (Official Court Dimensions) -----
# See: https://en.wikipedia.org/wiki/Badminton_court
COURT_LEN = 13.4                # m
COURT_W   = 6.1                 # m (Doubles width)
HALF_W    = COURT_W / 2
NET_X     = COURT_LEN / 2       # 6.7m
NET_H     = 1.524               # m (Center height)

SINGLES_W = 5.18                # m
SINGLES_HALF_W = SINGLES_W / 2  # 2.59m

SHORT_SERVICE_DIST = 1.98       # m (from net)
LONG_SERVICE_DOUBLES_DIST = 0.76 # m (from baseline)

# Z-coordinates for horizontal lines
Z_BASELINE_NEAR = 0.0
Z_BASELINE_FAR = COURT_LEN
Z_NET = NET_X
Z_SHORT_SERVICE_NEAR = NET_X - SHORT_SERVICE_DIST # 4.72 m
Z_SHORT_SERVICE_FAR  = NET_X + SHORT_SERVICE_DIST # 8.68 m
Z_LONG_SERVICE_DOUBLES_NEAR = LONG_SERVICE_DOUBLES_DIST    # 0.76 m
Z_LONG_SERVICE_DOUBLES_FAR  = COURT_LEN - LONG_SERVICE_DOUBLES_DIST # 12.64 m

# Line constants
LINE_THICKNESS = 0.04           # 40mm
LINE_Y_OFFSET  = 0.02          # To prevent z-fighting (flickering)

# ----- Trail sampling (reduce lag) -----
TRAIL_DT          = 0.01       # larger physics step for preview

# ----- 2) 物理模擬參數 (Physics) -----
G = 9.81
DRAG_K = 0.2           # Your drag coefficient
RELEASE_HEIGHT = 1.2    # Your release height

# Standalone trajectory simulation (MODIFIED: Reactive refinement; no predictive adaptive dt)
def simulate_trajectory(speed_mps=23.0, yaw_deg=6.0, pitch_deg=20.0,
                        drag_k=DRAG_K,
                        dt_base=0.01, dt_fine=0.001,
                        refine_net=False, refine_heights=False,
                        refine_heights_list=[0.7, 1.8, 2.5],
                        max_t=6.0, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):

    yaw   = radians(yaw_deg)
    pitch = radians(pitch_deg)

    vx = speed_mps * cos(pitch) * cos(yaw)
    vy = speed_mps * cos(pitch) * sin(yaw)
    vz = speed_mps * sin(pitch)

    x, y, z = start_x, start_y, start_z
    t = 0.0

    pts   = []  # Always store every point for pre-computation
    apex  = {"x": x, "y": y, "z": z, "t": t}
    cross_net = None
    landing   = None
    prev = None
    hit_net = False
    hit_points = {} if refine_heights else None  # Dict to store hit points {height: {'x': hit_x, 'y': hit_y}}

    def lerp(a, b, w): return a + w * (b - a)

    while t <= max_t and z >= 0.0:
        # ----- store every point -----
        pts.append((x, y, z, vx, vy, vz, t))

        if z > apex["z"]:
            apex = {"x": x, "y": y, "z": z, "t": t}

        prev = (x, y, z, vx, vy, vz, t)

        # ----- physics (always coarse dt) -----
        vmag = sqrt(vx*vx + vy*vy + vz*vz)
        ax = -drag_k * vmag * vx
        ay = -drag_k * vmag * vy
        az = -G - drag_k * vmag * vz

        vx += ax * dt_base
        vy += ay * dt_base
        vz += az * dt_base
        x  += vx * dt_base
        y  += vy * dt_base
        z  += vz * dt_base
        t  += dt_base

        # net crossing
        w_net = None
        if prev and (prev[0] - NET_X) * (x - NET_X) <= 0 and x != prev[0]:
            w_net = (NET_X - prev[0]) / (x - prev[0])
            if refine_net:
                # Reactive refinement: Subdivide the step for accuracy
                temp_x, temp_y, temp_z = prev[0], prev[1], prev[2]
                temp_vx, temp_vy, temp_vz = prev[3], prev[4], prev[5]
                temp_t = prev[6]
                fine_prev = (temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t)
                crossed = False
                while not crossed and temp_t < prev[6] + dt_base:
                    vmag = sqrt(temp_vx**2 + temp_vy**2 + temp_vz**2)
                    ax = -drag_k * vmag * temp_vx
                    ay = -drag_k * vmag * temp_vy
                    az = -G - drag_k * vmag * temp_vz
                    temp_vx += ax * dt_fine
                    temp_vy += ay * dt_fine
                    temp_vz += az * dt_fine
                    temp_x += temp_vx * dt_fine
                    temp_y += temp_vy * dt_fine
                    temp_z += temp_vz * dt_fine
                    temp_t += dt_fine
                    if (fine_prev[0] - NET_X) * (temp_x - NET_X) <= 0 and temp_x != fine_prev[0]:
                        w_net = (NET_X - fine_prev[0]) / (temp_x - fine_prev[0])
                        cross_z = lerp(fine_prev[2], temp_z, w_net)
                        cross_y = lerp(fine_prev[1], temp_y, w_net)
                        cross_t = lerp(fine_prev[6], temp_t, w_net)
                        clearance = cross_z - NET_H
                        cross_net = {
                            "x": NET_X,
                            "y": cross_y,
                            "z": cross_z,
                            "t": cross_t,
                            "clearance": clearance
                        }
                        if clearance <= 0 and cross_z > 0 and not hit_net:
                            hit_net = True
                            x = NET_X
                            y = cross_y
                            z = min(cross_z, NET_H)
                            vx = 0
                            vy = 0
                            t = cross_t
                            # vz remains temp_vz
                        crossed = True
                    fine_prev = (temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t)
                # Update main state to fine end for better accuracy post-crossing
                x, y, z, vx, vy, vz, t = temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t
            else:
                cross_z = lerp(prev[2], z, w_net)
                clearance = cross_z - NET_H
                cross_net = {
                    "x": NET_X,
                    "y": lerp(prev[1], y, w_net),
                    "z": cross_z,
                    "t": lerp(prev[6], t, w_net),
                    "clearance": clearance
                }
                if clearance <= 0 and cross_z > 0 and not hit_net:
                    hit_net = True
                    x = NET_X
                    y = lerp(prev[1], y, w_net)
                    z = min(cross_z, NET_H)
                    vx = 0
                    vy = 0
                    # vz keeps

        # Compute hit points at heights during descent (if flag set)
        if refine_heights and prev and vz < 0:
            for h in refine_heights_list:
                if h not in hit_points and prev[2] >= h >= z:  # Crossed h downward
                    w_h = (h - prev[2]) / (z - prev[2])
                    if refine_heights:
                        # Reactive refinement: Subdivide the step for accuracy
                        temp_x, temp_y, temp_z = prev[0], prev[1], prev[2]
                        temp_vx, temp_vy, temp_vz = prev[3], prev[4], prev[5]
                        temp_t = prev[6]
                        fine_prev = (temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t)
                        crossed_h = False
                        while not crossed_h and temp_t < prev[6] + dt_base:
                            vmag = sqrt(temp_vx**2 + temp_vy**2 + temp_vz**2)
                            ax = -drag_k * vmag * temp_vx
                            ay = -drag_k * vmag * temp_vy
                            az = -G - drag_k * vmag * temp_vz
                            temp_vx += ax * dt_fine
                            temp_vy += ay * dt_fine
                            temp_vz += az * dt_fine
                            temp_x += temp_vx * dt_fine
                            temp_y += temp_vy * dt_fine
                            temp_z += temp_vz * dt_fine
                            temp_t += dt_fine
                            if fine_prev[2] >= h >= temp_z:
                                w_h = (h - fine_prev[2]) / (temp_z - fine_prev[2])
                                hit_x = lerp(fine_prev[0], temp_x, w_h)
                                hit_y = lerp(fine_prev[1], temp_y, w_h)
                                # Check bounds
                                if hit_x > NET_X and abs(hit_y) <= HALF_W:
                                    hit_points[h] = {'x': hit_x, 'y': hit_y}
                                crossed_h = True
                            fine_prev = (temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t)
                        # Update main state to fine end for better accuracy post-crossing
                        x, y, z, vx, vy, vz, t = temp_x, temp_y, temp_z, temp_vx, temp_vy, temp_vz, temp_t
                    else:
                        hit_x = lerp(prev[0], x, w_h)
                        hit_y = lerp(prev[1], y, w_h)
                        # Check bounds
                        if hit_x > NET_X and abs(hit_y) <= HALF_W:
                            hit_points[h] = {'x': hit_x, 'y': hit_y}

        # ground landing
        w_land = None
        if prev and prev[2] >= 0.0 and z < 0.0 and z != prev[2]:
            w_land = (0.0 - prev[2]) / (z - prev[2])
        if w_land is not None and 0 <= w_land <= 1:
            landing = {
                "x": lerp(prev[0], x, w_land),
                "y": lerp(prev[1], y, w_land),
                "z": 0.0,
                "t": lerp(prev[6], t, w_land)
            }
            break

    if landing:
        pts.append((landing["x"], landing["y"], landing["z"], vx, vy, vz, landing["t"]))

    result = {"points": pts, "apex": apex, "cross_net": cross_net, "landing": landing, "hit_net": hit_net}
    if refine_heights:
        result["hit_points"] = hit_points
    return result

# Function to find speed for target landing x
def find_fastest_clearing_shot(
        start_x, target_x, start_z,
        yaw_deg, start_y=0.0,
        tol=0.1,
        max_iter_pitch=10,
        max_iter_speed=10):
    """
    Returns (speed, pitch, sim) for the *fastest* speed that:
      • lands within tol of target_x
      • clears the net (clearance > 0)
      • uses the *lowest* possible pitch for that speed
    """
    yaw = radians(yaw_deg)
    max_speed = 100.0
    min_speed = 0.0
    high_pitch = 90.0
    low_pitch = -90.0
    
    best_speed = None
    best_pitch = None
    
    for _ in range(max_iter_pitch):
        if high_pitch - low_pitch < 0.01: break
        pitch = (low_pitch + high_pitch) / 2.0
 
        low_speed  = min_speed
        high_speed = max_speed
        found = False
        local_best_speed = -inf

        for _ in range(max_iter_speed):
            if high_speed - low_speed < 0.01: break
            mid_speed = (low_speed + high_speed) / 2.0

            sim = simulate_trajectory(
                mid_speed, yaw_deg, pitch,
                start_x=start_x, start_y=start_y, start_z=start_z,
                refine_net=True, refine_heights=False,
            )
            land = sim.get('landing')
            net  = sim.get('cross_net')

            if not land or land['x'] < 0:
                high_speed = mid_speed  # Too high, never lands
                continue
            
            clearance = net['clearance'] if net else 0.0
            # print(mid_speed, pitch, land['x'], target_x, clearance)
            if clearance <= 0.05:  # > 5 cm above net
                low_speed = mid_speed   # need more speed
                continue

            land_err = abs(land['x'] - target_x)
            

            if land_err > tol:
                if land['x'] < target_x:
                    high_speed = mid_speed  # Overshot → reduce speed
                else:
                    low_speed = mid_speed   # Undershot → increase speed
                continue
            else:
                found = True
                low_speed = mid_speed
                local_best_speed = mid_speed
        if found:
            best_speed = local_best_speed
            best_pitch = pitch
            high_pitch = pitch
        else:
            low_pitch = pitch

        # ----- If this pitch gave a valid speed, compare with global best -----
    if best_pitch is not None and best_speed is not None:
        # Re-simulate at the best speed for this pitch (use refine for accuracy)
        sim = simulate_trajectory(
            best_speed, yaw_deg, best_pitch,
            start_x=start_x, start_y=start_y, start_z=start_z,
            dt_base=0.01,
            refine_net=True, refine_heights=False,
        )
        clear = sim['cross_net']['clearance']
        # print(f"speed={best_speed} m/s, pitch={best_pitch}°, land={sim['landing']['x']}m, " +
        #       f"Δx={abs(sim['landing']['x']-target_x)}m, net={clear}m")
        return best_speed, best_pitch, sim
    return None, None, None

# NEW: Global for pre-computed trajectory points
trajectory_points = []

# Current launch parameters (updated via MQTT)
current_speed = 30.0        # m/s
current_yaw = 3.0           # degrees (left/right)
current_pitch = 22.0        # degrees (up/down)

# Additional globals for new features
show_trajectory = True
serve_trails = []  # Separate for serve
return_trails = []  # Separate for returns
landing_markers = []
landings = []
is_player_view = True
auto_serve = True
last_landing = None
show_returns = False
current_return_view = '0'  # 'all' or 1-9
return_entities = []
return_options = []
is_return_flight = False
solutions_ready = False
trail_timer = 0.0
trail_interval = 0.001  # seconds between trail dots for serve/animation

# NEW: Simulation time for real-time playback
simulation_time = 0.0

# Define return presets
heights = [0.7, 1.8, 2.5]
locations_1 = ['left', 'mid', 'right']
locations_2 = ['front', 'mid', 'back']
targets_x = [5.90, 3.35, 0.76]  # front, mid, back on machine side
target_ys = [-(SINGLES_HALF_W - 0.5), 0, (SINGLES_HALF_W - 0.5)]  # left, mid, right, inset by 0.5m
colors = [color.cyan, color.lime, color.orange]

return_presets = []
for i in range(3):
    for j in range(3):
        return_presets.append({
            "name": f"{heights[i]}m {locations_1[j]}-{locations_2[i]}",
            "height": heights[i],
            "target_x": targets_x[i],
            "target_y": target_ys[j],
            "color": colors[i],
            "solution": None
        })

def clear_return_entities():
    global return_info_text
    return_info_text.visible = False
    for e in return_entities:
        destroy(e)
    return_entities.clear()

def compute_return_solutions():
    """Compute all return solutions ONCE after a serve lands."""
    global return_presets, last_landing, current_yaw
    if last_landing is None:
        return

    # Simulate the serve trajectory with refinements
    serve_sim = simulate_trajectory(
        speed_mps=current_speed,
        yaw_deg=current_yaw,
        pitch_deg=current_pitch,
        refine_net=True, refine_heights=True,
        refine_heights_list=heights,
        max_t=6.0,
        start_x=0.0,
        start_y=0.0,
        start_z=RELEASE_HEIGHT,
    )
    apex_z = serve_sim['apex']['z']
    hit_points = serve_sim.get('hit_points', {})

    start_x = last_landing['x']
    for preset in return_presets:
        if preset['solution'] is not None:
            continue  # Already computed

        h = preset['height']
        if h > apex_z:
            # print(f"[SKIPPED] {preset['name']}: Height {h}m > apex {apex_z:.2f}m")
            preset['solution'] = None
            continue

        hit_point = hit_points.get(h)
        if not hit_point:
            print(f"[SKIPPED] {preset['name']}: No valid hit point at {h}m (out of bounds or before net)")
            preset['solution'] = None
            continue

        # Compute yaw_deg based on target
        delta_x = preset['target_x'] - hit_point['x']
        delta_y = preset['target_y'] - hit_point['y']
        yaw_deg = degrees(atan2(delta_y, delta_x))

        # Compute solution using hit x/y
        speed, pitch, sim = find_fastest_clearing_shot(
            start_x=hit_point['x'],
            target_x=preset['target_x'],
            start_z=h,
            yaw_deg=yaw_deg,
            start_y=hit_point['y']  # NEW: Pass actual start_y
        )
        if speed:
            solution = {'speed': speed, 'pitch': pitch, 'sim': sim, 'hit_point': hit_point, 'yaw_deg': yaw_deg}
            preset['solution'] = solution
            # print(f"[SOLVED] {preset['name']}: {speed:.1f}m/s, {pitch:.1f}°, land={sim['landing']['x']:.2f}m" +
            #       f" Δx={abs(sim['landing']['x']-preset['target_x'])}m, net={sim['cross_net']['clearance']:.2f}m" +
            #       f" (hit at x={hit_point['x']:.2f}, y={hit_point['y']:.2f}, yaw={yaw_deg:.1f}°)")
        else:
            preset['solution'] = None
            # print(f"[NO SOLUTION] {preset['name']}")

def display_return_view(view_id):
    """Show only the selected return (or all). Clears previous."""
    global return_entities, return_options, current_return_view, return_info_text, is_return_flight, trail_timer, simulation_time, trajectory_points

    clear_return_entities()
    return_info_text.visible = True
    current_return_view = view_id
    return_options = []

    if last_landing is None:
        return_info_text.text = "No landing yet."
        return

    target_preset = None
    if view_id == '0':
        return_info_text.text = "Showing ALL return options"
    else:
        idx = int(view_id) - 1
        if 0 <= idx < len(return_presets):
            target_preset = return_presets[idx]
            return_info_text.text = f"Return {idx+1}: {target_preset['name']}\n" \
                                   f"{'No solution' if not target_preset['solution'] else ''}"
        else:
            return_info_text.text = "Invalid return ID"
            return

    if view_id == '0':
        # Draw static trails for all
        for e in return_trails:
            destroy(e)
        return_trails.clear()
        presets_to_draw = return_presets
        for i, preset in enumerate(presets_to_draw):
            sol = preset['solution']
            if not sol:
                continue

            sim = sol['sim']
            land = sim['landing']
            if not land:
                continue

            # Trail
            trail_color = color.rgba(preset['color'].r, preset['color'].g, preset['color'].b, 0.6)
            for p in sim['points']:
                trail = Entity(model='sphere', scale=0.02, color=trail_color,
                               position=(p[1], p[2], p[0]))
                return_entities.append(trail)

            # Landing marker
            marker = Entity(model='sphere', scale=0.15, color=preset['color'],
                            position=(land['y'], 0.05, land['x']))
            return_entities.append(marker)

            # Label
            label = Text(text=str(i+1) if view_id == '0' else "", scale=2,
                         position=(0, 0.2, 0), parent=marker, billboard=True)
            return_entities.append(label)

            return_options.append((i, preset))
    else:
        # Animate single return (MODIFIED: Use pre-computed points for animation)
        if target_preset:
            sol = target_preset['solution']
            if sol:
                is_return_flight = True
                hit_point = sol['hit_point']
                h = target_preset['height']
                speed = sol['speed']
                yaw_deg = sol['yaw_deg']
                pitch = sol['pitch']
                for e in return_trails:
                    destroy(e)
                return_trails.clear()
                trail_timer = 0.0  # Reset timer
                simulation_time = 0.0  # Reset simulation time
                # Pre-compute trajectory for this return
                sim = simulate_trajectory(speed, yaw_deg, pitch, start_x=hit_point['x'], start_y=hit_point['y'], start_z=h)
                trajectory_points = sim['points']  # Store pre-computed points
                ball.position = (hit_point['y'], h, hit_point['x'])  # Start position (Ursina: y, z, x -> x, y, z)
                ball.color = target_preset['color']  # Color ball for return

def reset_simulation(speed_mps, yaw_deg, pitch_deg, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):
    """(Re)initializes the ball using pre-computed trajectory."""
    global trajectory_points, simulation_time, trail_timer
    
    # Pre-compute the full trajectory
    sim = simulate_trajectory(speed_mps, yaw_deg, pitch_deg, start_x=start_x, start_y=start_y, start_z=start_z)
    trajectory_points = sim['points']
    
    # Set initial position (Ursina: user's y, z, x)
    ball.position = (start_y, start_z, start_x)
    ball.color = color.yellow
    
    simulation_time = 0.0
    trail_timer = 0.0
    print(f"Simulation Started with speed={speed_mps}, yaw={yaw_deg}, pitch={pitch_deg} from ({start_x}, {start_y}, {start_z})")

# ----- 3) Ursina 3D App Setup -----
app = Ursina()
Entity.default_shader = lit_with_shadows_shader

# --- Create the 3D Scene ---
ground = Entity(model='plane', collider='box', scale=64, texture='grass', texture_scale=(4,4))
# Create the court floor (using quad + rotation)
court = Entity(
    model='quad', 
    scale=(COURT_W, COURT_LEN),
    color=color.rgb(40/255, 110/255, 40/255), # Dark green
    rotation_x=90,                # Make it flat on the ground
    position=(0, 0.01, COURT_LEN / 2), # Center it
    collider='box'
)

# Create the net
net = Entity(
    model='quad', 
    color=color.rgba(100/255, 100/255, 100/255, 150/255),
    # texture=net_tex,
    scale=(COURT_W, NET_H),
    position=(0, NET_H / 2, NET_X),
    double_sided=True
)

# ----- 4) Line Drawing Helpers -----
def add_line_x_full(z_pos):
    """Draws a horizontal line (X-axis) across the full court width."""
    Entity(
        model='quad', color=color.white,
        scale=(COURT_W, LINE_THICKNESS),
        position=(0, LINE_Y_OFFSET, z_pos),
        rotation_x=90
    )

def add_line_z_full(x_pos):
    """Draws a vertical line (Z-axis) down the full court length."""
    Entity(
        model='quad', color=color.white,
        scale=(LINE_THICKNESS, COURT_LEN),
        position=(x_pos, LINE_Y_OFFSET, COURT_LEN / 2),
        rotation_x=90
    )

def add_line_z_segment(x_pos, z_start, z_end):
    """Draws a vertical line (Z-axis) between two z-points."""
    length = abs(z_end - z_start)
    center_z = (z_start + z_end) / 2
    Entity(
        model='quad', color=color.white,
        scale=(LINE_THICKNESS, length),
        position=(x_pos, LINE_Y_OFFSET, center_z),
        rotation_x=90
    )

# --- Draw All Court Lines ---
# 1. Baselines (Horizontal, full width)
add_line_x_full(Z_BASELINE_NEAR)
add_line_x_full(Z_BASELINE_FAR)

# 2. Doubles Sidelines (Vertical, full length)
add_line_z_full(-HALF_W)
add_line_z_full(HALF_W)

# 3. Singles Sidelines (Vertical, full length)
add_line_z_full(-SINGLES_HALF_W)
add_line_z_full(SINGLES_HALF_W)

# 4. Short Service Lines (Horizontal, full width)
add_line_x_full(Z_SHORT_SERVICE_NEAR)
add_line_x_full(Z_SHORT_SERVICE_FAR)

# 5. Long Service Lines for Doubles (Horizontal, full width)
add_line_x_full(Z_LONG_SERVICE_DOUBLES_NEAR)
add_line_x_full(Z_LONG_SERVICE_DOUBLES_FAR)

# 6. Center Lines (Vertical, partial)
#    (From short service line to baseline)
add_line_z_segment(0, Z_SHORT_SERVICE_NEAR, Z_BASELINE_NEAR)
add_line_z_segment(0, Z_SHORT_SERVICE_FAR, Z_BASELINE_FAR)


# ----- 5) Entities & Player -----
# Create the ball
ball = Entity(model='sphere', position=(0, RELEASE_HEIGHT, 0), color=color.yellow, scale=0.15)

# Add landing text UI
landing_text = Text(position=window.top_left + Vec2(0.05, -0.05), text='', scale=1.0, background=True)

# Add FirstPersonController
player = FirstPersonController(
    model='cube',
    collider='box',
    position=(0, 1, -2),  # Start 1 unit in the air to land on ground
    origin_y=-0.5,
    jump_height=0,
    speed=8,
    color=color.orange
)
# Set the specific collider size *after* creation
player.collider = BoxCollider(player, center=Vec3(0,1,0), size=Vec3(1,2,1))
player.visible = False


def update_landing_text():
    txt = "Landings:\n"
    for i, ld in enumerate(landings):
        pos = ld['pos']
        params = ld['params']
        txt += f"{i+1}: Pos ({pos[0]:.2f}, {pos[1]:.2f}), Speed={params[0]}, Yaw={params[1]}, Pitch={params[2]}\n"
    landing_text.text = txt

def get_instructions_text():
    traj = "ON / off" if show_trajectory else "on / OFF"
    view_mode = "PLAYER / fixed" if is_player_view else "player / FIXED"
    serve_mode = "AUTO / manual" if auto_serve else "auto / MANUAL"
    returns_mode = "ON / off" if show_returns else "on / OFF"
    view = "ALL" if current_return_view == '0' else (str(current_return_view) if isinstance(current_return_view, int) else "—")
    return f"""Q: Quit
R: Reset
T: Toggle Trajectory ({traj})
V: Toggle View ({view_mode})
M: Toggle Serve Mode ({serve_mode})
B: Toggle Returns ({returns_mode})
0-9: Show & Play Return ({view})
Enter: Serve (Manual)"""

instructions_text = Text(get_instructions_text(), position=(0.85, -0.2), origin=(0.5, 0), scale=1.0)
return_info_text = Text("", position=(0.4, 0.4), scale=1.2, color=color.white, visible=False)

def update_instructions():
    instructions_text.text = get_instructions_text()

# ----- 6) The Animation Loop (MODIFIED: Use pre-computed points with real-time interpolation) -----
def update():
    global current_speed, current_yaw, current_pitch
    global last_landing, is_return_flight, show_returns, current_return_view, solutions_ready, trail_timer, simulation_time
    global trajectory_points

    if not trajectory_points:  # No active simulation
        if auto_serve:
            try:
                params = serve_queue.get_nowait()
                current_speed = params['speed']
                current_yaw = params['yaw']
                current_pitch = params['pitch']
                reset_simulation(current_speed, current_yaw, current_pitch)
                # Reset everything on new serve
                last_landing = None
                solutions_ready = False
                for p in return_presets:
                    p['solution'] = None
                clear_return_entities()
                show_returns = False
            except queue.Empty:
                pass
        return

    # Advance simulation time
    simulation_time += time.dt

    # Find the current segment in pre-computed points
    for i in range(len(trajectory_points) - 1):
        curr_t = trajectory_points[i][6]
        next_t = trajectory_points[i + 1][6]
        if curr_t <= simulation_time < next_t:
            frac = (simulation_time - curr_t) / (next_t - curr_t)
            curr_pos = trajectory_points[i]
            next_pos = trajectory_points[i + 1]
            # Lerp position (x, y, z)
            x = curr_pos[0] + frac * (next_pos[0] - curr_pos[0])
            y = curr_pos[1] + frac * (next_pos[1] - curr_pos[1])
            z = curr_pos[2] + frac * (next_pos[2] - curr_pos[2])
            # Set ball position (Ursina: y, z, x)
            ball.position = (y, z, x)
            break
    else:
        # Beyond last point: Set to final landing and stop
        final_pos = trajectory_points[-1]
        ball.position = (final_pos[1], final_pos[2], final_pos[0])
        trajectory_points = []  # End simulation

    if show_trajectory:
        trail_timer += time.dt
        if trail_timer >= trail_interval:
            trail = Entity(model='sphere', color=color.red, scale=0.03, position=ball.position)
            if is_return_flight:
                return_trails.append(trail)
            else:
                serve_trails.append(trail)
            trail_timer -= trail_interval

    # === ONLY SERVE (not return) triggers landing logic ===
    if not trajectory_points and not is_return_flight:  # Simulation ended
        ball.color = color.red
        print(f"Landed at (x={ball.z:.2f}, y={ball.x:.2f})")  # Ursina z = user's x, x = user's y

        last_landing = {'x': ball.z, 'y': ball.x}
        landings.append({'pos': (ball.z, ball.x), 'params': (current_speed, current_yaw, current_pitch)})
        update_landing_text()

        marker = Entity(model='sphere', scale=0.1, color=color.blue, position=(ball.x, 0.05, ball.z))
        landing_markers.append(marker)

        simulator.client.publish(simulator.status_topic, "serve=done")

        # === COMPUTE RETURN SOLUTIONS ONCE ===
        if not solutions_ready:
            compute_return_solutions()
            solutions_ready = True

        # Auto-show if enabled
        if show_returns:
            display_return_view(current_return_view)

    # === RETURN FLIGHT: Just animate ===
    elif not trajectory_points and is_return_flight:
        ball.color = color.red
        is_return_flight = False
        # DO NOT compute solutions here!

def input(key):
    global show_trajectory, is_player_view, auto_serve, show_returns, current_return_view, is_return_flight, simulation_time, trajectory_points

    if key == 'q':
        application.quit()

    if key == 'r':
        for e in serve_trails + return_trails + landing_markers + return_entities:
            destroy(e)
        serve_trails.clear()
        return_trails.clear()
        landing_markers.clear()
        return_entities.clear()
        landings.clear()
        update_landing_text()
        ball.position = (0, RELEASE_HEIGHT, 0)
        ball.color = color.yellow
        trajectory_points = []
        simulation_time = 0.0
        global last_landing
        last_landing = None
        for p in return_presets:
            p['solution'] = None
        show_returns = False  
        update_instructions()

    if key == 't':
        show_trajectory = not show_trajectory
        for e in serve_trails + return_trails:
            e.visible = show_trajectory
        update_instructions()

    if key == 'v':
        is_player_view = not is_player_view
        if is_player_view:
            player.enabled = True
            camera.parent = player.camera_pivot
        else:
            player.enabled = False
            camera.parent = scene
            camera.position = (0, 1.8, -4.0)
            camera.rotation = (0, 0, 0)
        update_instructions()

    if key == 'm':
        auto_serve = not auto_serve
        update_instructions()

    if key == 'enter' and not auto_serve:
        if not trajectory_points and not serve_queue.empty():
            params = serve_queue.get()
            current_speed = params['speed']
            current_yaw = params['yaw']
            current_pitch = params['pitch']
            reset_simulation(current_speed, current_yaw, current_pitch)
            # Reset returns
            for p in return_presets:
                p['solution'] = None
            last_landing = None
            clear_return_entities()

    if key == 'b':
        show_returns = not show_returns
        if show_returns and last_landing:
            display_return_view(current_return_view)
        else:
            clear_return_entities()
            return_info_text.text = ""
        update_instructions()

    # === RETURN VIEW KEYS: 0-9 ===
    if key in '0123456789':
        if show_returns:
            display_return_view(key)
        update_instructions()


# Add light and sky for the FPC view
sun = DirectionalLight()
sun.look_at(Vec3(1, -1, 1)) # Point the light
Sky() # Add a skybox for a realistic background

# ----- MQTT Integration -----
class MQTTSimulator:
    def __init__(self, broker='broker.emqx.io', port=1883,
                 command_topic='Machine_A', status_topic='app', serve_queue=None):
        self.broker = broker
        self.port = port
        self.command_topic = command_topic
        self.status_topic = status_topic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.serve_queue = serve_queue
        self.current_speed = 30.0
        self.current_yaw = 0.0
        self.current_pitch = 0.0
        self.is_stopped = False

    def on_connect(self, client, userdata, flags, rc, properties):
        print("Simulator connected to MQTT broker with result code", rc)
        # 訂閱命令主題與廣播主題
        client.subscribe(self.command_topic)
        client.subscribe("broadcast")
    

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        print(payload)
        # 如果訊息來自 "broadcast" 主題，檢查是否為查詢機器名稱的訊息
        if msg.topic == "broadcast":
            try:
                data = json.loads(payload)
                if data.get("msg_type") == "query" and data.get("parameter") == "topic_name":
                    reply = {
                        "source": "Machine_A",
                        "msg_type": "reply",
                        "parameter": {
                            "topic_name": "Machine_A",
                            "range": {
                                "speed": {"min": 0, "max": 100},
                                "yaw": {"min": -90, "max": 90},
                                "pitch": {"min": -45, "max": 45}
                            }
                        }
                    }
                    # 將回覆發佈到 "app" 主題，讓 MachineClient 收到
                    self.client.publish(self.status_topic, json.dumps(reply))
                    print("Simulator replied with topic name and range info")
                    return
            except Exception as e:
                print("Error parsing broadcast JSON:", e)
        # 如果訊息來自命令主題，先嘗試解析 JSON，看是否為查詢狀態
        if msg.topic == self.command_topic:
            try:
                data = json.loads(payload)
                if data.get("msg_type") == "query":
                    if data.get("parameter") == "status":
                        # 回覆狀態資訊
                        status_reply = {
                            "source": "Machine_A",
                            "msg_type": "reply",
                            "parameter": {
                                "status": {
                                    "available": True,
                                    "settings": {
                                        "speed": self.current_speed,
                                        "yaw": self.current_yaw,
                                        "pitch": self.current_pitch
                                    },
                                    "range": {
                                        "speed": {"min": 0, "max": 100},
                                        "yaw": {"min": -90, "max": 90},
                                        "pitch": {"min": -45, "max": 45}
                                    }
                                }
                            }
                        }
                        self.client.publish(self.status_topic, json.dumps(status_reply))
                        print("Simulator replied with status info")
                        return
                elif data.get("msg_type") == "command":
                    commands = data.get("parameter").split(';')
                    for command in commands:
                        if '=' in command:
                            key, value = command.split('=')
                            self.process_command(key.strip(), value.strip())
                        elif command:
                            self.process_command(command.strip(), None)
                    
            except Exception as e:
                print("Error parsing JSON for query or commands:", e)
        else:
            # 如果不是來自廣播或命令主題，則直接印出訊息
            print("Simulator received message on unknown topic:", msg.topic, payload)


    def process_command(self, command, value):
        if command == 'speed':
            try:
                self.current_speed = float(value)
                self.publish_status()
            except Exception as e:
                print("Error setting speed:", e)
        elif command == 'yaw':
            try:
                self.current_yaw = float(value)
                self.publish_status()
            except Exception as e:
                print("Error setting yaw:", e)
        elif command == 'pitch':
            try:
                self.current_pitch = float(value)
                self.publish_status()
            except Exception as e:
                print("Error setting pitch:", e)
        elif command == 'serve':
            print("Received serve command")
            params = {
                'speed': self.current_speed,
                'yaw': self.current_yaw,
                'pitch': self.current_pitch
            }
            self.serve_queue.put(params)
            print("Queued serve with params:", params)
        elif command == 'MQTT_disconnect':
            print("Simulator: received MQTT_disconnect command")
            self.stop()
        else:
            print("Simulator: set", command)

    def publish_status(self):
        message = f"speed={self.current_speed};yaw={self.current_yaw};pitch={self.current_pitch}"
        print("Simulator publishing status:", message)
        self.client.publish(self.status_topic, message)

    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_forever()  # Blocking loop in background thread

    def stop(self):
        print("\nShutting down simulator...")
        self.client.unsubscribe(self.command_topic)
        self.client.unsubscribe("broadcast")
        self.client.disconnect()
        print("Simulator disconnected.")
        self.is_stopped = True

# Create the queue for serve commands
serve_queue = queue.Queue()

# Create and start the MQTT thread
simulator = MQTTSimulator(command_topic='Machine_A', status_topic='abcde12345', serve_queue=serve_queue)
mqtt_thread = threading.Thread(target=simulator.start, daemon=True)
mqtt_thread.start()

# ----- 8) Run the App -----
app.run()