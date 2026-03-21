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

MQTT_BROKER = 'broker.emqx.io'
MQTT_PORT = 1883
DEFAULT_DEVICE = 'Badminton_simulator'

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
        IoT/menu payload。
        menu = { menuName, drills:[{parameters:{speed,yaw,pitch}, interval}, ...] }
    """
    meta = req.meta or {}
    menu_name = (
        meta.get("menuName")
        or meta.get("menu_name")
        or (f"Sequence {req.call_id}" if req.call_id else "Sequence")
    )

    base_drills: List[Dict[str, Any]] = []
    for s in req.shots:
        base_drills.append(
            {
                "parameters": {
                    "speed": s.speed,
                    "yaw": s.yaw,
                    "pitch": s.pitch,
                },
                "interval": int(s.delay_ms),
            }
        )

    cycles = req.repeat if (req.repeat and req.repeat > 0) else 1
    gap_ms = int(req.repeat_gap_ms or 0)

    drills: List[Dict[str, Any]] = []
    for i in range(cycles):
        one_cycle = [
            {
                "parameters": dict(d["parameters"]),
                "interval": int(d["interval"]),
            }
            for d in base_drills
        ]

        if one_cycle and gap_ms > 0 and i < cycles - 1:
            one_cycle[-1]["interval"] += gap_ms

        drills.extend(one_cycle)

    return {
        "schema_version": 1,
        "call_id": req.call_id,
        "action": "start",
        "menu": {
            "menuName": menu_name,
            "drills": drills,
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
