# Donne le rôle admin à un agent déjà connecté une fois (premiers administrateurs, ADR-0060 du front).
# Usage : docker exec solscore_fastapi python -m app.domains.admin.grant_admin prenom.nom@fondasol.fr

import sys

from app.core.errors import NotFound
from app.domains.admin.services import grant_admin_by_email


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("Usage : python -m app.domains.admin.grant_admin <adresse>", file=sys.stderr)
        return 2
    try:
        user = grant_admin_by_email(arguments[0])
    except NotFound as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{user['email']} : {', '.join(user['roles'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
