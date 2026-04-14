import paho.mqtt.client as mqtt
import json
import time

class RemoteClient:
    """
    A remote client to interact with the MQTTSimulator.
    It sends commands and subscribes to the 'app' topic to receive replies.
    """
    def __init__(self, broker='broker.emqx.io', port=1883, command_topic='Badminton_simulator', status_topic='app'):
        self.broker = broker
        self.port = port
        self.command_topic = command_topic
        self.status_topic = status_topic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """The callback for when the client receives a CONNACK response from the server."""
        if reason_code.is_failure:
            print(f"Failed to connect: {reason_code}. Exiting.")
            return
        print(f"Remote client connected to {self.broker}")
        # Subscribe to the topic where the emulator sends replies
        print(f"Subscribing to topic: '{self.status_topic}'")
        client.subscribe(self.status_topic)

    def on_message(self, client, userdata, msg):
        """The callback for when a PUBLISH message is received from the server."""
        print(f"\n[Reply Received on topic '{msg.topic}']")
        try:
            # Try to pretty-print if it's a JSON payload
            parsed_json = json.loads(msg.payload.decode())
            print(json.dumps(parsed_json, indent=2))
        except json.JSONDecodeError:
            # Otherwise, print as plain text
            print(msg.payload.decode())
        self.prompt()

    def prompt(self):
        """Prints the command prompt."""
        print("\nEnter command > ", end='', flush=True)

    def start(self):
        """Connects the client and starts the command input loop."""
        try:
            self.client.connect(self.broker, self.port, 60)
        except Exception as e:
            print(f"Error connecting to broker: {e}")
            return

        self.client.loop_start()
        print("--- Remote Client for Badminton Simulator ---")
        print("Enter commands to send to the emulator.")
        print("Examples:")
        print("  query topic_name   (Broadcast to find machines)")
        print(f"  query status       (Send to '{self.command_topic}')")
        print(f"  speed=50           (Send to '{self.command_topic}')")
        print("  serve")
        print("  exit               (To quit the client)")
        print("---------------------------------------------")

        while True:
            self.prompt()
            try:
                command = input()
                if not command:
                    continue
                if command.lower() == 'exit':
                    payload = json.dumps({"msg_type": "command", "parameter": "MQTT_disconnect"})
                    self.client.publish(self.command_topic, payload)
                    print(f"Published to '{self.command_topic}': {payload}")
                    break

                if command == "query topic_name":
                    # This is a broadcast query
                    payload = json.dumps({"msg_type": "query", "parameter": "topic_name"})
                    self.client.publish("broadcast", payload)
                    print(f"Published to 'broadcast': {payload}")
                elif command == "query status":
                    # This is a status query for a specific machine
                    payload = json.dumps({"msg_type": "query", "parameter": "status"})
                    self.client.publish(self.command_topic, payload)
                    print(f"Published to '{self.command_topic}': {payload}")
                elif command == "serve":
                    # Send the serve command
                    payload = json.dumps({"msg_type": "command", "parameter": "serve"})
                    self.client.publish(self.command_topic, payload)
                    print(f"Published to '{self.command_topic}': {payload}")
                else:
                    # Send any other command directly to the machine's topic
                    payload = json.dumps({"msg_type": "command", "parameter": command})
                    self.client.publish(self.command_topic, payload)
                    print(f"Published to '{self.command_topic}': {payload}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"An error occurred: {e}")

        self.client.loop_stop()
        self.client.disconnect()
        print("\nRemote client disconnected.")

if __name__ == '__main__':
    # The command_topic must match the one used by the emulator instance
    remote = RemoteClient(command_topic='Badminton_simulator', status_topic='abcde12345')
    remote.start()