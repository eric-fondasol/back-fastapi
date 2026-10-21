# Sécurisation des routes : vérification du jeton

La protection est posée **une seule fois par groupe de routes** dans `app/main.py` ; la
vérification elle-même est dans `app/core/auth.py`.

---

## 1. Le branchement : une dépendance sur chaque routeur

`app/main.py`

```python
protected = [Depends(current_user)]

app.include_router(health.router)                          # public
app.include_router(map_router, dependencies=protected)
app.include_router(france_router, dependencies=protected)
app.include_router(canada_router, dependencies=protected)
app.include_router(luxembourg_router, dependencies=protected)
```

FastAPI exécute `current_user` **avant chaque route** de ces routeurs. Une route ajoutée
dans n'importe quel thème est donc protégée sans rien écrire de plus.

Sont publiques : `/api/health`, `/docs` et la redirection de `/` vers `/docs`.

---

## 2. La lecture du jeton

```python
bearer = HTTPBearer(auto_error=False)
```

`HTTPBearer` lit l'en-tête `Authorization: Bearer <jeton>`. Avec `auto_error=False`,
l'absence de jeton n'est pas rejetée par FastAPI lui-même : c'est notre code qui répond
**401** de façon uniforme, avec l'en-tête `WWW-Authenticate: Bearer`.

---

## 3. La vérification du jeton Azure

Fonction `verified_username()` dans `app/core/auth.py`.

### 3.1 Récupération des clés publiques d'Azure

```python
@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    discovery = httpx.get(f"{config.oidc_issuer}/.well-known/openid-configuration", timeout=10)
    discovery.raise_for_status()
    return jwt.PyJWKClient(discovery.json()["jwks_uri"], lifespan=3600)
```

- On lit la configuration OpenID du tenant pour trouver l'adresse des clés de signature
  (JWKS).
- Le client est créé une seule fois (`lru_cache`) et garde les clés en mémoire **1 heure**
  (`lifespan=3600`).
- Les clés sont chargées dès le démarrage par `app/core/warmup.py`, pour que la première
  requête n'attende pas.

### 3.2 Choix de la clé

`get_signing_key_from_jwt` utilise l'identifiant de clé (`kid`) indiqué dans l'en-tête du
jeton pour sélectionner la bonne clé publique.

### 3.3 Décodage et contrôles

```python
claims = jwt.decode(
    credentials.credentials,
    signing_key.key,
    algorithms=["RS256"],
    audience=config.oidc_audience,
    issuer=config.oidc_issuer,
    options={"require": ["exp", "iss", "aud"]},
)
```

| Contrôle | Ce qui est vérifié |
|---|---|
| Signature | le jeton a été signé par Azure. Seul `RS256` est accepté, ce qui bloque les jetons `none` ou `HS256` forgés |
| Audience | `aud` doit valoir `OIDC_AUDIENCE` (notre application) |
| Émetteur | `iss` doit valoir `OIDC_ISSUER` (notre tenant Azure) |
| Expiration | le jeton n'est pas expiré (durée de vie : environ une heure) |
| Présence | `exp`, `iss` et `aud` sont obligatoires |

### 3.4 Identité

Le jeton doit contenir `preferred_username` (l'adresse de l'agent), sinon on répond 401.

### 3.5 Gestion des erreurs

```python
except (jwt.PyJWTError, httpx.HTTPError):
    raise unauthorized() from None
```

Toute erreur de jeton ou de réseau donne un **401 sans détail** : on ne révèle rien à
l'appelant sur la raison du refus.

---

## 4. Après la vérification

```python
def current_user(request: Request, credentials = Depends(bearer)) -> str:
    with timed("auth"):
        username = verified_username(credentials)

    request.state.username = username
    return username
```

- La durée de l'étape est mesurée (`timed("auth")`) et apparaît dans
  `details.timings_ms` de l'audit.
- L'utilisateur est placé dans `request.state.username`, que le middleware d'audit
  (`app/core/audit.py`) enregistre dans la colonne `username` de `audit_log`.

---

## 5. Le jeton de développement

Il permet de travailler en local sans jeton Azure.

```dotenv
APP_ENV=dev
AUTH_DEV_TOKEN=<au moins 32 caractères, par exemple : openssl rand -hex 32>
AUTH_DEV_USER=dev@fondasol.fr
```

Garde-fous :

- il n'est accepté que si `APP_ENV=dev`, sinon une `RuntimeError` est levée. Comme
  `dev_token()` est appelé au démarrage (`lifespan` dans `app/main.py`), **l'API refuse de
  démarrer** si ce jeton est défini dans un autre environnement ;
- il doit faire au moins 32 caractères ;
- il est comparé en temps constant (`hmac.compare_digest`), pour qu'on ne puisse pas le
  deviner caractère par caractère.

---

## 6. En complément

- **CORS** (`app/main.py`) : seules les origines de `CORS_ORIGINS` sont autorisées, avec
  les méthodes `GET`/`POST` et les en-têtes `Authorization`/`Content-Type`. Cela restreint
  les appels faits depuis un navigateur, pas les appels directs (curl, script) : la vraie
  barrière reste le jeton.
- **Tests** : `tests/core/test_auth.py` (18 tests) couvre ces cas.

---

## 7. Limite actuelle : pas de contrôle de rôles

Tout agent du tenant qui possède un jeton valide pour l'application accède à **toutes**
les routes. Si certaines données doivent être réservées à une partie des agents, il faudra
vérifier une claim `roles` ou `groups` dans `verified_username()`, ou ajouter une
dépendance dédiée sur le routeur concerné.
