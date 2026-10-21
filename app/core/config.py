# Configuration de l'API, lue dans les variables d'environnement et le fichier .env.
# Pydantic vérifie les types au démarrage : une valeur obligatoire manquante empêche l'API de démarrer.

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    # Lit le .env à la racine ; les variables inconnues sont ignorées au lieu de lever une erreur.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # « dev » sur un poste de développement ; seul cet environnement accepte AUTH_DEV_TOKEN.
    app_env: str = "prod"

    # Base PostgreSQL d'apisolscore (sites, sondages), lue en lecture seule.
    db_solscore_host: str
    db_solscore_port: int = 5432
    db_solscore_name: str
    db_solscore_user: str
    # SecretStr : la valeur n'apparaît pas si la configuration est affichée ou journalisée.
    db_solscore_password: SecretStr

    # Base métier de la refonte (affaires, profils, enquêtes), en lecture et écriture.
    # Son schéma est tenu par les migrations Alembic (dossier migrations/).
    db_refonte_host: str
    db_refonte_port: int = 5432
    db_refonte_name: str
    db_refonte_user: str
    db_refonte_password: SecretStr
    # Base utilisée par les tests à la place de db_refonte_name : vidée à chaque test qui écrit.
    db_refonte_test_name: str = "fondasol_fastapi_test"

    # GED (serveur Talend) : fiche d'une affaire et téléchargement de ses fichiers, en Basic Auth.
    # Facultative : sans elle, l'API démarre et les routes de la GED répondent 502.
    ged_base_uri: str | None = None
    ged_files_base_uri: str | None = None
    ged_username: str | None = None
    ged_password: SecretStr | None = None

    # Images d'attente téléversées depuis l'écran Paramètres (dossier monté dans le conteneur).
    waiting_images_dir: str = "uploads/waitingImages"

    # Dépôt FTP des rapports archivés (GET /reports). Facultatif : sans hôte, la route répond 502.
    ftp_host: str | None = None
    ftp_port: int = 21
    ftp_username: str | None = None
    ftp_password: SecretStr | None = None
    ftp_base_path: str = ""

    # Sources des planches de l'enquête documentaire (POST /api/enquetes/planches) : l'API publique
    # Géorisques, et l'ancien apisolscore (catnat, ppr, geol…). Sans adresse, ses planches sont
    # « unavailable ».
    georisques_base_uri: str = "https://www.georisques.gouv.fr/api/v1"
    planches_apisolscore_base_uri: str | None = None

    # Base MySQL d'audit (table audit_log).
    db_audit_host: str
    db_audit_port: int = 3306
    db_audit_name: str
    db_audit_user: str
    db_audit_password: SecretStr

    # Dossier des journaux texte (un fichier par jour).
    log_dir: str = "logs"

    # Tenant Azure AD qui émet les jetons, et identifiant de notre application (audience attendue).
    oidc_issuer: str
    oidc_audience: str

    # Jeton fixe pour appeler l'API en local sans Azure, et l'utilisateur qu'il représente.
    auth_dev_token: SecretStr | None = None
    auth_dev_user: str = "dev@fondasol.fr"

    # Origines autorisées à appeler l'API depuis un navigateur, séparées par des virgules.
    cors_origins: str = ""

    # Transforme « https://a, https://b » en ["https://a", "https://b"], en ignorant les entrées vides.
    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


# Instance unique, importée partout sous le nom « config ».
config = Config()
