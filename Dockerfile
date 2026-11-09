FROM python:3.11-slim

# Установка FFmpeg для наложения анимированной ватермарки Poco AI
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Запуск полноценного POCO AI Web Studio и Telegram-бота
CMD ["python", "app.py"]
