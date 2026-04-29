import logging
import inspect
import os
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
_global_log_file = os.getenv("LOG_FILE_PATH", "universal.log")
_default_fallback_log_file = os.path.join("logs", "universal.log")


def _select_log_file(path: str) -> str:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except Exception:
        directory = os.path.dirname(_default_fallback_log_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        return _default_fallback_log_file


_global_log_file = _select_log_file(_global_log_file)

# чтобы не дублировал
logger.propagate = False
if not logger.handlers:
    logger.addHandler(console_handler)

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
    *args, print: bool = True, save: bool | None = None, level: str | int = "info"
) -> None:
    """
    Логирует сообщение с указанием функции, из которой был вызов.
    Пишет в консоль (по уровню) и всегда в универсальный лог-файл.

    :param args: Аргументы для логирования.
    :param print: Логировать в консоль.
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

    message = _truncate(message)

    level_num = _coerce_level(level)
    if print and level_num >= console_handler.level:
        logger.log(level_num, message, extra=extra)

    formatted = _format_record(level_num, message, extra)
    _append_line(_global_log_file, formatted)
