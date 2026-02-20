FROM python:3.13 AS backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1️⃣ copy only dependency files first
COPY requirements.txt .

# 2️⃣ install deps (cached unless requirements change)
RUN pip install uv && \
    uv pip install --system -r requirements.txt

# 3️⃣ now copy project code
COPY . .

RUN mkdir -p /app/static

EXPOSE 8000
