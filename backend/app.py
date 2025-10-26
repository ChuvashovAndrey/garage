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
    "temperature_battery": 100,           # Новое поле - батарея датчика температуры
    "temperature_linkquality": 0,         # Новое поле - уровень сигнала датчика температуры
    "temperature_device_id": "temperature_sensor",  # Новое поле - ID датчика температуры
    "door_open": False,
    "door_battery": 100,           
    "door_linkquality": 0,    
    "door_device_id": "door_sensor",
    "motion_detected": False,
    "motion_battery": 100,           # Новое поле - батарея датчика движения
    "motion_linkquality": 0,         # Новое поле - уровень сигнала датчика движения
    "motion_device_id": "motion_sensor",  # Новое поле - ID датчика движения
    "light_on": False,
    "light_brightness": 0,
    "light_color_temp": 300,            # НОВОЕ - цветовая температура
    "light_device_id": "smart_bulb",  # НОВОЕ - ID устройства
    "light_linkquality": 0,           # НОВОЕ - качество связи
    "light_voltage": 0,                # НОВОЕ - напряжение
    "water_leak_1": False,           # Новое поле - датчик протечки 1
    "water_battery_1": 100,          # Батарея датчика 1
    "water_device_id_1": "water_leak_1",         # ID датчика 1
    "water_leak_2": False,           # Новое поле - датчик протечки 2  
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
            garage_state["temperature_battery"] = payload.get("battery", garage_state["temperature_battery"])  # Добавлено
            garage_state["temperature_linkquality"] = payload.get("linkquality", garage_state["temperature_linkquality"])  # Добавлено
            logger.info(f"🌡️ Обновлена температура: {garage_state['temperature']}°C")
            
        # Обрабатываем данные от конкретного датчика двери
        elif "door_sensor" in topic:  # Ваш конкретный датчик
            garage_state["door_open"] = not payload.get("contact", True)
            garage_state["door_battery"] = payload.get("battery", 100)
            garage_state["door_linkquality"] = payload.get("linkquality", 0)  
            door_status = "открыта" if garage_state["door_open"] else "закрыта"
            logger.info(f"🚪 Обновлено состояние двери: {door_status}")
            
        elif "occupancy" in payload:
            garage_state["motion_detected"] = payload.get("occupancy", False)
            garage_state["motion_battery"] = payload.get("battery", garage_state["motion_battery"])
            garage_state["motion_linkquality"] = payload.get("linkquality", garage_state["motion_linkquality"])
            garage_state["motion_device_id"] = topic.split('/')[-1]  # Берем ID из топика
            logger.info(f"👤 Обновлено движение: {'обнаружено' if garage_state['motion_detected'] else 'нет'}, батарея: {garage_state['motion_battery']}%, сигнал: {garage_state['motion_linkquality']}")
     
       # Обработка данных от умной лампочки
        elif "smart_bulb" in topic:
           garage_state["light_on"] = payload.get("state", "OFF") == "ON"
           garage_state["light_brightness"] = payload.get("brightness", 0)
           garage_state["light_color_temp"] = payload.get("color_temp", garage_state["light_color_temp"])
           garage_state["light_device_id"] = topic.split('/')[-1]  # Берем ID из топика
           garage_state["light_linkquality"] = payload.get("linkquality", garage_state["light_linkquality"]) 
           garage_state["light_voltage"] = payload.get("voltage", garage_state["light_voltage"]) 
           light_status = "включена" if garage_state["light_on"] else "выключен"
           logger.info(f"💡 Обновлена лампочка: {light_status}, яркость: {garage_state['light_brightness']}, цветовая температура: {garage_state['light_color_temp']}K")

               
         # Обрабатываем датчики протечки воды
        elif "water" in topic.lower() or "leak" in topic.lower():
            # Определяем какой это датчик по ID в топике
            if "first" in topic.lower() or "1" in topic or "0xa4c1389122c0f5f0" in topic:  # Замените на реальный ID
                garage_state["water_leak_1"] = payload.get("water_leak", False)
                garage_state["water_battery_1"] = payload.get("battery", 100)
                garage_state["water_device_id_1"] = topic.split('/')[-1]  # Берем ID из топика
                logger.info(f"💧 Датчик протечки 1: {'ОБНАРУЖЕНО' if garage_state['water_leak_1'] else 'Норма'}")
                
            elif "second" in topic.lower() or "2" in topic or "0x0xa4c13833fff3d106" in topic:  # Замените на реальный ID  
                garage_state["water_leak_2"] = payload.get("water_leak", False)
                garage_state["water_battery_2"] = payload.get("battery", 100)
                garage_state["water_device_id_2"] = topic.split('/')[-1]
                logger.info(f"💧 Датчик протечки 2: {'ОБНАРУЖЕНО' if garage_state['water_leak_2'] else 'Норма'}")
        
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
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f" WebSocket подключен: {websocket.client}") 

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
        logger.info(" WebSocket отключен")

@app.post("/api/control/light")
async def control_light():
    """Управление светом"""
    try:
        new_state = "ON" if not garage_state["light_on"] else "OFF"
        brightness = 255 if new_state == "ON" else 0
        
        # Отправляем команду в Zigbee2MQTT
        mqtt_client.publish(
            "zigbee2mqtt/smart_bulb/set",  # ИЗМЕНИТЕ НА smart_bulb
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
            "zigbee2mqtt/smart_bulb/set",  # ИЗМЕНИТЕ НА smart_bulb
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

@app.post("/api/control/light_color_temp")
async def control_light_color_temp(request: dict):
    """Управление цветовой температурой света"""
    try:
        color_temp = request.get("color_temp", 300)
        
        # Ограничиваем диапазон (зависит от модели лампы)
        color_temp = max(150, min(500, color_temp))
            
        # Отправляем команду в Zigbee2MQTT
        mqtt_client.publish(
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
    garage_state["system_info"] = get_system_info()
    return garage_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
