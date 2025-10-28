from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from ursina.shaders import lit_with_shadows_shader
from math import cos, sin, radians, sqrt
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
TRAIL_SAMPLE_STEP = 1          # keep only every 8th point (≈ 0.32 s)
TRAIL_DT          = 0.01       # larger physics step for preview

# ----- 2) 物理模擬參數 (Physics) -----
g = 9.81
drag_k = 0.2           # Your drag coefficient
release_height = 1.2    # Your release height

# Standalone trajectory simulation
def simulate_trajectory(speed_mps=23.0, yaw_deg=6.0, pitch_deg=20.0,
                        drag_k=0.08, release_height=1.2,
                        dt=TRAIL_DT, max_t=6.0, start_x=0.0, start_y=0.0, start_z=None,
                        full_res=False):
    """
    full_res=False  → coarse physics + sampled points (for preview)
    full_res=True   → fine physics (for actual serve/return animation)
    """
    if start_z is None:
        start_z = release_height

    yaw   = radians(yaw_deg)
    pitch = radians(pitch_deg)

    vx = speed_mps * cos(pitch) * cos(yaw)
    vy = speed_mps * cos(pitch) * sin(yaw)
    vz = speed_mps * sin(pitch)

    x, y, z = start_x, start_y, start_z
    t = 0.0

    pts   = []
    apex  = {"x": x, "y": y, "z": z, "t": t}
    cross_net = None
    landing   = None
    prev = None
    step_counter = 0

    while t <= max_t and z >= 0.0:
        # ----- store point only when drawing preview -----
        if not full_res and step_counter % TRAIL_SAMPLE_STEP == 0:
            pts.append((x, y, z, vx, vy, vz, t))

        if full_res:                     # fine resolution for real flight
            pts.append((x, y, z, vx, vy, vz, t))

        if z > apex["z"]:
            apex = {"x": x, "y": y, "z": z, "t": t}

        prev = (x, y, z, vx, vy, vz, t)

        # ----- physics -----
        vmag = sqrt(vx*vx + vy*vy + vz*vz)
        ax = -drag_k * vmag * vx
        ay = -drag_k * vmag * vy
        az = -g - drag_k * vmag * vz

        vx += ax * dt
        vy += ay * dt
        vz += az * dt
        x  += vx * dt
        y  += vy * dt
        z  += vz * dt
        t  += dt
        step_counter += 1

        # ----- interpolation helpers -----
        def lerp(a, b, w): return a + w * (b - a)

        # net crossing
        w_net = None
        if prev and (prev[0] - NET_X) * (x - NET_X) <= 0 and x != prev[0]:
            w_net = (NET_X - prev[0]) / (x - prev[0])
        if w_net is not None and 0 <= w_net <= 1:
            cross_net = {
                "x": NET_X,
                "y": lerp(prev[1], y, w_net),
                "z": lerp(prev[2], z, w_net),
                "t": lerp(prev[6], t, w_net),
                "clearance": lerp(prev[2], z, w_net) - NET_H
            }

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

    # always store the final landing point
    if landing and (full_res or step_counter % TRAIL_SAMPLE_STEP == 0):
        pts.append((landing["x"], landing["y"], landing["z"], vx, vy, vz, landing["t"]))

    return {"points": pts, "apex": apex, "cross_net": cross_net, "landing": landing}

# Function to find speed for target landing x
def find_fastest_clearing_shot(
        start_x, target_x, start_z,
        yaw_offset,
        tol=0.1,
        max_iter_pitch=10,
        max_iter_speed=10):
    """
    Returns (speed, pitch, sim) for the *fastest* speed that:
      • lands within tol of target_x
      • clears the net (clearance > 0)
      • uses the *lowest* possible pitch for that speed
    """
    yaw = 180.0 + yaw_offset
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
                mid_speed, yaw, pitch,
                start_x=start_x, start_y=0, start_z=start_z,
                dt=0.005, full_res=False
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
        # Re-simulate at the best speed for this pitch
        sim = simulate_trajectory(
            best_speed, yaw, best_pitch,
            start_x=start_x, start_y=0, start_z=start_z,
            dt=0.005, full_res=False
        )
        clear = sim['cross_net']['clearance']
        print(f"speed={best_speed} m/s, pitch={best_pitch}°, land={sim['landing']['x']}m, " +
              f"Δx={abs(sim['landing']['x']-target_x)}m, net={clear}m")
        return best_speed, best_pitch, sim
    return None, None, None

# This dictionary will hold the physics state of the ball
sim_state = {
    'x': 0.0, 'y': 0.0, 'z': release_height,  # Position (user's coordinate system)
    'vx': 0.0, 'vy': 0.0, 'vz': 0.0, # Velocity
    'running': False
}

# Current launch parameters (updated via MQTT)
current_speed = 30.0        # m/s
current_yaw = 3.0           # degrees (left/right)
current_pitch = 22.0        # degrees (up/down)

# Additional globals for new features
show_trajectory = True
all_trails = []
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

# Define return presets
heights = [0.7, 1.8, 2.5]
locations_1 = ['left', 'mid', 'right']
locations_2 = ['front', 'mid', 'back']
targets_x = [4.72, 3.35, 0.76]  # front, mid, back on machine side
yaws = [
    [-15, 0, 15],   # low height
    [-10, 0, 10],   # mid height
    [-8,  0,  8]    # high height
]
colors = [color.red, color.yellow, color.blue]

