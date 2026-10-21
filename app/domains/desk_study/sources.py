# Appels aux sources de l'enquête documentaire : planches (ancien apisolscore et Géorisques),
# interrogées en parallèle, et fiches Infoterre du BRGM, relayées. Repris de
# ConcurrentGeoRiskProvider et HttpExternalContentGateway du back Symfony.

import asyncio
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.core.config import config
from app.core.logger import logger
from app.domains.desk_study import entities
from app.domains.desk_study.entities import PlancheResult, coordinate_text

# Au-delà de 12 s, les planches qui n'ont pas répondu sont abandonnées.
GLOBAL_TIMEOUT_SECONDS = 12.0
INFOTERRE_TIMEOUT_SECONDS = 10.0

# Planche → (source, chemin, délai). {lon}, {lat} et {codeInsee} sont remplacés à l'appel.
CATALOGUE = {
    "catnat": ("apisolscore", "/fr/catnat?lat={lat}&lon={lon}&rayon=1000", 8.0),
    "ppr": ("apisolscore", "/fr/ppr?lat={lat}&lon={lon}", 8.0),
    "geol": ("apisolscore", "/fr/geol?lat={lat}&lon={lon}", 10.0),
    "cavites": ("apisolscore", "/fr/cavites?lat={lat}&lon={lon}", 8.0),
    "pyrotechnique": ("apisolscore", "/fr/risque_pyrotechnique?lat={lat}&lon={lon}", 8.0),
    "ades": ("apisolscore", "/fr/hydrogeology/points_ades?lat={lat}&lon={lon}", 10.0),
    "bss": ("apisolscore", "/fr/hydrogeology/points_bss?lat={lat}&lon={lon}", 10.0),
    "gaspar_risques": ("georisques", "/gaspar/risques?rayon=1000&code_insee={codeInsee}&page=1&page_size=100", 8.0),
    "zonage_sismique": ("georisques", "/zonage_sismique?rayon=1000&code_insee={codeInsee}&page=1&page_size=10", 8.0),
    "radon": ("georisques", "/radon?rayon=1000&code_insee={codeInsee}&page=1&page_size=10", 8.0),
}

# Remplacé par les tests pour simuler les sources (httpx.MockTransport).
transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None


class ExternalContentUnavailable(Exception):
    pass


@dataclass
class ExternalContent:
    status_code: int
    content_type: str
    body: Iterator[bytes]


def _base_uri(source: str) -> str | None:
    return config.georisques_base_uri if source == "georisques" else config.planches_apisolscore_base_uri


# Interroge toutes les planches demandées en même temps ; chacune a son délai, l'ensemble 12 s.
# Une planche inconnue ou sans source configurée est « unavailable » ; une réponse lente, en
# erreur ou illisible est « degraded ».
async def fetch_planches(planches: list[str], longitude: float, latitude: float, insee_code: str | None) -> dict[str, PlancheResult]:
    started = time.perf_counter()
    results: dict[str, PlancheResult] = {}
    tasks: dict[str, asyncio.Task] = {}

    async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
        for planche in planches:
            definition = CATALOGUE.get(planche)

            if definition is None:
                results[planche] = entities.unavailable(planche, "planche inconnue", 0.0)
                continue

            source, path, timeout = definition
            base_uri = _base_uri(source)

            if not base_uri:
                results[planche] = entities.unavailable(planche, "source non configuree", 0.0)
                continue

            url = base_uri.rstrip("/") + path.format(lon=coordinate_text(longitude), lat=coordinate_text(latitude), codeInsee=insee_code or "")
            tasks[planche] = asyncio.create_task(_fetch(client, planche, url, timeout, started))

        if tasks:
            await asyncio.wait(tasks.values(), timeout=GLOBAL_TIMEOUT_SECONDS)

        for planche, task in tasks.items():
            if task.done():
                results[planche] = task.result()
            else:
                task.cancel()
                results[planche] = entities.degraded(planche, "aucune reponse", time.perf_counter() - started)

    return {planche: results[planche] for planche in planches}


async def _fetch(client: httpx.AsyncClient, planche: str, url: str, timeout: float, started: float) -> PlancheResult:
    # wait_for borne la durée totale de l'appel (connexion, attente et transfert compris).
    try:
        response = await asyncio.wait_for(client.get(url, timeout=timeout), timeout)
    except (httpx.TimeoutException, TimeoutError):
        return entities.degraded(planche, "timeout", time.perf_counter() - started)
    except httpx.TransportError as error:
        logger.warning("Planche %s en échec de transport : %s", planche, type(error).__name__)
        return entities.degraded(planche, f"transport: {type(error).__name__}", time.perf_counter() - started)

    elapsed = time.perf_counter() - started

    if response.status_code >= 400:
        return entities.degraded(planche, f"upstream_{response.status_code}", elapsed)

    try:
        return entities.ok(planche, response.json(), elapsed)
    except ValueError as error:
        logger.warning("Planche %s illisible", planche)
        return entities.degraded(planche, str(error), elapsed)


# Relaie une fiche Infoterre : statut et type d'origine, corps en flux.
def fetch_external(url: str) -> ExternalContent:
    client = httpx.Client(timeout=INFOTERRE_TIMEOUT_SECONDS, follow_redirects=False, transport=transport)

    try:
        response = client.send(client.build_request("GET", url, headers={"Accept-Encoding": "identity"}), stream=True)
    except httpx.TransportError as error:
        client.close()
        logger.error("Service documentaire externe injoignable : %s (%s)", url, type(error).__name__)
        raise ExternalContentUnavailable(f"Service externe injoignable : {type(error).__name__}") from error

    return ExternalContent(response.status_code, response.headers.get("content-type", "application/octet-stream"), _stream(response, client))


def _stream(response: httpx.Response, client: httpx.Client) -> Iterator[bytes]:
    try:
        yield from response.iter_bytes()
    finally:
        response.close()
        client.close()
