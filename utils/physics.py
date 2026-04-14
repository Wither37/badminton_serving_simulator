from math import cos, sin, radians, sqrt, inf
from utils.config import *

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

    # Always store the final landing point
    if landing:
        pts.append((landing["x"], landing["y"], landing["z"], vx, vy, vz, landing["t"]))

    result = {"points": pts, "apex": apex, "cross_net": cross_net, "landing": landing, "hit_net": hit_net}
    if refine_heights:
        result["hit_points"] = hit_points
    return result

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