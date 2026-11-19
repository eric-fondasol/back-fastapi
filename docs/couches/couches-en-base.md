# Couches du catalogue stockées en base

Une couche du catalogue peut avoir ses données dans la base métier plutôt que chez un service
(migration `0038`, ADR-0062 du front) :

| Type (`kind`) | Données | Route qui les sert |
|---|---|---|
| `database` | objets GeoJSON, table `catalog_layer_features` | `GET /layer-catalog/{code}/features?bbox=…&zoom=…` |
| `database-tiles` | tuiles d'images XYZ, table `catalog_layer_tiles` | `GET /layer-catalog/{code}/tiles/{z}/{x}/{y}` |

Toute couche peut aussi avoir une image de légende en base (`catalog_layer_legends`), servie par
`GET /layer-catalog/{code}/legend` et annoncée dans le catalogue par `storedLegend: true`.

Ces couches n'ont pas d'adresse : `url` est `NULL`.

## Paramètres d'une couche d'objets

Dans `params` (valables aussi pour une couche `wfs` ou `geojson`) :

| Clé | Rôle | Exemple |
|---|---|---|
| `color` | couleur unique des objets | `"#0000ff"` |
| `labelField` | propriété affichée en étiquette | `"Élévation de la nappe (m)"` |
| `classes` | couleur selon la valeur d'une propriété ; les valeurs qui ont un `label` forment la légende | `{"property": "Nom_AP", "values": [{"value": "1", "color": "#e60000", "label": {"fr": "Immédiate", "en": "Immediate"}}]}` |

Une valeur absente de `classes` prend la couleur de la couche.

## Ajouter une couche

1. **La fiche** : une ligne dans `catalog_layers` (par une migration, sur le modèle de la `0038`), avec
   `kind` à `database` ou `database-tiles` et `url` à `NULL`.
2. **Les données** : préparées hors de l'API (voir plus bas), puis importées dans le conteneur.

L'import remplace en une transaction ce que la couche avait déjà : pour corriger, on relance avec le
fichier corrigé.

```bash
docker cp <dossier préparé> solscore_fastapi:/tmp/import
docker exec -w /srv solscore_fastapi python -m app.domains.layer_catalog.imports features <code> /tmp/import/<fichier>.geojson
docker exec -w /srv solscore_fastapi python -m app.domains.layer_catalog.imports tiles <code> /tmp/import/<dossier z/x/y>
docker exec -w /srv solscore_fastapi python -m app.domains.layer_catalog.imports legend <code> /tmp/import/<image>.png
```

## Initialisation d'une base

Les données ne sont pas dans la migration : sur une nouvelle base, la migration crée les tables et les
fiches, puis les données se chargent une fois, à l'initialisation.

Le 12/11/2026, la recette (serveur Windows, PostgreSQL installé sans Docker) a reçu un fichier SQL exporté
de la base locale, passé à `psql`. HeidiSQL ne convient pas, il ne lit pas `COPY … FROM stdin`. Dans
PowerShell, mettre `&` devant le chemin entre guillemets :

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -U <utilisateur> -d <base> -f couches_canada.sql
```

Ce fichier retrouvait chaque couche par son code, puisque les identifiants diffèrent d'une base à l'autre.
Il s'arrêtait si une couche manquait au catalogue. Le script qui l'a produit n'est pas conservé : c'était une
opération unique.

Piège rencontré : sur la base `fondasol` de recette, Alembic était en `0038` mais le catalogue était vide
(aucune catégorie). La `0038` rattache ses couches à leur catégorie par leur code : sans catégorie, elle
n'a rien inséré, sans erreur. Le catalogue a été rechargé à partir d'un export `pg_dump` de la base
locale (`layer_categories`, `catalog_layers`), avant les données des couches.

## Préparer les fichiers

L'image de l'API n'embarque pas GDAL. On utilise l'image officielle, sans rien installer :

```bash
G="docker run --rm -u $(id -u):$(id -g) -v $PWD:/d ghcr.io/osgeo/gdal:ubuntu-small-3.10.3"
```

### Objets (shapefile, GeoPackage…)

Le fichier attendu est un FeatureCollection GeoJSON en longitude, latitude (EPSG:4326) :

```bash
$G ogr2ogr -f GeoJSON -t_srs EPSG:4326 -lco COORDINATE_PRECISION=6 -lco RFC7946=YES -makevalid \
  -select <champs gardés> /d/sortie.geojson /d/source.shp
