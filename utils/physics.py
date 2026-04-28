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


def _return_candidate_rank(candidate, preferred_speed=None):
    if candidate is None:
        return (inf, inf, inf)
    if preferred_speed is not None and candidate.get("within_tol"):
        return (0, abs(float(candidate["speed"]) - float(preferred_speed)), candidate["error_xy"])
    if candidate.get("within_tol"):
        return (1, candidate["error_xy"], abs(float(candidate["speed"]) - float(preferred_speed or candidate["speed"])))
    return (2, candidate["error_xy"], 0.0)


def _is_better_return_candidate(candidate, current, preferred_speed=None):
    return _return_candidate_rank(candidate, preferred_speed) < _return_candidate_rank(current, preferred_speed)


def solve_return_to_target(start_xyz, target_xyz, shot_profile="auto", tol_xy=0.25, max_iter_speed=16, debug_stats=None):
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

    profile_cfg = RETURN_PROFILES.get(shot_profile) or {}
    clearance_cfg = profile_cfg.get("clearance_m") or {}
    clearance_min = float(clearance_cfg.get("min", RETURN_SHOT_CLEARANCE_MIN))
    clearance_max = clearance_cfg.get("max")
    preferred_speed = profile_cfg.get("preferred_speed_mps")

    if shot_profile == "clear":
        pitch_candidates = [38, 42, 46, 50, 54, 58]
        apex_rise_min, apex_rise_max = 1.2, 7.5
        flight_t_min, flight_t_max = 0.70, 3.20
    elif shot_profile == "drive":
        pitch_candidates = [0, 2, 4, 6, 8]
        apex_rise_min, apex_rise_max = -0.1, 1.0
        flight_t_min, flight_t_max = 0.20, 1.40
    elif shot_profile == "drop":
        pitch_candidates = [12, 16, 20, 24, 28]
        apex_rise_min, apex_rise_max = -0.1, 2.0
        flight_t_min, flight_t_max = 0.30, 1.80
    elif shot_profile == "smash":
        # Smash return: fast, flatter trajectory, low net margin.
        pitch_candidates = [-18, -14, -10, -6, -2]
        apex_rise_min, apex_rise_max = -1.0, 1.0
        flight_t_min, flight_t_max = 0.12, 0.85
    elif shot_profile == "net_soft":
        # Soft net return: medium contact height, gentle trajectory, low pace,
        # just enough clearance to cross and tumble into the front court.
        pitch_candidates = [16, 20, 24, 28, 32, 36, 40, 44]
        apex_rise_min, apex_rise_max = -0.05, 3.2
        flight_t_min, flight_t_max = 0.35, 2.20
    elif shot_profile == "block":
        # Sideways-only block contacts can be relatively low; allow a wider arc search
        # so the solver can still find legal net-clearing trajectories.
        pitch_candidates = [8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48]
        apex_rise_min, apex_rise_max = -0.3, 3.5
        flight_t_min, flight_t_max = 0.18, 1.60
    else:  # lift and fallback
        pitch_candidates = [62, 60, 64, 66]
        apex_rise_min, apex_rise_max = 2.0, 12.0
        flight_t_min, flight_t_max = 0.55, 3.20

    yaw_deg = base_yaw

    best = None
    stats = {
        "tested": 0,
        "no_landing": 0,
        "apex_reject": 0,
        "flight_time_reject": 0,
        "clearance_reject": 0,
        "clearance_low_reject": 0,
        "clearance_high_reject": 0,
        "short_zone_reject": 0,
        "net_shape_reject": 0,
        "candidate_updates": 0,
        "profile": shot_profile,
    }

    for pitch_deg in pitch_candidates:
        low_speed = 2.0
        high_speed = 85.0
        local_best = None

        for _ in range(max_iter_speed):
            mid_speed = (low_speed + high_speed) / 2.0
            stats["tested"] += 1
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
                stats["no_landing"] += 1
                high_speed = mid_speed
                continue

            apex_z = apex["z"] if apex else None
            apex_rise = (apex_z - sz) if apex_z is not None else None
            if apex_rise is None or apex_rise < apex_rise_min or apex_rise > apex_rise_max:
                stats["apex_reject"] += 1
                if apex_rise is not None and apex_rise > apex_rise_max:
                    low_speed = mid_speed
                else:
                    high_speed = mid_speed
                continue

            if land["t"] < flight_t_min or land["t"] > flight_t_max:
                stats["flight_time_reject"] += 1
                if land["t"] > flight_t_max:
                    low_speed = mid_speed
                else:
                    high_speed = mid_speed
                continue

            clearance = cross["clearance"] if cross else 0.0
            if clearance <= clearance_min:
                stats["clearance_reject"] += 1
                stats["clearance_low_reject"] += 1
                low_speed = mid_speed
                continue
            if clearance_max is not None and clearance > clearance_max:
                stats["clearance_reject"] += 1
                stats["clearance_high_reject"] += 1
                high_speed = mid_speed
                continue

            if shot_profile == "net_soft":
                # Keep landing within the short service-line zone on the receiver side.
                if tx < NET_X:
                    if land["x"] < -SHORT_SERVICE_LINE:
                        stats["short_zone_reject"] += 1
                        high_speed = mid_speed
                        continue
                    if land["x"] >= NET_X:
                        stats["short_zone_reject"] += 1
                        low_speed = mid_speed
                        continue
                else:
                    if land["x"] > SHORT_SERVICE_LINE:
                        stats["short_zone_reject"] += 1
                        high_speed = mid_speed
                        continue
                    if land["x"] <= NET_X:
                        stats["short_zone_reject"] += 1
                        low_speed = mid_speed
                        continue

                # Prefer trajectory apex on the hitter side and before net crossing,
                # so shuttle is already descending when it passes the net.
                apex_x = apex["x"] if apex else sx
                apex_t = apex["t"] if apex else 0.0
                cross_t = cross["t"] if cross else 0.0
                same_side_as_hitter = (apex_x - NET_X) * (sx - NET_X) > 0.0
                if not same_side_as_hitter or apex_t >= cross_t:
                    stats["net_shape_reject"] += 1
                    low_speed = mid_speed
                    continue
            elif shot_profile == "drop":
                # Keep drop returns landing in short service-line zone.
                if tx < NET_X:
                    if land["x"] < -SHORT_SERVICE_LINE:
                        stats["short_zone_reject"] += 1
                        high_speed = mid_speed
                        continue
                    if land["x"] >= NET_X:
                        stats["short_zone_reject"] += 1
                        low_speed = mid_speed
                        continue
                else:
                    if land["x"] > SHORT_SERVICE_LINE:
                        stats["short_zone_reject"] += 1
                        high_speed = mid_speed
                        continue
                    if land["x"] <= NET_X:
                        stats["short_zone_reject"] += 1
                        low_speed = mid_speed
                        continue

            err_x = abs(land["x"] - tx)
            err_y = abs(land["y"] - ty)
            err_xy = math.sqrt(err_x * err_x + err_y * err_y)

            candidate = {
                "speed": mid_speed,
                "yaw_deg": yaw_deg,
                "pitch_deg": pitch_deg,
                "sim": sim,
                "error_x": err_x,
                "error_y": err_y,
                "error_xy": err_xy,
                "within_tol": err_x <= tol_xy and err_y <= tol_xy,
                "profile": shot_profile,
            }
            candidate_summary = {
                "speed": mid_speed,
                "pitch_deg": pitch_deg,
                "landing": {"x": land["x"], "y": land["y"], "z": land["z"], "t": land["t"]},
                "target": {"x": tx, "y": ty, "z": tz},
                "error_x": err_x,
                "error_y": err_y,
                "error_xy": err_xy,
                "clearance": clearance,
                "apex_z": apex["z"] if apex else None,
                "flight_t": land["t"],
            }
            if _is_better_return_candidate(candidate, local_best, preferred_speed):
                local_best = candidate
                stats["best_candidate"] = candidate_summary
                stats["candidate_updates"] += 1

            if err_x <= tol_xy and err_y <= tol_xy:
                high_speed = mid_speed
            else:
                if land["x"] < tx:
                    high_speed = mid_speed
                else:
                    low_speed = mid_speed

        candidate = local_best
        if not candidate:
            continue
        if _is_better_return_candidate(candidate, best, preferred_speed):
            best = candidate

    if best is not None:
        stats["best_error_x"] = best.get("error_x")
        stats["best_error_y"] = best.get("error_y")
        stats["best_error_xy"] = best.get("error_xy")
        stats["tol_xy"] = tol_xy
        if best.get("error_x", inf) > tol_xy or best.get("error_y", inf) > tol_xy:
            stats["tolerance_reject"] = 1
            best = None
        else:
            stats["tolerance_reject"] = 0
    else:
        stats["tolerance_reject"] = 0

    if isinstance(debug_stats, dict):
        debug_stats.clear()
        debug_stats.update(stats)

    return best
