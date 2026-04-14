import logging
import math
from math import cos, sin, radians, inf

import numpy as np
from scipy.integrate import solve_ivp

from utils.config import *


def bm_ball(t, x, alpha=DRAG_K, g=G):
    v = math.sqrt(x[3] ** 2 + x[4] ** 2 + x[5] ** 2)
    return [x[3], x[4], x[5], -alpha * x[3] * v, -alpha * x[4] * v, -g - alpha * x[5] * v]


def physics_predict3d(starting_point, second_point, flight_time=10, touch_ground_cut=True, alpha=DRAG_K, g=G):
    dt = second_point[3] - starting_point[3]
    if dt <= 0:
        logging.warning("physics_predict3d: invalid timestamp delta")
        return None

    fps = 1 / dt
    initial_velocity = (second_point[:3] - starting_point[:3]) * fps

    traj = solve_ivp(
        lambda t, y: bm_ball(t, y, alpha=alpha, g=g),
        [0, flight_time],
        np.concatenate((starting_point[:3], initial_velocity)),
        t_eval=np.arange(0, flight_time, 1 / fps),
    )

    if not traj.success:
        logging.warning(f"solve_ivp failed: {traj.message}")
        return None

    xyz = np.swapaxes(traj.y[:3, :], 0, 1)
    t = np.expand_dims(traj.t, axis=1)
    trajectories = np.concatenate((xyz, t), axis=1)

    if touch_ground_cut:
        for i in range(trajectories.shape[0] - 1):
            if trajectories[i, 2] >= 0 and trajectories[i + 1, 2] <= 0:
                trajectories = trajectories[: i + 1, :]
                break

    trajectories[:, 3] += starting_point[3]
    return trajectories


def physics_predict3d_v2(starting_point, v, fps, flight_time=10, touch_ground_cut=True, alpha=DRAG_K, g=G):
    if fps <= 0:
        logging.warning("physics_predict3d_v2: fps must be > 0")
        return None

    traj = solve_ivp(
        lambda t, y: bm_ball(t, y, alpha=alpha, g=g),
        [0, flight_time],
        np.concatenate((starting_point[:3], v)),
        t_eval=np.arange(0, flight_time, 1 / fps),
    )

    if not traj.success:
        logging.warning(f"solve_ivp failed: {traj.message}")
        return None

    if isinstance(traj.y, list) or isinstance(traj.t, list):
        logging.warning("physics_predict3d_v2: sol.y or sol.t is list, skipping")
        return None

    xyz = np.swapaxes(traj.y[:3, :], 0, 1)
    t = np.expand_dims(traj.t, axis=1)
    trajectories = np.concatenate((xyz, t), axis=1)

    if touch_ground_cut:
        for i in range(trajectories.shape[0] - 1):
            if trajectories[i, 2] >= 0 and trajectories[i + 1, 2] <= 0:
                trajectories = trajectories[: i + 1, :]
                break

    trajectories[:, 3] += starting_point[3]
    return trajectories


def _lerp(a, b, w):
    return a + w * (b - a)


def _build_points_with_velocity(trajectories):
    n = len(trajectories)
    pts = []
    if n == 0:
        return pts

    for i in range(n):
        x, y, z, t = trajectories[i]
        if n == 1:
            vx = vy = vz = 0.0
        elif i < n - 1:
            nx, ny, nz, nt = trajectories[i + 1]
            dt = nt - t
            if dt <= 0:
                vx = vy = vz = 0.0
            else:
                vx = (nx - x) / dt
                vy = (ny - y) / dt
                vz = (nz - z) / dt
        else:
            px, py, pz, pt = trajectories[i - 1]
            dt = t - pt
            if dt <= 0:
                vx = vy = vz = 0.0
            else:
                vx = (x - px) / dt
                vy = (y - py) / dt
                vz = (z - pz) / dt

        pts.append((float(x), float(y), float(z), float(vx), float(vy), float(vz), float(t)))
    return pts


