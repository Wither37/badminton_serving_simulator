# ----- 1) Court Geometry (Net-Centered Global Coordinates) -----
# Global frame used by menus/policies:
#   X = width (left/right), Y = court length/depth, Z = height.
# Ursina mapping remains (world_x, world_y, world_z) = (X, Z, Y).
COURT_LENGTH = 13.40
COURT_WIDTH_DOUBLES = 6.10
COURT_WIDTH_SINGLES = 5.18
COURT = {
    "length": COURT_LENGTH,
    "width_doubles": COURT_WIDTH_DOUBLES,
    "width_singles": COURT_WIDTH_SINGLES,
    "short_service_line": 1.98,
    "net_height_center": 1.524,
}

HALF_LEN = COURT_LENGTH / 2.0
HALF_WIDTH_DOUBLES = COURT_WIDTH_DOUBLES / 2.0
HALF_WIDTH_SINGLES = COURT_WIDTH_SINGLES / 2.0

SHORT_SERVICE_LINE = COURT["short_service_line"]
DOUBLES_LONG_SERVICE_LINE = HALF_LEN - 0.76
BACK_BASELINE = HALF_LEN

NET_HEIGHT_CENTER = COURT["net_height_center"]

# Compatibility aliases for existing solver/render code.
COURT_LEN = COURT_LENGTH
COURT_W = COURT_WIDTH_DOUBLES
HALF_W = HALF_WIDTH_DOUBLES
SINGLES_HALF_W = HALF_WIDTH_SINGLES

# Physics depth axis origin now at net center.
NET_X = 0.0
NET_H = NET_HEIGHT_CENTER

# Court marking positions along global Y / Ursina Z.
Z_BASELINE_NEAR = -BACK_BASELINE
Z_BASELINE_FAR = BACK_BASELINE
Z_SHORT_SERVICE_NEAR = -SHORT_SERVICE_LINE
Z_SHORT_SERVICE_FAR = SHORT_SERVICE_LINE
Z_LONG_SERVICE_DOUBLES_NEAR = -DOUBLES_LONG_SERVICE_LINE
Z_LONG_SERVICE_DOUBLES_FAR = DOUBLES_LONG_SERVICE_LINE

# Line constants.
LINE_THICKNESS = 0.04
LINE_Y_OFFSET = 0.02

DECORATIVE_COURTS = {
    "enabled": True,
    "side_gap": 5.0,
}

SERVE_VISUAL = {
    "max_active_balls": 3,
    "trail_clear_delay": 0.20,
    "hide_after_return_contact": True,
    "model": "badminton.glb",
    "scale": 0.025,
    "look_axis": "forward",
    "rotation_offset": (180, 0, 0),
}

RETURN_BALL_VISUAL = {
    "model": "badminton.glb",
    "scale": 0.025,
    "look_axis": "forward",
    "rotation_offset": (180, 0, 0),
}

LANDING_MARKER_VISUAL_SERVE = {
    "model": "sphere",
    "scale": 0.1,
    "color_rgba": (0, 0, 1, 1),
    "rotation": (0, 0, 0),
    "height": 0.05,
}

LANDING_MARKER_VISUAL_RETURN = {
    "model": "sphere",
    "scale": 0.1,
    "color_rgba": (0, 0, 1, 1),
    "rotation": (0, 0, 0),
    "height": 0.05,
}

# Default simulator launch point in global coordinates (X, Y, Z).
SIMULATOR_DEFAULT_POSITION = {
    "x": 0.0,
    "y": -BACK_BASELINE,
    "z": 1.2,
}

# ----- 2) Physics -----
G = 9.81
DRAG_K = 0.2151959552
RELEASE_HEIGHT = 1.2
TRAIL_INTERVAL = 0.01
PHYSICS = {
    "gravity": G,
    "drag_k": DRAG_K,
    "release_height": RELEASE_HEIGHT,
    "trail_interval": TRAIL_INTERVAL,
}

# ----- 3) Return Behavior -----
# Return animation tuning.
RETURN_ANIMATION = {
    "point_step_mult": 10.0,
    "trail_interval": 0.02,
    "trail_clear_delay": 0.20,
}

