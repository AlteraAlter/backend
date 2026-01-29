FROM python:3.13

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Устанавливаем uv и зависимости
RUN pip install uv && \
    uv pip install --system -r requirements.txt

# Создаём папку для статики
RUN mkdir -p /app/static

EXPOSE 8000