```

`-select` limite les propriétés à celles qui servent : elles s'affichent toutes dans la fiche d'un objet.
Une géométrie encore invalide est réparée à l'import (`ST_MakeValid`).

### KML ou KMZ exporté d'ArcGIS

Les attributs y sont dans un tableau HTML (balise `description`), qu'`ogr2ogr` ne lit pas.
`kml_arcgis_vers_geojson.py` (dans ce dossier, bibliothèque standard seulement) les extrait : lignes
`<td>clé</td><td>valeur</td>` de la description, et `name` du `Placemark` dans `CODE`. Les champs techniques
d'ArcGIS (`FID`, `AREA`…) sont écartés ; d'autres s'ajoutent en arguments :

```bash
unzip -p <fichier>.kmz doc.kml > doc.kml
python3 -I kml_arcgis_vers_geojson.py doc.kml sortie.geojson [champ écarté …]
```

Pour les isopièzes, `CODE` a ensuite été retiré, et les deux élévations renommées en « Élévation de la nappe
(m) » et « (pi) », noms affichés dans la fiche d'un objet. Les couleurs du KML (`PolyStyle`, en `aabbggrr`) se reportent dans `params.classes`.

### Image calée (GroundOverlay d'un KMZ, GeoTIFF)

1. Extraire l'image du KMZ (`unzip -j <fichier>.kmz "files/*"`) et relever `north`, `south`, `east` et
   `west` de son `LatLonBox` dans `doc.kml`.
2. Caler l'image, puis la découper en tuiles XYZ (WebP : environ 6 à 9 ko par tuile pour une planche scannée) :

```bash
$G gdal_translate -of VRT -a_srs EPSG:4326 -a_ullr <west> <north> <east> <south> /d/image.jpg /d/image.vrt
$G gdal2tiles.py --xyz -z 9-15 -r bilinear --processes=4 --tiledriver=WEBP --webp-quality=82 --webviewer=none \
  /d/image.vrt /d/tuiles