# Legacy fallback targets along physics depth axis (same as global Y).
# Explicit return_policy.target remains the expected menu contract.
RETURN_DEFAULT_TARGETS = {
    "clear": {"x": -6.55, "y": 0.0, "z": 0.0},
    "drive": {"x": -6.20, "y": 0.0, "z": 0.0},
    "lift": {"x": -1.50, "y": 0.0, "z": 0.0},
}

RETURN_SHOT_CLEARANCE_MIN = 0.03
RETURN_PROFILES = {
    "lift": {
        "height_range_m": [0.30, 0.50],
        "contact_offset_m": {"x": 0.30, "y": 1.20},
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": None},
        "preferred_speed_mps": 35.0,
    },
    "net_soft": {
        "height_range_m": [1.10, 1.35],
        "contact_offset_m": {"x": 0.30, "y": 1.20},
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": 0.10},
    },
    "smash": {
        "height_range_m": [3.00, 3.20],
        "contact_offset_m": {"x": 0.00, "y": 0.50},
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": None},
        "preferred_speed_mps": 145.0,
        "min_speed_mps": 120.0,
        "max_speed_mps": 170.0,
    },
    "clear": {
        "height_range_m": [2.50, 2.80],
        "contact_offset_m": {"x": 0.00, "y": 0.50},
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": None},
    },
    "drop": {
        "height_range_m": [2.50, 2.80],
        "contact_offset_m": {"x": 0.00, "y": 0.50},
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": 0.15},
    },
    "drive": {
        "height_range_m": [1.50, 1.80],
        "contact_offset_m": {"x": 0.30, "y": 0.50},
        "depth_lock_to_home": True,
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": 0.30},
    },
    "block": {
        "height_range_m": [1.00, 1.20],
        "contact_offset_m": {"x": 0.80, "y": 0.00},
        "depth_lock_to_home": True,
        "clearance_m": {"min": RETURN_SHOT_CLEARANCE_MIN, "max": 0.30},
    },
}

RETURN_TARGET_PRESETS = {
    "clear": {
        "Center deep (x=0.00, y=-6.50)": {"x": 0.0, "y": -6.5},
        "Center deep safe (x=0.00, y=-6.35)": {"x": 0.0, "y": -6.35},
        "Left deep (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
        "Left back line (x=-2.35, y=-6.55)": {"x": -2.35, "y": -6.55},
        "Right back line (x=2.35, y=-6.55)": {"x": 2.35, "y": -6.55},
    },
    "drive": {
        "Center deep drive (x=0.00, y=-6.50)": {"x": 0.0, "y": -6.5},
        "Left drive (x=-2.35, y=-5.80)": {"x": -2.35, "y": -5.8},
        "Right drive (x=2.35, y=-5.80)": {"x": 2.35, "y": -5.8},
    },
    "lift": {
        "Left deep lift (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep lift (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
    },
    "drop": {
        "Left front drop (x=-2.35, y=-1.00)": {"x": -2.35, "y": -1.0},
        "Right front drop (x=2.35, y=-1.00)": {"x": 2.35, "y": -1.0},
    },
    "block": {
        "Left block (x=-2.35, y=-3.30)": {"x": -2.35, "y": -3.3},
        "Right block (x=2.35, y=-3.30)": {"x": 2.35, "y": -3.3},
    },
    "net_soft": {
        "Left soft net (x=-2.20, y=-1.60)": {"x": -2.2, "y": -1.6},
        "Right soft net (x=2.20, y=-1.60)": {"x": 2.2, "y": -1.6},
    },
    "smash": {
        "Left deep smash (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep smash (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
    },
}

RETURN_RUNTIME = {
    "precompute_serve_warmup": 0.50,
    "precompute_cache_max": 128,
}
RETURN_PLAYER = {
    "home": {
        "width": 0.0,
        "height": 0.9,
        "depth": NET_X + 3.5,
    },
    "movement": {
        "max_speed": 6,
        "accel": 15.0,
        "decel": 30.0,
    },
    "reaction_delay": 0.1,
    "block_on_recover": True,
}

RETURN_CAMERA = {
    "height": 1.75,
    "sensitivity": 140.0,
    "pitch_min": -70.0,
    "pitch_max": 70.0,
}

CAMERA = {
    "fov": 130.0,
}

# Temporary debug instrumentation for return solving.
RETURN_DEBUG_LOG = False
