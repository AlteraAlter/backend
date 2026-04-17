# Kaufland API Integration Guide (External Django Service)

This document describes how an external service should work with the Kaufland API.

## 1) Base URL and prerequisites

- Base URL (prod): `https://kaufland.automatonsoft.de`
- API prefix: `/api`
- Auth type: JWT Bearer token (except `/api/health/`)
- Required controller value in operations: `jv` or `xl`

Recommended for external Django service:
- Use server-to-server auth user (dedicated account).
- Store `access` + `refresh` token securely.
- Auto-refresh token on `401`.

---

## 2) Authentication

## 2.1 Get access token

- **Method**: `POST`
- **URL**: `/api/token/`
- **Body (JSON)**:

```json
{
  "username": "YOUR_USERNAME",
  "password": "YOUR_PASSWORD"
}
```

- **Success response (`200`)**:

```json
{
  "refresh": "<jwt_refresh>",
  "access": "<jwt_access>",
  "user": {
    "id": 1,
    "username": "YOUR_USERNAME"
  }
}
```

## 2.2 Refresh token

- **Method**: `POST`
- **URL**: `/api/token/refresh/`
- **Body (JSON)**:

```json
{
  "refresh": "<jwt_refresh>"
}
```

- **Success response (`200`)**:

```json
{
  "access": "<new_jwt_access>"
}
```

Use this header for protected endpoints:

```http
Authorization: Bearer <jwt_access>
```

---

## 3) Healthcheck (public)

- **Method**: `GET`
- **URL**: `/api/health/`
- **Auth**: Not required

### Success (`200`)

```json
{
  "status": "ok",
  "service": "kaufland-api",
  "database": "ok"
}
```

### Degraded (`503`)

```json
{
  "status": "degraded",
  "service": "kaufland-api",
  "database": "error"
}
```

---

## 4) Get product by EAN (single checker)

- **Method**: `GET`
- **URL**: `/api/products/ean/{ean}/?controller=jv`
- **Auth**: Required
- **Path param**: `ean` (string)
- **Query param**:
  - `controller`: `jv` or `xl` (default `jv`)

### Success (`200`) when found

```json
{
  "controller": "jv",
  "ean": "1234567890123",
  "found": true,
  "storefronts": ["de", "pl"],
  "items": [ ... ],
  "message": null
}
```

### Success (`200`) when not found

```json
{
  "controller": "jv",
  "ean": "1234567890123",
  "found": false,
  "storefronts": [],
  "items": [],
  "message": "not found"
}
```

### Validation error (`400`)

```json
{
  "error": "controller must be 'jv' or 'xl'"
}
```

---

## 5) Main operations endpoint (checker/delete/change_price)

- **Method**: `POST`
- **URL**: `/api/kaufland_main/`
- **Auth**: Required

Input style:
- `multipart/form-data` for file-based operations
- `application/json` for single EAN checker

Supported `mode` values:
- `checker`
- `delete`
- `change_price`

## 5.1 Checker by single EAN (async job)

- **Content-Type**: `application/json`
- **Body**:

```json
{
  "controller": "jv",
  "mode": "checker",
  "ean": "1234567890123",
  "job_id": "optional_custom_job_id"
}
```

- **Response (`202`)**:

```json
{
  "message": "checker job started",
  "job_id": "<job_id>",
  "eans": ["1234567890123"]
}
```

## 5.2 Checker by file (async job)

- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `controller`: `jv` or `xl`
  - `mode`: `checker`
  - `file`: `.csv` or `.xlsx` with **exact column set**: `ean`
  - `job_id`: optional

- **Response (`202`)**:

```json
{
  "message": "checker job started",
  "job_id": "<job_id>",
  "eans": ["..."]
}
```

## 5.3 Delete by file (async job)

- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `controller`: `jv` or `xl`
  - `mode`: `delete`
  - `file`: `.csv` or `.xlsx` with columns:
    - exact `ean`, or
    - includes `ean` and `price` (price ignored for delete)
  - `job_id`: optional

- **Response (`202`)**:

```json
{
  "message": "delete job started",
  "job_id": "<job_id>"
}
```

## 5.4 Change price by file (sync request)

- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `controller`: `jv` or `xl`
  - `mode`: `change_price`
  - `file`: `.csv` or `.xlsx` with `ean` and `price`

- **Success (`200`)**:
```json
"all prices updated"
```

