# Archive ZIP des rapports de plusieurs affaires, lus sur le dépôt FTP. Repris de
# ReportArchiveController du back Symfony : chaque fichier est rangé sous le chemin de son affaire.

import zipfile
from io import BytesIO

from app.domains.reports import sources
from app.domains.reports.entities import ProjectArchivePath


def archive(projects: list[ProjectArchivePath]) -> bytes:
    content = BytesIO()

    with sources.ReportArchive() as reports, zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for project in projects:
            for file_name in reports.files(project):
                data = reports.read(project, file_name)

                if data is not None:
                    zip_file.writestr(f"{project.path}/{file_name}", data)

    return content.getvalue()
