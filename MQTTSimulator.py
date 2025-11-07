import paho.mqtt.client as mqtt
import json

class MQTTSimulator:
    def __init__(self, broker='broker.emqx.io', port=1883,
                 command_topic='Machine_A', status_topic='app', serve_queue=None):
        self.broker = broker
        self.port = port
        self.command_topic = command_topic
        self.status_topic = status_topic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.serve_queue = serve_queue
        self.current_speed = 30.0
        self.current_yaw = 0.0
        self.current_pitch = 0.0
        self.is_stopped = False

    def on_connect(self, client, userdata, flags, rc, properties):
        print("Simulator connected to MQTT broker with result code", rc)
        # 訂閱命令主題與廣播主題
        client.subscribe(self.command_topic)
        client.subscribe("broadcast")
    
    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        # print(payload)
        # 如果訊息來自 "broadcast" 主題，檢查是否為查詢機器名稱的訊息
        if msg.topic == "broadcast":
            try:
                data = json.loads(payload)
                if data.get("msg_type") == "query" and data.get("parameter") == "topic_name":
                    reply = {
                        "source": "Machine_A",
                        "msg_type": "reply",
                        "parameter": {
                            "topic_name": "Machine_A",
                            "range": {
                                "speed": {"min": 0, "max": 100},
                                "yaw": {"min": -90, "max": 90},
                                "pitch": {"min": -45, "max": 45}
                            }
                        }
                    }
                    # 將回覆發佈到 "app" 主題，讓 MachineClient 收到
                    self.client.publish(self.status_topic, json.dumps(reply))
                    print("Simulator replied with topic name and range info")
                    return
            except Exception as e:
                print("Error parsing broadcast JSON:", e)
        # 如果訊息來自命令主題，先嘗試解析 JSON，看是否為查詢狀態
        if msg.topic == self.command_topic:
            try:
                data = json.loads(payload)
                if data.get("msg_type") == "query":
                    if data.get("parameter") == "status":
                        # 回覆狀態資訊
                        status_reply = {
                            "source": "Machine_A",
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
                elif data.get("msg_type") == "command":
                    commands = data.get("parameter").split(';')
                    for command in commands:
                        if '=' in command:
                            key, value = command.split('=')
                            self.process_command(key.strip(), value.strip())
                        elif command:
                            self.process_command(command.strip(), None)
                    self.publish_status()
                    
            except Exception as e:
                print("Error parsing JSON for query or commands:", e)
        else:
            # 如果不是來自廣播或命令主題，則直接印出訊息
            print("Simulator received message on unknown topic:", msg.topic, payload)

    def process_command(self, command, value):
        if command == 'speed':
            try:
                self.current_speed = float(value)
            except Exception as e:
                print("Error setting speed:", e)
        elif command == 'yaw':
            try:
                self.current_yaw = float(value)
            except Exception as e:
                print("Error setting yaw:", e)
        elif command == 'pitch':
            try:
                self.current_pitch = float(value)
            except Exception as e:
                print("Error setting pitch:", e)
        elif command == 'serve':
            print("Received serve command")
            params = {
                'speed': self.current_speed,
                'yaw': self.current_yaw,
                'pitch': self.current_pitch
            }
            self.serve_queue.put(params)
            print("Queued serve with params:", params)
        elif command == 'MQTT_disconnect':
            print("Simulator: received MQTT_disconnect command")
            self.stop()
        else:
            print("Simulator: set", command)

    def publish_status(self):
        message = f"speed={self.current_speed};yaw={self.current_yaw};pitch={self.current_pitch}"
        print("Simulator publishing status:", message)
        self.client.publish(self.status_topic, message)

    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_forever()  # Blocking loop in background thread

    def stop(self):
        print("\nShutting down simulator...")
        self.client.unsubscribe(self.command_topic)
        self.client.unsubscribe("broadcast")
        self.client.disconnect()
        print("Simulator disconnected.")
        self.is_stopped = True