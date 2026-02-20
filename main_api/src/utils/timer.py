import time
from contextlib import contextmanager
from main_api.src.logger import log


@contextmanager
def log_time(label: str, *, save: bool = False):
    """
    Usage:
        with log_time("process images"):
            await process_pics(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        log(f"TIMING {label} took {duration:.3f}s", save=save)
