# /home/andrey/Projects/garage/zigbee-simulator/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Копируем requirements
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код симулятора
COPY simulator.py .

CMD ["python", "simulator.py"]
