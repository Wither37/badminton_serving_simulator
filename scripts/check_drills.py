import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENUS_PATH = ROOT / "menus.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ursina import Vec3

from utils.config import (
    BACK_BASELINE,
    RETURN_PLAYER,
    SINGLES_HALF_W,
    SIMULATOR_DEFAULT_POSITION,
)
from utils.physics import simulate_trajectory, solve_return_to_target
from utils.return_solver import ReturnSolver


def global_to_physics(pos):
    # Global frame: x=width, y=depth, z=height
    # Physics frame: x=depth, y=width, z=height
    return (float(pos["y"]), float(pos["x"]), float(pos["z"]))


def _load_storage(path):
    if not path.exists():
        raise FileNotFoundError(f"menus.json not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        storage = json.load(f)
    if not isinstance(storage, dict) or not isinstance(storage.get("menus"), list):
        raise ValueError("menus.json must contain top-level key 'menus' as a list")
    return storage


def _resolve_menu_position(menu):
    payload_menu = (menu.get("payload") or {}).get("menu") or {}
    pos = payload_menu.get("simulator_position")
    if isinstance(pos, dict):
        return {
            "x": float(pos.get("x", SIMULATOR_DEFAULT_POSITION["x"])),
            "y": float(pos.get("y", SIMULATOR_DEFAULT_POSITION["y"])),
            "z": float(pos.get("z", SIMULATOR_DEFAULT_POSITION["z"])),
        }
    return dict(SIMULATOR_DEFAULT_POSITION)


def _runtime_drills(menu):
    payload_menu = (menu.get("payload") or {}).get("menu") or {}
    drills = deepcopy(payload_menu.get("drills") or [])
    menu_pos = payload_menu.get("simulator_position")
    if isinstance(menu_pos, dict):
        for drill in drills:
            drill["simulator_position"] = deepcopy(menu_pos)

    sim_meta = menu.get("simulator") or {}
    default_policy = sim_meta.get("default_return_policy")
    overrides = sim_meta.get("drill_overrides") or {}
    for idx, drill in enumerate(drills):
        policy = deepcopy(default_policy) if isinstance(default_policy, dict) else None
        override = overrides.get(str(idx))
        if isinstance(override, dict) and isinstance(override.get("return_policy"), dict):
            policy = deepcopy(override["return_policy"])
        if policy is not None:
            drill["simulator_return_policy"] = policy
    return drills


def _select_menus(storage, selector):
    menus = storage.get("menus", [])
    tokens = [x.strip() for x in str(selector or "all").split(",") if x.strip()]
    if not tokens or "all" in {x.lower() for x in tokens}:
        return list(enumerate(menus))

    selected = []
    for token in tokens:
        matched = []
        if token.isdigit():
            idx = int(token)
            if 0 <= idx < len(menus):
                matched.append((idx, menus[idx]))
        for idx, menu in enumerate(menus):
            if token in (str(menu.get("id")), str(menu.get("call_id")), str(menu.get("menuName"))):
                matched.append((idx, menu))
        if not matched:
            raise ValueError(f"No menu matched selector '{token}'")
        for item in matched:
            if item not in selected:
                selected.append(item)
    return selected


def _select_indexes(drills, selector):
    if selector is None or str(selector).strip().lower() == "all":
        return set(range(len(drills)))
    selected = set()
    for token in str(selector).split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            start_i = int(start)
            end_i = int(end)
            selected.update(range(start_i, end_i + 1))
        else:
            selected.add(int(token))
    return {idx for idx in selected if 0 <= idx < len(drills)}


def _make_solver():
    solver = ReturnSolver.__new__(ReturnSolver)
    home = RETURN_PLAYER["home"]
    movement = RETURN_PLAYER["movement"]
    solver.player_home = Vec3(home["width"], home["height"], home["depth"])
    solver.return_player = type("ReturnPlayerStub", (), {"y": home["height"]})()
    solver.player_max_speed = float(movement["max_speed"])
    solver.player_accel = float(movement["accel"])
    solver.player_decel = float(movement["decel"])
    solver._precompute_cache = {}
    solver._debug = lambda _msg: None
    return solver


def _simulate_drill(menu, drill):
    pos = drill.get("simulator_position")
    if not isinstance(pos, dict):
        pos = _resolve_menu_position(menu)
    start_x, start_y, start_z = global_to_physics(pos)
    params = drill.get("parameters") or {}
    return simulate_trajectory(
        speed_mps=float(params.get("speed", 0.0)),
        yaw_deg=float(params.get("yaw", 0.0)),
        pitch_deg=float(params.get("pitch", 0.0)),
        start_x=start_x,
        start_y=start_y,
        start_z=start_z,
        refine_net=True,
        refine_heights=False,
        max_t=6.0,
    )


def _format_float(value, digits=3):
    if value is None:
        return "None"
    return str(round(float(value), digits))


def _return_failure_detail(solver, menu, drill, policy):
    pos = drill.get("simulator_position") or _resolve_menu_position(menu)
    start_x, start_y, start_z = global_to_physics(pos)
    params = drill.get("parameters") or {}
    serve = simulate_trajectory(
        speed_mps=float(params.get("speed", 0.0)),
        yaw_deg=float(params.get("yaw", 0.0)),
        pitch_deg=float(params.get("pitch", 0.0)),
        start_x=start_x,
        start_y=start_y,
        start_z=start_z,
        refine_net=True,
        refine_heights=False,
        max_t=6.0,
    )
    points = serve.get("points") or []
    if not points:
        return {"reason": "no_serve_points"}

    landing = {"x": points[-1][0], "y": points[-1][1]}
    profile, target, contact_cfg = solver._resolve_profile_target_and_contact(landing, policy)
    if profile is None or target is None:
        return {"reason": "invalid_policy"}

    contact = solver._pick_contact_point(points, preferred_profile=profile, contact_cfg=contact_cfg)
    if contact is None:
        return {"reason": "no_playable_contact", "profile": profile, "target": target}

    tol_xy, precompute_iters, _runtime_iters = solver._solver_params_for_profile(profile)
    stats = {}
    sol = solve_return_to_target(
        start_xyz=(contact["x"], contact["y"], contact["z"]),
        target_xyz=(target["x"], target["y"], target["z"]),
        shot_profile=profile,
        tol_xy=tol_xy,
        max_iter_speed=precompute_iters,
        debug_stats=stats,
    )
    detail = {
        "reason": "solver_rejected",
        "profile": profile,
        "target": target,
        "contact": contact,
        "tol_xy": tol_xy,
        "stats": stats,
    }
    if sol is not None:
        detail["solution"] = sol
    return detail


def check_serves(menu_items, indexes, min_clearance):
    failures = []
    summaries = []
    for menu_idx, menu in menu_items:
        drills = _runtime_drills(menu)
        selected = _select_indexes(drills, indexes)
        min_seen = None
        checked = 0
        for idx, drill in enumerate(drills):
            if idx not in selected:
                continue
            checked += 1
            sim = _simulate_drill(menu, drill)
            cross = sim.get("cross_net")
            land = sim.get("landing")
            clearance = None if cross is None else float(cross.get("clearance", 0.0))
            if clearance is not None:
                min_seen = clearance if min_seen is None else min(min_seen, clearance)
            landing_x = None if land is None else float(land.get("x", -99.0))
            if cross is None or land is None or clearance <= min_clearance or landing_x <= 0.2:
                failures.append((menu.get("id"), idx, clearance, landing_x))
        summaries.append((menu_idx, menu.get("id"), checked, min_seen))
    return summaries, failures


def check_returns(menu_items, indexes):
    solver = _make_solver()
    failures = []
    summaries = []
    for menu_idx, menu in menu_items:
        drills = _runtime_drills(menu)
        selected = _select_indexes(drills, indexes)
        checked = 0
        for idx, drill in enumerate(drills):
            if idx not in selected:
                continue
            policy = drill.get("simulator_return_policy")
            if not isinstance(policy, dict):
                continue
            checked += 1
            pos = drill.get("simulator_position") or _resolve_menu_position(menu)
            start_x, start_y, start_z = global_to_physics(pos)
            params = drill.get("parameters") or {}
            result = solver.precompute_return_for_serve(
                speed_mps=float(params.get("speed", 0.0)),
                yaw_deg=float(params.get("yaw", 0.0)),
                pitch_deg=float(params.get("pitch", 0.0)),
                start_x=start_x,
                start_y=start_y,
                start_z=start_z,
                return_policy=policy,
            )
            if result is None:
                failures.append(
                    (
                        menu.get("id"),
                        idx,
                        policy.get("profile"),
                        policy.get("target"),
                        "no_valid_solution",
                        _return_failure_detail(solver, menu, drill, policy),
                    )
                )
                continue

            solution = result.get("solution") or {}
            sim = solution.get("sim") or {}
            land = sim.get("landing")
            target = result.get("target") or {}
            profile = result.get("profile") or policy.get("profile")
            tol_xy, _precompute_iters, _runtime_iters = solver._solver_params_for_profile(profile)
            if not isinstance(land, dict):
                failures.append((menu.get("id"), idx, profile, policy.get("target"), "no_landing", None))
                continue

            err_x = abs(float(land["x"]) - float(target["x"]))
            err_y = abs(float(land["y"]) - float(target["y"]))
            in_bounds = abs(float(land["y"])) <= SINGLES_HALF_W and -BACK_BASELINE <= float(land["x"]) <= BACK_BASELINE
            if err_x > tol_xy or err_y > tol_xy or not in_bounds:
                failures.append(
                    (
                        menu.get("id"),
                        idx,
                        profile,
                        policy.get("target"),
                        "landing_invalid",
                        {
                            "landing_global": {"x": land["y"], "y": land["x"]},
                            "target_global": {"x": target["y"], "y": target["x"]},
                            "err_depth": err_x,
                            "err_width": err_y,
                            "tol_xy": tol_xy,
                            "in_singles": in_bounds,
                        },
                    )
                )
        summaries.append((menu_idx, menu.get("id"), checked))
    return summaries, failures


def check_movement(menu_items, indexes):
    solver = _make_solver()
    failures = []
    summaries = []
    for menu_idx, menu in menu_items:
        drills = _runtime_drills(menu)
        selected = _select_indexes(drills, indexes)
        checked = 0
        for idx, drill in enumerate(drills):
            if idx not in selected:
                continue
            policy = drill.get("simulator_return_policy")
            if not isinstance(policy, dict):
                continue

            checked += 1
            sim = _simulate_drill(menu, drill)
            points = sim.get("points") or []
            if not points:
                failures.append((menu.get("id"), idx, None, "no_serve_points", None, None, None, None))
                continue

            landing = {"x": points[-1][0], "y": points[-1][1]}
            profile, _target, contact_cfg = solver._resolve_profile_target_and_contact(landing, policy)
            if profile is None:
                failures.append((menu.get("id"), idx, None, "invalid_policy", None, None, None, None))
                continue

            contact = solver._pick_contact_point(points, preferred_profile=profile, contact_cfg=contact_cfg)
            if contact is None:
                failures.append((menu.get("id"), idx, profile, "no_contact", None, None, None, None))
                continue

            intercept = solver._intercept_position_from_contact(contact, profile=profile, contact_cfg=contact_cfg)
            dist = (intercept - solver.player_home).length()
            required = solver._travel_time_with_player_profile(dist)
            natural_start = max(0.0, float(contact["t"]) - required)
            move_start = min(natural_start, max(0.0, float(RETURN_PLAYER["reaction_delay"])))
            available = max(0.0, float(contact["t"]) - move_start)
            if required > available + 1e-6:
                failures.append(
                    (
                        menu.get("id"),
                        idx,
                        profile,
                        "late",
                        dist,
                        required,
                        available,
                        float(contact["t"]),
                    )
                )
        summaries.append((menu_idx, menu.get("id"), checked))
    return summaries, failures


def _print_serve_report(summaries, failures):
    print("Serve check:")
    for menu_idx, menu_id, checked, min_clearance in summaries:
        print(f"  [{menu_idx}] {menu_id}: checked={checked} min_clearance={_format_float(min_clearance)}")
    if failures:
        print("Serve failures:")
        for menu_id, idx, clearance, landing_x in failures:
            print(
                f"  {menu_id} idx={idx} clearance={_format_float(clearance)} "
                f"landing_x={_format_float(landing_x)}"
            )


def _print_return_report(summaries, failures):
    print("Return trajectory check:")
    for menu_idx, menu_id, checked in summaries:
        print(f"  [{menu_idx}] {menu_id}: checked_returns={checked}")
    if failures:
        print("Return failures:")
        for menu_id, idx, profile, target, reason, detail in failures:
            extra = ""
            if isinstance(detail, dict):
                if "landing_global" in detail:
                    extra = (
                        f" landing={detail['landing_global']} target={detail['target_global']} "
                        f"err_depth={_format_float(detail['err_depth'])} "
                        f"err_width={_format_float(detail['err_width'])} "
                        f"tol={_format_float(detail['tol_xy'])} in_singles={detail['in_singles']}"
                    )
                elif "stats" in detail:
                    stats = detail.get("stats") or {}
                    best = stats.get("best_candidate") or {}
                    landing = best.get("landing") or {}
                    target_phys = best.get("target") or detail.get("target") or {}
                    extra = (
                        f" solver_reason={detail.get('reason')} "
                        f"tested={stats.get('tested')} candidates={stats.get('candidate_updates')} "
                        f"apex_reject={stats.get('apex_reject')} "
                        f"flight_reject={stats.get('flight_time_reject')} "
                        f"clear_low={stats.get('clearance_low_reject')} "
                        f"clear_high={stats.get('clearance_high_reject')} "
                        f"short_zone_reject={stats.get('short_zone_reject')} "
                        f"net_shape_reject={stats.get('net_shape_reject')} "
                        f"tolerance_reject={stats.get('tolerance_reject')}"
                    )
                    if best:
                        extra += (
                            f" best_pitch={best.get('pitch_deg')} "
                            f"best_speed={_format_float(best.get('speed'))} "
                            f"best_landing_global={{'x': {_format_float(landing.get('y'))}, 'y': {_format_float(landing.get('x'))}}} "
                            f"best_target_global={{'x': {_format_float(target_phys.get('y'))}, 'y': {_format_float(target_phys.get('x'))}}} "
                            f"best_err_depth={_format_float(best.get('error_x'))} "
                            f"best_err_width={_format_float(best.get('error_y'))} "
                            f"tol={_format_float(detail.get('tol_xy'))} "
                            f"clearance={_format_float(best.get('clearance'))} "
                            f"apex_z={_format_float(best.get('apex_z'))}"
                        )
            print(f"  {menu_id} idx={idx} profile={profile} reason={reason} target={target}{extra}")


def _print_movement_report(summaries, failures):
    print("Movement check:")
    for menu_idx, menu_id, checked in summaries:
        print(f"  [{menu_idx}] {menu_id}: checked_returns={checked}")
    if failures:
        print("Movement timing issues:")
        for menu_id, idx, profile, reason, dist, required, available, contact_t in failures:
            detail = (
                f"move_dist={_format_float(dist)} required_t={_format_float(required)} "
                f"available_t={_format_float(available)} contact_t={_format_float(contact_t)}"
            )
            print(f"  {menu_id} idx={idx} profile={profile} reason={reason} {detail}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate existing menus.json drills against current physics and return config."
    )
    parser.add_argument(
        "--menus",
        default="all",
        help="Comma-separated menu selectors: all, zero-based menu index, id, call_id, or exact menuName.",
    )
    parser.add_argument(
        "--indexes",
        default="all",
        help="Comma-separated drill row indexes or ranges within each selected menu, e.g. all, 0,2,4-7.",
    )
    parser.add_argument(
        "--mode",
        choices=("check-serves", "check-solves", "check-returns", "check-return", "check-movement", "check-all"),
        default="check-serves",
        help="Checks are read-only and never write menus.json.",
    )
    parser.add_argument(
        "--min-clearance",
        type=float,
        default=0.03,
        help="Minimum serve net clearance for check-serves.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the selected check reports failures.",
    )
    args = parser.parse_args()

    storage = _load_storage(MENUS_PATH)
    selected = _select_menus(storage, args.menus)
    mode = {
        "check-solves": "check-serves",
        "check-return": "check-returns",
    }.get(args.mode, args.mode)

    any_failures = False
    if mode in ("check-serves", "check-all"):
        summaries, failures = check_serves(selected, args.indexes, args.min_clearance)
        _print_serve_report(summaries, failures)
        any_failures = any_failures or bool(failures)

    if mode in ("check-returns", "check-all"):
        summaries, failures = check_returns(selected, args.indexes)
        _print_return_report(summaries, failures)
        any_failures = any_failures or bool(failures)

    if mode in ("check-movement", "check-all"):
        summaries, failures = check_movement(selected, args.indexes)
        _print_movement_report(summaries, failures)
        any_failures = any_failures or bool(failures)

    if args.strict and any_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
