"""Menu storage and retrieval system for badminton simulator."""
import copy
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any

STORAGE_FILE = "menus.json"
MAX_STORED_MENUS = 9
RETURN_POLICY_PROFILES = ("clear", "drive", "lift", "drop", "block", "net_soft", "smash")


def _normalize_storage(storage: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure storage has expected top-level keys and valid values."""
    if not isinstance(storage, dict):
        storage = {}

    menus = storage.get("menus")
    if not isinstance(menus, list):
        menus = []

    storage["menus"] = menus
    storage["menu_count"] = len(menus)
    return storage


def _load_storage() -> Dict[str, List[Dict[str, Any]]]:
    """Load menu storage from JSON file."""
    if not os.path.exists(STORAGE_FILE):
        return {"menus": [], "menu_count": 0}
    try:
        with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
            return _normalize_storage(json.load(f))
    except Exception as e:
        print(f"[MenuStorage] Error loading {STORAGE_FILE}: {e}")
        return {"menus": [], "menu_count": 0}


def _save_storage(storage: Dict[str, List[Dict[str, Any]]]) -> bool:
    """Save menu storage to JSON file."""
    storage = _normalize_storage(storage)
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(storage, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MenuStorage] Error saving {STORAGE_FILE}: {e}")
        return False


def save_menu(payload: Dict[str, Any]) -> str:
    """
    Save a menu from API/MQTT payload.
    
    Args:
        payload: Dict with 'call_id', 'menu' (menuName, drills, etc.), and optional 'meta'
    
    Returns:
        Menu ID (call_id or generated ID)
    """
    storage = _load_storage()
    
    # Extract key fields
    call_id = payload.get("call_id") or f"menu-{int(datetime.now().timestamp())}"
    menu_data = payload.get("menu") or {}
    meta = payload.get("meta") or {}
    
    menu_name = menu_data.get("menuName") or meta.get("menuName") or "Untitled Menu"
    description = menu_data.get("description") or meta.get("description") or ""
    
    # Check for duplicate call_id and overwrite
    existing = None
    for i, m in enumerate(storage["menus"]):
        if m["call_id"] == call_id:
            existing = i
            break
    
    menu_entry = {
        "id": call_id,
        "call_id": call_id,
        "menuName": menu_name,
        "description": description,
        "payload": payload,  # Store full payload for re-execution
        # Simulator-only metadata (local extension, never sent back to server).
        "simulator": {
            "schema_version": 1,
            "default_return_policy": None,
            "drill_overrides": {}
        },
        "timestamp": datetime.now().isoformat(),
        "source": "api"
    }

    if existing is not None:
        prev_sim = storage["menus"][existing].get("simulator")
        if isinstance(prev_sim, dict):
            menu_entry["simulator"] = prev_sim
    
    if existing is not None:
        # Overwrite existing
        storage["menus"][existing] = menu_entry
        print(f"[MenuStorage] Updated menu '{menu_name}' (id={call_id})")
    else:
        # Add new
        storage["menus"].append(menu_entry)
        print(f"[MenuStorage] Saved new menu '{menu_name}' (id={call_id})")

        # Keep only latest MAX_STORED_MENUS menus; remove oldest from top.
        while len(storage["menus"]) > MAX_STORED_MENUS:
            removed = storage["menus"].pop(0)
            print(f"[MenuStorage] Removed oldest menu '{removed['menuName']}' (id={removed['id']}) due to limit={MAX_STORED_MENUS}")

    storage["menu_count"] = len(storage["menus"])
    
    _save_storage(storage)
    return call_id


def load_menu(menu_id: str) -> Optional[Dict[str, Any]]:
    """Load a menu by ID."""
    storage = _load_storage()
    for menu in storage.get("menus", []):
        if menu["id"] == menu_id or menu["call_id"] == menu_id:
            return menu
    return None


def list_menus() -> List[Dict[str, Any]]:
    """List all stored menus with metadata."""
    storage = _load_storage()
    return [
        {
            "id": m["id"],
            "menuName": m["menuName"],
            "description": m["description"],
            "timestamp": m["timestamp"],
            "source": m.get("source", "unknown")
        }
        for m in storage.get("menus", [])
    ]


def get_menu_drills_for_simulator(menu_id: str) -> Optional[List[Dict[str, Any]]]:
    """Return simulator runtime drills with local-only overrides applied.

    This preserves original API payload shape while allowing local simulator metadata.
    """
    menu = load_menu(menu_id)
    if not menu:
        return None

    payload = menu.get("payload") or {}
    drills = (payload.get("menu") or {}).get("drills") or []
    runtime_drills = copy.deepcopy(drills)

    sim_meta = menu.get("simulator") or {}
    default_policy = sim_meta.get("default_return_policy")
    menu_simulator_position = (payload.get("menu") or {}).get("simulator_position")
    if not isinstance(menu_simulator_position, dict):
        menu_simulator_position = None
    drill_overrides = sim_meta.get("drill_overrides") or {}

    for idx, drill in enumerate(runtime_drills):
        policy = None

        if isinstance(default_policy, dict):
            policy = copy.deepcopy(default_policy)

        override = drill_overrides.get(str(idx))
        if isinstance(override, dict):
            override_policy = override.get("return_policy")
            if isinstance(override_policy, dict):
                policy = copy.deepcopy(override_policy)

        if policy is not None:
            drill["simulator_return_policy"] = policy
        if menu_simulator_position is not None:
            drill["simulator_position"] = copy.deepcopy(menu_simulator_position)

    return runtime_drills


def get_menu_drill_count(menu_id: str) -> int:
    """Return the number of drills in a stored menu."""
    menu = load_menu(menu_id)
    if not menu:
        return 0

    payload = menu.get("payload") or {}
    drills = (payload.get("menu") or {}).get("drills") or []
    return len(drills) if isinstance(drills, list) else 0


def _normalize_return_policy(policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and normalize a simulator return policy before saving it."""
    if not isinstance(policy, dict):
        return None

    profile = policy.get("profile")
    if isinstance(profile, str):
        profile = profile.strip().lower()
    if profile not in RETURN_POLICY_PROFILES:
        return None

    target = policy.get("target")
    if not isinstance(target, dict):
        return None

    try:
        target_x = float(target.get("x"))
        target_y = float(target.get("y"))
    except (TypeError, ValueError):
        return None

    normalized = {
        "profile": profile,
        "target": {
            "x": target_x,
            "y": target_y,
        },
    }

    for key in ("contact_depth_offset", "contact_lateral_offset"):
        if policy.get(key) is None:
            continue
        try:
            normalized[key] = float(policy.get(key))
        except (TypeError, ValueError):
            pass

    return normalized


def set_menu_return_policy(menu_id: str, policy: Dict[str, Any], drill_index: Optional[int] = None) -> bool:
    """Set a menu default return policy or one drill override in menus.json."""
    normalized_policy = _normalize_return_policy(policy)
    if normalized_policy is None:
        return False

    storage = _load_storage()
    for menu in storage.get("menus", []):
        if menu["id"] != menu_id and menu["call_id"] != menu_id:
            continue

        simulator = menu.get("simulator")
        if not isinstance(simulator, dict):
            simulator = {}
            menu["simulator"] = simulator

        simulator["schema_version"] = simulator.get("schema_version") or 1

        if drill_index is None:
            simulator["default_return_policy"] = normalized_policy
        else:
            try:
                idx = int(drill_index)
            except (TypeError, ValueError):
                return False

            if idx < 0 or idx >= get_menu_drill_count(menu_id):
                return False

            drill_overrides = simulator.get("drill_overrides")
            if not isinstance(drill_overrides, dict):
                drill_overrides = {}
                simulator["drill_overrides"] = drill_overrides

            drill_overrides[str(idx)] = {"return_policy": normalized_policy}

        return _save_storage(storage)

    return False


def delete_menu(menu_id: str) -> bool:
    """Delete a menu by ID."""
    storage = _load_storage()
    for i, menu in enumerate(storage.get("menus", [])):
        if menu["id"] == menu_id or menu["call_id"] == menu_id:
            removed = storage["menus"].pop(i)
            storage["menu_count"] = len(storage["menus"])
            _save_storage(storage)
            print(f"[MenuStorage] Deleted menu '{removed['menuName']}' (id={menu_id})")
            return True
    return False
