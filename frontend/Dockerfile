FROM python:3.11

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем необходимые папки
RUN mkdir -p templates static

EXPOSE 5000

CMD ["python", "app.py", "--reload"]
