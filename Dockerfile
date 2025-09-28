# /home/andrey/Projects/garage/Dockerfile
FROM python:3.11

WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

# Создаем необходимые папки
RUN mkdir -p templates static

EXPOSE 5000

CMD ["python", "app.py"]
