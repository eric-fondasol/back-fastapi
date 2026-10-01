import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

timings: ContextVar[dict[str, float] | None] = ContextVar("timings", default=None)


@contextmanager
def timed(step: str) -> Iterator[None]:
    started = time.perf_counter()

    try:
        yield
    finally:
        current = timings.get()

        if current is not None:
            current[step] = current.get(step, 0) + (time.perf_counter() - started) * 1000
