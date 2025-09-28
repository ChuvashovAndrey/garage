# /home/andrey/Projects/garage/app.py
import asyncio
import json
import random
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояние системы
garage_state = {
    "temperature": 20.0,
    "humidity": 45.0,
    "door_open": False,
    "motion_detected": False,
    "light_on": False,
    "light_brightness": 0,
    "last_update": None
}

connected_clients = []

class GarageSimulator:
    def __init__(self):
        self.mqtt_client = None
        self.is_running = False
        self.simulation_task = None
        
    def connect_mqtt(self):
        try:
            mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.connect(mqtt_host, 1883, 60)
            
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.subscribe("zigbee2mqtt/garage_light/set")
            
            self.mqtt_client.loop_start()
            logger.info(f"Connected to MQTT broker at {mqtt_host}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT: {e}")
            return False
    
    def on_mqtt_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            if topic == "zigbee2mqtt/garage_light/set":
                if "state" in payload:
                    garage_state["light_on"] = (payload["state"].upper() == "ON")
                    logger.info(f"Light turned {'ON' if garage_state['light_on'] else 'OFF'}")
                
                if "brightness" in payload:
                    garage_state["light_brightness"] = max(0, min(100, payload["brightness"]))
                    logger.info(f"Light brightness set to {garage_state['light_brightness']}%")
                    
        except Exception as e:
            logger.error(f"Error processing MQTT command: {e}")
    
    def publish_state(self):
        if not self.mqtt_client:
            return
            
        temperature_data = {
            "temperature": round(garage_state["temperature"], 1),
            "humidity": round(garage_state["humidity"], 1),
            "pressure": 1013.25,
            "battery": 100,
            "linkquality": 100,
            "last_seen": datetime.now().isoformat()
        }
        
        door_data = {
            "contact": not garage_state["door_open"],
            "battery": 100,
            "linkquality": 100,
            "last_seen": datetime.now().isoformat()
        }
        
        motion_data = {
            "occupancy": garage_state["motion_detected"],
            "battery": 100,
            "linkquality": 100,
            "last_seen": datetime.now().isoformat()
        }
        
        light_data = {
            "state": "ON" if garage_state["light_on"] else "OFF",
            "brightness": garage_state["light_brightness"],
            "power": garage_state["light_brightness"] * 10,
            "last_seen": datetime.now().isoformat()
        }
        
        self.mqtt_client.publish("zigbee2mqtt/garage_temperature", json.dumps(temperature_data))
        self.mqtt_client.publish("zigbee2mqtt/garage_door", json.dumps(door_data))
        self.mqtt_client.publish("zigbee2mqtt/garage_motion", json.dumps(motion_data))
        self.mqtt_client.publish("zigbee2mqtt/garage_light", json.dumps(light_data))
    
    async def simulate_environment(self):
        while self.is_running:
            try:
                hour = datetime.now().hour
                if 2 <= hour <= 6:
                    temp_change = random.uniform(-0.3, 0.1)
                elif 12 <= hour <= 16:
                    temp_change = random.uniform(-0.1, 0.3)
                else:
                    temp_change = random.uniform(-0.2, 0.2)
                
                garage_state["temperature"] = max(15, min(30, 
                    garage_state["temperature"] + temp_change))
                
                garage_state["humidity"] = max(30, min(80, 45 + random.uniform(-3, 3)))
                
                if random.random() < 0.005:
                    garage_state["door_open"] = not garage_state["door_open"]
                    logger.info(f"Door {'opened' if garage_state['door_open'] else 'closed'}")
                
                if garage_state["motion_detected"]:
                    if random.random() < 0.2:
                        garage_state["motion_detected"] = False
                else:
                    if random.random() < 0.01:
                        garage_state["motion_detected"] = True
                
                # Автоматическое управление светом
                if garage_state["motion_detected"] and not garage_state["light_on"]:
                    garage_state["light_on"] = True
                    garage_state["light_brightness"] = 100
                    logger.info("Light turned ON automatically (motion detected)")
                
                elif not garage_state["motion_detected"] and garage_state["light_on"]:
                    if random.random() < 0.1:
                        garage_state["light_on"] = False
                        garage_state["light_brightness"] = 0
                        logger.info("Light turned OFF automatically (no motion)")
                
                garage_state["last_update"] = datetime.now().isoformat()
                
                self.publish_state()
                await self.broadcast_to_clients()
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in simulation: {e}")
                await asyncio.sleep(5)
    
    async def broadcast_to_clients(self):
        for client in connected_clients[:]:
            try:
                await client.send_json(garage_state)
            except:
                connected_clients.remove(client)
    
    async def start(self):
        if self.connect_mqtt():
            self.is_running = True
            self.simulation_task = asyncio.create_task(self.simulate_environment())
    
    async def stop(self):
        self.is_running = False
        if self.simulation_task:
            self.simulation_task.cancel()
            try:
                await self.simulation_task
            except asyncio.CancelledError:
                pass
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

