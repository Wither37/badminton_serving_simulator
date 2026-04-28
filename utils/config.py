# ----- 1) Court Geometry (Net-Centered Global Coordinates) -----
# Global frame used by menus/policies:
#   X = width (left/right), Y = court length/depth, Z = height.
# Ursina mapping remains (world_x, world_y, world_z) = (X, Z, Y).
COURT_LENGTH = 13.40
COURT_WIDTH_DOUBLES = 6.10
COURT_WIDTH_SINGLES = 5.18

HALF_LEN = COURT_LENGTH / 2.0              # 6.70
HALF_WIDTH_DOUBLES = COURT_WIDTH_DOUBLES / 2.0  # 3.05
HALF_WIDTH_SINGLES = COURT_WIDTH_SINGLES / 2.0  # 2.59

SHORT_SERVICE_LINE = 1.98                  # from net toward each baseline
DOUBLES_LONG_SERVICE_LINE = HALF_LEN - 0.76  # 5.94 from net
BACK_BASELINE = HALF_LEN                   # 6.70 from net

NET_HEIGHT_POSTS = 1.55
NET_HEIGHT_CENTER = 1.524

# Compatibility aliases for existing solver/render code.
COURT_LEN = COURT_LENGTH
COURT_W = COURT_WIDTH_DOUBLES
SINGLES_W = COURT_WIDTH_SINGLES
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

# Line constants
LINE_THICKNESS = 0.04           # 40mm
LINE_Y_OFFSET  = 0.02          # To prevent z-fighting (flickering)

MAX_SERVE_TRAIL   = 3
SERVE_TRAIL_CLEAR_DELAY = 0.20  # seconds after serve landing before clearing serve trajectory

# Default simulator launch point in global coordinates (X, Y, Z).
SIMULATOR_DEFAULT_X = 0.0
SIMULATOR_DEFAULT_Y = -BACK_BASELINE
SIMULATOR_DEFAULT_Z = 1.2

# ----- 2) 物理模擬參數 (Physics) -----
G = 9.81
DRAG_K = 0.2           # Your drag coefficient
RELEASE_HEIGHT = 1.2    # Your release height
TRAIL_INTERVAL = 0.01

# Return animation tuning
RETURN_POINT_STEP_MULT = 10.0      # >1.0 means fewer return trajectory points than serve
RETURN_TRAIL_INTERVAL = 0.02      # larger interval means fewer return trail spheres
RETURN_TRAIL_CLEAR_DELAY = 0.20   # seconds after return landing before clearing return trajectory
# Return targets along physics depth axis (same as global Y).
# Near side is negative after net-centered migration.
RETURN_TARGET_X_CLEAR = -6.55
RETURN_TARGET_X_DRIVE = -6.20
RETURN_TARGET_X_LIFT = -1.50
RETURN_TARGET_X_BLOCK = -2.15
RETURN_PLAYER_CONTACT_BACK_OFFSET = 0.50  # meters; player stands behind contact point
RETURN_BLOCK_CONTACT_SIDE_OFFSET = 0.50   # player stays this much inside contact laterally for block
RETURN_DRIVE_CONTACT_BACK_OFFSET = 0.50   # contact depth is this much in front of player home depth
RETURN_DRIVE_CONTACT_SIDE_OFFSET = 0.50   # player stays this much inside contact laterally for drive drill mode
RETURN_DRIVE_CONTACT_HEIGHT_MIN = 1.35    # head-height band (with margin)
RETURN_DRIVE_CONTACT_HEIGHT_MAX = 2.25
RETURN_PLAYER_HOME_WIDTH = 0.0            # global width axis (left/right)
RETURN_PLAYER_HOME_HEIGHT = 0.9           # player marker center height
RETURN_PLAYER_HOME_DEPTH = NET_X + 3.5    # physics depth axis (from net toward player side)
RETURN_REACTION_DELAY_AFTER_SERVE = 0.3  # seconds; start moving shortly after serve
PRECOMPUTE_SERVE_WARMUP = 0.50    # seconds to wait after precompute before first serve
RETURN_BLOCK_ON_PLAYER_RECOVER = True  # if True, next serve waits until player fully returns home

# Return-follow camera (available only when dynamic return mode is ON)
RETURN_CAMERA_HEIGHT = 1.75
RETURN_CAMERA_SENSITIVITY = 140.0
RETURN_CAMERA_PITCH_MIN = -70.0
RETURN_CAMERA_PITCH_MAX = 70.0

# Return precompute cache
RETURN_PRECOMPUTE_CACHE_MAX = 128

# Temporary debug instrumentation for return solving
RETURN_DEBUG_LOG = False
