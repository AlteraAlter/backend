FROM python:3.13 AS backend

# System libs required by Pillow/image processing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency file first for better layer caching.
COPY requirements.docker.txt .

# Install dependencies (uv is used as fast installer frontend).
RUN pip install uv && \
    uv pip install --system -r requirements.docker.txt

# Copy application source after deps.
COPY . .

# Static directory expected by Django/Whitenoise setup.
RUN mkdir -p /app/static

EXPOSE 8000
