# Solscore — API FastAPI

Modèle d'API pour structurer apisolscore. Elle fournit au front Solscore :

- les **sites** et les **sondages** à afficher sur la carte (`app/domains/map/`), lus
  directement dans la base PostgreSQL d'apisolscore ;
- les **données métier de la refonte** (profils, affaires, enquêtes), lues et écrites dans la
  base métier (`refonte_postgis` en local) : back-fastapi remplace le back Symfony, lot par
  lot (ADR-0034 du front). Faits : le socle (connexion, migrations Alembic, profil de
  l'agent connecté, erreurs métier) ; le profil, avec ses préférences et ses favoris
  (`app/domains/profile/`, routes `/me/…`) ; les affaires, sondages et référentiels
  (`app/domains/projects/`, routes `/projects/…`, `/surveys/…`), et la GED (`/case-detail`,
  `/case-file`) ; les enquêtes enregistrées
  et leurs versions (`app/domains/investigations/`, routes `/investigations/…`) ; le socle
  (paramétrage, statistiques, zones restreintes, images d'attente), les rapports FTP et
  l'enquête documentaire (planches, Infoterre) : `socle/`, `reports/`, `desk_study/` ;
- les **données d'enquête par pays** (`app/domains/france/`, `app/domains/canada/`, `app/domains/luxembourg/`),
  découpées par thème métier. La structure est prête : chaque thème a son routeur
  déjà branché, les routes restent à y ajouter.

Toutes les routes métier exigent le jeton SSO (Azure AD) de l'utilisateur connecté.
Chaque requête est tracée (qui, quoi, comment, quand) dans un fichier texte par jour
(`logs/AAAA-MM-JJ.txt`) et dans la table `audit_log` d'une base MySQL.

L'architecture, le parcours d'une requête et la façon d'ajouter une route, un thème ou
un pays sont détaillés dans [docs/architecture.md](docs/architecture.md).

---

## Démarrer

Prérequis : Docker.

```bash
cp .env.example .env              # puis renseigner les valeurs (voir docs/architecture.md, section 8)
docker compose up -d --build
docker compose exec api alembic stamp 0001   # une seule fois, sur une base métier déjà créée par Symfony
# GED : reporter GED_* du back Symfony dans le .env, et créer docker-compose.override.yml si
# un réseau Docker occupe 172.19.0.0/16 (docs/architecture.md, « Limites connues »)
curl http://localhost:8082/api/health        # "apisolscore" et "refonte" doivent être "ok"
```

La base métier tourne dans le conteneur `refonte_postgis` du back Symfony (`../back`,
`docker compose up -d db`). L'API la joint par `host.docker.internal:5434`. Les migrations
sont décrites dans `docs/architecture.md`, section 6.

- `http://localhost:8082/` redirige vers la documentation interactive `/docs`.
- L'API n'écoute que sur la machine (`127.0.0.1:8082`).
- phpMyAdmin, pour consulter la base d'audit : `http://localhost:8083` (identifiants
  `DB_AUDIT_USER` / `DB_AUDIT_PASSWORD` du `.env`). MySQL est aussi joignable sur
  `127.0.0.1:3307`.
- Le code de `app/` et le `.env` sont montés dans le conteneur : l'API redémarre toute
  seule à chaque modification, y compris du `.env`. Rien à reconstruire.
- Seules une modification du `Dockerfile` ou des dépendances (`requirements.txt`)
  demandent de reconstruire l'image : `docker compose up -d --build`.

### Dépendances

Deux fichiers, deux rôles :

| Fichier | Rôle | Qui l'écrit |
|---|---|---|
| `pyproject.toml` | **ce dont l'API a besoin** : `fastapi`, `sqlalchemy`… sans version | nous, à la main |
| `requirements.txt` | **les versions exactes installées**, dépendances indirectes comprises | `pip-compile`, jamais à la main |

L'image installe `requirements.txt` : tout le monde a exactement les mêmes versions, en
local comme en production, et un rebuild ne change rien par surprise.

**Ajouter une dépendance** : l'ajouter dans `pyproject.toml`, puis régénérer
`requirements.txt`. Les versions déjà figées sont conservées ; seule la nouvelle est
ajoutée :

```bash
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/src" -w /src python:3.13-slim \
  sh -c "pip install -q pip-tools && python -m piptools compile --strip-extras -o requirements.txt pyproject.toml"
docker compose up -d --build
```

**Mettre à jour les versions** : même commande avec `--upgrade` après `compile`, puis
relancer les tests avant de valider. On le fait volontairement, par exemple une fois par
trimestre ou pour une faille de sécurité, jamais par hasard lors d'un rebuild.

### Appeler l'API en local sans jeton Azure

En développement, un jeton fixe peut remplacer l'id token Azure. Dans le `.env` :

```dotenv
APP_ENV=dev
AUTH_DEV_TOKEN=<sortie de : openssl rand -hex 32>
AUTH_DEV_USER=dev@fondasol.fr
```

```bash
export JETON=$(grep '^AUTH_DEV_TOKEN=' .env | cut -d= -f2)
curl -X POST localhost:8082/searchSurveysByAreaDetails -H "Authorization: Bearer $JETON" \
  -H 'Content-Type: application/json' -d '{"bounds":{"minLat":48.84,"maxLat":48.87,"minLng":2.33,"maxLng":2.37}}'
```

Ce jeton n'est accepté que si `APP_ENV=dev`, sinon l'API refuse de démarrer. Ne jamais
le définir sur un serveur partagé.

---

## Tests

```bash
docker compose run --rm -v ./tests:/srv/tests api \
  sh -c "pip install --user -q pytest && python -m pytest -v tests"
```

Avec `-v`, chaque test s'affiche avec son nom et son résultat. **432 tests**, dans vingt-deux
fichiers. Le dossier `tests/` reprend l'arborescence d'`app/`.

| Fichier | Tests | Dépend de |
|---|---|---|
| `tests/core/test_auth.py` | 21 | rien |
| `tests/core/test_audit.py` | 9 | la base d'apisolscore et la base d'audit |
| `tests/core/test_errors.py` | 6 | rien |
| `tests/core/test_profile.py` | 7 | la base métier de test |
| `tests/core/test_warmup.py` | 2 | la base d'apisolscore et la base métier |
| `tests/domains/france/land_registry/test_services.py` | 4 | rien |
| `tests/domains/france/land_registry/test_routes.py` | 9 | rien (IGN simulé) |
| `tests/domains/map/test_routes.py` | 15 | la base d'apisolscore |
| `tests/domains/profile/test_entities.py` | 24 | rien |
| `tests/domains/profile/test_routes.py` | 22 | la base métier de test |
| `tests/domains/projects/test_entities.py` | 50 | rien |
| `tests/domains/projects/test_routes.py` | 74 | la base métier de test |
| `tests/domains/investigations/test_routes.py` | 30 | la base métier de test |
| `tests/domains/projects/test_ged.py` | 14 | la base métier de test (GED simulée) |
| `tests/domains/layer_catalog/test_routes.py` | 9 | base de test (migration `0007` rejouée par sa fonction `seed`) |
| `tests/domains/survey_imports/test_routes.py` | 13 | rien (classeurs .xlsx créés par le test ; .xls dans `fixtures/`, généré par `make_sondages_xls.py`) |
| `tests/domains/socle/test_routes.py` | 28 | la base métier de test (images dans un dossier temporaire) |
| `tests/domains/reports/test_reports.py` | 13 | rien (dépôt FTP simulé) |
| `tests/domains/desk_study/test_desk_study.py` | 26 | rien (sources simulées) |

Les tests qui écrivent n'utilisent jamais la base métier de `DB_REFONTE_NAME`. Ils passent
par `DB_REFONTE_TEST_NAME` (`fondasol_fastapi_test` par défaut), sur le même serveur. Cette
base est créée si besoin et les migrations y sont rejouées à chaque session. Un nom qui ne
finit pas par `_test` est refusé.

### `tests/core/test_auth.py` — l'authentification (18 tests)

Ces tests n'appellent pas Azure. Ils génèrent leur propre clé de signature et fabriquent
de faux id tokens, que l'API vérifie exactement comme les vrais.

| Test | Ce qu'il vérifie |
|---|---|
| `test_health_check_stays_public` | `/api/health` répond sans jeton |
| `test_a_route_without_token_is_rejected` (×4) | chacune des 4 routes de la carte répond 401 sans jeton, avec l'en-tête `WWW-Authenticate: Bearer` |
| `test_a_valid_id_token_is_accepted` | un jeton correct est accepté (200) |
| `test_an_invalid_token_is_rejected` (×7) | refus (401) d'un jeton : signé par une autre clé ; pour une autre application ; d'un autre tenant ; expiré ; sans `preferred_username` ; signé avec un secret partagé (HS256) au lieu de la clé Azure ; qui n'est pas un jeton du tout |
| `test_the_dev_token_is_accepted_in_dev` | en `APP_ENV=dev`, le jeton de dev est accepté, mais pas une version modifiée d'un seul caractère |
| `test_the_dev_token_is_ignored_when_not_configured` | sans `AUTH_DEV_TOKEN` défini, ce jeton ne donne aucun accès |
| `test_the_dev_token_prevents_startup_outside_dev` (×2) | avec `APP_ENV=prod` ou `staging`, un jeton de dev défini empêche l'API de démarrer |
| `test_a_too_short_dev_token_prevents_startup` | un jeton de dev de moins de 32 caractères empêche l'API de démarrer |
| `test_the_identity_carries_the_azure_identifier_and_name` | l'identité tirée du jeton porte l'oid et le nom affiché |
| `test_the_identity_leaves_missing_claims_empty` | un oid absent ou un nom vide donnent `None` |
| `test_the_dev_token_always_gives_the_same_azure_identifier` | le jeton de dev a un oid stable, pour retrouver son profil |

### `tests/core/test_profile.py` — le profil de l'agent connecté (7 tests)

| Test | Ce qu'il vérifie |
|---|---|
| `test_the_first_request_creates_the_profile_from_the_token` | le profil est créé dans `users` (oid en minuscules, adresse, nom) |
| `test_the_next_requests_find_the_same_profile_without_touching_it` | les requêtes suivantes le retrouvent sans changer la date de dernière connexion |
| `test_signing_in_again_updates_the_address_and_keeps_a_known_name` | à la connexion, l'adresse est mise à jour, et un nom absent du jeton n'efface pas le nom connu |
| `test_a_profile_imported_before_sso_gets_its_azure_identifier` | un profil connu par sa seule adresse reçoit l'oid au lieu d'être dupliqué |
| `test_a_token_without_azure_identifier_is_forbidden` (×3) | sans oid valide : 403, et rien n'est écrit |

### `tests/domains/profile/` — le profil, ses préférences et ses favoris (45 tests)

Portage des tests du back Symfony (`MeTest`, `UserPreferencesTest`), avec les mêmes cas.

| Fichier | Ce qu'il vérifie |
|---|---|
| `test_entities.py` | un PATCH ne change que les préférences envoyées ; une couche en double gardée une fois ; null vide une préférence ; 12 valeurs refusées (langue, thème, préférence inconnue, opacité hors bornes, en texte ou booléenne, visibilité absente, identifiant de couche, couches en objet, plus de 100 couches, `extra` en liste, style trop long) ; les règles d'une adresse favorite et ses messages ; son format de réponse |
| `test_routes.py` | profil créé puis réutilisé ; profil importé qui reçoit son oid ; préférences vides par défaut et `extra` toujours objet ; PATCH partiel ; refus sans rien enregistrer ; corps non JSON ou non objet ; favoris affaire et couche ajoutés puis retirés ; affaire inconnue (404) ; couche invalide (400) ; adresse unique par identifiant de géocodeur (201 puis 200) ; 21ᵉ adresse refusée (422) ; adresse sans coordonnées ; cloisonnement entre deux agents ; adresse inconnue (404) ; import sans doublon ni écrasement, qui remplit « Mes couches » vides, plafonné à 20 adresses, et qui n'enregistre rien s'il est invalide ; 401 sans jeton |

### `tests/domains/projects/` — les affaires, sondages et référentiels

Portage des tests du back Symfony (`GeolocationClassifierTest`, `ProjectSearchCriteriaTest`,
`AddSurveyHandlerTest`, `AffairesContractTest`, `ProjectSortTest`,
`ProjectGeolocationStatusesTest`, `GeolocationConsistencyTest`, `MalformedJsonBodyTest`).

| Fichier | Ce qu'il vérifie |
|---|---|
| `test_entities.py` | les 9 cas du statut de géolocalisation ; décompte incohérent refusé ; lecture des critères de recherche (valeurs « undefined », bornes de pagination, codes de filtre, tri fermé) ; nom de sondage ; chantier le plus proche ; position absente ou à zéro ; conversions à la manière de PHP |
| `test_routes.py` | enveloppe `items`/`count` et champs de l'ancien contrat ; fiche sans statut deviné ; sondages en liste ; référentiels ; chaque filtre ; requête réelle du front ; mode sans total ; tri français, égalités, valeurs absentes, avant pagination ; **le SQL de chaque filtre `selectedGeo` désigne les mêmes affaires que la règle métier** ; statuts en un appel ; repositionnement (altitude, chantiers déplacés et fiables, motif) ; identifiants base64 invalides ou avec « / » ; numéro d'affaire avec « / » ; ajout de sondage (chantier, doublon 409, nom invalide, affaire inconnue 404, sans chantier 422) ; présence de documents GED déclarée à la main (valeur, auteur et date enregistrés, `updated_at` intact, filtre `selectedGeds` à jour ; sans trace par défaut ; corps invalide 400 ; affaire inconnue 404) ; 401 sans jeton |

### `tests/domains/investigations/test_routes.py` — les enquêtes et leurs versions (30 tests)

Portage des tests du back Symfony (`InvestigationTest`, recherche de `SavedPageTest`), plus :
contenu envoyé en objet, `saved_pages.data` qui suit la dernière version, et 12
enregistrements simultanés qui prennent chacun un numéro différent (sans le verrou
`FOR UPDATE`, ce test échoue sur la contrainte d'unicité).

| Ce qu'il vérifie |
|---|
| V1 créée au nom de l'agent ; nouvelle version qui laisse la précédente intacte ; écrasement de la dernière version qui garde son numéro ; version antérieure protégée (409) ; numérotation propre à chaque enquête d'une affaire ; renommage valable pour toutes les versions ; 5 enregistrements incomplets refusés sans rien écrire ; 8 cas de 404 (enquête, version, identifiant ou numéro mal formés) ; `projectRef` obligatoire ; compte supprimé qui garde le nom de l'auteur ; recherche (casse, clés, position, joker littéral, limite, 404) ; 401 sans jeton |

### `tests/domains/projects/test_ged.py` — la GED (14 tests)

Portage de `HttpGedGatewayTest` et `GedProxyTest`, la GED étant simulée (`httpx.MockTransport`) :
en-têtes relayés (et seulement ceux-là), Basic Auth, seconde tentative après une erreur réseau,
indisponibilité après deux échecs, pas de reprise sur une réponse d'erreur ni sur un nom
introuvable, encodage du numéro et du nom de fichier, 3 s pour la fiche et 60 s pour un
fichier, GED non configurée, recherche de l'affaire par son identifiant GED, fichier relayé
avec son nom, 502 sans l'adresse interne, nom de fichier obligatoire.

### `tests/domains/socle/`, `reports/`, `desk_study/` — le lot 5 (67 tests)

Portage de `SocleTest`, `AddressSearchTracingTest`, `DepartmentAccessPolicyTest`,
`WaitingImageTest`, `ProjectArchivePathTest`, `ExternalResourceTest`, `InfoterreTest`,
`PlancheResultTest` et `FanOutBenchmarkTest`. Entre autres : un SVG porteur de script et un
fichier qui n'est pas une image sont refusés ; la route des fichiers refuse une remontée
d'arborescence ; l'habilitation d'une recherche d'adresse (territoire, accès général, agent
inconnu) ; l'archive ZIP range chaque rapport sous le chemin de son affaire et omet un fichier
illisible ; Infoterre refuse 7 adresses internes ou trompeuses sans les appeler ; les planches
sont interrogées en parallèle, une planche trop lente est dégradée, celles qui dépassent le
budget global sont abandonnées.

### `tests/core/test_errors.py` — les erreurs métier (6 tests)

| Test | Ce qu'il vérifie |
|---|---|
| `test_a_domain_error_becomes_its_http_status_with_the_symfony_body` (×5) | chaque erreur donne son code (400, 403, 404, 409, 422) et `{ "errors": message }` |
| `test_the_api_converts_domain_errors` | le gestionnaire est branché sur l'API |

### `tests/core/test_audit.py` — le journal et l'audit (9 tests)

Pendant les tests, l'écriture en base d'audit est remplacée par une liste en mémoire
(`tests/conftest.py`) et le journal va dans un dossier temporaire : les tests ne
polluent ni `audit_log` ni `logs/`.

| Test | Ce qu'il vérifie |
|---|---|
| `test_a_request_is_recorded_with_who_what_how_and_when` | une requête acceptée produit une entrée avec l'utilisateur, l'action, la méthode, le chemin, le statut, la durée, l'IP, le corps de la requête, la date, et le même identifiant que l'en-tête `X-Request-ID` |
| `test_a_rejected_request_is_recorded_as_anonymous` | une requête sans jeton est tracée (401, sans utilisateur) |
| `test_an_invalid_request_is_recorded` | une requête invalide est tracée (422, avec l'utilisateur) |
| `test_technical_routes_are_not_recorded` (×3) | `/api/health`, `/docs` et `/openapi.json` ne sont pas tracés |
| `test_an_unavailable_audit_database_does_not_break_the_request` | si la base d'audit est en panne, la requête répond quand même 200 |
| `test_an_entry_is_saved_in_the_audit_database` | une entrée est réellement insérée dans `audit_log`, relue, puis supprimée |
| `test_the_log_file_is_named_after_the_day_of_the_event` | le journal change de fichier quand le jour change |

### `tests/core/test_warmup.py` — le préchauffage au démarrage (2 tests)

| Test | Ce qu'il vérifie |
|---|---|
| `test_the_warm_up_fetches_the_azure_keys_and_opens_the_database_connections` | les clés Azure sont demandées une fois, deux connexions à apisolscore et une à la base métier restent ouvertes dans les pools |
| `test_an_unreachable_azure_does_not_prevent_startup` | si Azure est injoignable, le préchauffage n'échoue pas : il journalise un avertissement |

Dans les autres tests, le préchauffage est désactivé (`tests/conftest.py`) pour ne pas
appeler Azure.

### `tests/domains/map/test_routes.py` — les routes de la carte (15 tests)

Ces tests interrogent **la vraie base d'apisolscore**, en lecture seule.
L'authentification y est remplacée par un utilisateur de test : elle est déjà couverte
par le fichier précédent.

| Test | Ce qu'il vérifie |
|---|---|
| `test_an_area_returns_a_geojson_collection_of_points_within_bounds` (×4) | sur un secteur de Paris, chaque route renvoie un GeoJSON bien formé, au moins un point, tous les points dans l'emprise demandée, des coordonnées à 6 décimales au plus, et exactement les propriétés attendues (aucune pour les routes simples ; `uuid`, `affaire_id`, `affaire_numero`, `affaire_nom` ou `id`, `nom`, `site_uuid`, `has_mesure_pressiometrique` pour les routes détaillées) |
| `test_the_pressiometric_flag_is_always_a_boolean` | `has_mesure_pressiometrique` vaut toujours `true` ou `false`, jamais `null` |
| `test_an_area_without_data_returns_an_empty_collection` (×4) | une zone en plein Atlantique renvoie une collection vide (200), pas une erreur |
| `test_invalid_bounds_are_rejected` (×5) | refus (422) de latitudes inversées, de longitudes inversées, d'une latitude supérieure à 90, d'une longitude inférieure à -180, d'une emprise incomplète |
| `test_a_request_without_bounds_is_rejected` | une requête sans emprise est refusée (422) |

### Ce que les tests ne vérifient pas

- **Les valeurs exactes** : les tests contrôlent la forme des réponses, pas qu'un sondage
  précis porte tel nom. C'est voulu, pour qu'ils ne cassent pas à chaque évolution des
  données. En contrepartie, une erreur de SQL qui renverrait des propriétés fausses mais
  bien formées passerait inaperçue.
- **Les performances** : aucun test sur les temps de réponse.
- **Le CORS**, la redirection de `/` vers `/docs`, et l'appel réel à Azure pour récupérer
  les clés de signature.
- **Une panne de la base** : la réponse 503 de `/api/health` n'est pas testée.

### Dépendance à la base

Les tests de la carte ont besoin de la base d'apisolscore. Ils échouent, sans que le code
soit en cause, si :
- la base est injoignable (réseau, identifiants du `.env`) ;
- le secteur de Paris utilisé ne contient plus aucun site ou sondage.
