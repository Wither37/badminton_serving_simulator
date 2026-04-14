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
MAX_SERVE_TRAIL   = 3

# ----- 2) 物理模擬參數 (Physics) -----
G = 9.81
DRAG_K = 0.2           # Your drag coefficient
RELEASE_HEIGHT = 1.2    # Your release height
# Define return presets
HEIGHTS = [0.7, 1.8, 2.5]
LOCATIONS_1 = ['left', 'mid', 'right']
LOCATIONS_2 = ['front', 'mid', 'back']
TARGETS_X = [5.90, 3.35, 0.76]
TARGET_YS = [-(SINGLES_HALF_W - 0.5), 0, (SINGLES_HALF_W - 0.5)]
TRAIL_INTERVAL = 0.01

# Return animation tuning
RETURN_POINT_STEP_MULT = 10.0      # >1.0 means fewer return trajectory points than serve
RETURN_TRAIL_INTERVAL = 0.02      # larger interval means fewer return trail spheres
RETURN_TARGET_X_CLEAR = 0.35      # deeper backcourt target (near baseline x=0)
RETURN_TARGET_X_DRIVE = 2.90
RETURN_TARGET_X_LIFT = 5.20
RETURN_PLAYER_CONTACT_BACK_OFFSET = 0.20  # meters; player stands behind contact point
PRECOMPUTE_SERVE_WARMUP = 1.50    # seconds to wait after precompute before first serve

# Return-follow camera (available only when dynamic return mode is ON)
RETURN_CAMERA_HEIGHT = 1.65
RETURN_CAMERA_SENSITIVITY = 140.0
RETURN_CAMERA_PITCH_MIN = -70.0
RETURN_CAMERA_PITCH_MAX = 70.0

# Return precompute cache
RETURN_PRECOMPUTE_CACHE_MAX = 128