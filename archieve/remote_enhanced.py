import paho.mqtt.client as mqtt
import json
import time

class EnhancedRemoteClient:
    """
    Enhanced remote client to test both legacy and new MQTT protocols.
    """
    def __init__(self, broker='140.113.213.131', port=1884, 
                 command_topic='Machine_A', status_topic='abcde12345',
                 device_name='MachineA'):
        self.broker = broker
        self.port = port
        self.command_topic = command_topic
        self.status_topic = status_topic
        self.device_name = device_name
        
        # New protocol topics
        self.menu_topic = f"/CALL/{device_name}/IoT/menu"
        self.control_topic = f"/CALL/{device_name}/Feeder/control"
        self.status_topic_new = f"/CALL/{device_name}/IoT/status"
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """The callback for when the client receives a CONNACK response from the server."""
        if reason_code.is_failure:
            print(f"Failed to connect: {reason_code}. Exiting.")
            return
        print(f"Connected to {self.broker}")
        
        # Subscribe to both legacy and new protocol topics
        client.subscribe(self.status_topic)  # Legacy
        client.subscribe(self.status_topic_new)  # New protocol status
        
        print(f"Subscribed to topics:")
        print(f"  Legacy status: '{self.status_topic}'")
        print(f"  New status: '{self.status_topic_new}'")

    def on_message(self, client, userdata, msg):
        """The callback for when a PUBLISH message is received from the server."""
        topic = msg.topic
        
        if topic == self.status_topic_new:
            print(f"\n[new protocol status on '{topic}']")
        else:
            print(f"\n[legacy reply on '{topic}']")
            
        try:
            # Try to pretty-print if it's a JSON payload with proper Unicode support
            parsed_json = json.loads(msg.payload.decode())
            print(json.dumps(parsed_json, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            # Otherwise, print as plain text
            print(msg.payload.decode())
        self.prompt()

    def send_new_menu(self, menu_name="Test Menu", custom_drills=None):
        """Send a test menu using the new protocol with correct format"""
        if custom_drills is None:
            # Default test menu with correct structure
            drills = [
                {
                    "drillSetName": "平球練習",
                    "repeatSet": 1,
                    "actions": [
                        {
                            "actionId": "H001",
                            "actionType": "shot",
                            "description": "左右平球",
                            "repeatAction": 3,
                            "delayBeforeShotSeconds": 2.0,
                            "shotParameters": {
                                "targetPosition": {"x": 3.0, "y": 6.5, "z": 2.5},
                                "ballSpeed": 8,
                                "ballAngle": 70
                            }
                        }
                    ]
                },
                {
                    "drillSetName": "網前對角線小球練習",
                    "repeatSet": 1,
                    "actions": [
                        {
                            "actionId": "D001", 
                            "actionType": "shot",
                            "description": "網前對角放小球",
                            "repeatAction": 2,
                            "delayBeforeShotSeconds": 1.5,
                            "shotParameters": {
                                "targetPosition": {"x": 2.0, "y": 1.0, "z": 0.3},
                                "ballSpeed": 3,
                                "ballAngle": 15
                            }
                        }
                    ]
                }
            ]
        else:
            drills = custom_drills
        
        payload = {
            "schema_version": 1,
            "call_id": f"test-{int(time.time())}",
            "action": "start",
            "menu": {
                "menuName": menu_name,
                "description": "自動生成的測試訓練菜單",
                "dateCreated": "2026-02-04",
                "repeatMenu": 1,
                "drills": drills
            }
        }
        
        self.client.publish(self.menu_topic, json.dumps(payload))
        print(f"Published menu to '{self.menu_topic}':")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    def send_control(self, action):
        """Send control command using new protocol"""
        payload = {"action": action}
        self.client.publish(self.control_topic, json.dumps(payload))
        print(f"Published control '{action}' to '{self.control_topic}'")

    def send_legacy_command(self, command):
        """Send command using legacy protocol"""
        if command == "query topic_name":
            payload = json.dumps({"msg_type": "query", "parameter": "topic_name"})
            self.client.publish("broadcast", payload)
            print(f"Published to 'broadcast': {payload}")
        elif command == "query status":
            payload = json.dumps({"msg_type": "query", "parameter": "status"})
            self.client.publish(self.command_topic, payload)
            print(f"Published to '{self.command_topic}': {payload}")
        elif command == "serve":
            payload = json.dumps({"msg_type": "command", "parameter": "serve"})
            self.client.publish(self.command_topic, payload)
            print(f"Published serve to '{self.command_topic}': {payload}")
        else:
            payload = json.dumps({"msg_type": "command", "parameter": command})
            self.client.publish(self.command_topic, payload)
            print(f"Published to '{self.command_topic}': {payload}")

    def prompt(self):
        """Prints the command prompt."""
        print("\nEnter command > ", end='', flush=True)

    def print_help(self):
        """Print available commands"""
        print("\navailable commands:")
        print("new protocol:")
        print("  menu                    - send test menu")
        print("  menu custom             - create custom menu")
        print("  pause                   - pause execution")
        print("  resume                  - resume execution") 
        print("  stop                    - stop execution")
        print("  heartbeat on/off        - toggle heartbeat messages")
        print("  verbose on/off          - toggle detailed status")
        print()
        print("legacy protocol:")
        print("  query topic_name        - find machines")
        print("  query status            - query machine status")
        print("  speed=50                - set speed parameter")
        print("  serve                   - execute single serve")
        print()
        print("other:")
        print("  help                    - show commands")
        print("  exit                    - quit")

    def start(self):
        """Connects the client and starts the command input loop."""
        try:
            self.client.connect(self.broker, self.port, 60)
        except Exception as e:
            print(f"Error connecting to broker: {e}")
            return

        self.client.loop_start()
        print("badminton simulator remote client")
        print("type 'help' for commands\n")

        while True:
            self.prompt()
            try:
                command = input().strip()
                if not command:
                    continue
                    
                if command.lower() == 'exit':
                    payload = json.dumps({"msg_type": "command", "parameter": "MQTT_disconnect"})
                    self.client.publish(self.command_topic, payload)
                    print(f"Published disconnect to '{self.command_topic}': {payload}")
                    break
                elif command.lower() == 'help':
                    self.print_help()
                elif command == 'menu':
                    self.send_new_menu()
                elif command == 'menu custom':
                    print("creating custom menu...")
                    print("drill set name (enter for default):")
                    drill_name = input("> ").strip() or "Custom Drill Set"
                    print("repeat count (enter for 1):")
                    try:
                        repeat_set = int(input("> ").strip() or "1")
                    except ValueError:
                        repeat_set = 1
                    
                    print("enter actions:")
                    print("format: actionId,description,repeatAction,delaySeconds,ballSpeed,ballAngle,targetX,targetY,targetZ")
                    print("example: A001,Test Shot,2,1.5,8,45,3.0,6.5,2.5")
                    print("empty line to finish:")
                    
                    actions = []
                    while True:
                        action_input = input("> ").strip()
                        if not action_input:
                            break
                        try:
                            parts = action_input.split(',')
                            if len(parts) >= 9:
                                action_id, description, repeat_action, delay, ball_speed, ball_angle, target_x, target_y, target_z = parts[:9]
                                action = {
                                    "actionId": action_id.strip(),
                                    "actionType": "shot",
                                    "description": description.strip(),
                                    "repeatAction": int(repeat_action.strip()),
                                    "delayBeforeShotSeconds": float(delay.strip()),
                                    "shotParameters": {
                                        "targetPosition": {
                                            "x": float(target_x.strip()),
                                            "y": float(target_y.strip()),
                                            "z": float(target_z.strip())
                                        },
                                        "ballSpeed": int(ball_speed.strip()),
                                        "ballAngle": int(ball_angle.strip())
                                    }
                                }
                                actions.append(action)
                                print(f"added: {action_id} - {description}")
                            else:
                                print("invalid format. need 9 values separated by commas")
                        except ValueError as e:
                            print(f"invalid values: {e}")
                    
                    if actions:
                        custom_drills = [{
                            "drillSetName": drill_name,
                            "repeatSet": repeat_set,
                            "actions": actions
                        }]
                        self.send_new_menu("Custom Menu", custom_drills)
                    else:
                        print("no actions entered, using default menu")
                        self.send_new_menu()
                elif command in ['pause', 'resume', 'stop']:
                    self.send_control(command)
                elif command == 'heartbeat on':
                    self.send_control('enable_heartbeat')
                elif command == 'heartbeat off':
                    self.send_control('disable_heartbeat')
                elif command == 'verbose on':
                    self.send_control('enable_verbose')
                elif command == 'verbose off':
                    self.send_control('disable_verbose')
                else:
                    # Legacy command
                    self.send_legacy_command(command)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"An error occurred: {e}")

        self.client.loop_stop()
        self.client.disconnect()
        print("\ndisconnected.")

if __name__ == '__main__':
    remote = EnhancedRemoteClient()
    remote.start()