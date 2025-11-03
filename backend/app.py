# app.py
import json
import logging
import asyncio
import os
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel

from mqtt_handler import MQTTHandler
from websocket_handler import WebSocketHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные
garage_state = {
    "temperature": 20.0,
    "humidity": 45.0,
    "temperature_battery": 100,           #батарея датчика температуры
    "temperature_linkquality": 0,         #уровень сигнала датчика температуры
    "temperature_device_id": "temperature_sensor",  #ID датчика температуры
    "door_open": False,
    "door_battery": 100,           
    "door_linkquality": 0,    
    "door_device_id": "door_sensor",
    "motion_detected": False,
    "motion_battery": 100,           #батарея датчика движения
    "motion_linkquality": 0,         #уровень сигнала датчика движения
    "motion_device_id": "motion_sensor",  #ID датчика движения
    "light_on": False,
    "light_brightness": 0,
    "light_color_temp": 300,            #цветовая температура
    "light_device_id": "smart_bulb",  #ID устройства
    "light_linkquality": 0,           #качество связи
    "light_voltage": 0,                #напряжение
    "water_leak_1": False,           #датчик протечки 1
    "water_battery_1": 100,          # Батарея датчика 1
    "water_device_id_1": "water_leak_1",         # ID датчика 1
    "water_leak_2": False,           # датчик протечки 2  
    "water_battery_2": 100,          # Батарея датчика 2
    "water_device_id_2": "water_leak_2",         # ID датчика 2
    "last_update": None,
    "system_info": {
        "cpu_percent": 0,
        "memory_percent": 0,
        "disk_usage": 0,
        "uptime": 0
    }
}

# Инициализация обработчиков
mqtt_handler = None
websocket_handler = None

class BrightnessRequest(BaseModel):
    brightness: int

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Запуск Backend API...")
    try:
        global mqtt_handler, websocket_handler
        
        # Инициализация обработчиков
        websocket_handler = WebSocketHandler(garage_state)
        mqtt_handler = MQTTHandler(garage_state, websocket_handler.broadcast_to_clients)
        
        # Подключаем MQTT
        mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
        
        # Даем время на запуск loop
        await asyncio.sleep(1)
        
        # Подключаем MQTT клиент
        if not mqtt_handler.connect(mqtt_host):
            raise Exception("Не удалось подключиться к MQTT брокеру")
        
        logger.info("✅ MQTT клиент запущен")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска MQTT клиента: {e}")
    
    yield  # Работа приложения
    
    # Shutdown
    logger.info("🛑 Остановка Backend API...")
    if mqtt_handler:
        mqtt_handler.disconnect()

app = FastAPI(title="Smart Garage Backend", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://85.237.34.9:5000",
        "http://localhost:5000",
        "http://127.0.0.1:5000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if websocket_handler:
        await websocket_handler.handle_websocket_connection(websocket)

@app.post("/api/control/light")
async def control_light():
    """Управление светом"""
    try:
        new_state = "ON" if not garage_state["light_on"] else "OFF"

        # ИСПРАВЛЕНО: Используем последнюю установленную яркость вместо 255
        brightness = garage_state["light_brightness"] if new_state == "ON" else 0

        # Если яркость 0 при включении, устанавливаем разумное значение по умолчанию
        if new_state == "ON" and brightness == 0:
            brightness = 128  # 50% яркости по умолчанию

        # Отправляем команду в Zigbee2MQTT
        mqtt_handler.publish(
            "zigbee2mqtt/smart_bulb/set",
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
            
        # ИСПРАВЛЕНО: Включаем свет только если он был выключен и устанавливаем яркость
        should_turn_on = not garage_state["light_on"] and brightness > 0
        
        # Отправляем команду в Zigbee2MQTT
        mqtt_handler.publish(
            "zigbee2mqtt/smart_bulb/set",
            json.dumps({
                "state": "ON" if should_turn_on else ("ON" if garage_state["light_on"] else "OFF"),
                "brightness": brightness
            })
        )
        
        return {
            "status": "success",
            "brightness": brightness,
            "light_on": brightness > 0 or garage_state["light_on"],
            "message": f"Яркость установлена на {round((brightness / 255) * 100)}%"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления яркостью: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/light_color_temp")
async def control_light_color_temp(request: dict):
    """Управление цветовой температурой света"""
    try:
        color_temp = request.get("color_temp", 300)
        
        # Ограничиваем диапазон (зависит от модели лампы)
        color_temp = max(150, min(500, color_temp))
            
        # Отправляем команду в Zigbee2MQTT
        mqtt_handler.publish(
            "zigbee2mqtt/smart_bulb/set",  # ИЗМЕНИТЕ НА smart_bulb
            json.dumps({
                "color_temp": color_temp
            })
        )
        
        return {
            "status": "success",
            "color_temp": color_temp,
            "message": f"Цветовая температура установлена на {color_temp}K"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка управления цветовой температурой: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/door")
async def control_door():
    """Управление дверью гаража"""
    try:
        # Отправляем команду в Zigbee2MQTT для управления дверью
        mqtt_handler.publish(
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

@app.get("/api/devices")
async def get_devices():
    """Получение списка подключенных устройств"""
    return {
        "status": "success",
        "devices": [
            {
                "type": "temperature_sensor",
                "id": garage_state.get("temperature_device_id", "unknown"),
                "battery": garage_state.get("temperature_battery", 0),
                "linkquality": garage_state.get("temperature_linkquality", 0),
                "status": f"{garage_state.get('temperature', 0)}°C, {garage_state.get('humidity', 0)}%"
            },
            {
                "type": "door_sensor", 
                "id": garage_state.get("door_device_id", "unknown"),
                "battery": garage_state.get("door_battery", 0),
                "linkquality": garage_state.get("door_linkquality", 0),
                "status": "open" if garage_state.get("door_open") else "closed"
            },
            {
                "type": "motion_sensor",
                "id": garage_state.get("motion_device_id", "unknown"),
                "battery": garage_state.get("motion_battery", 0),
                "linkquality": garage_state.get("motion_linkquality", 0),
                "status": "motion" if garage_state.get("motion_detected") else "no_motion"
            },
            "light_switch"
        ]
    }

@app.get("/api/water_sensors")
async def get_water_sensors():
    """Получение информации о датчиках протечки"""
    return {
        "status": "success",
        "sensors": {
            "sensor_1": {
                "leak": garage_state.get("water_leak_1", False),
                "battery": garage_state.get("water_battery_1", 100),
                "device_id": garage_state.get("water_device_id_1", ""),
                "status": "leak" if garage_state.get("water_leak_1") else "normal"
            },
            "sensor_2": {
                "leak": garage_state.get("water_leak_2", False),
                "battery": garage_state.get("water_battery_2", 100),
                "device_id": garage_state.get("water_device_id_2", ""),
                "status": "leak" if garage_state.get("water_leak_2") else "normal"
            }
        }
    }

@app.get("/api/status")
async def get_status():
    """Получение текущего статуса"""
    garage_state["system_info"] = websocket_handler.get_system_info() if websocket_handler else {}
    return garage_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")