```

Un GeoTIFF déjà géoréférencé se découpe directement, sans l'étape `gdal_translate`.

Zoom maximal : celui dont le pixel est proche de celui de l'image. Pour un scan d'une dizaine de milliers de
pixels sur une cinquantaine de kilomètres, c'est le zoom 15. Au-delà, la carte agrandit les tuiles du
zoom 15 (`max_zoom` de la couche à 15).

Une `rotation` dans le `LatLonBox` n'est pas reprise par `-a_ullr`. Elle est négligeable sous 0,1°.

## Les couches importées le 12/11/2026 (Canada)

| Code | Type | Source |
|---|---|---|
| `ca-qc-aires-protection-eau-souterraine` | `database` | `eau_souterraine.shp` (MELCCFP, dossier `solscore_apis/database/aires_protection_eau`), 4 585 objets |
| `ca-qc-aires-protection-eau-surface` | `database` | `eau_surface.shp`, 408 objets |
| `ca-mtl-depots-meubles-1426-polygones` | `database` | `geo1426_ply_DépôtsMeubles.kmz`, 675 objets, propriété `CODE` |
| `ca-mtl-isopiezes` | `database` | `Hypsometr.kmz`, 29 lignes, élévation de la nappe en mètres et en pieds |
| `ca-mtl-depots-meubles-1426` | `database-tiles` | `1426A - Carte des dépôts meuble - Montréal.kmz`, 3 726 tuiles |
| `ca-mtl-profondeur-roc-1427` | `database-tiles` | `Profondeur du roc - Montréal.kmz`, 3 966 tuiles |
| `ca-mtl-carte-hydrogeologique` | `database-tiles` | `Carte hydrogeologique - Montreal.kmz`, 3 969 tuiles |

Légendes : `Legende FR.png` (réduite à 600 px de large) pour les deux couches 1426, `Échelle de conversion.png`
pour la 1427. Les fichiers KMZ viennent du dossier « Annexe 3 - Cartes mtl » transmis par le métier. Ils ne
sont pas versionnés : pour réimporter, repartir de ce dossier.

## Les ouvrages de la Banque du Sous-Sol (BSS)

Couche `fr-brgm-bss-tous-ouvrages`, type `bss` (migration `0047`, ADR-0066 du front). Ses ouvrages ne sont pas dans
`catalog_layer_features` mais dans une table dédiée, `bss_wells` : près d'un million de points, servis en tuiles
vectorielles par `GET /layer-catalog/fr-brgm-bss-tous-ouvrages/tiles/{z}/{x}/{y}`.

Source : `BSS_TOTAL.gpkg`, extrait de la BSS transmis par le métier (946 130 ouvrages, 1,3 Go, au 16/11/2026).
Il n'est pas versionné. Toutes ses colonnes sont copiées, en texte, sous leur nom d'origine (liste dans la migration
`0047`) ; une chaîne vide devient NULL. `bss_id`, `code_log` (classe de la légende, 1 à 6) et `lien` (formule Excel
contenant l'adresse de la fiche InfoTerre) sont obligatoires ; l'import en tire `sheet_url` et le point en
EPSG:3857. Les colonnes absentes d'un futur extrait restent vides, celles en trop sont ignorées : l'import liste
les unes et les autres.

```bash
docker cp BSS_TOTAL.gpkg solscore_fastapi:/tmp/BSS_TOTAL.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.bss /tmp/BSS_TOTAL.gpkg
docker exec solscore_fastapi rm /tmp/BSS_TOTAL.gpkg
```

L'import remplace tous les ouvrages en une transaction (2 min 20 pour l'extrait complet, 1,2 Go en base) et affiche le nombre
d'ouvrages importés et écartés (sans géométrie, classe ou lien). Pour un nouvel extrait, relancer la même
commande.

Légende : dessinée par le front à partir des classes de la couche (`params.classes`, `params.symbol` à `point`),
en ronds comme sur la carte ; aucune image à importer.

## Les sites CASIAS (anciens sites industriels et activités de service)

Couches `fr-georisques-casias-points` et `fr-georisques-casias-polygones`, type `casias` (migration `0048`,
ADR-0068 du front). Comme la BSS, leurs sites sont dans une table dédiée, `casias_sites`, une ligne par site et par
forme (`shape` à `point` ou `polygon`), servis en tuiles vectorielles par
`GET /layer-catalog/<code>/tiles/{z}/{x}/{y}` (chaque couche ne sert que sa forme).

Source : `CASIAS.gpkg`, extrait transmis par le métier (tables `SSP_ETS_GE_POINT`, 253 733 points, et
`SSP_ETS_GE_POLYGON`, 3 756 emprises, au 17/11/2026). Il n'est pas versionné. Toutes ses colonnes sont copiées, en
texte, sous leur nom d'origine (liste dans la migration `0048`) ; une chaîne vide devient NULL. `code_metier` et la
géométrie sont obligatoires ; un code en double dans une table garde la première ligne.

```bash
docker cp CASIAS.gpkg solscore_fastapi:/tmp/CASIAS.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.casias /tmp/CASIAS.gpkg
docker exec solscore_fastapi rm /tmp/CASIAS.gpkg
```

L'import remplace tous les sites des deux formes en une transaction (9 s pour l'extrait complet, 123 Mo en base) et
affiche le nombre de points et d'emprises importés, et de lignes écartées. Pour un nouvel extrait, relancer la même
commande.

Légende : dessinée par le front à partir de `params.color` (rond pour les points, `params.symbol` à `point` ;
carré pour les emprises) ; aucune image à importer.

## Les sites BASOL (pollution des sols appelant une action des pouvoirs publics)

Couches `fr-georisques-pollution-instruction-points` et `fr-georisques-pollution-instruction-polygones`, type
`basol` (migration `0051`, ADR-0071 du front). Même modèle que CASIAS : table dédiée `basol_sites`, une ligne par
site et par forme, servie en tuiles vectorielles par `GET /layer-catalog/<code>/tiles/{z}/{x}/{y}`. L'import est
commun avec CASIAS (`site_layers.py`).

Source : `BASOL.gpkg`, extrait transmis par le métier (tables `SSP_INSTR_GE_POINT`, 11 625 points, et
`SSP_INSTR_GE_POLYGONE`, 7 650 emprises, au 17/11/2026). Il n'est pas versionné. Toutes ses colonnes sont copiées
(liste dans la migration `0051`). Le fichier répète un site sur chacune de ses communes (même code, même
géométrie) : l'import garde la première ligne du fichier, d'où 1 206 lignes écartées pour l'extrait complet.

```bash
docker cp BASOL.gpkg solscore_fastapi:/tmp/BASOL.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.basol /tmp/BASOL.gpkg
docker exec solscore_fastapi rm /tmp/BASOL.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.basol C:\apps\solscore\solscore_apis\database\basol\BASOL.gpkg
```

4 s en local, 58 Mo en base : 11 019 points et 7 050 emprises. Pour un nouvel extrait, relancer la même commande.

Légende : dessinée par le front à partir de `params.color` (rouge `#d7301f`) ; aucune image à importer.

