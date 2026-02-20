# Kaufland API Service

Django service for managing Kaufland marketplace operations:
- product upload
- bulk upload
- price update
- product checker
- product delete
- progress updates over WebSocket

## Stack
- Django + DRF (async views)
- PostgreSQL
- Redis + Channels
- Uvicorn (ASGI)
- Nginx (reverse proxy)
- Docker Compose

## Project Structure
- `kaufland_API/settings.py`: app config, database, static/media, JWT, Channels.
- `kaufland_API/asgi.py`: ASGI entrypoint (required for WebSockets).
- `main_api/views.py`: main HTTP endpoints and job orchestration.
- `main_api/src/controller/kaufland_controller.py`: core Kaufland API integration logic.
- `main_api/src/servises/kaufland_upload_service.py`: upload workflow service.
- `main_api/src/servises/pic_pipline.py`: image pipeline orchestration.
- `main_api/src/servises/image_processing.py`: image download + transform helpers.
- `main_api/src/servises/json_mapper.py`: input JSON to internal schema mapper.
- `main_api/consumers.py`, `main_api/routing.py`: WebSocket events and routing.
- `docker-compose.yaml`, `Dockerfile`, `nginx.conf`: runtime/infrastructure setup.

## API Endpoints
Base prefix: `/api/`

- `POST /api/token/`: get JWT token.
- `POST /api/token/refresh/`: refresh token.
- `GET/POST /api/kaufland_main/`: checker/delete/price update via file or single EAN.
- `POST /api/kaufland_main/upload_json/`: upload one product or a collection from JSON.
- `POST /api/kaufland_main/stop_job/`: request cancellation for a running job.
- `GET /api/protected/`: test protected endpoint.

## Code Pieces Explained

### `main_api/src/controller/kaufland_controller.py`
- Responsible for authenticated requests to Kaufland.
- Handles retries, rate-limit behavior, error normalization, and status polling.
- Exposes business methods used by views: checker, upload, delete, price updates.

### `main_api/views.py`
- Thin API layer.
- Validates input, starts jobs, returns immediate response for async workflows.
- Sends progress/failure updates tied to `job_id`.

### `main_api/src/servises/image_processing.py`
- Downloads product images asynchronously.
- Normalizes extension/filename.
- Resizes to minimum dimensions and compresses to size limits.

### `main_api/src/servises/json_mapper.py`
- Converts supplier JSON keys into the normalized internal payload format.
- Keeps mapping rules in one place to simplify upstream schema changes.

### `main_api/src/job_registry.py`
- Tracks cancellable jobs by `job_id`.
- Used by long operations so frontend can stop running tasks.

### `main_api/src/logger.py`
- Centralized logging helper.
- Supports both console and file logging for long async operations.

## Infrastructure Notes

### `docker-compose.yaml`
- `django` runs migrations and starts `uvicorn`.
- `postgres` and `redis` are health-checked before app startup.
- `nginx` proxies HTTP and WebSocket traffic to Django.

### `Dockerfile`
- Installs image-related system libs (`libjpeg`, `zlib`, `libpng`).
- Uses dependency-layer caching (`COPY requirements.txt` before app code).

### `nginx.conf`
- Forwards `/` to Django.
- Handles WebSocket upgrade under `/ws/`.
- Serves media via `/media/` alias.

## Run
```bash
docker compose up --build -d
```

## Environment
- `.env`: local development values.
- `.env.docker`: container runtime values.

Required values include:
- database credentials/host/port
- Kaufland API credentials
- JWT and app settings
- any SSH/FTP related credentials used by services
