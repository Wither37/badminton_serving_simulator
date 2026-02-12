import paho.mqtt.client as mqtt
import json
import time
from queue import Queue

class MQTTSimulator:
    def __init__(
        self,
        broker="140.113.213.131",
        port=1884,
        # 你原本的命令主題（舊協議）
        command_topic="Machine_A",
        status_topic="app",
        serve_queue: Queue | None = None,
        # 新增：對應後端 device 名稱（後端 DEFAULT_DEVICE）
        device_name="MachineA",
    ):
        self.broker = broker
        self.port = port

        # 舊協議 topic（保留相容）
        self.command_topic = command_topic
        self.status_topic = status_topic

        # 新協議 topic（接後端）
        self.device_name = device_name
        self.menu_topic = f"/CALL/{self.device_name}/IoT/menu"
        self.control_topic = f"/CALL/{self.device_name}/Feeder/control"
        self.status_topic_new = f"/CALL/{self.device_name}/IoT/status"
        # 也可以用萬用字元一次訂閱：f"/CALL/{self.device_name}/#"

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        self.serve_queue = serve_queue
        if self.serve_queue is None:
            self.serve_queue = Queue()

        # 舊協議用的即時設定
        self.current_speed = 30.0
        self.current_yaw = 0.0
        self.current_pitch = 0.0

        # 控制狀態（新協議也會用到）
        self.is_stopped = False
        self.is_paused = False
        
        # 新協議：進度追蹤
        self.current_menu = None
        self.current_call_id = None
        self.total_drills = 0
        self.completed_drills = 0
        self.current_drill_index = 0
        self.machine_status = "ready"  # ready, executing, paused, stopped, error
        self.heartbeat_enabled = False  # 心跳功能預設關閉
        self.quiet_mode = True  # 安靜模式：預設啟用，減少狀態報告

    # -------------------------
    # MQTT callbacks
    # -------------------------
    def on_connect(self, client, userdata, flags, rc, properties):
        print("Simulator connected to MQTT broker with result code", rc)

        # 舊：訂閱命令主題與廣播主題
        client.subscribe(self.command_topic)
        client.subscribe("broadcast")

        # 新：訂閱後端會發的 topic
        client.subscribe(self.menu_topic)
        client.subscribe(self.control_topic)

        print("[SIM] subscribed:", self.command_topic, "broadcast", self.menu_topic, self.control_topic)
        
        # 新協議：報告連線狀態
        if rc == 0:
            self.machine_status = "ready"
            self.publish_new_status(status_type="connected", message="Simulator connected and ready")
        else:
            self.machine_status = "error"
            self.report_error("connection_failed", f"MQTT connection failed with code {rc}", connection_code=rc)

    def on_message(self, client, userdata, msg):
        payload_text = msg.payload.decode(errors="ignore")

        # 1) 新協議：後端送菜單（/IoT/menu）
        if msg.topic == self.menu_topic:
            self.handle_backend_menu(payload_text)
            return

        # 2) 新協議：後端控制（pause/resume/stop）
        if msg.topic == self.control_topic:
            self.handle_backend_control(payload_text)
            return

        # 3) 舊協議：broadcast / Machine_A（保留你原本的邏輯）
        if msg.topic == "broadcast":
            self.handle_broadcast(payload_text)
            return

        if msg.topic == self.command_topic:
            self.handle_legacy_command(payload_text)
            return

        print("Simulator received message on unknown topic:", msg.topic, payload_text)

    # -------------------------
    # 新協議：接後端菜單 -> 塞進 serve_queue
    # -------------------------
    def handle_backend_menu(self, payload_text: str):
        try:
            data = json.loads(payload_text)
        except Exception as e:
            self.report_error("invalid_json", f"Menu payload is not valid JSON: {e}", payload=payload_text[:200])
            print("[SIM] menu payload is not valid JSON:", e, payload_text[:200])
            return

        action = data.get("action")
        menu = data.get("menu") or {}
        drills = menu.get("drills") or []
        menu_name = menu.get("menuName")
        repeat_menu = menu.get("repeatMenu", 1)

        if action != "start":
            self.report_error("invalid_action", f"Menu action {action} not supported", action=action)
            print(f"[SIM] menu action={action} ignored")
            return

        if not drills:
            self.report_error("empty_drills", "Menu drills list is empty", menu_name=menu_name)
            print("[SIM] menu drills empty")
            return
            
        # 驗證並解析訓練動作
        try:
            parsed_actions = self._parse_menu_drills(drills, repeat_menu)
        except ValueError as e:
            self.report_error("invalid_drill_format", str(e), menu_name=menu_name)
            print(f"[SIM] Menu validation failed: {e}")
            return

        # 設置進度追蹤
        self.current_menu = menu_name
        self.current_call_id = data.get("call_id")
        self.total_drills = len(parsed_actions)
        self.completed_drills = 0
        self.machine_status = "executing"
        
        # 報告菜單開始
        self.report_menu_start()

        # 將解析的動作加入執行佇列
        queued = 0
        for i, action_item in enumerate(parsed_actions):
            action_item["drill_index"] = i
            action_item["is_new_protocol"] = True
            self.serve_queue.put(action_item)
            queued += 1

        print(f"[SIM] START menu={menu_name} queued={queued} actions into serve_queue")

    def _parse_menu_drills(self, drills, repeat_menu=1):
        """解析菜單訓練結構為執行佇列項目"""
        all_actions = []
        
        for menu_repeat in range(repeat_menu):
            for drill_idx, drill in enumerate(drills):
                drill_name = drill.get("drillSetName", f"Drill {drill_idx}")
                repeat_set = drill.get("repeatSet", 1)
                actions = drill.get("actions", [])
                
                if not actions:
                    raise ValueError(f"Drill '{drill_name}' has no actions")
                
                for set_repeat in range(repeat_set):
                    for action in actions:
                        action_type = action.get("actionType")
                        if action_type != "shot":
                            raise ValueError(f"Unsupported action type: {action_type}")
                        
                        # 驗證shot參數 - Updated to handle API format
                        shot_params = action.get("shotParameters", {})
                        target_pos = shot_params.get("targetPosition", {})
                        
                        # Handle both API format (ballSpeed, ballAngle) and potential legacy format
                        ball_speed = shot_params.get("ballSpeed", 0)
                        # API uses 'ballAngle' but also check for 'angle' fallback
                        ball_angle = shot_params.get("ballAngle", shot_params.get("angle", 0))
                        
                        # 參數驗證
                        if not (0 <= ball_speed <= 50):
                            raise ValueError(f"Ball speed {ball_speed} out of range [0, 50]")
                        if not (0 <= ball_angle <= 90):
                            raise ValueError(f"Ball angle {ball_angle} out of range [0, 90]")
                        
                        # 重複每個動作指定次數
                        repeat_action = action.get("repeatAction", 1)
                        delay_seconds = action.get("delayBeforeShotSeconds", 0)
                        
                        for action_repeat in range(repeat_action):
                            action_item = {
                                "menuName": self.current_menu,
                                "drillSetName": drill_name,
                                "actionId": action.get("actionId", f"A{drill_idx}-{set_repeat}-{action_repeat}"),
                                "description": action.get("description", ""),
                                "targetPosition": target_pos,
                                "ballSpeed": float(ball_speed),
                                "ballAngle": float(ball_angle),
                                "delaySeconds": float(delay_seconds),
                                "menu_repeat": menu_repeat,
                                "set_repeat": set_repeat,
                                "action_repeat": action_repeat
                            }
                            all_actions.append(action_item)
        
        return all_actions

    def handle_backend_control(self, payload_text: str):
        try:
            data = json.loads(payload_text)
        except Exception as e:
            print("[SIM] control payload not valid JSON:", e, payload_text[:200])
            return

        action = data.get("action")
        if action == "pause":
            self.is_paused = True
            self.machine_status = "paused"
            self.publish_new_status(status_type="control", action="paused")
            print("[SIM] paused")
        elif action == "resume":
            self.is_paused = False
            self.machine_status = "executing"
            self.publish_new_status(status_type="control", action="resumed")
            print("[SIM] resumed")
        elif action == "stop":
            # 停止：標記停機 +（可選）清空 queue
            self.is_stopped = True
            self.is_paused = False
            self.machine_status = "stopped"
            self.clear_queue()
            self.publish_new_status(status_type="control", action="stopped")
            self._reset_progress()
            print("[SIM] stopped and cleared queue")
        elif action == "enable_heartbeat":
            self.heartbeat_enabled = True
            self.publish_new_status(status_type="control", action="heartbeat_enabled")
            print("[SIM] heartbeat enabled")
        elif action == "disable_heartbeat":
            self.heartbeat_enabled = False
            self.publish_new_status(status_type="control", action="heartbeat_disabled")
            print("[SIM] heartbeat disabled")
        elif action == "enable_verbose":
            self.quiet_mode = False
            self.publish_new_status(status_type="control", action="verbose_enabled")
            print("[SIM] verbose mode enabled - full status reporting")
        elif action == "disable_verbose":
            self.quiet_mode = True
            self.publish_new_status(status_type="control", action="verbose_disabled")
            print("[SIM] verbose mode disabled - quiet status reporting")
        else:
            self.report_error("invalid_control", f"Unknown control action: {action}", action=action)
            print("[SIM] unknown control action:", action)

    def clear_queue(self):
        # 安全清空 queue（不保證絕對即時，但足夠用於模擬）
        try:
            while not self.serve_queue.empty():
                self.serve_queue.get_nowait()
        except Exception:
            pass

    # -------------------------
    # 新協議：狀態報告
    # -------------------------
    def publish_new_status(self, status_type="status", **kwargs):
        """發布機器狀態到後端"""
        payload = {
            "schema_version": 1,
            "device_name": self.device_name,
            "timestamp": int(time.time() * 1000),
            "status_type": status_type,
            "machine_status": self.machine_status,
            **kwargs
        }
        
        if self.current_call_id:
            payload["call_id"] = self.current_call_id
            
        try:
            # Use ensure_ascii=False to properly display Chinese characters
            self.client.publish(self.status_topic_new, json.dumps(payload, ensure_ascii=False))
            print(f"[STATUS] Published {status_type}: {payload}")
        except Exception as e:
            print(f"[STATUS] Failed to publish: {e}")

    def report_menu_start(self):
        """報告菜單開始執行"""
        self.publish_new_status(
            status_type="menu_start",
            menu_name=self.current_menu,
            total_drills=self.total_drills
        )

    def report_drill_start(self, drill_index, drill_params):
        """報告單個訓練開始"""
        self.current_drill_index = drill_index
        if not self.quiet_mode:  # 安靜模式下不報告個別訓練開始
            self.publish_new_status(
                status_type="drill_start",
                drill_index=drill_index,
                total_drills=self.total_drills,
                drill_params=drill_params
            )

    def report_drill_complete(self, drill_index):
        """報告單個訓練完成"""
        self.completed_drills += 1
        if not self.quiet_mode:  # 安靜模式下不報告個別訓練完成
            self.publish_new_status(
                status_type="drill_complete",
                drill_index=drill_index,
                completed_drills=self.completed_drills,
                total_drills=self.total_drills,
                progress_percent=round((self.completed_drills / max(self.total_drills, 1)) * 100, 2)
            )

    def report_menu_complete(self):
        """報告菜單執行完成"""
        self.machine_status = "ready"
        self.publish_new_status(
            status_type="menu_complete",
            menu_name=self.current_menu,
            total_drills=self.total_drills,
            completed_drills=self.completed_drills
        )
        self._reset_progress()

    def report_error(self, error_type, error_message, **kwargs):
        """報告錯誤"""
        self.machine_status = "error"
        self.publish_new_status(
            status_type="error",
            error_type=error_type,
            error_message=error_message,
            **kwargs
        )

    def _reset_progress(self):
        """重置進度追蹤"""
        self.current_menu = None
        self.current_call_id = None
        self.total_drills = 0
        self.completed_drills = 0
        self.current_drill_index = 0

    # -------------------------
    # 舊協議：保留你原本 broadcast / command 處理
    # -------------------------
    def handle_broadcast(self, payload_text: str):
        try:
            data = json.loads(payload_text)
            if data.get("msg_type") == "query" and data.get("parameter") == "topic_name":
                reply = {
                    "source": self.command_topic,
                    "msg_type": "reply",
                    "parameter": {
                        "topic_name": self.command_topic,
                        "range": {
                            "speed": {"min": 0, "max": 100},
                            "yaw": {"min": -90, "max": 90},
                            "pitch": {"min": -45, "max": 45}
                        }
                    }
                }
                self.client.publish(self.status_topic, json.dumps(reply))
                print("Simulator replied with topic name and range info")
        except Exception as e:
            print("Error parsing broadcast JSON:", e)

    def handle_legacy_command(self, payload_text: str):
        try:
            data = json.loads(payload_text)

            if data.get("msg_type") == "query" and data.get("parameter") == "status":
                status_reply = {
                    "source": self.command_topic,
                    "msg_type": "reply",
                    "parameter": {
                        "status": {
                            "available": True,
                            "settings": {
                                "speed": self.current_speed,
                                "yaw": self.current_yaw,
                                "pitch": self.current_pitch
                            },
                            "range": {
                                "speed": {"min": 0, "max": 100},
                                "yaw": {"min": -90, "max": 90},
                                "pitch": {"min": -45, "max": 45}
                            }
                        }
                    }
                }
                self.client.publish(self.status_topic, json.dumps(status_reply))
                print("Simulator replied with status info")
                return

            if data.get("msg_type") == "command":
                commands = data.get("parameter").split(';')
                for command in commands:
                    if '=' in command:
                        key, value = command.split('=', 1)
                        self.process_command(key.strip(), value.strip())
                    elif command:
                        self.process_command(command.strip(), None)

                self.publish_status()
        except Exception as e:
            print("Error parsing JSON for query or commands:", e)

    def process_command(self, command, value):
        if command == 'speed':
            self.current_speed = float(value)
        elif command == 'yaw':
            self.current_yaw = float(value)
        elif command == 'pitch':
            self.current_pitch = float(value)
        elif command == 'serve':
            params = {
                'speed': self.current_speed,
                'yaw': self.current_yaw,
                'pitch': self.current_pitch,
                'interval_ms': 0,
                'menuName': 'legacy',
                'drill_index': 0,
                'is_new_protocol': False  # 標記為舊協議
            }
            self.serve_queue.put(params)
            print("Queued legacy serve with params:", params)
        elif command == 'MQTT_disconnect':
            self.stop()
        else:
            print("Simulator: set", command)

    def publish_status(self):
        message = f"speed={self.current_speed};yaw={self.current_yaw};pitch={self.current_pitch}"
        print("Simulator publishing status:", message)
        self.client.publish(self.status_topic, message)

    # -------------------------
    # lifecycle
    # -------------------------
    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()  # 建議用 loop_start，讓你可以在同一程式跑 worker
        
        # Always start heartbeat thread (but only sends when enabled)
        if hasattr(self, 'status_topic_new'):
            import threading
            heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
            heartbeat_thread.start()
    
    def _heartbeat_worker(self):
        """定期發送心跳狀態（僅在啟用時）"""
        while not self.is_stopped:
            try:
                time.sleep(30)  # 每30秒檢查一次
                if not self.is_stopped and self.heartbeat_enabled:
                    self.publish_new_status(status_type="heartbeat", uptime_seconds=int(time.time()))
            except Exception as e:
                print(f"[HEARTBEAT] Error: {e}")
                break

    def stop(self):
        print("\nShutting down simulator...")
        
        # Report disconnection before stopping
        if hasattr(self, 'status_topic_new') and not self.is_stopped:
            self.machine_status = "disconnected"
            self.publish_new_status(status_type="disconnected", message="Simulator shutting down")
        
        self.client.unsubscribe(self.command_topic)
        self.client.unsubscribe("broadcast")
        self.client.unsubscribe(self.menu_topic)
        self.client.unsubscribe(self.control_topic)
        self.client.disconnect()
        print("Simulator disconnected.")
        self.is_stopped = True