def simulate_trajectory(
    speed_mps=23.0,
    yaw_deg=6.0,
    pitch_deg=20.0,
    drag_k=DRAG_K,
    dt_base=0.01,
    dt_fine=0.001,
    refine_net=False,
    refine_heights=False,
    refine_heights_list=[0.7, 1.8, 2.5],
    max_t=6.0,
    start_x=0.0,
    start_y=0.0,
    start_z=RELEASE_HEIGHT,
):
    del dt_fine

    yaw = radians(yaw_deg)
    pitch = radians(pitch_deg)

    vx0 = speed_mps * cos(pitch) * cos(yaw)
    vy0 = speed_mps * cos(pitch) * sin(yaw)
    vz0 = speed_mps * sin(pitch)

    fps = 1.0 / dt_base if dt_base > 0 else 100.0
    start = np.array([start_x, start_y, start_z, 0.0], dtype=float)
    v0 = np.array([vx0, vy0, vz0], dtype=float)

    traj = physics_predict3d_v2(
        starting_point=start,
        v=v0,
        fps=fps,
        flight_time=max_t,
        touch_ground_cut=False,
        alpha=drag_k,
        g=G,
    )

    if traj is None or len(traj) == 0:
        result = {
            "points": [(start_x, start_y, start_z, vx0, vy0, vz0, 0.0)],
            "apex": {"x": start_x, "y": start_y, "z": start_z, "t": 0.0},
            "cross_net": None,
            "landing": None,
            "hit_net": False,
        }
        if refine_heights:
            result["hit_points"] = {}
        return result

    pts_all = _build_points_with_velocity(traj)
    apex = max(({"x": p[0], "y": p[1], "z": p[2], "t": p[6]} for p in pts_all), key=lambda a: a["z"])

    cross_net = None
    hit_net = False
    landing = None
    hit_points = {} if refine_heights else None
    landing_idx = None

    for i in range(len(pts_all) - 1):
        p0 = pts_all[i]
        p1 = pts_all[i + 1]

        x0, y0, z0, _, _, _, t0 = p0
        x1, y1, z1, _, _, _, t1 = p1

        if cross_net is None and (x0 - NET_X) * (x1 - NET_X) <= 0 and x1 != x0:
            w_net = (NET_X - x0) / (x1 - x0)
            cross_z = _lerp(z0, z1, w_net)
            cross_y = _lerp(y0, y1, w_net)
            cross_t = _lerp(t0, t1, w_net)
            clearance = cross_z - NET_H
            cross_net = {"x": NET_X, "y": cross_y, "z": cross_z, "t": cross_t, "clearance": clearance}
            if clearance <= 0 and cross_z > 0:
                hit_net = True

        if refine_heights:
            for h in refine_heights_list:
                if h in hit_points:
                    continue
                if z0 >= h >= z1 and z1 != z0:
                    w_h = (h - z0) / (z1 - z0)
                    hit_x = _lerp(x0, x1, w_h)
                    hit_y = _lerp(y0, y1, w_h)
                    if hit_x > NET_X and abs(hit_y) <= HALF_W:
                        hit_points[h] = {"x": hit_x, "y": hit_y}

        if landing is None and z0 >= 0.0 > z1 and z1 != z0:
            w_land = (0.0 - z0) / (z1 - z0)
            landing = {"x": _lerp(x0, x1, w_land), "y": _lerp(y0, y1, w_land), "z": 0.0, "t": _lerp(t0, t1, w_land)}
            landing_idx = i
            break

    if landing is not None and landing_idx is not None:
        pts = pts_all[: landing_idx + 1]
        if landing_idx + 1 < len(pts_all):
            p0 = pts_all[landing_idx]
            p1 = pts_all[landing_idx + 1]
            z0 = p0[2]
            z1 = p1[2]
            w = (0.0 - z0) / (z1 - z0) if z1 != z0 else 0.0
            lvx = _lerp(p0[3], p1[3], w)
            lvy = _lerp(p0[4], p1[4], w)
            lvz = _lerp(p0[5], p1[5], w)
        else:
            lvx, lvy, lvz = pts_all[-1][3], pts_all[-1][4], pts_all[-1][5]
        pts.append((landing["x"], landing["y"], landing["z"], lvx, lvy, lvz, landing["t"]))
    else:
        pts = [p for p in pts_all if p[2] >= 0.0]
        if not pts:
            pts = [pts_all[0]]

    result = {"points": pts, "apex": apex, "cross_net": cross_net, "landing": landing, "hit_net": hit_net}
    if refine_heights:
        result["hit_points"] = hit_points
    return result


def find_fastest_clearing_shot(start_x, target_x, start_z, yaw_deg, start_y=0.0, tol=0.1, max_iter_pitch=10, max_iter_speed=10):
    max_speed = 100.0
    min_speed = 0.0
    high_pitch = 90.0
    low_pitch = -90.0

    best_speed = None
    best_pitch = None

    for _ in range(max_iter_pitch):
        if high_pitch - low_pitch < 0.01:
            break
        pitch = (low_pitch + high_pitch) / 2.0

        low_speed = min_speed
        high_speed = max_speed
        found = False
        local_best_speed = -inf

        for _ in range(max_iter_speed):
            if high_speed - low_speed < 0.01:
                break
            mid_speed = (low_speed + high_speed) / 2.0

            sim = simulate_trajectory(mid_speed, yaw_deg, pitch, start_x=start_x, start_y=start_y, start_z=start_z, refine_net=True, refine_heights=False)
            land = sim.get("landing")
            net = sim.get("cross_net")

            if not land or land["x"] < 0:
                high_speed = mid_speed
                continue

            clearance = net["clearance"] if net else 0.0
            if clearance <= 0.05:
                low_speed = mid_speed
                continue

            land_err = abs(land["x"] - target_x)
            if land_err > tol:
                if land["x"] < target_x:
                    high_speed = mid_speed
                else:
                    low_speed = mid_speed
                continue

            found = True
            low_speed = mid_speed
            local_best_speed = mid_speed

        if found:
            best_speed = local_best_speed
            best_pitch = pitch
            high_pitch = pitch
        else:
            low_pitch = pitch

    if best_pitch is not None and best_speed is not None:
        sim = simulate_trajectory(best_speed, yaw_deg, best_pitch, start_x=start_x, start_y=start_y, start_z=start_z, dt_base=0.01, refine_net=True, refine_heights=False)
        return best_speed, best_pitch, sim
    return None, None, None


