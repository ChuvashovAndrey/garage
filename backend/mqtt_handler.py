# mqtt_handler.py
import json
import logging
import asyncio
from datetime import datetime
import paho.mqtt.client as mqtt
import psutil
import time
import threading

logger = logging.getLogger(__name__)

class MQTTHandler:
    def __init__(self, garage_state, broadcast_callback):
        self.garage_state = garage_state
        self.broadcast_callback = broadcast_callback
        self.mqtt_loop = asyncio.new_event_loop()
        self.mqtt_client = mqtt.Client()
        
    def get_system_info(self):
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
    
    def run_async_in_mqtt_thread(self, coro):
        """Запуск асинхронной функции в MQTT потоке"""
        asyncio.run_coroutine_threadsafe(coro, self.mqtt_loop)
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        logger.info("✅ Backend подключен к MQTT брокеру")
        client.subscribe("zigbee2mqtt/#")
    
    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            logger.info(f"📨 MQTT сообщение: {topic} -> {payload}")
            
            # Определяем тип устройства по payload, а не по названию топика

            if "temperature" in payload:
                self.garage_state["temperature"] = payload.get("temperature", self.garage_state["temperature"])
                self.garage_state["humidity"] = payload.get("humidity", self.garage_state["humidity"])
                self.garage_state["temperature_battery"] = payload.get("battery", self.garage_state["temperature_battery"])  # Добавлено
                self.garage_state["temperature_linkquality"] = payload.get("linkquality", self.garage_state["temperature_linkquality"])  # Добавлено
                logger.info(f"🌡️ Обновлена температура: {self.garage_state['temperature']}°C")
                
            # Обрабатываем данные от конкретного датчика двери
            elif "door_sensor" in topic:  # Ваш конкретный датчик
                self.garage_state["door_open"] = not payload.get("contact", True)
                self.garage_state["door_battery"] = payload.get("battery", 100)
                self.garage_state["door_linkquality"] = payload.get("linkquality", 0)  
                door_status = "открыта" if self.garage_state["door_open"] else "закрыта"
                logger.info(f"🚪 Обновлено состояние двери: {door_status}")
                
            elif "occupancy" in payload:
                self.garage_state["motion_detected"] = payload.get("occupancy", False)
                self.garage_state["motion_battery"] = payload.get("battery", self.garage_state["motion_battery"])
                self.garage_state["motion_linkquality"] = payload.get("linkquality", self.garage_state["motion_linkquality"])
                self.garage_state["motion_device_id"] = topic.split('/')[-1]  # Берем ID из топика
                logger.info(f"👤 Обновлено движение: {'обнаружено' if self.garage_state['motion_detected'] else 'нет'}, батарея: {self.garage_state['motion_battery']}%, сигнал: {self.garage_state['motion_linkquality']}")
         
           # Обработка данных от умной лампочки
            elif "smart_bulb" in topic:
               self.garage_state["light_on"] = payload.get("state", "OFF") == "ON"
               self.garage_state["light_brightness"] = payload.get("brightness", 0)
               self.garage_state["light_color_temp"] = payload.get("color_temp", self.garage_state["light_color_temp"])
               self.garage_state["light_device_id"] = topic.split('/')[-1]  # Берем ID из топика
               self.garage_state["light_linkquality"] = payload.get("linkquality", self.garage_state["light_linkquality"]) 
               self.garage_state["light_voltage"] = payload.get("voltage", self.garage_state["light_voltage"]) 
               light_status = "включена" if self.garage_state["light_on"] else "выключен"
               logger.info(f"💡 Обновлена лампочка: {light_status}, яркость: {self.garage_state['light_brightness']}, цветовая температура: {self.garage_state['light_color_temp']}K")

                   
             # Обрабатываем датчики протечки воды
            elif "water" in topic.lower() or "leak" in topic.lower():
                # Определяем какой это датчик по ID в топике
                if "first" in topic.lower() or "1" in topic or "0xa4c1389122c0f5f0" in topic:  # Замените на реальный ID
                    self.garage_state["water_leak_1"] = payload.get("water_leak", False)
                    self.garage_state["water_battery_1"] = payload.get("battery", 100)
                    self.garage_state["water_device_id_1"] = topic.split('/')[-1]  # Берем ID из топика
                    logger.info(f"💧 Датчик протечки 1: {'ОБНАРУЖЕНО' if self.garage_state['water_leak_1'] else 'Норма'}")
                    
                elif "second" in topic.lower() or "2" in topic or "0x0xa4c13833fff3d106" in topic:  # Замените на реальный ID  
                    self.garage_state["water_leak_2"] = payload.get("water_leak", False)
                    self.garage_state["water_battery_2"] = payload.get("battery", 100)
                    self.garage_state["water_device_id_2"] = topic.split('/')[-1]
                    logger.info(f"💧 Датчик протечки 2: {'ОБНАРУЖЕНО' if self.garage_state['water_leak_2'] else 'Норма'}")
            
            # Всегда обновляем время последнего обновления
            self.garage_state["system_info"] = self.get_system_info()
            self.garage_state["last_update"] = datetime.now().isoformat()
            
            # Рассылаем обновление
            self.run_async_in_mqtt_thread(self.broadcast_callback(self.garage_state.copy()))
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки MQTT сообщения: {e}")
    
    def process_temperature_sensor_data(self, payload):
        """Обработка данных датчика температуры"""
        self.garage_state["sensor_online"] = True
        self.garage_state["last_sensor_update"] = datetime.now().isoformat()
        
        # Популярные поля для температуры в разных датчиках
        temperature_fields = ["temperature", "temp", "current_temperature"]
        humidity_fields = ["humidity", "hum", "current_humidity"]
        battery_fields = ["battery", "battery_level", "voltage"]
        
        # Ищем температуру
        for field in temperature_fields:
            if field in payload and isinstance(payload[field], (int, float)):
                self.garage_state["temperature"] = round(payload[field], 1)
                logger.info(f"🌡️ Температура: {self.garage_state['temperature']}°C")
                break
        
        # Ищем влажность
        for field in humidity_fields:
            if field in payload and isinstance(payload[field], (int, float)):
                self.garage_state["humidity"] = round(payload[field], 1)
                logger.info(f"💧 Влажность: {self.garage_state['humidity']}%")
                break
        
        # Ищем батарею
        for field in battery_fields:
            if field in payload and isinstance(payload[field], (int, float)):
                self.garage_state["battery_level"] = payload[field]
                logger.info(f"🔋 Батарея: {self.garage_state['battery_level']}%")
                break
        
        # Если не нашли стандартные поля, ищем любые числовые значения
        if "temperature" not in self.garage_state or "humidity" not in self.garage_state:
            for key, value in payload.items():
                if isinstance(value, (int, float)):
                    if 10 <= value <= 40:  # Диапазон температур
                        self.garage_state["temperature"] = round(value, 1)
                        logger.info(f"🌡️ Температура (автоопределение): {value}°C из поля '{key}'")
                    elif 0 <= value <= 100:  # Диапазон влажности
                        self.garage_state["humidity"] = round(value, 1)
                        logger.info(f"💧 Влажность (автоопределение): {value}% из поля '{key}'")
    
    def start_mqtt_loop(self):
        """Запуск event loop для MQTT в отдельном потоке"""
        asyncio.set_event_loop(self.mqtt_loop)
        self.mqtt_loop.run_forever()
    
    def connect(self, mqtt_host):
        """Подключение к MQTT брокеру"""
        try:
            # Запускаем MQTT loop в отдельном потоке
            mqtt_thread = threading.Thread(target=self.start_mqtt_loop, daemon=True)
            mqtt_thread.start()
            
            # Подключаем MQTT клиент
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.connect(mqtt_host, 1883, 60)
            self.mqtt_client.loop_start()
            
            logger.info("✅ MQTT клиент запущен")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка запуска MQTT клиента: {e}")
            return False
    
    def disconnect(self):
        """Отключение от MQTT брокера"""
        self.mqtt_client.loop_stop()
        self.mqtt_loop.stop()
    
    def publish(self, topic, payload):
        """Публикация сообщения в MQTT"""
        self.mqtt_client.publish(topic, payload)