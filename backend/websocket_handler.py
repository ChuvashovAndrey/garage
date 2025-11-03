# websocket_handler.py
import logging
import asyncio
import psutil
import time
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class WebSocketHandler:
    def __init__(self, garage_state):
        self.garage_state = garage_state
        self.connected_clients = []
    
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
    
    async def broadcast_to_clients(self, data):
        """Рассылка данных всем подключенным WebSocket клиентам"""
        for client in self.connected_clients[:]:
            try:
                await client.send_json(data)
            except:
                self.connected_clients.remove(client)
    
    async def handle_websocket_connection(self, websocket: WebSocket):
        """Обработка WebSocket соединения"""
        await websocket.accept()
        self.connected_clients.append(websocket)
        logger.info(f" WebSocket подключен: {websocket.client}") 

        try:
            # При подключении отправляем текущее состояние
            self.garage_state["system_info"] = self.get_system_info()
            await websocket.send_json(self.garage_state)
            
            # Периодически обновляем системную информацию
            while True:
                await asyncio.sleep(5)
                self.garage_state["system_info"] = self.get_system_info()
                await websocket.send_json(self.garage_state)
                
        except Exception as e:
            logger.error(f"❌ WebSocket ошибка: {e}")
        finally:
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)
            logger.info(" WebSocket отключен")