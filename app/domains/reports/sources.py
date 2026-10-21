# Le dépôt FTP des rapports archivés (FTP_HOST…). Repris de FtpReportArchiveGateway du back
# Symfony : une connexion par archive, mode passif, fichiers lus en binaire.

import ftplib
from io import BytesIO
from pathlib import PurePosixPath

from app.core.config import config
from app.core.logger import logger
from app.domains.reports.entities import ProjectArchivePath

TIMEOUT_SECONDS = 20


class ReportArchiveUnavailable(Exception):
    pass


class ReportArchive:
    def __enter__(self) -> "ReportArchive":
        if not config.ftp_host:
            raise ReportArchiveUnavailable("FTP_HOST absent de la configuration")

        try:
            self.ftp = ftplib.FTP(timeout=TIMEOUT_SECONDS)
            self.ftp.connect(config.ftp_host, config.ftp_port)
            self.ftp.login(config.ftp_username or "", config.ftp_password.get_secret_value() if config.ftp_password else "")
            self.ftp.set_pasv(True)
        except (OSError, ftplib.Error) as error:
            raise ReportArchiveUnavailable(f"Depot de rapports injoignable : {type(error).__name__}") from error

        return self

    def __exit__(self, *_) -> None:
        try:
            self.ftp.quit()
        except (OSError, ftplib.Error):
            self.ftp.close()

    # Fichiers du dossier de l'affaire, triés ; un dossier absent donne une liste vide.
    def files(self, project: ProjectArchivePath) -> list[str]:
        try:
            entries = self.ftp.nlst(self._remote(project))
        except ftplib.error_perm:
            logger.info("Aucun dossier de rapports pour l'affaire %s", project.project_number)
            return []

        # Dernier segment, comme basename : « …/dossier/. » donne « . » (PurePosixPath donnerait « dossier »).
        return sorted(name for name in (entry.rstrip("/").rsplit("/", 1)[-1] for entry in entries) if name not in ("", ".", ".."))

    # Contenu d'un fichier, ou None s'il est illisible (il est alors simplement omis de l'archive).
    def read(self, project: ProjectArchivePath, file_name: str) -> bytes | None:
        content = BytesIO()

        try:
            self.ftp.retrbinary(f"RETR {self._remote(project)}/{PurePosixPath(file_name).name}", content.write)
        except ftplib.Error:
            logger.warning("Rapport illisible sur le dépôt : %s, %s", project.project_number, file_name)
            return None

        return content.getvalue()

    def _remote(self, project: ProjectArchivePath) -> str:
        return f"{config.ftp_base_path.rstrip('/')}/{project.path}"
