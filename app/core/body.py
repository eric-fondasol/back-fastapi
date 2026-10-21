# Lecture du corps JSON d'une requête, pour les routes qui contrôlent elles-mêmes leurs données
# (règles métier reprises du back Symfony, refus en 400 avec { "errors": … } au lieu du 422 de FastAPI).
# Usage : « payload: dict = Depends(json_object) ».

import json
from typing import Any

from fastapi import Request

from app.core.errors import InvalidRequest


async def json_object(request: Request) -> dict[str, Any]:
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise InvalidRequest("Corps JSON invalide.") from None

    # Une liste vide est acceptée comme un objet vide, comme le faisait PHP (« [] » et « {} » s'y confondent).
    if payload == []:
        return {}

    if not isinstance(payload, dict):
        raise InvalidRequest("Le corps doit etre un objet JSON.")

    return payload