# ====== 這段只是示範：如何從 serve_queue 取出來「真的執行」 ======
def worker(sim: MQTTSimulator):
    """增強的工作線程，包含狀態報告和錯誤處理"""
    while True:
        try:
            item = sim.serve_queue.get()  # blocking
            if sim.is_stopped:
                continue
                
            # 報告訓練開始（如果是新協議）
            is_new_protocol = item.get("is_new_protocol", False)
            if is_new_protocol:
                drill_index = item.get("drill_index", 0)
                if "ballSpeed" in item:  # 新格式
                    drill_params = {
                        "actionId": item.get("actionId"),
                        "drillSetName": item.get("drillSetName"),
                        "description": item.get("description"),
                        "targetPosition": item.get("targetPosition"),
                        "ballSpeed": item.get("ballSpeed"),
                        "ballAngle": item.get("ballAngle"),
                        "delaySeconds": item.get("delaySeconds")
                    }
                else:  # 舊格式兼容
                    drill_params = {
                        "speed": item.get("speed"),
                        "yaw": item.get("yaw"), 
                        "pitch": item.get("pitch"),
                        "interval_ms": item.get("interval_ms")
                    }
                sim.report_drill_start(drill_index, drill_params)
            
            # 等待暫停狀態解除
            while sim.is_paused:
                time.sleep(0.05)
                if sim.is_stopped:
                    break
                    
            if sim.is_stopped:
                continue

            print(f"[WORKER] executing action {item.get('drill_index', 0)}: {item.get('actionId', 'unknown')}")
            
            # 模擬執行訓練
            delay = item.get("delaySeconds", item.get("interval_ms", 0) / 1000.0)
            time.sleep(max(delay, 0))
            
            # 報告訓練完成（如果是新協議）
            if is_new_protocol:
                drill_index = item.get("drill_index", 0)
                sim.report_drill_complete(drill_index)
                
                # 如果是最後一個訓練，報告菜單完成
                if sim.completed_drills >= sim.total_drills:
                    sim.report_menu_complete()
                    
        except Exception as e:
            print(f"[WORKER] Error processing item: {e}")
            sim.report_error("worker_error", str(e), item=item)
            time.sleep(1)  # 避免錯誤循環


if __name__ == "__main__":
    sim = MQTTSimulator(
        broker="140.113.213.131",
        port=1884,
        command_topic="Machine_A",   # 舊協議
        status_topic="app",
        device_name="MachineA",      # ⭐跟後端 DEFAULT_DEVICE 對齊
    )
    sim.start()

    t = __import__("threading").Thread(target=worker, args=(sim,), daemon=True)
    t.start()

    print("[SIM] running... Ctrl+C to exit")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()
