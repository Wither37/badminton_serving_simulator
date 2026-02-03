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
        self.is_paused = False # 還沒實作(?)

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
            print("[SIM] menu payload is not valid JSON:", e, payload_text[:200])
            return

        action = data.get("action")
        menu = data.get("menu") or {}
        drills = menu.get("drills") or []
        menu_name = menu.get("menuName")

        if action != "start":
            print(f"[SIM] menu action={action} ignored")
            return

        if not drills:
            print("[SIM] menu drills empty")
            return

        # 你要的核心：把後端資料轉成 queue 任務
        queued = 0
        for d in drills:
            params = (d.get("parameters") or {})
            interval_ms = int(d.get("interval") or 0)

            item = {
                "speed": float(params.get("speed", 0)),
                "yaw": float(params.get("yaw", 0)),
                "pitch": float(params.get("pitch", 0)),
                "interval_ms": interval_ms,
                "menuName": menu_name,
            }
            self.serve_queue.put(item)
            queued += 1

        print(f"[SIM] START menu={menu_name} queued={queued} items into serve_queue")

    def handle_backend_control(self, payload_text: str):
        try:
            data = json.loads(payload_text)
        except Exception as e:
            print("[SIM] control payload not valid JSON:", e, payload_text[:200])
            return

        action = data.get("action")
        if action == "pause":
            self.is_paused = True
            print("[SIM] paused")
        elif action == "resume":
            self.is_paused = False
            print("[SIM] resumed")
        elif action == "stop":
            # 停止：標記停機 +（可選）清空 queue
            self.is_stopped = True
            self.is_paused = False
            self.clear_queue()
            print("[SIM] stopped and cleared queue")
        else:
            print("[SIM] unknown control action:", action)

    def clear_queue(self):
        # 安全清空 queue（不保證絕對即時，但足夠用於模擬）
        try:
            while not self.serve_queue.empty():
                self.serve_queue.get_nowait()
        except Exception:
            pass

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
                'menuName': 'legacy'
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

    def stop(self):
        print("\nShutting down simulator...")
        self.client.unsubscribe(self.command_topic)
        self.client.unsubscribe("broadcast")
        self.client.unsubscribe(self.menu_topic)
        self.client.unsubscribe(self.control_topic)
        self.client.disconnect()
        print("Simulator disconnected.")
        self.is_stopped = True


# ====== 這段只是示範：如何從 serve_queue 取出來「真的執行」 ======
def worker(sim: MQTTSimulator):
    while True:
        item = sim.serve_queue.get()  # blocking
        if sim.is_stopped:
            continue
        while sim.is_paused:
            time.sleep(0.05)

        print("[WORKER] executing:", item)
        time.sleep(max(item.get("interval_ms", 0), 0) / 1000.0)


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
