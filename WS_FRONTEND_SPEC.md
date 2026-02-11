# WebSocket API Spec (`checker` / `delete`)

## 1) Base WS Message Envelope

All websocket messages use one envelope:

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

## 2) Checker Progress WebSocket

Connect URL (preferred):

`ws://<HOST>/ws/checker-progress/<job_id>/`

Alternative URL:

`ws://<HOST>/ws/checker-progress/?job_id=<job_id>`

### Events

`job_started`

```json
{
  "job_id": "abc123",
  "event": "job_started",
  "payload": {
    "total": 120,
    "controller": "jv"
  },
  "info": null,
  "timestamp": "2026-02-11T10:00:00"
}
```

`item` (one per EAN, found case)

```json
{
  "job_id": "abc123",
  "event": "item",
  "payload": {
    "controller": "jv",
    "ean": "4067282748224",
    "items": [
      {
        "ean": "4067282748224",
        "title": "Product title",
        "price": 49.99,
        "storefront": "de"
      }
    ]
  },
  "info": null,
  "timestamp": "2026-02-11T10:00:02"
}
```

`item` (not found case)

```json
{
  "job_id": "abc123",
  "event": "item",
  "payload": {
    "controller": "jv",
    "ean": "4067282748224",
    "items": []
  },
  "info": "not found",
  "timestamp": "2026-02-11T10:00:02"
}
```

`job_progress`

```json
{
  "job_id": "abc123",
  "event": "job_progress",
  "payload": {
    "total": 120,
    "processed": 35,
    "ean": "4067282748224"
  },
  "info": null,
  "timestamp": "2026-02-11T10:00:03"
}
```

`job_completed`

```json
{
  "job_id": "abc123",
  "event": "job_completed",
  "payload": {
    "total": 120,
    "processed": 120,
    "result_count": 97,
    "result": [
      {
        "ean": "4067282748224",
        "title": "Product title",
        "price": 49.99,
        "storefront": "de"
      }
    ]
  },
  "info": null,
  "timestamp": "2026-02-11T10:01:10"
}
```

---

## 3) Delete Progress WebSocket

Connect URL (preferred):

`ws://<HOST>/ws/delete-progress/<job_id>/`

Alternative URL:

`ws://<HOST>/ws/delete-progress/?job_id=<job_id>`

### Events

`job_started`

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

`storefront_result`

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

`job_progress`

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

`job_completed`

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

`info` values on completion:

- `success`
- `partial_or_failed`

---

## 4) How Front Gets `job_id` (HTTP)

Endpoint:

`POST /kaufland_main/`

Modes relevant here:

- `checker`
- `delete`

Now `checker` and `delete` start in background and return immediately.

Checker start response:

```json
{
  "message": "checker job started",
  "job_id": "abc123",
  "eans": ["4067282748224"]
}
```

Delete start response:

```json
{
  "message": "delete job started",
  "job_id": "del123"
}
```

HTTP status for started jobs: `202 Accepted`

---

## 5) Recommended Front Flow

1. Send `POST /kaufland_main/` with `mode=checker` or `mode=delete`.
2. Read `job_id` from HTTP response (`202 Accepted`).
3. Open WS with this `job_id` immediately:
   - checker: `/ws/checker-progress/<job_id>/`
   - delete: `/ws/delete-progress/<job_id>/`
4. Update UI from WS events.
5. Close socket on `job_completed`.
