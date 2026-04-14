import logging
import math
import numpy as np

from scipy.integrate import solve_ivp

def physics_predict3d(starting_point, second_point, flight_time=10, touch_ground_cut=True, alpha=0.2151959552, g=9.81):
    # starting_point, second_point, shape: (4,) 4: XYZt
    fps = 1/(second_point[3] - starting_point[3])

    initial_velocity = (second_point[:3]-starting_point[:3]) * fps # shape: (3,) unit: m/s

    traj = solve_ivp(lambda t, y: bm_ball(t, y, alpha=alpha, g=g), [0, flight_time], np.concatenate((starting_point[:3], initial_velocity)), t_eval = np.arange(0, flight_time, 1/fps)) # traj.t traj.y

    xyz = np.swapaxes(traj.y[:3,:], 0, 1) # shape: (N points, 3)
    t = np.expand_dims(traj.t,axis=1) # shape: (N points, 1)
    trajectories = np.concatenate((xyz, t),axis=1) # shape: (N points, 4)

    # Cut the part under the ground
    if touch_ground_cut:
        for i in range(trajectories.shape[0]-1):
            if trajectories[i,2] >= 0 and trajectories[i+1,2] <= 0:
                trajectories = trajectories[:i+1,:]
                break
    # Add timestamp correctly
    trajectories[:,3] += (starting_point[3]) # shape: (N points, 4)

    return trajectories # shape: (N points, 4) , include input two Points

def physics_predict3d_v2(starting_point, v, fps, flight_time=10, touch_ground_cut=True, alpha=0.2151959552, g=9.81):

    if fps <= 0:
        logging.warning("physics_predict3d_v2: fps must be > 0")
        return None

    initial_velocity = v

    traj = solve_ivp(lambda t, y: bm_ball(t, y, alpha=alpha, g=g), [0, flight_time], np.concatenate((starting_point[:3], initial_velocity)), t_eval = np.arange(0, flight_time, 1/fps)) # traj.t traj.y

    if not traj.success:
        logging.warning(f"solve_ivp failed: {traj.message}")
        return None

    # 檢查 sol.y / sol.t 型態
    if isinstance(traj.y, list) or isinstance(traj.t, list):
        logging.warning("physics_predict3d_v2: sol.y or sol.t is list, skipping")
        return None
    
    xyz = np.swapaxes(traj.y[:3,:], 0, 1) # shape: (N points, 3)
    t = np.expand_dims(traj.t,axis=1) # shape: (N points, 1)
    trajectories = np.concatenate((xyz, t),axis=1) # shape: (N points, 4)

    # Cut the part under the ground
    if touch_ground_cut:
        for i in range(trajectories.shape[0]-1):
            if trajectories[i,2] >= 0 and trajectories[i+1,2] <= 0:
                trajectories = trajectories[:i+1,:]
                break
    # Add timestamp correctly
    trajectories[:,3] += (starting_point[3]) # shape: (N points, 4)

    return trajectories # shape: (N points, 4) , include starting_point


def bm_ball(t,x,alpha=0.2151959552, g=9.81):
    # velocity
    v = math.sqrt(x[3]**2+x[4]**2+x[5]**2)
    # ordinary differential equations (3)
    xdot = [ x[3], x[4], x[5], -alpha*x[3]*v, -alpha*x[4]*v, -g-alpha*x[5]*v]
    return xdot
