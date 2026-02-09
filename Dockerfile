FROM python:3.13 AS backend

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

FROM node:20-alpine AS frontend

WORKDIR /app/frontend-app

COPY frontend-app/package.json ./
RUN npm install

COPY frontend-app ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