- **Failure (`500`)**:
```json
"something went wrong"
```

## 5.5 Common errors (`400`)

Examples:
- invalid/missing fields
- unsupported file format
- wrong file columns

---

## 6) Upload endpoint (JSON product upload)

- **Method**: `POST`
- **URL**: `/api/kaufland_main/upload_json/`
- **Auth**: Required
- **Content-Type**: `multipart/form-data`

Fields:
- `controller`: `jv` or `xl`
- `mode`: `upload_product` or `upload_collection`
- `file`: `.json`
- `job_id`: optional

## 6.1 Upload single product (`upload_product`)

- **Response (`200` or `500`)**:

```json
{
  "message": "success",
  "job_id": "<job_id>"
}
```

or

```json
{
  "message": "failed",
  "job_id": "<job_id>"
}
```

## 6.2 Upload collection (`upload_collection`, async job)

- **Response (`202`)**:

```json
{
  "message": "upload job started",
  "job_id": "<job_id>"
}
```

---

## 7) Stop running job

- **Method**: `POST`
- **URL**: `/api/kaufland_main/stop_job/`
- **Auth**: Required
- **Body (JSON)**:

```json
{
  "job_id": "<job_id>"
}
```

- **Success (`200`)**:

```json
{
  "message": "stop requested",
  "job_id": "<job_id>"
}
```

- **Validation (`400`)**:
```json
{
  "error": "job_id is required"
}
```

---

## 8) Aftercool sync job

- **Method**: `GET`
- **URL**: `/api/aftercool_login/`
- **Auth**: Not required currently

- **Response (`202`)**:

```json
{
  "message": "aftercool price sync job started",
  "job_id": "<job_id>",
  "controller": "jv",
  "ws_task": "checker",
  "progress_ws": "/ws/checker-progress/<job_id>/",
  "change_log_file": "logs/aftercool_price_changes.csv"
}
```

---

## 9) Job ID rules

- You can pass your own `job_id`.
- If omitted, backend generates one (`uuid4().hex`) and returns it in response.

Recommendation:
- External service should save returned `job_id` and use it as correlation key.

---

## 10) WebSocket progress channels

Use `ws://` or `wss://` with same host.

- Upload progress: `/ws/upload-progress/{job_id}/`
- Checker progress: `/ws/checker-progress/{job_id}/`
- Delete progress: `/ws/delete-progress/{job_id}/`

Common message shape:

```json
{
  "job_id": "<job_id>",
  "event": "job_completed",
  "payload": { ... },
  "info": null,
  "timestamp": "2026-04-17T12:00:00.000000"
}
```

Note:
- `delete` channel may also emit legacy event payloads (`delete_progress`, `delete_message`) in addition to `ws_message`.

---

## 11) Integration flow (recommended)

1. Call `GET /api/health/` and require `200`.
2. Authenticate via `/api/token/`.
3. Send operation request (`upload_json` or `kaufland_main`).
4. Read `job_id` from response (`202`).
5. Subscribe to corresponding WS channel by `job_id`.
6. Track completion/failure events and persist status in your DB.
7. If needed, call `/api/kaufland_main/stop_job/` to cancel.

---

## 12) External Django service example (HTTP)

```python
import requests

BASE = "https://kaufland.automatonsoft.de"

def get_tokens(username: str, password: str) -> dict:
    r = requests.post(f"{BASE}/api/token/", json={
        "username": username,
        "password": password,
    }, timeout=30)
    r.raise_for_status()
    return r.json()

def checker_single(access: str, ean: str, controller: str = "jv") -> dict:
    r = requests.post(
        f"{BASE}/api/kaufland_main/",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "controller": controller,
            "mode": "checker",
            "ean": ean,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()  # contains job_id

def product_by_ean(access: str, ean: str, controller: str = "jv") -> dict:
    r = requests.get(
        f"{BASE}/api/products/ean/{ean}/",
        params={"controller": controller},
        headers={"Authorization": f"Bearer {access}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
```

---

## 13) Operational notes

- File formats:
  - CSV/XLSX for `/api/kaufland_main/`
  - JSON for `/api/kaufland_main/upload_json/`
- For multipart requests, do not set manual `Content-Type`; let client library build boundary.
- Treat `job_id` as required business key for async operations.
- Add retry with backoff for transient `5xx`/network failures only.

