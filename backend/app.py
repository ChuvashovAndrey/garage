import json
import logging
import asyncio
from datetime import datetime
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import threading
import psutil
import time
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные
garage_state = {
    "temperature": 20.0,
    "humidity": 45.0,
    "door_open": False,
    "door_battery": 100,           # Новое поле
    "door_linkquality": 0,         # Новое поле  
    "door_device_id": "0xa4c138ffcbf1c3aa",  # Новое поле
    "motion_detected": False,
    "light_on": False,
    "light_brightness": 0,
    "water_leak": False,
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

class BrightnessRequest(BaseModel):
    brightness: int

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
    logger.info("✅ Backend подключен к MQTT брокеру")
    client.subscribe("zigbee2mqtt/#")

def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        logger.info(f"📨 MQTT сообщение: {topic} -> {payload}")
        
        # Определяем тип устройства по payload, а не по названию топика


        if "temperature" in payload:
            garage_state["temperature"] = payload.get("temperature", garage_state["temperature"])
            garage_state["humidity"] = payload.get("humidity", garage_state["humidity"])
            logger.info(f"🌡️ Обновлена температура: {garage_state['temperature']}°C")
            
        # Обрабатываем данные от конкретного датчика двери
        elif "0xa4c138ffcbf1c3aa" in topic:  # Ваш конкретный датчик
            garage_state["door_open"] = not payload.get("contact", True)
            garage_state["door_battery"] = payload.get("battery", 100)
            garage_state["door_linkquality"] = payload.get("linkquality", 0)  
            door_status = "открыта" if garage_state["door_open"] else "закрыта"
            logger.info(f"🚪 Обновлено состояние двери: {door_status}")
            
        elif "occupancy" in payload:
            garage_state["motion_detected"] = payload.get("occupancy", False)
            logger.info(f"👤 Обновлено движение: {'обнаружено' if garage_state['motion_detected'] else 'нет'}")
            
        elif "state" in payload or "brightness" in payload:
            garage_state["light_on"] = payload.get("state", "OFF") == "ON"
            garage_state["light_brightness"] = payload.get("brightness", 0)
            logger.info(f"💡 Обновлен свет: {'включен' if garage_state['light_on'] else 'выключен'}")
            
        elif "water_leak" in payload:
            garage_state["water_leak"] = payload.get("water_leak", False)
            if garage_state["water_leak"]:
                logger.warning("🚨 ОБНАРУЖЕНА ПРОТЕЧКА ВОДЫ!")
            else:
                logger.info("💧 Протечки воды нет")
        
        # Всегда обновляем время последнего обновления
        garage_state["system_info"] = get_system_info()
        garage_state["last_update"] = datetime.now().isoformat()
        
        # Рассылаем обновление
        run_async_in_mqtt_thread(broadcast_to_clients(garage_state.copy()))
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки MQTT сообщения: {e}")

def process_temperature_sensor_data(payload):
    """Обработка данных датчика температуры"""
    garage_state["sensor_online"] = True
    garage_state["last_sensor_update"] = datetime.now().isoformat()
    
    # Популярные поля для температуры в разных датчиках
    temperature_fields = ["temperature", "temp", "current_temperature"]
    humidity_fields = ["humidity", "hum", "current_humidity"]
    battery_fields = ["battery", "battery_level", "voltage"]
    
    # Ищем температуру
    for field in temperature_fields:
        if field in payload and isinstance(payload[field], (int, float)):
            garage_state["temperature"] = round(payload[field], 1)
            logger.info(f"🌡️ Температура: {garage_state['temperature']}°C")
            break
    
    # Ищем влажность
    for field in humidity_fields:
        if field in payload and isinstance(payload[field], (int, float)):
            garage_state["humidity"] = round(payload[field], 1)
            logger.info(f"💧 Влажность: {garage_state['humidity']}%")
            break
    
    # Ищем батарею
    for field in battery_fields:
        if field in payload and isinstance(payload[field], (int, float)):
            garage_state["battery_level"] = payload[field]
            logger.info(f"🔋 Батарея: {garage_state['battery_level']}%")
            break
    
    # Если не нашли стандартные поля, ищем любые числовые значения
    if "temperature" not in garage_state or "humidity" not in garage_state:
        for key, value in payload.items():
            if isinstance(value, (int, float)):
                if 10 <= value <= 40:  # Диапазон температур
                    garage_state["temperature"] = round(value, 1)
                    logger.info(f"🌡️ Температура (автоопределение): {value}°C из поля '{key}'")
                elif 0 <= value <= 100:  # Диапазон влажности
                    garage_state["humidity"] = round(value, 1)
                    logger.info(f"💧 Влажность (автоопределение): {value}% из поля '{key}'")

def start_mqtt_loop():
    """Запуск event loop для MQTT в отдельном потоке"""
    asyncio.set_event_loop(mqtt_loop)
    mqtt_loop.run_forever()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Запуск Backend API...")
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
    logger.info("🛑 Остановка Backend API...")
    mqtt_client.loop_stop()
    mqtt_loop.stop()

app = FastAPI(title="Smart Garage Backend", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            await asyncio.sleep(5)
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
        # Отправляем команду в Zigbee2MQTT для управления дверью
        mqtt_client.publish(
            "zigbee2mqtt/door_controller/set",
            json.dumps({"action": "toggle"})
        )
        
        return {
            "status": "success", 
            "message": "Команда отправлена на управление дверью"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления дверью: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/light")
async def control_light():
    """Управление светом"""
    try:
        new_state = "ON" if not garage_state["light_on"] else "OFF"
        brightness = 255 if new_state == "ON" else 0
        
        # Отправляем команду в Zigbee2MQTT
        mqtt_client.publish(
            "zigbee2mqtt/light_switch/set",
            json.dumps({
                "state": new_state,
                "brightness": brightness
            })
        )
        
        return {
            "status": "success",
            "light_on": new_state == "ON",
            "message": f"Свет {'включен' if new_state == 'ON' else 'выключен'}"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления светом: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/light_brightness")
async def control_light_brightness(request: BrightnessRequest):
    """Управление яркостью света"""
    try:
        brightness = request.brightness
        
        if brightness < 0 or brightness > 255:
            return {"status": "error", "message": "Яркость должна быть от 0 до 255"}
            
        # Отправляем команду в Zigbee2MQTT
        mqtt_client.publish(
            "zigbee2mqtt/light_switch/set",
            json.dumps({
                "state": "ON" if brightness > 0 else "OFF",
                "brightness": brightness
            })
        )
        
        return {
            "status": "success",
            "brightness": brightness,
            "light_on": brightness > 0,
            "message": f"Яркость установлена на {round((brightness / 255) * 100)}%"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления яркостью: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/devices")
async def get_devices():
    """Получение списка подключенных устройств"""
    # Можно добавить логику для получения списка устройств из Zigbee2MQTT
    return {
        "status": "success",
        "devices": [
            "temperature_sensor",
            "door_sensor", 
            "motion_sensor",
            "light_switch",
            "door_sensor": {
                "id": garage_state.get("door_device_id", "unknown"),
                "battery": garage_state.get("door_battery", 0),
                "linkquality": garage_state.get("door_linkquality", 0),
                "status": "open" if garage_state.get("door_open") else "closed"
            }
        ]
    }

@app.get("/api/status")
async def get_status():
    """Получение текущего статуса"""
    garage_state["system_info"] = get_system_info()
    return garage_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
