# Erreurs métier : un service lève l'une de ces erreurs, l'API répond le code HTTP correspondant
# avec { "errors": "<message>" }, le même format que l'ancien back Symfony.
# Branché dans main.py (app.add_exception_handler).

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400


# Donnée reçue refusée par une règle métier (coordonnées hors bornes, numéro mal formé…).
class InvalidRequest(DomainError):
    status_code = 400


# Le jeton est valide, mais ne permet pas l'action (identifiant Azure absent…).
class Forbidden(DomainError):
    status_code = 403


# La ressource demandée n'existe pas (affaire, enquête, version…).
class NotFound(DomainError):
    status_code = 404


# L'action entre en conflit avec l'état actuel (version qui n'est plus la dernière, doublon…).
class Conflict(DomainError):
    status_code = 409


# La requête est bien formée mais ne peut pas être traitée (limite de favoris atteinte…).
class Unprocessable(DomainError):
    status_code = 422


def domain_error_response(_: Request, error: Exception) -> JSONResponse:
    status_code = error.status_code if isinstance(error, DomainError) else 500
    return JSONResponse({"errors": str(error)}, status_code=status_code)
