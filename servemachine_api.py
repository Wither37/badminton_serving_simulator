# app/api/machine.py
import os
import json
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
from fastapi import APIRouter, Query, HTTPException

from pydantic import BaseModel

class MachineShot(BaseModel):
    speed: float
    yaw: float
    pitch: float
    delay_ms: int
    description: Optional[str] = None


class FeederSequenceRunRequest(BaseModel):
    call_id: Optional[str] = None 
    shots: List[MachineShot]
    repeat: int = 0
    repeat_gap_ms: int = 0
    stop_on_event: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None

router = APIRouter(prefix="/machine", tags=["machine"])

MQTT_BROKER = os.getenv("MQTT_BROKER", "140.113.213.131")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1884))
DEFAULT_DEVICE = os.getenv("DEFAULT_DEVICE", "MachineA")

mqtt_client = mqtt.Client()

_mqtt_connected = False

def _on_connect(client, userdata, flags, rc):
    global _mqtt_connected
    _mqtt_connected = (rc == 0)
    print(f"[MQTT] on_connect rc={rc} connected={_mqtt_connected}")

def _on_disconnect(client, userdata, rc):
    global _mqtt_connected
    _mqtt_connected = False
    print(f"[MQTT] on_disconnect rc={rc} connected={_mqtt_connected}")

mqtt_client.on_connect = _on_connect
mqtt_client.on_disconnect = _on_disconnect

def init_mqtt() -> None:
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[MQTT] connect() called to {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        print(f"[MQTT] connect failed: {e}")

init_mqtt()

def ensure_connected() -> bool:
    try:
        if mqtt_client.is_connected():
            return True
        try:
            mqtt_client.reconnect()
        except Exception:
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        return mqtt_client.is_connected()
    except Exception as e:
        print(f"[MQTT] ensure_connected error: {e}")
        return False

def publish_mqtt(topic: str, payload: dict) -> bool:
    try:
        if not ensure_connected():
            print(f"[MQTT] publish blocked: not connected topic={topic}")
            return False
        info = mqtt_client.publish(topic, json.dumps(payload))
        print(f"[MQTT] publish topic={topic} rc={info.rc} mid={info.mid} connected={mqtt_client.is_connected()}")
        return info.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception as e:
        print(f"[MQTT] publish error: {e}")
        return False


def _sequence_to_iot_menu_payload(req: FeederSequenceRunRequest) -> dict:
    """
    Convert FeederSequenceRunRequest to new IoT/menu format with correct drill structure.
    """
    meta = req.meta or {}
    menu_name = (
        meta.get("menuName")
        or meta.get("menu_name")
        or (f"Sequence {req.call_id}" if req.call_id else "Sequence")
    )
    
    description = meta.get("description", "Auto-generated training sequence")
    repeat_menu = req.repeat if (req.repeat and req.repeat > 0) else 1
    
    # Convert shots to drill actions
    actions = []
    for i, shot in enumerate(req.shots):
        action = {
            "actionId": f"A{i:03d}",
            "actionType": "shot", 
            "description": shot.description or f"Shot {i+1}",
            "repeatAction": 1,  # Each shot is executed once per drill set
            "delayBeforeShotSeconds": shot.delay_ms / 1000.0 if shot.delay_ms else 0,
            "shotParameters": {
                "targetPosition": {
                    "x": getattr(shot, 'target_x', 0.0),
                    "y": getattr(shot, 'target_y', 0.0), 
                    "z": getattr(shot, 'target_z', 2.0)
                },
                "ballSpeed": shot.speed,
                "ballAngle": getattr(shot, 'angle', shot.pitch)  # Use angle if available, fallback to pitch
            }
        }
        actions.append(action)
    
    # Create a single drill set containing all actions
    drill = {
        "drillSetName": f"{menu_name} - Main Set",
        "repeatSet": 1,
        "actions": actions
    }
    
    # Apply repeat_gap_ms as delay after the last action if specified
    if req.repeat_gap_ms and req.repeat_gap_ms > 0 and actions:
        actions[-1]["delayBeforeShotSeconds"] += req.repeat_gap_ms / 1000.0

    return {
        "schema_version": 1,
        "call_id": req.call_id,
        "action": "start",
        "menu": {
            "menuName": menu_name,
            "description": description,
            "dateCreated": "2026-02-04",  # Current date
            "repeatMenu": repeat_menu,
            "drills": [drill]
        },
    }


@router.get("/machine_status")
async def machine_status(
    machine_id: str | None = Query(None),
):
    return {
        "online": True,
        "remaining_time_sec": 120,
    }


@router.post("/start_program")
async def start_program(
    req: FeederSequenceRunRequest,
    machine_id: str | None = Query(None),
):
    if not req.shots:
        raise HTTPException(status_code=400, detail="shots is empty")

    device = machine_id or DEFAULT_DEVICE
    topic = f"/CALL/{device}/IoT/menu"

    payload = _sequence_to_iot_menu_payload(req)

    ok = publish_mqtt(topic, payload)
    if not ok:
        return {"status": "error", "message": "MQTT 發送失敗"}

    return {
        "status": "success",
        "message": "已透過 MQTT 發送訓練指令（IoT/menu）",
        "topic": topic,
        "drills": len(payload["menu"]["drills"]),
        "call_id": payload.get("call_id"),
    }


# /CALL/{device}/Feeder/control
# payload = {"action":"pause|resume|stop|reset"...}

@router.post("/stop_program")
async def stop_program(
    machine_id: str | None = Query(None),
):
    device = machine_id or DEFAULT_DEVICE
    topic = f"/CALL/{device}/Feeder/control"
    payload = {"action": "stop"}

    ok = publish_mqtt(topic, payload)
    if not ok:
        return {"status": "error", "message": "MQTT 發送失敗"}

    return {"status": "success"}


@router.post("/resume_program")
async def resume_program(
    machine_id: str | None = Query(None),
):
    device = machine_id or DEFAULT_DEVICE
    topic = f"/CALL/{device}/Feeder/control"
    payload = {"action": "resume"}

    ok = publish_mqtt(topic, payload)
    if not ok:
        return {"status": "error", "message": "MQTT 發送失敗"}

    return {"status": "success"}


@router.post("/pause_program")
async def pause_program(
    machine_id: str | None = Query(None),
):
    device = machine_id or DEFAULT_DEVICE
    topic = f"/CALL/{device}/Feeder/control"
    payload = {"action": "pause"}

    ok = publish_mqtt(topic, payload)
    if not ok:
        return {"status": "error", "message": "MQTT 發送失敗"}

    return {"status": "success"}
