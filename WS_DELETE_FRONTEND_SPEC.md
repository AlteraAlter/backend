# Delete API + WebSocket Spec

## 1) HTTP Start Endpoint

Start delete job:

- Method: `POST`
- URL: `/kaufland_main/`
- Auth: required (`IsAuthenticated`)
- Content-Type: `multipart/form-data`

Required fields:

- `controller`: `jv` or `xl`
- `mode`: `delete`
- `file`: `.csv` or `.xlsx`

Optional fields:

- `job_id`: custom job id; if omitted, backend generates one

Input file rules:

- file must contain column `ean`
- if `price` is present, it is ignored for delete

Success start response:

- HTTP: `202 Accepted`

```json
{
  "message": "delete job started",
  "job_id": "del123"
}
```

---

## 2) Delete WebSocket Endpoint

Connect by path param (preferred):

`ws://<HOST>/ws/delete-progress/<job_id>/`

Or by query param:

`ws://<HOST>/ws/delete-progress/?job_id=<job_id>`

---

## 3) WS Message Envelope

All delete WS messages use this format:

```json
{
  "job_id": "string",
  "event": "string",
  "payload": {},
  "info": "string|null",
  "timestamp": "ISO datetime"
}
```

---

## 4) Delete WS Events

### `job_started`

```json
{
  "job_id": "del123",
  "event": "job_started",
  "payload": {
    "total": 80,
    "controller": "xl"
  },
  "info": null,
  "timestamp": "2026-02-11T10:10:00"
}
```

Use for initializing progress UI.

### `storefront_result`

```json
{
  "job_id": "del123",
  "event": "storefront_result",
  "payload": {
    "controller": "xl",
    "ean": "4067282748224",
    "storefront": "de",
    "result": "success"
  },
  "info": null,
  "timestamp": "2026-02-11T10:10:02"
}
```

`result` values:

- `success`
- `fail`
- `no_unit_ids`

Use for detailed rows/log table per storefront.

### `job_progress`

```json
{
  "job_id": "del123",
  "event": "job_progress",
  "payload": {
    "total": 80,
    "processed": 22,
    "ean": "4067282748224",
    "status": "success"
  },
  "info": null,
  "timestamp": "2026-02-11T10:10:03"
}
```

`status` values:

- `success`
- `failed`

Use for progress bar and processed counter.

### `job_completed`

```json
{
  "job_id": "del123",
  "event": "job_completed",
  "payload": {
    "total": 80,
    "processed": 80,
    "success": 77,
    "failed": 3
  },
  "info": "success",
  "timestamp": "2026-02-11T10:12:10"
}
```

`info` values:

- `success`
- `partial_or_failed`

Use for final status screen and stopping socket updates.

---

## 5) Frontend Integration Flow

1. Upload delete request to `POST /kaufland_main/`.
2. Read `job_id` from `202 Accepted` response.
3. Open WS: `/ws/delete-progress/<job_id>/`.
4. Handle events:
   - `job_started`: set `total`
   - `storefront_result`: append/update detailed status rows
   - `job_progress`: update progress bar (`processed / total`)
   - `job_completed`: show final summary and close WS
5. If WS closes unexpectedly, reconnect to same `job_id`.

