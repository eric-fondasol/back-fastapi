# Audit : trace chaque requête métier (qui, quoi, comment, quand) dans le journal du jour et
# dans la table audit_log de la base MySQL. Branché comme middleware dans main.py.

import logging
import re
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

# Chemins non tracés : sonde, documentation et fichiers techniques du navigateur.
IGNORED_PATHS = {"/", "/api/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/favicon.ico"}
# Tuiles de carte relayées : des dizaines à chaque déplacement de la carte, sans intérêt une à une.
IGNORED_PATH_PATTERN = re.compile(r"^/layer-catalog/[^/]+/tiles/")
# Au-delà de 10 Ko, le corps de la requête n'est pas recopié dans l'audit.
MAX_BODY_SIZE = 10_000

# Requête paramétrée (:nom) : les valeurs ne sont jamais concaténées dans le SQL.
INSERT = """
    INSERT INTO audit_log
        (created_at, request_id, username, action, method, path, status_code, duration_ms,
         ip_address, user_agent, details)
    VALUES
        (:created_at, :request_id, :username, :action, :method, :path, :status_code, :duration_ms,
         :ip_address, :user_agent, :details)
"""


# Middleware : enveloppe chaque requête. call_next exécute la suite (authentification, route).
async def audit(request: Request, call_next) -> Response:
    # Pré-requêtes CORS du navigateur (OPTIONS) et chemins ignorés : on laisse passer sans tracer.
    path = request.url.path
    if request.method == "OPTIONS" or path in IGNORED_PATHS or IGNORED_PATH_PATTERN.match(path):
        return await call_next(request)

    # Identifiant unique de la requête : préfixe des lignes du journal et colonne request_id.
    identifier = str(uuid.uuid4())
    request_id.set(identifier)
    # Dictionnaire que timed() remplira pendant la requête (auth, db, geojson…).
    steps: dict[str, float] = {}
    timings.set(steps)
    created_at = datetime.now()
    started = time.perf_counter()
    # Lu avant l'exécution de la route : paramètres d'URL et corps JSON.
    details = await _request_details(request)

    try:
        response = await call_next(request)
    except Exception as error:
        # Erreur non gérée dans la route : tracée en 500 avec l'erreur, puis relancée pour que
        # FastAPI renvoie sa réponse d'erreur.
        details["error"] = repr(error)
        _add_timings(details, steps)
        entry = _entry(request, identifier, created_at, started, 500, details)
        logger.exception(_line(entry))
        # Écriture en base dans un thread, pour ne pas bloquer la boucle asynchrone.
        await run_in_threadpool(save, entry)
        raise

    _add_timings(details, steps)
    entry = _entry(request, identifier, created_at, started, response.status_code, details)
    logger.log(_level(response.status_code), _line(entry))

    # Renvoie l'identifiant au client : utile pour retrouver une requête signalée par un utilisateur.
    response.headers["X-Request-ID"] = identifier
    # L'écriture en base se fait après l'envoi de la réponse : elle n'ajoute rien au temps de réponse.
    response.background = BackgroundTask(save, entry)

    return response


# Écrit la ligne dans audit_log. Si la base d'audit est injoignable, l'erreur est seulement
# journalisée : la requête de l'utilisateur a déjà abouti.
def save(entry: dict[str, Any]) -> None:
    try:
        execute_audit(INSERT, **entry)
    except Exception:
        logger.exception("audit_log: could not save the entry")


# Rassemble le « comment » de la requête : paramètres d'URL et corps JSON.
async def _request_details(request: Request) -> dict[str, Any]:
    details: dict[str, Any] = {}

    if request.query_params:
        details["query"] = dict(request.query_params)

    if "application/json" in request.headers.get("content-type", ""):
        # Le corps est mis en cache par Starlette : la route pourra encore le lire ensuite.
        body = await request.body()

        if body and len(body) <= MAX_BODY_SIZE:
            try:
                details["body"] = orjson.loads(body)
            except orjson.JSONDecodeError:
                # JSON invalide : la route renverra un 422 ; on n'enregistre pas le corps.
                pass

    return details


# Ajoute les durées par étape, arrondies à la milliseconde, s'il y en a.
def _add_timings(details: dict[str, Any], steps: dict[str, float]) -> None:
    if steps:
        details["timings_ms"] = {step: round(duration) for step, duration in steps.items()}


# Construit la ligne d'audit ; les clés correspondent aux paramètres :nom de INSERT.
def _entry(
    request: Request, identifier: str, created_at: datetime, started: float, status_code: int, details: dict[str, Any]
) -> dict[str, Any]:
    # Route reconnue par FastAPI ; absente si l'URL n'existe pas (404).
    route = request.scope.get("route")
    user_agent = request.headers.get("user-agent")

    return {
        "created_at": created_at,
        "request_id": identifier,
        # Posé par core/auth.py ; None si la requête a été refusée avant (jeton absent ou invalide).
        "username": getattr(request.state, "username", None),
        # Nom de la fonction de route, par exemple « search_sites_by_area ».
        "action": getattr(route, "name", None),
        "method": request.method,
        # Tronqué à 255 caractères, la taille de la colonne.
        "path": request.url.path[:255],
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "ip_address": request.client.host if request.client else None,
        "user_agent": user_agent[:255] if user_agent else None,
        # Stocké en texte JSON dans la colonne details.
        "details": orjson.dumps(details).decode() if details else None,
    }


# Ligne lisible pour le journal texte, par exemple :
# « dev@fondasol.fr POST /searchSitesByArea -> 200 in 312 ms action=search_sites_by_area ip=… details=… »
def _line(entry: dict[str, Any]) -> str:
    return (
        f"{entry['username'] or 'anonymous'} {entry['method']} {entry['path']} "
        f"-> {entry['status_code']} in {entry['duration_ms']} ms "
        f"action={entry['action'] or '-'} ip={entry['ip_address'] or '-'} details={entry['details'] or '-'}"
    )


# Niveau de la ligne selon le statut : ERROR pour 5xx, WARNING pour 4xx (refus, requête invalide), INFO sinon.
def _level(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR

    if status_code >= 400:
        return logging.WARNING

    return logging.INFO
