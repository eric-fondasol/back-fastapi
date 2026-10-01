import logging
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from app.core.config import config

request_id: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger("solscore")


class DailyFileHandler(logging.Handler):
    """Writes to <directory>/YYYY-MM-DD.txt and switches file when the day changes."""

    def __init__(self, directory: str):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.day: str | None = None
        self.stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d")

            if day != self.day:
                self._close_stream()
                self.stream = open(self.directory / f"{day}.txt", "a", encoding="utf-8")
                self.day = day

            self.stream.write(self.format(record) + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._close_stream()
        super().close()

    def _close_stream(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
            self.day = None


def _with_request_id(record: logging.LogRecord) -> bool:
    record.request_id = request_id.get()
    return True


def setup_logging() -> None:
    if logger.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-7s [%(request_id)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    for handler in (DailyFileHandler(config.log_dir), logging.StreamHandler()):
        handler.setFormatter(formatter)
        handler.addFilter(_with_request_id)
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False


setup_logging()