La même table sert le tableau « Sites ex-BASOL » de l'enquête : `POST /fr/environment/basol-sites` (point ou
parcelles, rayon), sans passer par l'API Solscore v2. De même, `casias_sites` sert le tableau « Sites CASIAS »
(`POST /fr/environment/casias-sites`) : un seul import par fichier pour les couches et les tableaux.

## Les secteurs d'information sur les sols (SIS)

Couche `fr-georisques-sis`, type `sis` (migration `0052`, ADR-0072 du front). Même modèle que BASOL : table dédiée
`sis_sites` (emprises seules), servie en tuiles vectorielles et au tableau « Sites SIS » de l'enquête
(`POST /fr/environment/sis-sites`). L'import est commun avec CASIAS et BASOL (`site_layers.py`).

Source : `SIS.gpkg`, extrait transmis par le métier (table `SSP_CLASSIF_SIS_GE`, 6 006 emprises au 17/11/2026).
Il n'est pas versionné. Un secteur répété sur plusieurs communes garde la première ligne du fichier, d'où 310
lignes écartées pour l'extrait complet.

```bash
docker cp SIS.gpkg solscore_fastapi:/tmp/SIS.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.sis /tmp/SIS.gpkg
docker exec solscore_fastapi rm /tmp/SIS.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.sis C:\apps\solscore\solscore_apis\database\sis\SIS.gpkg
```

Quelques secondes, 7 Mo en base : 5 696 emprises. Légende : dessinée par le front à partir de `params.color`
(violet `#7b3294`).

## Les établissements pollueurs (registre IREP)

Couche `fr-georisques-etablissements-pollueurs`, type `polluting-facilities` (migration `0053`, ADR-0073 du
front). Même modèle que SIS : table dédiée `polluting_facilities` (points seuls), servie en tuiles vectorielles.
L'import est commun avec CASIAS, BASOL et SIS (`site_layers.py`) ; le fichier n'ayant pas de `code_metier`, un
établissement est identifié par `identifiant` (identifiant IREP).

Source : `ETABLISSEMENTS_POLLUEURS.gpkg`, extrait transmis par le métier (table `ETABLISSEMENTS_POLLUEURS`,
23 197 points au 18/11/2026). Il n'est pas versionné.

```bash
docker cp ETABLISSEMENTS_POLLUEURS.gpkg solscore_fastapi:/tmp/ETABLISSEMENTS_POLLUEURS.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.polluting_facilities /tmp/ETABLISSEMENTS_POLLUEURS.gpkg
docker exec solscore_fastapi rm /tmp/ETABLISSEMENTS_POLLUEURS.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.polluting_facilities C:\apps\solscore\solscore_apis\database\etablissements_pollueurs\ETABLISSEMENTS_POLLUEURS.gpkg
```

