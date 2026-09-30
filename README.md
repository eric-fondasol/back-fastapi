# Solscore — API FastAPI

Modèle d'API pour structurer apisolscore. Elle fournit au front Solscore :

- les **sites** et les **sondages** à afficher sur la carte (`app/domains/map/`), lus
  directement dans la base PostgreSQL d'apisolscore ;
- les **données d'enquête par pays** (`app/domains/france/`, `app/domains/canada/`, `app/domains/luxembourg/`),
  découpées par thème métier. La structure est prête : chaque thème a son routeur
  déjà branché, les routes restent à y ajouter.

Toutes les routes métier exigent le jeton SSO (Azure AD) de l'utilisateur connecté.

L'architecture, le parcours d'une requête et la façon d'ajouter une route, un thème ou
un pays sont détaillés dans [docs/architecture.md](docs/architecture.md).

---

## Démarrer

Prérequis : Docker.

```bash
cp .env.example .env              # puis renseigner les valeurs (voir docs/architecture.md, section 8)
docker compose up -d --build
curl http://localhost:8082/api/health
```

- `http://localhost:8082/` redirige vers la documentation interactive `/docs`.
- L'API n'écoute que sur la machine (`127.0.0.1:8082`).
- Le code de `app/` et le `.env` sont montés dans le conteneur : l'API redémarre toute
  seule à chaque modification, y compris du `.env`. Rien à reconstruire.
- Seules une modification du `Dockerfile` ou des dépendances (`pyproject.toml`)
  demandent de reconstruire l'image : `docker compose up -d --build`.

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

Avec `-v`, chaque test s'affiche avec son nom et son résultat. **33 tests**, dans deux
fichiers. Le dossier `tests/` reprend l'arborescence d'`app/`.

| Fichier | Tests | Dépend de |
|---|---|---|
| `tests/core/test_auth.py` | 18 | rien |
| `tests/domains/map/test_routes.py` | 15 | la base d'apisolscore |

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
