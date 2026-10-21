# Appels à la GED (serveur Talend) : fiche d'une affaire et téléchargement de ses fichiers.
# Repris de HttpGedGateway du back Symfony : la réponse de la GED est relayée en flux, avec son
# statut et trois en-têtes (type, nom du fichier, taille), sans jamais exposer l'adresse interne.
#
# Vérification TLS désactivée (verify=False) : dette héritée du back Go puis Symfony, le
# certificat de la GED n'est pas signé par une autorité connue du conteneur. Voir
# docs/architecture.md, « Limites connues ».

import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

import httpx

from app.core.config import config
from app.core.logger import logger

# Au-delà de 2 s, l'appel est journalisé comme lent.
SLOW_CALL_SECONDS = 2.0
# Fiche : la GED répond vite ou pas du tout. Après 3 s de silence, on réessaie une fois.
DETAIL_SILENCE_SECONDS = 3.0
# Fichier : un gros PDF peut mettre longtemps à arriver.
FILE_SILENCE_SECONDS = 60.0
PASSED_HEADERS = ("content-type", "content-disposition", "content-length")
# Un nom introuvable dans le DNS ne se corrige pas en réessayant.
DNS_FAILURES = ("could not resolve host", "name or service not known", "getaddrinfo", "nodename nor servname", "temporary failure in name resolution")

# Remplacé par les tests pour simuler la GED (httpx.MockTransport).
transport: httpx.BaseTransport | None = None


class GedUnavailable(Exception):
    pass


@dataclass
class GedResponse:
    status_code: int
    headers: dict[str, str]
    body: Iterator[bytes]
    retried: bool = False
    elapsed_seconds: float = 0.0


def case_detail(project_id: str) -> GedResponse:
    if not config.ged_base_uri:
        raise GedUnavailable("GED_BASE_URI absent de la configuration")

    url = f"{config.ged_base_uri.rstrip('/')}/affaires/{quote(project_id, safe='')}"
    return _call(url, project_id, DETAIL_SILENCE_SECONDS)


def case_file(project_number: str, file_name: str) -> GedResponse:
    if not config.ged_files_base_uri:
        raise GedUnavailable("GED_FILES_BASE_URI absent de la configuration")

    url = f"{config.ged_files_base_uri.rstrip('/')}/download/{quote(project_number, safe='')}?file={quote_plus(file_name)}"
    return _call(url, project_number, FILE_SILENCE_SECONDS)


# Deux tentatives au plus : une seconde seulement après une erreur réseau qui n'est pas un échec
# de résolution du nom. Une réponse d'erreur de la GED (404, 500…) est relayée telle quelle.
def _call(url: str, project_id: str, silence_seconds: float) -> GedResponse:
    started = time.perf_counter()
    retried = False
    client = httpx.Client(
        auth=_auth(),
        timeout=silence_seconds,
        verify=False,
        follow_redirects=False,
        transport=transport,
    )

    for attempt in range(2):
        try:
            # identity : le corps arrive tel quel, et sa taille (content-length) reste juste une fois relayé.
            response = client.send(client.build_request("GET", url, headers={"Accept-Encoding": "identity"}), stream=True)
        except httpx.TransportError as error:
            if attempt == 0 and _worth_retrying(error):
                retried = True
                logger.warning("GED muette pour l'affaire %s, seconde tentative (%s)", project_id, type(error).__name__)
                continue

            client.close()
            logger.error("GED injoignable pour l'affaire %s : %s", project_id, type(error).__name__)
            raise GedUnavailable(f"GED injoignable pour l'affaire {project_id}") from error

        elapsed = time.perf_counter() - started

        if retried or elapsed >= SLOW_CALL_SECONDS:
            logger.info("GED lente ou réessayée pour l'affaire %s : statut %s en %.3f s", project_id, response.status_code, elapsed)

        return GedResponse(
            status_code=response.status_code,
            headers={name: response.headers[name] for name in PASSED_HEADERS if name in response.headers},
            body=_stream(response, client),
            retried=retried,
            elapsed_seconds=elapsed,
        )

    raise GedUnavailable(f"GED injoignable pour l'affaire {project_id}")


# Relaie le corps morceau par morceau, puis libère la connexion, même si le client abandonne.
def _stream(response: httpx.Response, client: httpx.Client) -> Iterator[bytes]:
    try:
        yield from response.iter_bytes()
    finally:
        response.close()
        client.close()


def _auth() -> httpx.BasicAuth | None:
    if not config.ged_username:
        return None

    password = config.ged_password.get_secret_value() if config.ged_password else ""
    return httpx.BasicAuth(config.ged_username, password)


def _worth_retrying(error: httpx.TransportError) -> bool:
    message = str(error).lower()
    return not any(signature in message for signature in DNS_FAILURES)
