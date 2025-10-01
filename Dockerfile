FROM python:3.11

WORKDIR /app

# Устанавливаем зависимости вручную
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    paho-mqtt==1.6.1 \
    jinja2==3.1.2 \
    psutil==5.9.6 \
    websockets==12.0

COPY . .

RUN mkdir -p templates static

EXPOSE 5000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000", "--ws", "websockets"]