Quelques secondes, 8 Mo en base : 23 197 points. Légende : dessinée par le front à partir de `params.color`
(orange `#e08214`, rond cerné de sombre).

## Les servitudes d'utilité publique liées à la pollution des sols (SUP)

Couche `fr-georisques-sup`, type `sup` (migration `0054`, ADR-0074 du front), créée par la migration dans la
catégorie « environnement », juste après les secteurs SIS (le catalogue n'avait pas de couche SUP). Même modèle
que SIS : table dédiée `sup_sites` (emprises seules), servie en tuiles vectorielles, vides sous le zoom 12. Pas de
tableau dans l'enquête. L'import est commun avec CASIAS, BASOL et SIS (`site_layers.py`).

Source : `SUP.gpkg`, extrait transmis par le métier (table `SSP_CLASSIF_SUP_GE`, 888 emprises au 17/11/2026). Il
n'est pas versionné. Une servitude répétée sur plusieurs communes garde la première ligne du fichier, d'où 35
lignes écartées pour l'extrait complet.

```bash
docker cp SUP.gpkg solscore_fastapi:/tmp/SUP.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.sup /tmp/SUP.gpkg
docker exec solscore_fastapi rm /tmp/SUP.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.sup C:\apps\solscore\solscore_apis\database\sup\SUP.gpkg
```

Moins d'une seconde, 853 emprises. Légende : dessinée par le front à partir de `params.color` (vert d'eau
`#018571`).

## Les installations classées (ICPE)

Couche `fr-georisques-icpe`, type `icpe` (migration `0055`, ADR-0075 du front). Même modèle que les établissements
pollueurs : table dédiée `icpe_sites` (points seuls), servie en tuiles vectorielles, vides sous le zoom 11, et au
tableau « Sites ICPE » de l'enquête (`POST /fr/environment/icpe-sites`). L'import est commun avec les autres
couches de sites (`site_layers.py`) ; le fichier n'ayant pas de `code_metier`, une installation est identifiée par
`code_aiot`.

Source : `ICPE.gpkg`, extrait transmis par le métier (table `INSTALLATIONS_CLASSEES_SIMPLIFIE_GE`, 136 194 points
au 18/11/2026). Il n'est pas versionné.

```bash
docker cp ICPE.gpkg solscore_fastapi:/tmp/ICPE.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.icpe /tmp/ICPE.gpkg
docker exec solscore_fastapi rm /tmp/ICPE.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.icpe C:\apps\solscore\solscore_apis\database\icpe\ICPE.gpkg
```

5 s en local, 59 Mo en base : 136 194 points. Légende : dessinée par le front à partir de `params.classes`
(par valeur de la colonne `legende`) : icône de la légende de Géorisques pour chaque catégorie (`icon`, migration
`0056` : usine Seveso, usine non Seveso, éolienne, élevages, carrière), rond gris pour les autres installations ;
aucune image à importer.

## Les milieux humides du sud du Québec

Couche `ca-qc-milieux-humides`, type `wetlands` (migration `0049`, ADR-0069 du front). Comme la BSS et CASIAS,
ses milieux sont dans une table dédiée, `quebec_wetlands`, une ligne par milieu (clé `globalid`), servis en tuiles
vectorielles par `GET /layer-catalog/ca-qc-milieux-humides/tiles/{z}/{x}/{y}`, vides sous le zoom 12.