# Создаем глобальный экземпляр симулятора
simulator = GarageSimulator()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Smart Garage System")
    await simulator.start()
    
    yield  # Приложение работает
    
    # Shutdown
    logger.info("Stopping Smart Garage System")
    await simulator.stop()

# Создаем FastAPI приложение с lifespan
app = FastAPI(title="Smart Garage", lifespan=lifespan)

os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    
    try:
        await websocket.send_json(garage_state)
        
        while True:
            await asyncio.sleep(30)
            await websocket.send_json(garage_state)
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# API endpoints остаются без изменений
@app.post("/api/control/door")
async def control_door():
    garage_state["door_open"] = not garage_state["door_open"]
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    return {
        "status": "success", 
        "door_open": garage_state["door_open"],
        "message": f"Door {'opened' if garage_state['door_open'] else 'closed'}"
    }

@app.post("/api/simulate/motion")
async def simulate_motion():
    garage_state["motion_detected"] = True
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    async def reset_motion():
        await asyncio.sleep(30)
        garage_state["motion_detected"] = False
        garage_state["last_update"] = datetime.now().isoformat()
        await simulator.broadcast_to_clients()
    
    asyncio.create_task(reset_motion())
    
    return {
        "status": "success",
        "motion_detected": True,
        "message": "Motion simulation started"
    }

@app.post("/api/control/light")
async def control_light():
    garage_state["light_on"] = not garage_state["light_on"]
    
    if garage_state["light_on"] and garage_state["light_brightness"] == 0:
        garage_state["light_brightness"] = 100
    
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    return {
        "status": "success",
        "light_on": garage_state["light_on"],
        "brightness": garage_state["light_brightness"],
        "message": f"Light turned {'ON' if garage_state['light_on'] else 'OFF'}"
    }

@app.post("/api/control/light/brightness")
async def set_light_brightness(brightness: int):
    garage_state["light_brightness"] = max(0, min(100, brightness))
    garage_state["light_on"] = (garage_state["light_brightness"] > 0)
    
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    return {
        "status": "success",
        "light_on": garage_state["light_on"],
        "brightness": garage_state["light_brightness"],
        "message": f"Brightness set to {garage_state['light_brightness']}%"
    }

@app.post("/api/control/light/on")
async def turn_light_on():
    garage_state["light_on"] = True
    garage_state["light_brightness"] = 100
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    return {
        "status": "success",
        "light_on": True,
        "brightness": 100,
        "message": "Light turned ON at 100% brightness"
    }

@app.post("/api/control/light/off")
async def turn_light_off():
    garage_state["light_on"] = False
    garage_state["light_brightness"] = 0
    garage_state["last_update"] = datetime.now().isoformat()
    simulator.publish_state()
    await simulator.broadcast_to_clients()
    
    return {
        "status": "success",
        "light_on": False,
        "brightness": 0,
        "message": "Light turned OFF"
    }

@app.get("/api/status")
async def get_status():
    return garage_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
