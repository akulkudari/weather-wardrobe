import paho.mqtt.client as mqtt
import json
from datetime import datetime
from collections import deque
import numpy as np
import os
import time
from dotenv import load_dotenv
import requests


#env_path = "C:\\Users\akulk\Downloads\ECE140A\ECE140-WI25-Lab6\IOT\.env"
load_dotenv("../IOT/.env")
last_request_time = 0
WEB_SERVER_URL = "https://tech-assignment-final-project-sherif-and.onrender.com/update_temperature_reading"
# MQTT Broker settings
BROKER = "broker.emqx.io"
# broker.emqx.io
PORT = 1883
BASE_TOPIC = "apple/ece140/sensors"
TOPIC = BASE_TOPIC + "/#"

if BASE_TOPIC == "ENTER_SOMETHING_UNIQUE_HERE_THAT_SHOULD_ALSO_MATCH_MAINCPP/ece140/sensors":
    print("Please enter a unique topic for your server")
    exit()


def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the broker."""
    if rc == 0:
        print("Successfully connected to MQTT broker")
        client.subscribe(TOPIC)
        print(f"Subscribed to {TOPIC}")
    else:
        print(f"Failed to connect with result code {rc}")

def on_message(client, userdata, msg):
    global last_request_time

    """Callback for when a message is received."""
    try:
        # Parse JSON message
        payload = json.loads(msg.payload.decode())

        if "temperature" in payload:
            temperature = payload["temperature"]
            current_time = time.time()
            mac_address = payload["mac_address"]
            if current_time  - last_request_time >= 5:
                last_request_time = current_time
                data = {"value": temperature, "unit": "celsius", "mac_address": mac_address}
                response = requests.post(WEB_SERVER_URL, json=data)
                if response.status_code == 200:
                    print(f"Temperature {temperature} sent successfully!")
                else:
                    print(f"Failed to send data. Status code: {response.status_code}")

            else:
                print("Skipping POST request to avoid sending too frequently.")        
        # check the topic if it is the base topic + /readings
        # if it is, print the payload
        if msg.topic == BASE_TOPIC + '/readings':
            print(f"Payload received: {payload}")
    except json.JSONDecodeError:
        print(f"\nReceived non-JSON message on {msg.topic}:")
        print(f"Payload: {msg.payload.decode()}")
    except requests.RequestException as e:
        print(f"Error sending data to server: {e}")



def main():
    # Create MQTT client
    client = mqtt.Client()
    print("Creating MQTT client...")
    client.on_connect = on_connect
    client.on_message = on_message
    # Set the callback functions onConnect and onMessage
    print("Setting callback functions...")
    
    try:
        # Connect to broker
        client.connect(BROKER, PORT, keepalive=60)

        print("Connecting to broker...")
        
        # Start the MQTT loop
        client.loop_forever()
        print("Starting MQTT loop...")
        
    except KeyboardInterrupt:
        print("\nDisconnecting from broker...")
        client.loop_stop()
        client.disconnect()
        # make sure to stop the loop and disconnect from the broker
        print("Exited successfully")
    except Exception as e:
        print(f"Error: {e}")
if __name__ == "__main__":
    main()