Source : `mh_2023.gpkg`, transmis par le métier le 18/11/2026 avec son style `style_mh.sld` (table
`milieux_humides_sudqc_nov2023`, 328 863 multipolygones, « Cartographie détaillée des milieux humides des secteurs
habités du sud du Québec », Canards Illimités Canada et MELCCFP, version de novembre 2023). Il n'est pas versionné.
Toutes ses colonnes sont copiées, en texte, sous leur nom passé en minuscules (liste dans la migration `0049`) ;
une chaîne vide (ou faite d'espaces, insécables compris) devient NULL. `GLOBALID` et la géométrie sont
obligatoires ; une clé en double garde la première ligne. Les `MULTISURFACE` deviennent des `MULTIPOLYGON`.

```bash
docker cp mh_2023.gpkg solscore_fastapi:/tmp/mh_2023.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.wetlands /tmp/mh_2023.gpkg
docker exec solscore_fastapi rm /tmp/mh_2023.gpkg
```

L'import remplace tous les milieux en une transaction (2 min 35 s pour le fichier complet, 772 Mo en base) et
affiche le nombre de milieux importés et de lignes écartées. Pour une nouvelle version, relancer la même commande.
Le chargement est commun avec les milieux humides potentiels (`polygon_layers.py`) : la table est vidée par
`TRUNCATE` (plus de lignes mortes, plus besoin de `VACUUM FULL`) et l'index spatial reconstruit après le
chargement ; la table est verrouillée jusqu'à la fin, les tuiles de la couche attendent.

Style : table `quebec_wetland_classes` (code, couleur, libellés français et anglais, ordre de la légende), remplie
par la migration `0049` d'après `style_mh.sld` ; `quebec_wetlands.classe` y renvoie par une clé étrangère.
`GET /layer-catalog` en tire `params.classes` pour le front, qui dessine la carte et la légende (un carré par
classe) ; aucune image à importer. Pour changer une couleur ou un libellé :

```sql
UPDATE quebec_wetland_classes SET color = '#2e9e00' WHERE code = 'ME';
```

L'opacité du remplissage (50 %) est dans `params.fillOpacity` de la couche, et non par classe.

Une classe absente de la table écarte ses milieux à l'import, qui la signale : l'ajouter à la table (dans une
migration) avant de réimporter.

## Les milieux humides potentiels du Québec

Couche `ca-qc-milieux-humides-potentiels`, type `potential-wetlands` (migration `0050`, ADR-0070 du front).
Milieux dans `quebec_potential_wetlands` (clé `objectid`), style dans `quebec_potential_wetland_classes` (clé : la
valeur de `CLASSE` en clair ; remplissage `color`, contour `outline`, libellés, ordre), liées par une clé étrangère
sur la classe. Tuiles vectorielles par `GET /layer-catalog/ca-qc-milieux-humides-potentiels/tiles/{z}/{x}/{y}`,
vides sous le zoom 12.

Source : `mh_potentiel_2023.gpkg`, transmis par le métier le 18/11/2026 avec `style.sld` (table `mh_potentiel_qc`,
2 446 410 multipolygones en EPSG:32198, « Milieux humides potentiels 2019 », MELCC - DCE). Il n'est pas versionné.
Tout le fichier est importé, y compris les sources `MH_DETAIL` (cartographie détaillée de 2019), qui recouvrent la
couche précédente.

```bash
docker cp mh_potentiel_2023.gpkg solscore_fastapi:/tmp/mh_potentiel_2023.gpkg
docker exec solscore_fastapi python -m app.domains.layer_catalog.potential_wetlands /tmp/mh_potentiel_2023.gpkg
docker exec solscore_fastapi rm /tmp/mh_potentiel_2023.gpkg
```

Sur le serveur Windows, avec le Python de l'environnement du back :

```powershell
python -m app.domains.layer_catalog.potential_wetlands C:\apps\solscore\solscore_apis\database\mh_potentiel_2023_gpkg\mh_potentiel_2023.gpkg
```

11 min 54 s en local pour le fichier complet, 6,2 Go en base ; prévoir de l'ordre de 6 Go de plus le temps de
l'import (table temporaire). La table est verrouillée jusqu'à la fin : à lancer hors des heures d'usage. Le
fichier `style.sld` n'est pas lu : son contenu est dans la migration `0050`. Pour changer une couleur ou un
contour :

```sql
UPDATE quebec_potential_wetland_classes SET color = '#a3ff73', outline = '#70a800' WHERE code = 'Marécage';
```