def solve_return_to_target(start_xyz, target_xyz, shot_profile="auto", tol_xy=0.25, max_iter_speed=16):
    """Solve return shot parameters to send shuttle from start_xyz to target_xyz using ODE physics.

    Returns dict: {speed, yaw_deg, pitch_deg, sim, error_xy, profile} or None.
    """
    sx, sy, sz = start_xyz
    tx, ty, tz = target_xyz
    _ = tz  # landing on ground is assumed in simulator output

    dx = tx - sx
    dy = ty - sy
    base_yaw = math.degrees(math.atan2(dy, dx))

    incoming_depth = sx
    if shot_profile == "auto":
        if incoming_depth > NET_X + 4.2:
            shot_profile = "clear"
        elif incoming_depth > NET_X + 2.0:
            shot_profile = "drive"
        else:
            shot_profile = "lift"

    if shot_profile == "clear":
        pitch_candidates = [20, 24, 28, 32, 36]
        clearance_min = 0.15
        apex_min, apex_max = 2.4, 4.9
        flight_t_min, flight_t_max = 0.60, 1.90
    elif shot_profile == "drive":
        pitch_candidates = [8, 12, 16, 20]
        clearance_min = 0.05
        apex_min, apex_max = 1.1, 2.6
        flight_t_min, flight_t_max = 0.25, 1.20
    elif shot_profile == "drop":
        pitch_candidates = [16, 20, 24, 28]
        clearance_min = 0.06
        apex_min, apex_max = 1.3, 3.0
        flight_t_min, flight_t_max = 0.35, 1.40
    else:  # lift and fallback
        pitch_candidates = [24, 30, 36, 42]
        clearance_min = 0.10
        apex_min, apex_max = 2.0, 4.8
        flight_t_min, flight_t_max = 0.45, 1.80

    yaw_candidates = [base_yaw - 6.0, base_yaw - 3.0, base_yaw, base_yaw + 3.0, base_yaw + 6.0]

    best = None

    for yaw_deg in yaw_candidates:
        for pitch_deg in pitch_candidates:
            low_speed = 2.0
            high_speed = 85.0
            local_best = None

            for _ in range(max_iter_speed):
                mid_speed = (low_speed + high_speed) / 2.0
                sim = simulate_trajectory(
                    speed_mps=mid_speed,
                    yaw_deg=yaw_deg,
                    pitch_deg=pitch_deg,
                    start_x=sx,
                    start_y=sy,
                    start_z=sz,
                    refine_net=True,
                    refine_heights=False,
                    max_t=6.0,
                )

                land = sim.get("landing")
                cross = sim.get("cross_net")
                apex = sim.get("apex")
                if not land:
                    high_speed = mid_speed
                    continue

                apex_z = apex["z"] if apex else None
                if apex_z is None or apex_z < apex_min or apex_z > apex_max:
                    if apex_z is not None and apex_z > apex_max:
                        low_speed = mid_speed
                    else:
                        high_speed = mid_speed
                    continue

                if land["t"] < flight_t_min or land["t"] > flight_t_max:
                    if land["t"] > flight_t_max:
                        low_speed = mid_speed
                    else:
                        high_speed = mid_speed
                    continue

                clearance = cross["clearance"] if cross else 0.0
                if clearance <= clearance_min:
                    low_speed = mid_speed
                    continue

                err_x = abs(land["x"] - tx)
                err_y = abs(land["y"] - ty)
                err_xy = math.sqrt(err_x * err_x + err_y * err_y)

                local_best = {
                    "speed": mid_speed,
                    "yaw_deg": yaw_deg,
                    "pitch_deg": pitch_deg,
                    "sim": sim,
                    "error_xy": err_xy,
                    "profile": shot_profile,
                }

                if err_x < tol_xy and err_y < tol_xy:
                    high_speed = mid_speed
                else:
                    if land["x"] < tx:
                        high_speed = mid_speed
                    else:
                        low_speed = mid_speed

            candidate = local_best
            if not candidate:
                continue
            if best is None or candidate["error_xy"] < best["error_xy"]:
                best = candidate

    return best
