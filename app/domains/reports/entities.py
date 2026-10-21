# Chemin d'une affaire sur le dépôt FTP des rapports : « agence/année/numéro », en minuscules
# sauf l'année (« 69GT.21.0142 » → « 69gt/21/69gt.21.0142 »). Repris de ProjectArchivePath du
# back Symfony ; un numéro qui permettrait de sortir du dépôt est refusé.

from dataclasses import dataclass

from app.core.errors import InvalidRequest


@dataclass(frozen=True)
class ProjectArchivePath:
    project_number: str
    path: str


def archive_path(project_number: str) -> ProjectArchivePath:
    project_number = project_number.strip()
    parts = project_number.split(".")

    if len(parts) < 3 or not parts[0] or not parts[1]:
        raise InvalidRequest(f"Numero d affaire attendu sous la forme AGENCE.ANNEE.NUMERO, recu : {project_number}")

    if any("/" in part or part == ".." for part in parts):
        raise InvalidRequest("Numero d affaire invalide.")

    return ProjectArchivePath(project_number, f"{parts[0].lower()}/{parts[1]}/{project_number.lower()}")
