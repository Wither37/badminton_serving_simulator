"""Dynamic return engine: player movement + context-aware return generation."""
import copy as pycopy
import math
import time

from ursina import *

from utils.config import *
from utils.physics import simulate_trajectory, solve_return_to_target


class ReturnSolver:
    def __init__(self, ball, ui_manager, game_state):
        self.ball = ball
        self.ui = ui_manager
        self.game_state = game_state

        self.enabled = False
        self._handled_ball_ids = set()

        self._active_return_animations = []
        self._player_returned_home_pulse = False

        player_home = RETURN_PLAYER["home"]
        player_movement = RETURN_PLAYER["movement"]
        self.player_home = Vec3(player_home["width"], player_home["height"], player_home["depth"])
        self.player_max_speed = float(player_movement["max_speed"])
        self.player_accel = float(player_movement["accel"])
        self.player_decel = float(player_movement["decel"])
        self._player_speed_now = 0.0
        self.player_state = "idle"
        self._player_target = self.player_home
        self._active_plan = None
        self._planned_returns = []
        self._pending_requests = []
        self._solve_cooldown = 0.0
        self._min_solve_interval = 0.03
        self._precompute_cache = {}

        self.return_player = Entity(
            model="sphere",
            scale=(0.55, 1.35, 0.55),
            color=color.azure,
            position=self.player_home,
            visible=False,
        )

    def _debug(self, msg):
        if RETURN_DEBUG_LOG:
            print(f"[ReturnDebug] {msg}")

    def _format_return_attempt(self, profile, target):
        if not isinstance(target, dict):
            return str(profile or "return")
        try:
            return f"{profile} to x={target['y']:.2f}, y={target['x']:.2f}"
        except Exception:
            return str(profile or "return")

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.return_player.visible = enabled
        if enabled:
            self.ui.update_return_info("Dynamic return mode: ON")
        else:
            self.ui.hide_return_info()
            self.stop_animation()
            self.player_state = "idle"
            self._active_plan = None
            self._planned_returns.clear()
            self._pending_requests.clear()
            self._handled_ball_ids.clear()
            self._player_returned_home_pulse = False
            self.return_player.position = self.player_home
            self._player_speed_now = 0.0

    def consume_player_returned_home_pulse(self):
        pulse = self._player_returned_home_pulse
        self._player_returned_home_pulse = False
        return pulse

    def _build_plan_from_solution(self, ball_obj, contact, target, sol, profile=None):
        active_profile = profile or sol.get("profile")
        contact_cfg = sol.get("contact_cfg")
        intercept_pos = self._intercept_position_from_contact(contact, profile=active_profile, contact_cfg=contact_cfg)
        move_dist = (intercept_pos - self.player_home).length()
        move_lead = self._travel_time_with_player_profile(move_dist)
        natural_start_t = max(0.0, contact["t"] - move_lead)
        early_react_t = max(0.0, float(RETURN_PLAYER["reaction_delay"]))
        return {
            "ball_id": id(ball_obj),
            "ball": ball_obj,
            "contact": contact,
            "target": target,
            "solution": sol,
            "profile": active_profile,
            "contact_cfg": contact_cfg,
            "contact_t": contact["t"],
            "move_start_t": min(natural_start_t, early_react_t),
            "state": "scheduled",
        }

    def _travel_time_with_player_profile(self, distance_m):
        d = max(0.0, float(distance_m))
        if d <= 0.03:
            return 0.0

        # Runtime considers the target reached once it is within this snap distance.
        d = max(0.0, d - 0.03)
        vmax = max(0.1, float(self.player_max_speed))
        accel = max(0.1, float(self.player_accel))
        decel = max(0.1, float(self.player_decel))

        d_acc = (vmax * vmax) / (2.0 * accel)
        d_dec = (vmax * vmax) / (2.0 * decel)
        if d >= d_acc + d_dec:
            return (vmax / accel) + ((d - d_acc - d_dec) / vmax) + (vmax / decel)

        v_peak = math.sqrt(max(0.0, 2.0 * d * accel * decel / (accel + decel)))
        return (v_peak / accel) + (v_peak / decel)

    def _intercept_position_from_contact(self, contact, profile=None, contact_cfg=None):
        offset = (contact_cfg or {}).get("contact_offset") or {}
        lateral_offset = float(offset.get("x", 0.0))
        depth_offset = float(offset.get("y", 0.0))
        depth_lock_to_home = bool((contact_cfg or {}).get("depth_lock_to_home", False))

        lateral = float(contact["y"])
        if abs(lateral) > 1e-6:
            lateral = lateral - math.copysign(lateral_offset, lateral)
        lateral = max(-SINGLES_HALF_W, min(SINGLES_HALF_W, lateral))

        # Offset is reach geometry only. The return still launches from the actual contact point.
        depth = float(self.player_home.z) if depth_lock_to_home else min(BACK_BASELINE, float(contact["x"]) + depth_offset)
        return Vec3(lateral, self.return_player.y, depth)

    def clear_entities(self):
        self.stop_animation()
        self._active_plan = None
        self._planned_returns.clear()
        self._pending_requests.clear()
        self._handled_ball_ids.clear()
        self._player_returned_home_pulse = False
        self.player_state = "idle"
        self.return_player.position = self.player_home
        self._player_speed_now = 0.0
        for anim in self._active_return_animations:
            for t in anim.get("trails", []):
                destroy(t)
            e = anim.get("entity")
            if e is not None:
                destroy(e)
        self._active_return_animations.clear()
        for e in list(self.game_state.return_trails):
            destroy(e)
        self.game_state.return_trails.clear()

    def stop_animation(self):
        for anim in self._active_return_animations:
            anim["landed"] = True
            anim["clear_timer"] = 0.0

    def _choose_target_point(self, incoming_landing):
        in_x = incoming_landing["x"]
        in_y = incoming_landing["y"]

        if in_x > NET_X + 4.0:
            profile = "clear"
        elif in_x > NET_X + 2.1:
            profile = "drive"
        else:
            profile = "lift"
        target = dict(RETURN_DEFAULT_TARGETS[profile])

        # Mirror lateral side for "opposite side" behavior.
        if abs(in_y) < 0.35:
            ty = 0.0
        else:
            ty = -in_y
            ty = max(min(ty, SINGLES_HALF_W - 0.35), -(SINGLES_HALF_W - 0.35))

        target["y"] = ty
        return profile, target

    def _resolve_profile_target_and_contact(self, landing, policy):
        profile, auto_target = self._choose_target_point(landing)
        target = dict(auto_target)

        if not isinstance(policy, dict):
            return profile, target, self._resolve_contact_cfg(profile, None)

        p = policy.get("profile")
        if isinstance(p, str):
            p = p.strip().lower()
        if p in ("clear", "drive", "lift", "drop", "block", "net_soft", "smash"):
            profile = p
        elif p is not None:
            self._debug(f"unknown return profile '{p}', fallback to auto profile '{profile}'")

        # Strict policy contract:
        # when a policy exists, target must be explicitly provided in global coordinates
        # (x=width, y=depth), then converted into physics coordinates.
        custom_target = policy.get("target")
        if not isinstance(custom_target, dict):
            return None, None, None

        gx = custom_target.get("x")
        gy = custom_target.get("y")
        if gx is None or gy is None:
            return None, None, None

        try:
            target["x"] = float(gy)  # physics depth
            target["y"] = float(gx)  # physics width
        except Exception:
            return None, None, None

        target["x"] = max(-BACK_BASELINE, min(BACK_BASELINE, target["x"]))
        target["y"] = max(-SINGLES_HALF_W, min(SINGLES_HALF_W, target["y"]))

        if policy.get("lateral_mode") is not None:
            self._debug("lateral_mode is ignored; using explicit target only")
        if policy.get("side") is not None:
            self._debug("side is ignored; using explicit target only")

        return profile, target, self._resolve_contact_cfg(profile, policy)

    def _resolve_contact_cfg(self, profile, policy):
        defaults = RETURN_PROFILES
        default_profile = defaults.get(profile) or defaults.get("clear") or {}
        range_vals = default_profile.get("height_range_m") or [0.65, 2.50]
        offset_vals = default_profile.get("contact_offset_m")
        if not isinstance(offset_vals, dict) or "x" not in offset_vals or "y" not in offset_vals:
            raise ValueError(f"RETURN_PROFILES['{profile}'] must define contact_offset_m.x and contact_offset_m.y")
        cfg = {
            "height_min": float(range_vals[0]),
            "height_max": float(range_vals[1]),
            "contact_offset": {"x": float(offset_vals.get("x", 0.0)), "y": float(offset_vals.get("y", 0.0))},
            "depth_lock_to_home": bool(default_profile.get("depth_lock_to_home", False)),
        }

        # Deprecated policy fields (ignored for deterministic profile behavior).
        if isinstance(policy, dict):
            if policy.get("contact_mode") is not None:
                self._debug("contact_mode is ignored; contact behavior is profile-defined")
            if policy.get("contact_height_min") is not None or policy.get("contact_height_max") is not None:
                self._debug("contact_height_min/max are ignored; constraints are profile-defined")
            if (
                policy.get("contact_offset") is not None
                or policy.get("contact_side_offset") is not None
                or policy.get("contact_back_offset") is not None
                or policy.get("contact_depth_offset") is not None
                or policy.get("contact_lateral_offset") is not None
            ):
                self._debug("contact offset fields are ignored; define a separate profile instead")

        cfg["height_min"] = max(0.05, float(cfg["height_min"]))
        cfg["height_max"] = min(4.0, float(cfg["height_max"]))
        if cfg["height_min"] > cfg["height_max"]:
            cfg["height_min"], cfg["height_max"] = cfg["height_max"], cfg["height_min"]
        return cfg

    def _pick_contact_point(self, points, preferred_profile=None, contact_cfg=None):
        if not points:
            return None

        min_h = float((contact_cfg or {}).get("height_min", 0.65))
        max_h = float((contact_cfg or {}).get("height_max", 2.50))
        offset = (contact_cfg or {}).get("contact_offset") or {}
        depth_lock_to_home = bool((contact_cfg or {}).get("depth_lock_to_home", False))

        if depth_lock_to_home:
            target_depth = float(self.player_home.z) - float(offset.get("y", 0.0))
            for i in range(len(points) - 1):
                p0 = points[i]
                p1 = points[i + 1]
                x0, y0, z0, vx0, vy0, vz0, t0 = p0
                x1, y1, z1, vx1, vy1, vz1, t1 = p1
                if vz0 >= 0 and vz1 >= 0:
                    continue
                if (x0 - target_depth) * (x1 - target_depth) > 0:
                    continue
                if x1 == x0:
                    continue
                w = (target_depth - x0) / (x1 - x0)
                if w < 0.0 or w > 1.0:
                    continue
                z = z0 + (z1 - z0) * w
                if min_h <= z <= max_h:
                    y = y0 + (y1 - y0) * w
                    t = t0 + (t1 - t0) * w
                    return {"x": target_depth, "y": y, "z": z, "t": t}
            return None

        # Contact must be a point from the serve trajectory. Offset only affects player reach.
        for p in points:
            x, y, z, vx, vy, vz, _t = p
            if x <= NET_X + 0.7:
                continue
            if vz >= 0:
                continue
            if min_h <= z <= max_h:
                return {"x": x, "y": y, "z": z, "t": _t}

        return None

    def _classify_serve_type(self, landing):
        lx = landing["x"]
        ly = landing["y"]

        if lx > NET_X + 4.0:
            depth = "back"
        elif lx > NET_X + 2.1:
            depth = "mid"
        else:
            depth = "front"

        if ly < -0.45:
            side = "left"
        elif ly > 0.45:
            side = "right"
        else:
            side = "center"

        return depth, side

    def register_ball(self, ball_obj, precomputed_return=None, allow_runtime_solve=True, return_policy=None):
        if not self.enabled or self.game_state.serve_mode != 1:
            return False
        if ball_obj is None:
            return False

        ball_id = id(ball_obj)
        if ball_id in self._handled_ball_ids:
            return False

        if precomputed_return is not None:
            plan = self._build_plan_from_solution(
                ball_obj=ball_obj,
                contact=precomputed_return["contact"],
                target=precomputed_return["target"],
                sol=precomputed_return["solution"],
                profile=precomputed_return.get("profile") or (precomputed_return.get("solution") or {}).get("profile"),
            )
            self._planned_returns.append(plan)
            self._planned_returns.sort(key=lambda p: p["move_start_t"])
            self._handled_ball_ids.add(ball_id)
            return True

        if not allow_runtime_solve:
            self._debug("playback skip: no precomputed return solution")
            self._handled_ball_ids.add(ball_id)
            return False

        points = getattr(ball_obj, "points", [])
        landing = {"x": points[-1][0], "y": points[-1][1]} if points else None
        if not landing:
            self._handled_ball_ids.add(ball_id)
            return False

        profile, target, contact_cfg = self._resolve_profile_target_and_contact(landing, return_policy)
        if profile is None or target is None:
            self.ui.update_return_info("Return skipped: return policy target missing/invalid")
            self._handled_ball_ids.add(ball_id)
            return False
        contact = self._pick_contact_point(points, preferred_profile=profile, contact_cfg=contact_cfg)
        if not contact:
            self.ui.update_return_info(f"Return failed: {self._format_return_attempt(profile, target)} (no playable contact)")
            self._handled_ball_ids.add(ball_id)
            return False

        serve_dt = 0.01
        if len(points) >= 2:
            est_dt = points[1][6] - points[0][6]
            if est_dt > 0:
                serve_dt = est_dt

        request = {
            "ball_id": ball_id,
            "ball": ball_obj,
            "contact": contact,
            "target": target,
            "profile": profile,
            "contact_cfg": contact_cfg,
            "serve_dt": serve_dt,
        }
        self._pending_requests.append(request)
        if len(self._pending_requests) > 4:
            # Keep planning close to realtime under heavy serve rates.
            self._pending_requests = self._pending_requests[-4:]
        self._handled_ball_ids.add(ball_id)
        return True

    def precompute_return_for_serve(self, speed_mps, yaw_deg, pitch_deg, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT, return_policy=None):
        t0 = time.perf_counter()
        sim = simulate_trajectory(
            speed_mps=speed_mps,
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
        )
        points = sim.get("points", [])
        if not points:
            return None

        landing = {"x": points[-1][0], "y": points[-1][1]}
        profile, target, contact_cfg = self._resolve_profile_target_and_contact(landing, return_policy)
        if profile is None or target is None:
            return None
        contact = self._pick_contact_point(points, preferred_profile=profile, contact_cfg=contact_cfg)
        if not contact:
            return None
        serve_type = self._classify_serve_type(landing)
        cache_key = (
            serve_type[0],
            serve_type[1],
            round(float(speed_mps), 2),
            round(float(yaw_deg), 2),
            round(float(pitch_deg), 2),
            profile,
            round(target["x"], 2),
            round(target["y"], 2),
        )

        cached = self._precompute_cache.get(cache_key)
        if cached is not None:
            self._debug(
                f"precompute cache-hit key={cache_key} serve=({speed_mps:.2f},{yaw_deg:.2f},{pitch_deg:.2f}) "
                f"elapsed_ms={(time.perf_counter() - t0) * 1000:.2f}"
            )
            return pycopy.deepcopy(cached)

        serve_dt = 0.01
        if len(points) >= 2:
            est_dt = points[1][6] - points[0][6]
            if est_dt > 0:
                serve_dt = est_dt

        stats = {}
        tol_xy, precompute_iters, _runtime_iters = self._solver_params_for_profile(profile)
        sol = solve_return_to_target(
            start_xyz=(contact["x"], contact["y"], contact["z"]),
            target_xyz=(target["x"], target["y"], target["z"]),
            shot_profile=profile,
            tol_xy=tol_xy,
            max_iter_speed=precompute_iters,
            debug_stats=stats,
        )
        if not sol or not sol.get("sim"):
            self._debug(
                "precompute no-solution "
                f"serve=({speed_mps:.2f},{yaw_deg:.2f},{pitch_deg:.2f}) "
                f"profile={profile} target=({target['x']:.2f},{target['y']:.2f}) "
                f"stats={stats} elapsed_ms={(time.perf_counter() - t0) * 1000:.2f}"
            )
            return None

        sim_points = sol["sim"].get("points", [])
        sol["sim"]["points"] = self._downsample_points(sim_points, serve_dt * RETURN_ANIMATION["point_step_mult"])
        sol["contact_cfg"] = pycopy.deepcopy(contact_cfg)

        result = {
            "contact": contact,
            "target": target,
            "solution": sol,
            "profile": profile,
            "contact_cfg": pycopy.deepcopy(contact_cfg),
        }

        self._precompute_cache[cache_key] = pycopy.deepcopy(result)
        if len(self._precompute_cache) > RETURN_RUNTIME["precompute_cache_max"]:
            oldest_key = next(iter(self._precompute_cache))
            del self._precompute_cache[oldest_key]

        self._debug(
            "precompute solved "
            f"serve=({speed_mps:.2f},{yaw_deg:.2f},{pitch_deg:.2f}) "
            f"profile={profile} target=({target['x']:.2f},{target['y']:.2f}) "
            f"stats={stats} elapsed_ms={(time.perf_counter() - t0) * 1000:.2f}"
        )

        return result

    def _downsample_points(self, points, step_t):
        if not points or step_t <= 0:
            return points

        sampled = [points[0]]
        next_t = points[0][6] + step_t
        for p in points[1:-1]:
            if p[6] + 1e-9 >= next_t:
                sampled.append(p)
                next_t = p[6] + step_t

        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled

    def _solver_params_for_profile(self, profile):
        # Net shots need tighter landing tolerance to avoid spilling outside singles width.
        if profile == "net_soft":
            return 0.16, 20, 16
        if profile == "lift":
            return 0.32, 16, 12
        if profile == "smash":
            return 0.32, 12, 10
        return 0.32, 8, 6

    def _solve_one_pending_request(self):
        if not self.enabled or self.game_state.serve_mode != 1:
            self._pending_requests.clear()
            return
        if not self._pending_requests:
            return
        if self._solve_cooldown > 0.0:
            return

        req = self._pending_requests.pop(0)
        ball = req["ball"]
        if ball not in self.game_state.active_balls:
            return

        t0 = time.perf_counter()
        stats = {}
        tol_xy, _precompute_iters, runtime_iters = self._solver_params_for_profile(req["profile"])
        sol = solve_return_to_target(
            start_xyz=(req["contact"]["x"], req["contact"]["y"], req["contact"]["z"]),
            target_xyz=(req["target"]["x"], req["target"]["y"], req["target"]["z"]),
            shot_profile=req["profile"],
            tol_xy=tol_xy,
            max_iter_speed=runtime_iters,
            debug_stats=stats,
        )

        if not sol or not sol.get("sim"):
            self.ui.update_return_info(
                f"Return failed: {self._format_return_attempt(req['profile'], req['target'])} (no valid trajectory)"
            )
            self._debug(
                "runtime no-solution "
                f"profile={req['profile']} target=({req['target']['x']:.2f},{req['target']['y']:.2f}) "
                f"stats={stats} elapsed_ms={(time.perf_counter() - t0) * 1000:.2f}"
            )
            self._solve_cooldown = self._min_solve_interval
            return False

        sim_points = sol["sim"].get("points", [])
        sol["sim"]["points"] = self._downsample_points(sim_points, req["serve_dt"] * RETURN_ANIMATION["point_step_mult"])
        sol["contact_cfg"] = pycopy.deepcopy(req.get("contact_cfg") or {})

        contact = req["contact"]
        target = req["target"]
        ball_id = req["ball_id"]

        plan = self._build_plan_from_solution(ball_obj=ball, contact=contact, target=target, sol=sol, profile=req["profile"])

        self._planned_returns.append(plan)
        self._planned_returns.sort(key=lambda p: p["move_start_t"])
        self._debug(
            "runtime solved "
            f"profile={req['profile']} target=({req['target']['x']:.2f},{req['target']['y']:.2f}) "
            f"stats={stats} elapsed_ms={(time.perf_counter() - t0) * 1000:.2f}"
        )
        self._solve_cooldown = self._min_solve_interval

    def _activate_due_plan(self):
        if self._active_plan is not None or self.player_state != "idle":
            return

        for plan in self._planned_returns:
            if plan["state"] != "scheduled":
                continue
            ball = plan["ball"]
            if ball not in self.game_state.active_balls:
                plan["state"] = "expired"
                continue
            if ball.simulation_time + 1e-6 < plan["move_start_t"]:
                continue

            self._active_plan = plan
            plan["state"] = "moving"
            contact = plan["contact"]
            self._player_target = self._intercept_position_from_contact(
                contact,
                profile=plan.get("profile"),
                contact_cfg=plan.get("contact_cfg"),
            )
            self.player_state = "move_to_intercept"
            return

    def _try_launch_active_plan(self):
        if self._active_plan is None or self.player_state not in ("move_to_intercept", "wait_contact"):
            return

        ball = self._active_plan["ball"]
        if ball not in self.game_state.active_balls:
            self._active_plan["state"] = "expired"
            self._active_plan = None
            self.player_state = "recover"
            self._player_target = self.player_home
            return

        if ball.simulation_time + 1e-6 < self._active_plan["contact_t"]:
            return

        self._start_return_from_active_plan()

    def _prune_plans(self):
        kept = []
        for plan in self._planned_returns:
            if plan is self._active_plan:
                kept.append(plan)
                continue
            if plan["state"] in ("done", "expired"):
                continue
            kept.append(plan)
        self._planned_returns = kept

    def _move_player(self):
        if self.player_state not in ("move_to_intercept", "recover"):
            return

        current = self.return_player.position
        target = self._player_target
        delta = target - current
        dist = delta.length()
        if dist < 0.03:
            self.return_player.position = target
            self._player_speed_now = 0.0
            if self.player_state == "move_to_intercept":
                self.player_state = "wait_contact"
            else:
                self.player_state = "idle"
                self._player_returned_home_pulse = True
            return

        dt = max(1e-6, float(time.dt))
        accel = max(0.1, float(self.player_accel))
        decel = max(0.1, float(self.player_decel))
        vmax = max(0.1, float(self.player_max_speed))

        # Braking-speed envelope:
        # stop_speed = sqrt(2 * decel * remaining_distance)
        # target speed is min(vmax, stop_speed), giving:
        # long distance: accel -> cruise -> decel
        # short distance: accel -> decel
        stop_speed = math.sqrt(max(0.0, 2.0 * decel * dist))
        target_speed = min(vmax, stop_speed)

        if self._player_speed_now < target_speed:
            self._player_speed_now = min(target_speed, self._player_speed_now + accel * dt)
        else:
            self._player_speed_now = max(target_speed, self._player_speed_now - decel * dt)

        step = self._player_speed_now * dt
        move = delta.normalized() * min(step, dist)
        self.return_player.position = current + move

    def _start_return_from_active_plan(self):
        if not self._active_plan:
            self.player_state = "recover"
            self._player_target = self.player_home
            return

        plan = self._active_plan
        sol = plan["solution"]
        contact = plan["contact"]
        points = sol["sim"]["points"]
        ball = plan.get("ball")

        if SERVE_VISUAL["hide_after_return_contact"] and ball is not None and hasattr(ball, "hide_remaining_after_return_contact"):
            ball.hide_remaining_after_return_contact()

        return_entity = Entity(
            model="sphere",
            scale=0.25,
            color=color.orange,
            position=(contact["y"], contact["z"], contact["x"]),
        )
        self._active_return_animations.append(
            {
                "entity": return_entity,
                "points": points,
                "time": 0.0,
                "trail_timer": 0.0,
                "landed": False,
                "clear_timer": None,
                "trails": [],
            }
        )

        plan["state"] = "launched"

        target = plan["target"]
        info = (
            f"Return {sol['profile']} | "
            f"to x={target['x']:.2f}, y={target['y']:.2f} | "
            f"speed={sol['speed']:.1f}, pitch={sol['pitch_deg']:.1f}"
        )
        self.ui.update_return_info(info)

        # Planner handoff: after launch, free active slot so next return plan can be scheduled.
        self._active_plan = None
        self.player_state = "recover"
        self._player_target = self.player_home

    def update_animation(self):
        # Dynamic return driver called once per frame from main.update
        if self._solve_cooldown > 0.0:
            self._solve_cooldown = max(0.0, self._solve_cooldown - time.dt)

        if self.enabled and self.game_state.serve_mode == 1:
            self._solve_one_pending_request()

        if self.enabled and self.game_state.serve_mode == 1:
            self._activate_due_plan()

        self._move_player()

        if self.enabled and self.game_state.serve_mode == 1:
            self._try_launch_active_plan()

        self._prune_plans()

        to_remove = []
        for anim in self._active_return_animations:
            entity = anim.get("entity")
            if entity is None:
                to_remove.append(anim)
                continue

            if not anim.get("landed", False):
                anim["time"] += time.dt
                points = anim["points"]
                advanced = False

                for i in range(len(points) - 1):
                    curr_t = points[i][6]
                    next_t = points[i + 1][6]

                    if curr_t <= anim["time"] < next_t:
                        frac = (anim["time"] - curr_t) / (next_t - curr_t)
                        curr_pos = points[i]
                        next_pos = points[i + 1]

                        x = curr_pos[0] + frac * (next_pos[0] - curr_pos[0])
                        y = curr_pos[1] + frac * (next_pos[1] - curr_pos[1])
                        z = curr_pos[2] + frac * (next_pos[2] - curr_pos[2])
                        entity.position = (y, z, x)

                        anim["trail_timer"] += time.dt
                        if anim["trail_timer"] >= RETURN_ANIMATION["trail_interval"]:
                            trail = Entity(model="sphere", scale=0.1, color=color.orange, position=entity.position)
                            anim["trails"].append(trail)
                            self.game_state.return_trails.append(trail)
                            anim["trail_timer"] -= RETURN_ANIMATION["trail_interval"]
                        advanced = True
                        break

                if not advanced:
                    final_pos = points[-1]
                    entity.position = (final_pos[1], final_pos[2], final_pos[0])
                    anim["landed"] = True
                    anim["clear_timer"] = RETURN_ANIMATION["trail_clear_delay"]
            else:
                anim["clear_timer"] = max(0.0, (anim.get("clear_timer") or 0.0) - time.dt)
                if anim["clear_timer"] <= 0.0:
                    for t in anim.get("trails", []):
                        destroy(t)
                        if t in self.game_state.return_trails:
                            self.game_state.return_trails.remove(t)
                    destroy(entity)
                    to_remove.append(anim)

        for anim in to_remove:
            if anim in self._active_return_animations:
                self._active_return_animations.remove(anim)
