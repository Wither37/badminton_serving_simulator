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
Z_SHORT_SERVICE_NEAR = NET_X - SHORT_SERVICE_DIST # 4.72m
Z_SHORT_SERVICE_FAR  = NET_X + SHORT_SERVICE_DIST # 8.68m
Z_LONG_SERVICE_DOUBLES_NEAR = LONG_SERVICE_DOUBLES_DIST    # 0.76m
Z_LONG_SERVICE_DOUBLES_FAR  = COURT_LEN - LONG_SERVICE_DOUBLES_DIST # 12.64m

# Line constants
LINE_THICKNESS = 0.04           # 40mm
LINE_Y_OFFSET  = 0.02          # To prevent z-fighting (flickering)

# ----- 2) 物理模擬參數 (Physics) -----
g = 9.81
drag_k = 0.08           # Your drag coefficient
release_height = 1.2    # Your release height

# This dictionary will hold the physics state of the ball
sim_state = {
    'x': 0.0, 'y': 0.0, 'z': 0.0,  # Position (user's coordinate system)
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
ball = Entity(model='sphere', position=(0,1.2,0), color=color.yellow, scale=0.15)

# Add instructions
Text("Q: Quit\nR: Reset\nT: Toggle Trajectory\nV: Toggle View", position=(0.85, -0.4), origin=(0.5, 0), alignment='right', scale=1.5)

# Add landing text UI
landing_text = Text(position=window.top_left + Vec2(0.05, -0.05), text='', scale=1.5, background=False)

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


def update_landing_text():
    txt = "Landings:\n"
    for i, ld in enumerate(landings):
        pos = ld['pos']
        params = ld['params']
        txt += f"{i+1}: Pos ({pos[0]:.2f}, {pos[1]:.2f}), Speed={params[0]}, Yaw={params[1]}, Pitch={params[2]}\n"
    landing_text.text = txt

# ----- 6) The Animation Loop -----

def update():
    """
    This function runs automatically every frame.
    We put the physics simulation logic here.
    """
    global current_speed, current_yaw, current_pitch

    if not sim_state['running']:
        # Check for queued serves non-blockingly
        try:
            params = serve_queue.get_nowait()
            current_speed = params['speed']
            current_yaw = params['yaw']
            current_pitch = params['pitch']
            reset_simulation(current_speed, current_yaw, current_pitch)
        except queue.Empty:
            pass
        return

    # Use 'time.dt' (delta time) for the time step
    dt = time.dt

    # Get current state
    x, y, z = sim_state['x'], sim_state['y'], sim_state['z']
    vx, vy, vz = sim_state['vx'], sim_state['vy'], sim_state['vz']

    # --- Physics Calculation (Copied from your simulate_trajectory) ---
    vmag = sqrt(vx*vx + vy*vy + vz*vz)
    ax = -drag_k * vmag * vx
    ay = -drag_k * vmag * vy
    az = -g - drag_k * vmag * vz

    # --- Euler Integration ---
    vx += ax * dt
    vy += ay * dt
    vz += az * dt
    x  += vx * dt
    y  += vy * dt
    z  += vz * dt

    # --- Update global state ---
    sim_state.update({ 'x': x, 'y': y, 'z': z, 'vx': vx, 'vy': vy, 'vz': vz })

    # --- Update 3D Ball Position (with coordinate mapping) ---
    # User's [x,y,z] = (Length, Width, Height)
    # Ursina's [x,y,z] = (Right, Up, Forward)
    # Mapping:
    #   Ursina.x = User.y (Width)
    #   Ursina.y = User.z (Height)
    #   Ursina.z = User.x (Length)
    ball.position = (y, z, x)

    # Add a trail dot if showing trajectory
    if show_trajectory:
        trail = Entity(
            name='trail_dot',
            model='sphere', 
            color=color.red, 
            scale=0.03, 
            position=ball.position
        )
        all_trails.append(trail)

    # Check for landing
    if z <= 0:
        sim_state['running'] = False
        sim_state['z'] = 0
        ball.position = (y, 0, x)
        ball.color = color.red # Show it landed
        print("Landed at (x, y) = ({:.2f}, {:.2f})".format(x, y))
        # Add landing marker
        marker = Entity(model='sphere', scale=0.1, color=color.blue, position=(y, 0.05, x))
        landing_markers.append(marker)
        # Save landing info
        landings.append({'pos': (x, y), 'params': (current_speed, current_yaw, current_pitch)})
        update_landing_text()
        # Publish serve done
        simulator.client.publish(simulator.status_topic, "serve=done")

# ----- 7) User Input -----

def input(key):
    """
    This function captures key presses.
    """
    global show_trajectory, is_player_view

    # if key == 'space':
    #     reset_simulation(current_speed, current_yaw, current_pitch)
    
    if key == 'q':
        application.quit()

    if key == 'r':
        for e in all_trails + landing_markers:
            destroy(e)
        all_trails.clear()
        landing_markers.clear()
        landings.clear()
        update_landing_text()
        ball.position = (0, release_height, 0)
        ball.color = color.yellow
        sim_state['running'] = False
        sim_state['x'] = 0
        sim_state['y'] = 0
        sim_state['z'] = release_height
        sim_state['vx'] = 0
        sim_state['vy'] = 0
        sim_state['vz'] = 0

    if key == 't':
        show_trajectory = not show_trajectory
        for e in all_trails:
            e.visible = show_trajectory

    if key == 'v':
        is_player_view = not is_player_view
        if is_player_view:
            player.enabled = True
            camera.parent = player.camera_pivot
        else:
            player.enabled = False
            camera.parent = None
            camera.position = (0, 1.2, 0)
            camera.rotation = (0, 0, 0)

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