return_presets = []
for i in range(3):
    for j in range(3):
        return_presets.append({
            "name": f"{heights[i]}m {locations_1[j]}-{locations_2[i]}",
            "height": heights[i],
            "yaw_offset": yaws[i][j],
            "target_x": targets_x[i],
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
    global return_presets, last_landing
    if last_landing is None:
        return

    start_x = last_landing['x']
    for preset in return_presets:
        if preset['solution'] is not None:
            continue  # Already computed

        speed, pitch, sim = find_fastest_clearing_shot(
            start_x=start_x,
            target_x=preset['target_x'],
            start_z=preset['height'],
            yaw_offset=preset['yaw_offset']
        )
        preset['solution'] = {'speed': speed, 'pitch': pitch, 'sim': sim} if speed else None
        if speed:
            print(f"[SOLVED] {preset['name']}: {speed:.1f}m/s, {pitch:.1f}°, land={sim['landing']['x']:.2f}m" +
                  f" Δx={abs(sim['landing']['x']-preset['target_x'])}m, net={sim['cross_net']['clearance']:.2f}m")
        else:
            print(f"[NO SOLUTION] {preset['name']}")

def display_return_view(view_id):
    """Show only the selected return (or all). Clears previous."""
    global return_entities, return_options, current_return_view, return_info_text

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

    # Draw selected returns
    presets_to_draw = return_presets if view_id == '0' else ([target_preset] if target_preset else [])
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

def reset_simulation(speed_mps, yaw_deg, pitch_deg):
    """(Re)initializes the ball's physics state with given parameters."""
    
    # Set initial position
    sim_state['x'] = 0.0
    sim_state['y'] = 0.0
    sim_state['z'] = release_height
    
    # Calculate initial velocities (from your simulate_trajectory)
    yaw   = radians(yaw_deg)
    pitch = radians(pitch_deg)
    
    sim_state['vx'] = speed_mps * cos(pitch) * cos(yaw)
    sim_state['vy'] = speed_mps * cos(pitch) * sin(yaw)
    sim_state['vz'] = speed_mps * sin(pitch)
    
    # Set the 3D ball to the start position
    # **Coordinate Mapping: (User's [x,y,z] -> Ursina's [z,x,y])**
    ball.position = (sim_state['y'], sim_state['z'], sim_state['x'])
    ball.color = color.yellow
            
    sim_state['running'] = True
    print(f"Simulation Started with speed={speed_mps}, yaw={yaw_deg}, pitch={pitch_deg}")


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
ball = Entity(model='sphere', position=(0, release_height, 0), color=color.yellow, scale=0.15)

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

# ----- 6) The Animation Loop -----

def update():
    global current_speed, current_yaw, current_pitch
    global last_landing, is_return_flight, show_returns, current_return_view, solutions_ready

    if not sim_state['running']:
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

    dt = time.dt
    x, y, z = sim_state['x'], sim_state['y'], sim_state['z']
    vx, vy, vz = sim_state['vx'], sim_state['vy'], sim_state['vz']

    vmag = sqrt(vx*vx + vy*vy + vz*vz)
    ax = -drag_k * vmag * vx
    ay = -drag_k * vmag * vy
    az = -g - drag_k * vmag * vz

    vx += ax * dt
    vy += ay * dt
    vz += az * dt
    x  += vx * dt
    y  += vy * dt
    z  += vz * dt

    sim_state.update({'x': x, 'y': y, 'z': z, 'vx': vx, 'vy': vy, 'vz': vz})
    ball.position = (y, z, x)

    if show_trajectory:
        trail = Entity(model='sphere', color=color.red, scale=0.03, position=ball.position)
        all_trails.append(trail)

    # === ONLY SERVE (not return) triggers landing logic ===
    if z <= 0 and not is_return_flight:
        sim_state['running'] = False
        sim_state['z'] = 0
        ball.position = (y, 0, x)
        ball.color = color.red
        print(f"Landed at (x={x:.2f}, y={y:.2f})")

        last_landing = {'x': x, 'y': y}
        landings.append({'pos': (x, y), 'params': (current_speed, current_yaw, current_pitch)})
        update_landing_text()

        marker = Entity(model='sphere', scale=0.1, color=color.blue, position=(y, 0.05, x))
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
    elif z <= 0 and is_return_flight:
        sim_state['running'] = False
        sim_state['z'] = 0
        ball.position = (y, 0, x)
        ball.color = color.red
        is_return_flight = False
        # DO NOT compute solutions here!

def input(key):
    global show_trajectory, is_player_view, auto_serve, show_returns, current_return_view, is_return_flight

    if key == 'q':
        application.quit()

    if key == 'r':
        for e in all_trails + landing_markers + return_entities:
            destroy(e)
        all_trails.clear()
        landing_markers.clear()
        return_entities.clear()
        landings.clear()
        update_landing_text()
        ball.position = (0, release_height, 0)
        ball.color = color.yellow
        sim_state['running'] = False
        sim_state['x'] = sim_state['y'] = 0
        sim_state['z'] = release_height
        sim_state['vx'] = sim_state['vy'] = sim_state['vz'] = 0
        global last_landing
        last_landing = None
        for p in return_presets:
            p['solution'] = None
        show_returns = False  
        update_instructions()

    if key == 't':
        show_trajectory = not show_trajectory
        for e in all_trails:
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
            camera.position = (0, 1.2, 0)
            camera.rotation = (0, 0, 0)
        update_instructions()

    if key == 'm':
        auto_serve = not auto_serve
        update_instructions()

    if key == 'enter' and not auto_serve:
        if not sim_state['running'] and not serve_queue.empty():
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
sim_state['running'] = False # Wait for user to press space or MQTT serve
app.run()