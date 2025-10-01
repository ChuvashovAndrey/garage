# /home/andrey/Projects/garage/app.py
import json
import logging
import asyncio
from datetime import datetime
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import os
import threading
import psutil
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные ДО создания app
garage_state = {
    "temperature": 20.0,
    "humidity": 45.0,
    "door_open": False,
    "motion_detected": False,
    "light_on": False,
    "light_brightness": 0,
    "last_update": None,
    "system_info": {
        "cpu_percent": 0,
        "memory_percent": 0,
        "disk_usage": 0,
        "uptime": 0
    }
}

connected_clients = []
mqtt_loop = asyncio.new_event_loop()
mqtt_client = mqtt.Client()

def get_system_info():
    """Получение системной информации"""
    try:
        return {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
            "uptime": int(time.time() - psutil.boot_time())
        }
    except:
        return {
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_usage": 0,
            "uptime": 0
        }

def run_async_in_mqtt_thread(coro):
    """Запуск асинхронной функции в MQTT потоке"""
    asyncio.run_coroutine_threadsafe(coro, mqtt_loop)

async def broadcast_to_clients(data):
    """Рассылка данных всем подключенным WebSocket клиентам"""
    for client in connected_clients[:]:
        try:
            await client.send_json(data)
        except:
            connected_clients.remove(client)

def on_mqtt_connect(client, userdata, flags, rc):
    logger.info("✅ Подключен к MQTT брокеру")
    client.subscribe("zigbee2mqtt/#")

def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        
        if "garage_temperature_sensor" in topic:
            garage_state["temperature"] = payload.get("temperature", 20.0)
            garage_state["humidity"] = payload.get("humidity", 45.0)
            
        elif "garage_door_sensor" in topic:
            garage_state["door_open"] = not payload.get("contact", True)
            
        elif "garage_motion_sensor" in topic:
            garage_state["motion_detected"] = payload.get("occupancy", False)
            
        elif "garage_light_switch" in topic:
            garage_state["light_on"] = payload.get("state", "OFF") == "ON"
            garage_state["light_brightness"] = payload.get("brightness", 0)
        
        # Обновляем системную информацию
        garage_state["system_info"] = get_system_info()
        garage_state["last_update"] = datetime.now().isoformat()
        
        # Запускаем рассылку в правильном event loop
        run_async_in_mqtt_thread(broadcast_to_clients(garage_state.copy()))
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки MQTT сообщения: {e}")

def start_mqtt_loop():
    """Запуск event loop для MQTT в отдельном потоке"""
    asyncio.set_event_loop(mqtt_loop)
    mqtt_loop.run_forever()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Запуск приложения...")
    try:
        # Запускаем MQTT loop в отдельном потоке
        mqtt_thread = threading.Thread(target=start_mqtt_loop, daemon=True)
        mqtt_thread.start()
        
        # Даем время на запуск loop
        await asyncio.sleep(1)
        
        # Подключаем MQTT клиент
        mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect(mqtt_host, 1883, 60)
        mqtt_client.loop_start()
        
        logger.info("✅ MQTT клиент запущен")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска MQTT клиента: {e}")
    
    yield  # Работа приложения
    
    # Shutdown
    logger.info("🛑 Остановка приложения...")
    mqtt_client.loop_stop()
    mqtt_loop.stop()

app = FastAPI(title="Smart Garage", lifespan=lifespan)

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
        # При подключении отправляем текущее состояние
        garage_state["system_info"] = get_system_info()
        await websocket.send_json(garage_state)
        
        # Периодически обновляем системную информацию
        while True:
            await asyncio.sleep(5)  # Обновляем каждые 5 секунд
            garage_state["system_info"] = get_system_info()
            await websocket.send_json(garage_state)
            
    except Exception as e:
        logger.error(f"❌ WebSocket ошибка: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

@app.post("/api/control/door")
async def control_door():
    """Управление дверью гаража"""
    try:
        garage_state["door_open"] = not garage_state["door_open"]
        garage_state["last_update"] = datetime.now().isoformat()
        
        await broadcast_to_clients(garage_state.copy())
        
        return {
            "status": "success", 
            "door_open": garage_state["door_open"],
            "message": f"Дверь {'открыта' if garage_state['door_open'] else 'закрыта'}"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления дверью: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/light")
async def control_light():
    """Управление светом"""
    try:
        garage_state["light_on"] = not garage_state["light_on"]
        garage_state["light_brightness"] = 255 if garage_state["light_on"] else 0
        garage_state["last_update"] = datetime.now().isoformat()
        
        # Отправляем команду в MQTT
        new_state = "ON" if garage_state["light_on"] else "OFF"
        brightness = 255 if garage_state["light_on"] else 0
        
        mqtt_client.publish(
            "zigbee2mqtt/garage_light_switch/set",
            json.dumps({
                "state": new_state,
                "brightness": brightness
            })
        )
        
        await broadcast_to_clients(garage_state.copy())
        
        return {
            "status": "success",
            "light_on": garage_state["light_on"],
            "brightness": garage_state["light_brightness"],
            "message": f"Свет {'включен' if garage_state['light_on'] else 'выключен'}"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления светом: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/light_brightness")
async def control_light_brightness(brightness: int):
    """Управление яркостью света"""
    try:
        if brightness < 0 or brightness > 255:
            return {"status": "error", "message": "Яркость должна быть от 0 до 255"}
            
        garage_state["light_brightness"] = brightness
        garage_state["light_on"] = brightness > 0
        garage_state["last_update"] = datetime.now().isoformat()
        
        mqtt_client.publish(
            "zigbee2mqtt/garage_light_switch/set",
            json.dumps({
                "state": "ON" if brightness > 0 else "OFF",
                "brightness": brightness
            })
        )
        
        await broadcast_to_clients(garage_state.copy())
        
        return {
            "status": "success",
            "brightness": brightness,
            "light_on": brightness > 0
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления яркостью: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/simulate/motion")
async def simulate_motion():
    """Симуляция движения"""
    try:
        garage_state["motion_detected"] = True
        garage_state["last_update"] = datetime.now().isoformat()
        
        await broadcast_to_clients(garage_state.copy())
        
        # Автоматическое выключение через 10 секунд
        async def reset_motion():
            await asyncio.sleep(10)
            garage_state["motion_detected"] = False
            garage_state["last_update"] = datetime.now().isoformat()
            await broadcast_to_clients(garage_state.copy())
        
        asyncio.create_task(reset_motion())
        
        return {
            "status": "success",
            "motion_detected": True,
            "message": "Движение симулировано"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка симуляции движения: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/status")
async def get_status():
    """Получение текущего статуса"""
    garage_state["system_info"] = get_system_info()
    return garage_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
