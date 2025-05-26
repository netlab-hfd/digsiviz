from confluent_kafka import Producer, admin, KafkaError, KafkaException


class KafkaConnector:
    def __init__(self, bootstrap_servers: str):
        self.bootstrap_servers = bootstrap_servers
        self.producer = Producer({
            'bootstrap.servers': self.bootstrap_servers
        })


    def send_message(self, topic: str, key: str, value: str):
        try:
            self.producer.produce(topic, key=key.encode('utf-8'), value=value.encode('utf-8'))
            self.producer.flush()
        except KafkaException as e:
            raise RuntimeError(f"Failed to send message to Kafka: {e}")

    def create_topic(self, topic: str, num_partitions: int = 1, replication_factor: int = 1):
        admin_client = admin.AdminClient({'bootstrap.servers': self.bootstrap_servers})
        metadata = admin_client.list_topics(timeout=10)
        if topic in metadata.topics:
            print(f"Topic '{topic}' already exists.")
            return
        new_topic = admin.NewTopic(topic, num_partitions=num_partitions, replication_factor=replication_factor)
        fs = admin_client.create_topics([new_topic])
        for topic, f in fs.items():
            try:
                f.result()
                print(f"Topic '{topic}' created successfully.")
            except KafkaError as e:
                raise RuntimeError(f"Failed to create topic {topic}: {e}")

    def check_topic_exists(self, topic: str) -> bool:
        admin_client = admin.AdminClient({'bootstrap.servers': self.bootstrap_servers})
        metadata = admin_client.list_topics(timeout=10)
        return topic in metadata.topics

    def close(self):
        self.producer.flush()
        self.producer.close()
        print("Kafka producer closed.")

