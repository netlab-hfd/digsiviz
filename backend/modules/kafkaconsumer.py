import threading
from confluent_kafka import Consumer, KafkaException
import flatdict
import json
from flask_socketio import SocketIO

class KafkaConsumerThread(threading.Thread):
    def __init__(self, topic, socketio: SocketIO,  bootstrap_servers="localhost:29092", group_id="gnmi_group"):
        super().__init__(daemon=True)
        self.topic = topic
        self.running = True
        self.consumer = Consumer({
            'bootstrap.servers': bootstrap_servers,
            'group.id': group_id,
            'auto.offset.reset': 'earliest',
        })
        self.socketio = socketio

    def run(self):
        self.consumer.subscribe([self.topic])
        print(f"[Kafka] Subscribed to topic: {self.topic}")

        try:
            while self.running:
                msg = self.consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    print(f"[Kafka] Error: {msg.error()}")
                    continue

                self.handle_message(msg.value().decode('utf-8'))

        except KafkaException as e:
            print(f"[Kafka] Exception: {e}")
        finally:
            self.consumer.close()
            print("[Kafka] Consumer closed.")


    def handle_message(self, message):
        try:
            parsed = json.loads(message) 
            flat = flatdict.FlatDict(parsed, delimiter='_')
            unflattened = flat.as_dict()

            print(f"[Kafka] Received message: {unflattened}")

            
        except json.JSONDecodeError as e:
            print(f"[Kafka] JSON Decode Error: {e}")
        except Exception as e:
            print(f"[Kafka] Error in handle_message: {e}")


    def stop(self):
        self.running = False
