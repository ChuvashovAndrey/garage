# /home/andrey/Projects/garage/zigbee-simulator/simulator.py
import time
import json
import random
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ZigbeeSimulator")

class ZigbeeDeviceSimulator:
    def __init__(self):
        self.mqtt_client = None
        self.is_running = True
        
        # Состояния виртуальных устройств
        self.devices = {
            "garage_temperature_sensor": {
                "temperature": 20.0,
                "humidity": 45.0,
                "pressure": 1013.25,
                "battery": 100,
                "voltage": 3000
            },
            "garage_door_sensor": {
                "contact": True,  # True = закрыто, False = открыто
                "battery": 100,
                "voltage": 3000
            },
            "garage_motion_sensor": {
                "occupancy": False,
                "battery": 100,
                "voltage": 3000,
                "illuminance": 0
            },
            "garage_light_switch": {
                "state": "OFF",
                "brightness": 0,
                "color_temp": 370
            }
        }
    
    def connect_mqtt(self):
        """Подключение к MQTT брокеру"""
        try:
            mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.connect(mqtt_host, 1883, 60)
            self.mqtt_client.loop_start()
            
            # Подписываемся на команды управления
            self.mqtt_client.subscribe("zigbee2mqtt/garage_light_switch/set")
            self.mqtt_client.on_message = self.on_message
            
            logger.info(f"✅ Подключен к MQTT брокеру: {mqtt_host}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MQTT: {e}")
            return False
    
    def on_message(self, client, userdata, msg):
        """Обработка входящих MQTT сообщений"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            logger.info(f"📨 Получена команда: {topic} -> {payload}")
            
            if "garage_light_switch/set" in topic:
                if "state" in payload:
                    self.devices["garage_light_switch"]["state"] = payload["state"]
                    self.publish_device_state("garage_light_switch")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
    
    def publish_device_state(self, device_name):
        """Публикация состояния устройства"""
        if not self.mqtt_client:
            return
            
        topic = f"zigbee2mqtt/{device_name}"
        payload = self.devices[device_name].copy()
        
        # Добавляем общие метрики
        payload["linkquality"] = random.randint(80, 100)
        payload["last_seen"] = datetime.now().isoformat()
        
        self.mqtt_client.publish(topic, json.dumps(payload))
        logger.debug(f"📤 Опубликовано: {topic} -> {payload}")
    
    def simulate_temperature_sensor(self):
        """Симуляция датчика температуры/влажности"""
        logger.info("🌡️ Запуск симулятора температуры")
        
        while self.is_running:
            try:
                # Реалистичные изменения температуры
                hour = datetime.now().hour
                if 2 <= hour <= 6:  # Ночь
                    temp_change = random.uniform(-0.2, 0.05)
                elif 12 <= hour <= 16:  # День
                    temp_change = random.uniform(-0.05, 0.2)
                else:
                    temp_change = random.uniform(-0.1, 0.1)
                
                # Обновляем температуру
                self.devices["garage_temperature_sensor"]["temperature"] = round(
                    max(15, min(30, self.devices["garage_temperature_sensor"]["temperature"] + temp_change)), 1
                )
                
                # Обновляем влажность
                self.devices["garage_temperature_sensor"]["humidity"] = round(
                    max(30, min(80, 45 + random.uniform(-5, 5))), 1
                )
                
                # Публикуем состояние
                self.publish_device_state("garage_temperature_sensor")
                
                time.sleep(30)  # Обновление каждые 30 секунд
                
            except Exception as e:
                logger.error(f"❌ Ошибка в симуляторе температуры: {e}")
                time.sleep(5)
    
    def simulate_door_sensor(self):
        """Симуляция датчика открытия/закрытия двери"""
        logger.info("🚪 Запуск симулятора датчика двери")
        
        while self.is_running:
            try:
                # Случайное изменение состояния (1% вероятность)
                if random.random() < 0.01:
                    old_state = self.devices["garage_door_sensor"]["contact"]
                    self.devices["garage_door_sensor"]["contact"] = not old_state
                    
                    status = "закрыта" if self.devices["garage_door_sensor"]["contact"] else "открыта"
                    logger.info(f"🚪 Дверь {status}")
                
                # Публикуем состояние
                self.publish_device_state("garage_door_sensor")
                
                time.sleep(10)  # Обновление каждые 10 секунд
                
            except Exception as e:
                logger.error(f"❌ Ошибка в симуляторе двери: {e}")
                time.sleep(5)
    
    def simulate_motion_sensor(self):
        """Симуляция датчика движения"""
        logger.info("👤 Запуск симулятора датчика движения")
        
        motion_active = False
        motion_timer = 0
        
        while self.is_running:
            try:
                if motion_active:
                    motion_timer -= 1
                    if motion_timer <= 0:
                        motion_active = False
                        self.devices["garage_motion_sensor"]["occupancy"] = False
                        logger.info("👤 Движение прекратилось")
                else:
                    # 3% вероятность обнаружения движения
                    if random.random() < 0.03:
                        motion_active = True
                        motion_timer = random.randint(5, 15)  # Длительность движения
                        self.devices["garage_motion_sensor"]["occupancy"] = True
                        logger.info("👤 Обнаружено движение!")
                
                # Обновляем освещенность
                hour = datetime.now().hour
                if 6 <= hour <= 18:  # День
                    self.devices["garage_motion_sensor"]["illuminance"] = random.randint(100, 500)
                else:  # Ночь
                    self.devices["garage_motion_sensor"]["illuminance"] = random.randint(0, 50)
                
                # Публикуем состояние
                self.publish_device_state("garage_motion_sensor")
                
                time.sleep(2)  # Частые обновления для движения
                
            except Exception as e:
                logger.error(f"❌ Ошибка в симуляторе движения: {e}")
                time.sleep(5)
    
    def simulate_light_switch(self):
        """Симуляция умного выключателя"""
        logger.info("💡 Запуск симулятора умного света")
        
        while self.is_running:
            try:
                # Автоматическое управление светом на основе движения
                if (self.devices["garage_motion_sensor"]["occupancy"] and 
                    self.devices["garage_motion_sensor"]["illuminance"] < 50):
                    if self.devices["garage_light_switch"]["state"] == "OFF":
                        self.devices["garage_light_switch"]["state"] = "ON"
                        self.devices["garage_light_switch"]["brightness"] = 255
                        logger.info("💡 Свет автоматически включен")
                
                # Публикуем состояние
                self.publish_device_state("garage_light_switch")
                
                time.sleep(5)  # Обновление каждые 5 секунд
                
            except Exception as e:
                logger.error(f"❌ Ошибка в симуляторе света: {e}")
                time.sleep(5)
    
    def start(self):
        """Запуск всех симуляторов"""
        if not self.connect_mqtt():
            logger.error("❌ Не удалось запустить симулятор")
            return False
        
        logger.info("🚀 Запуск всех симуляторов Zigbee устройств...")
        
        # Запускаем симуляторы в отдельных потоках
        import threading
        
        threads = [
            threading.Thread(target=self.simulate_temperature_sensor, daemon=True),
            threading.Thread(target=self.simulate_door_sensor, daemon=True),
            threading.Thread(target=self.simulate_motion_sensor, daemon=True),
            threading.Thread(target=self.simulate_light_switch, daemon=True)
        ]
        
        for thread in threads:
            thread.start()
        
        logger.info("✅ Все симуляторы запущены!")
        return True
    
    def stop(self):
        """Остановка симулятора"""
        self.is_running = False
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
        logger.info("🛑 Симулятор остановлен")

def main():
    """Основная функция"""
    simulator = ZigbeeDeviceSimulator()
    
    try:
        if simulator.start():
            # Бесконечный цикл для поддержания работы
            while simulator.is_running:
                time.sleep(1)
        else:
            logger.error("❌ Не удалось запустить симулятор Zigbee устройств")
            
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал прерывания...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        simulator.stop()

if __name__ == "__main__":
    main()
