import logging
import time
import uuid
from datetime import datetime
from typing import Any

import orjson
from fastapi import Request, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.core.logger import logger, request_id
from app.core.timing import timings
from app.database.connection import execute_audit

IGNORED_PATHS = {"/", "/api/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/favicon.ico"}
MAX_BODY_SIZE = 10_000

INSERT = """
    INSERT INTO audit_log
        (created_at, request_id, username, action, method, path, status_code, duration_ms,
         ip_address, user_agent, details)
    VALUES
        (:created_at, :request_id, :username, :action, :method, :path, :status_code, :duration_ms,
         :ip_address, :user_agent, :details)
"""


async def audit(request: Request, call_next) -> Response:
    if request.method == "OPTIONS" or request.url.path in IGNORED_PATHS:
        return await call_next(request)

    identifier = str(uuid.uuid4())
    request_id.set(identifier)
    steps: dict[str, float] = {}
    timings.set(steps)
    created_at = datetime.now()
    started = time.perf_counter()
    details = await _request_details(request)

    try:
        response = await call_next(request)
    except Exception as error:
        details["error"] = repr(error)
        _add_timings(details, steps)
        entry = _entry(request, identifier, created_at, started, 500, details)
        logger.exception(_line(entry))
        await run_in_threadpool(save, entry)
        raise

    _add_timings(details, steps)
    entry = _entry(request, identifier, created_at, started, response.status_code, details)
    logger.log(_level(response.status_code), _line(entry))

    response.headers["X-Request-ID"] = identifier
    response.background = BackgroundTask(save, entry)

    return response


def save(entry: dict[str, Any]) -> None:
    try:
        execute_audit(INSERT, **entry)
    except Exception:
        logger.exception("audit_log: could not save the entry")


async def _request_details(request: Request) -> dict[str, Any]:
    details: dict[str, Any] = {}

    if request.query_params:
        details["query"] = dict(request.query_params)

    if "application/json" in request.headers.get("content-type", ""):
        body = await request.body()

        if body and len(body) <= MAX_BODY_SIZE:
            try:
                details["body"] = orjson.loads(body)
            except orjson.JSONDecodeError:
                pass

    return details


def _add_timings(details: dict[str, Any], steps: dict[str, float]) -> None:
    if steps:
        details["timings_ms"] = {step: round(duration) for step, duration in steps.items()}


def _entry(
    request: Request, identifier: str, created_at: datetime, started: float, status_code: int, details: dict[str, Any]
) -> dict[str, Any]:
    route = request.scope.get("route")
    user_agent = request.headers.get("user-agent")

    return {
        "created_at": created_at,
        "request_id": identifier,
        "username": getattr(request.state, "username", None),
        "action": getattr(route, "name", None),
        "method": request.method,
        "path": request.url.path[:255],
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "ip_address": request.client.host if request.client else None,
        "user_agent": user_agent[:255] if user_agent else None,
        "details": orjson.dumps(details).decode() if details else None,
    }


def _line(entry: dict[str, Any]) -> str:
    return (
        f"{entry['username'] or 'anonymous'} {entry['method']} {entry['path']} "
        f"-> {entry['status_code']} in {entry['duration_ms']} ms "
        f"action={entry['action'] or '-'} ip={entry['ip_address'] or '-'} details={entry['details'] or '-'}"
    )


def _level(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR

    if status_code >= 400:
        return logging.WARNING

    return logging.INFO
