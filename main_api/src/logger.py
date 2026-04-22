import logging
import inspect
import contextvars
import os
import re
import io
import csv
import queue
import threading
import atexit
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------- ИНИЦИАЛИЗАЦИЯ ---------------- #

logger = logging.getLogger("log")
logger.setLevel(logging.INFO)


class AlmatyFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        tz = ZoneInfo("Asia/Almaty")
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    def format(self, record):
        # Если есть кастомный caller, подставляем его вместо funcName
        if hasattr(record, "caller"):
            record.funcName = record.caller
        return super().format(record)


# формат с указанием уровня и функции
formatter = AlmatyFormatter("[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
_console_min_level = os.getenv("LOG_CONSOLE_MIN_LEVEL", "warning")
console_handler.setLevel(
    {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(_console_min_level.strip().lower(), logging.WARNING)
)
_global_log_file = os.getenv("LOG_FILE_PATH", "logs.csv")

# чтобы не дублировал
logger.propagate = False
if not logger.handlers:
    logger.addHandler(console_handler)

_task_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "task_context", default=None
)
_task_log_dir = os.getenv("TASK_LOG_DIR", "task_logs")
_log_max_len = int(os.getenv("LOG_MAX_LEN", "1200"))
_log_queue_max = int(os.getenv("LOG_QUEUE_MAX", "10000"))
_write_queue: queue.Queue | None = None
_writer_thread: threading.Thread | None = None


def _writer_loop():
    while True:
        item = _write_queue.get()
        if item is None:
            _write_queue.task_done()
            return
        path, line = item
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        finally:
            _write_queue.task_done()


def _ensure_writer():
    global _write_queue, _writer_thread
    if _write_queue is None:
        _write_queue = queue.Queue(maxsize=max(1, _log_queue_max))
    if _writer_thread is None or not _writer_thread.is_alive():
        _writer_thread = threading.Thread(
            target=_writer_loop,
            name="log-writer",
            daemon=True,
        )
        _writer_thread.start()


def _shutdown_writer():
    global _write_queue
    if _write_queue is None:
        return
    try:
        _write_queue.put_nowait(None)
    except Exception:
        pass


atexit.register(_shutdown_writer)


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned or "unknown"


def set_task_context(job_id: str | None, username: str | None) -> contextvars.Token:
    os.makedirs(_task_log_dir, exist_ok=True)
    tz = ZoneInfo("Asia/Almaty")
    timestamp = datetime.now(tz).strftime("%Y%m%d_%H%M%S_%f")
    safe_user = _sanitize_name(username or "anonymous")
    filename = f"task_{timestamp}_{safe_user}.log"
    path = os.path.join(_task_log_dir, filename)
    token = _task_context.set(
        {
            "path": path,
            "job_id": job_id or "none",
            "user": username or "anonymous",
        }
    )
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(
                f"[{datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}] "
                f"[task] job_id={job_id or 'none'} user={username or 'anonymous'}\n"
            )
    except Exception:
        pass
    return token


def update_task_context(job_id: str | None = None, username: str | None = None) -> None:
    context = _task_context.get()
    if not context:
        return
    if job_id is not None:
        context["job_id"] = str(job_id).strip() or "none"
    if username is not None:
        context["user"] = username or "anonymous"
    _task_context.set(context)


def clear_task_context(token: contextvars.Token | None = None) -> None:
    if token is not None:
        _task_context.reset(token)
        return
    _task_context.set(None)


# ---------------- УДОБНАЯ ФУНКЦИЯ ---------------- #


def _coerce_level(level) -> int:
    if isinstance(level, int):
        return level
    name = str(level or "info").strip().lower()
    return {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(name, logging.INFO)


def _truncate(message: str) -> str:
    if _log_max_len <= 0:
        return message
    if len(message) > _log_max_len:
        return message[:_log_max_len] + " ...[truncated]"
    return message


def _format_record(level_num: int, message: str, extra: dict) -> str:
    record = logger.makeRecord(
        logger.name, level_num, "", 0, message, (), None, extra=extra
    )
    return formatter.format(record)


def _format_record_csv(level_num: int, message: str, extra: dict) -> str:
    record = logger.makeRecord(
        logger.name, level_num, "", 0, message, (), None, extra=extra
    )
    tz = ZoneInfo("Asia/Almaty")
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    func_name = getattr(record, "caller", record.funcName)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([timestamp, record.levelname, func_name, message])
    return buf.getvalue().rstrip("\r\n")


def _append_line(path: str, line: str) -> None:
    _ensure_writer()
    try:
        _write_queue.put_nowait((path, line))
    except Exception:
        # Fallback: if queue is full/unavailable, write directly.
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def log(
    *args, print: bool = True, save: bool = False, level: str | int = "info"
) -> None:
    """
    Логирует сообщение с указанием функции, из которой был вызов.
    По умолчанию логирует в консоль. Если нужно логировать в файл,
    укажите save=True.

    :param args: Аргументы для логирования.
    :param print: Логировать в консоль.
    :param save: Логировать в файл.
    """

    # Формируем сообщение
    message = " ".join(str(a) for a in args)

    # Faster than inspect.stack() for high-frequency logging paths.
    frame = inspect.currentframe()
    caller_frame = frame.f_back if frame else None
    func_name = caller_frame.f_code.co_name if caller_frame else "<unknown>"
    del frame

    # Доп. информация
    extra = {"caller": func_name}

    context = _task_context.get()
    if context:
        message = (
            f"[job_id={context.get('job_id')} user={context.get('user')}] {message}"
        )
    message = _truncate(message)

    level_num = _coerce_level(level)
    if print and level_num >= console_handler.level:
        logger.log(level_num, message, extra=extra)

    formatted = _format_record(level_num, message, extra)
    formatted_csv = _format_record_csv(level_num, message, extra)
    if save:
        _append_line(_global_log_file, formatted_csv)
    if context and context.get("path"):
        _append_line(context["path"], formatted)
