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
