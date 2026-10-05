# Inventaire des couches cartographiques et tests de disponibilité

Établi le 01/10/2026, à la suite d'un incident en production : un fournisseur de couches
n'a été accessible que depuis la France le 29/09 au soir (selon
l'information transmise), et les utilisateurs situés au Canada, au Luxembourg et au Sénégal
ont perdu une partie des cartes. Le fournisseur en cause n'est pas identifié.

## Comment les couches sont chargées

Aucune couche ne passe par un serveur Fondasol. **Le navigateur de chaque utilisateur
appelle directement chaque fournisseur**, dans l'ancien front Angular
(`/home/ericpaoli/source/frontend`) comme dans la refonte (`front/`, couches chargées par
Mapbox, US-CARTE-19). Le back Go d'origine (`/home/ericpaoli/source/backend`) ne relaie que
`/infoterre` (BRGM) et `/lux/geol` (service interne `10.1.0.23`). Si un fournisseur filtre
par pays, l'utilisateur à l'étranger est refusé et rien chez Fondasol ne peut l'éviter.

Les couches françaises sont bornées à la France (`bounds` du front) : un utilisateur à
l'étranger n'en a besoin que pour consulter une zone française. Les couches du Canada et du
Luxembourg viennent de fournisseurs locaux.

## Méthode

- Pour chaque couche, une vraie requête de tuile au zoom 14, au-dessus de Paris, de
  Luxembourg ou de Montréal selon le territoire. Succès = HTTP 200 **et** une image
  (un WMS renvoie souvent 200 avec une erreur XML).
- Depuis le réseau Fondasol en France (IP `212.106.127.186`), en Python puis dans Edge
  (page `test-couches.html`, ci-dessous). Les deux concordent.
- **Aucun test depuis l'étranger** : pas de point de sortie hors de France disponible (même
  l'outil de récupération web sortait par la même IP). C'est le rôle de la page de test.
- Non testés : les fonds Mapbox (CDN mondial de Mapbox, jeton requis), les API JSON
  `geoservice` de `solscore.fondasol.fr` et `api.soilcloud.fr`, les liens externes simples.
  Une seule API REST testée : Géorisques (`/api/v1/zonage_sismique`), OK.

## Inventaire

Durée = temps de réponse d'une tuile, depuis la France.

| Territoire | Fournisseur | Service | Couches | Utilisées par | Résultat (France, 01/10) | Durée |
|---|---|---|---|---|---|---|
| FR | BRGM | `geoservices.brgm.fr/risques` (WMS) | `ALEARG`, `MVT_LOCALISE`, `CAVITE_LOCALISEE`, `REMNAPPE_FIAB` | ancien front | ✅ toutes | 215–1268 ms |
| FR | BRGM | `geoservices.brgm.fr/geologie` (WMS) | `GEOLOGIE` | ancien front + refonte | ✅ toutes | 123–134 ms |
| FR | BRGM (Géorisques) | `mapsref.brgm.fr/wxs/georisques/risques` (WMS) | `SSP_CLASSIFICATION_SIS` | ancien front | ✅ toutes | 3361–3361 ms |
| FR | Carmen (INPN/MNHN) | `ws.carmencarto.fr/WMS/119/fxx_inpn` (WMS) | `Arretes_de_protection_de_biotope`, `Parcs_nationaux`, `Reserves_Naturelles_Nationales`, `Perimetre_de_protection_dune_reserve_naturelle_nationale`, `Reserves_naturelles_regionales`, `Perimetre_de_protection_dune_reserve_naturelle_regionale`, `Sites_Ramsar`, `Znieff1`, `Znieff2`, `ZICO`, `Sites_d_importance_communautaire`, `Zones_de_protection_speciale` | ancien front | ❌ aucune | — |
| FR | Fondasol (auto-hébergé) | `solscore.fondasol.fr/mbtiles/data/sis_test2/{z}/{x}/{y}.png` (Tuiles XYZ) | `sis_test2` (zonage sismique) | ancien front | ⚠️ OK dans le navigateur ; refusé par curl et Python (certificat, constat 3) | — |
| FR | Géorisques (MTE/BRGM) | `www.georisques.gouv.fr/services` (WMS) | `ALEA_SYNT_01_04FAI_FXX,ALEA_SYNT_01_02MOY_FXX,ALEA_SYNT_01_01FOR_FXX` | ancien front | ✅ toutes | 854–854 ms |
| FR | IGN (Géoplateforme) | `data.geopf.fr/wms-r` (WMS) | `CADASTRALPARCELS.PARCELLAIRE_EXPRESS`, `GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2`, `GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40`, `ORTHOIMAGERY.ORTHOPHOTOS.1950-1965`, `ORTHOIMAGERY.ORTHOPHOTOS2000-2005`, `ORTHOIMAGERY.ORTHOPHOTOS2006-2010`, `ORTHOIMAGERY.ORTHOPHOTOS2016-2020`, `ORTHOIMAGERY.ORTHOPHOTOS2021-2023`, `ORTHOIMAGERY.ORTHOPHOTOS2024`, `LANDCOVER.CLC18_FR` | ancien front | ✅ toutes | 144–1139 ms |
| FR | IGN (Géoplateforme) | `data.geopf.fr/wmts` (WMTS) | `CADASTRALPARCELS.PARCELLAIRE_EXPRESS` | refonte | ✅ toutes | 179–179 ms |
| LU | Geoportail.lu | `wmts1.geoportail.lu/opendata/wmts/topo_5k/GLOBAL_WEBMERCATOR_4_V3/{z}/{x}/{y}.png` (WMTS) | `topo_5k` | ancien front | ✅ toutes | 336–336 ms |
| LU | Geoportail.lu | `wmts1.geoportail.lu/opendata/wmts/ortho_latest/GLOBAL_WEBMERCATOR_4_V3/{z}/{x}/{y}.jpeg` (WMTS) | `ortho_latest` | ancien front | ✅ toutes | 165–165 ms |
| LU | Geoportail.lu | `wmsproxy.geoportail.lu/ogcproxywms` (WMS) | `geo_carte_geol_harmonisee` | ancien front | ✅ toutes | 214–214 ms |
| LU | Geoportail.lu | `wms.geoportail.lu/public_map_layers/service` (WMS) | `2119_2`, `749`, `214_1`, `664_1`, `573_1`, `2167_1` | ancien front + refonte | ⚠️ 5 OK, KO : 2119_2 | 117–126 ms |
| CA | Canards Illimités Canada | `maps.ducks.ca/arcgis/services/Public/QC_Carto_MH_sudqc_2022/MapServer/WMSServer` (WMS) | `0` | ancien front | ✅ toutes | 1077–1077 ms |
| CA | Québec (CPTAQ) | `carto.cptaq.gouv.qc.ca/cgi-bin/v2/cptaq` (WMS) | `demande` | refonte | ✅ toutes | 494–494 ms |
| CA | Québec (Environnement) | `www.servicesgeo.enviroweb.gouv.qc.ca/donnees/services/Public/Themes_publics/MapServer/WMSServer` (WMS) | `Milieux_humides_potentiels11904` | ancien front | ✅ toutes | 880–880 ms |
| CA | Québec (Environnement) | `geo.environnement.gouv.qc.ca/donnees/services/Biodiversite/MH_potentiels/MapServer/WMSServer` (WMS) | `Milieux_humides_potentiels11904` | ancien front | ✅ toutes | 458–458 ms |
| CA | Québec (Environnement) | `geo.environnement.gouv.qc.ca/donnees/services/Biodiversite/Aires_protegees/MapServer/WMSServer` (WMS) | `Ensemble_des_aires_protégées_et_autres_mesures_de_conservation_efficaces5256` | ancien front | ✅ toutes | 447–447 ms |
| CA | Québec (MSP) | `geoegl.msp.gouv.qc.ca/apis/wss/environnement.fcgi` (WMS) | `GRHQ_SENS_ECOULEMENT`, `GRHQ_RES_LIN_PERM`, `GRHQ_RES_SURF`, `GRHQ_RES_LIN_INTER` | ancien front | ✅ toutes | 1428–2103 ms |

Pages de l'ancien front : `pages/investigations` (enquête, l'essentiel des couches),
`pages/home` (BRGM, sismicité), `pages/cases`, `pages/surveys`, `pages/plps` (géologie BRGM),
`components/investigations/ca/*` (Québec). Refonte : `features/carte/application/layerCatalog.ts`.

Tous les fournisseurs qui répondent envoient `Access-Control-Allow-Origin` (`*`, ou l'origine
demandée pour les services ArcGIS du Québec) : la lecture par Mapbox est possible.

## Constats

1. **Carmen (INPN) est injoignable, même depuis la France** : `ws.carmencarto.fr` coupe la
   connexion juste après l'établissement TLS (`Connection reset by peer`), pour les
   12 couches environnementales de la page Enquête (ZNIEFF, Natura 2000, réserves…), et même
   pour sa page d'accueil. Service arrêté, ou filtrage de l'IP de Fondasol : à vérifier
   depuis une autre connexion (partage 4G). Dans les deux cas, ces couches sont aujourd'hui
   absentes pour les utilisateurs du réseau Fondasol.
2. **Geoportail.lu a retiré la couche `2119_2`** : `LayerNotDefined` (HTTP 500). La couche
   est morte dans l'ancien front pour tout le monde.
3. **`solscore.fondasol.fr` sert un certificat sans son certificat intermédiaire** (Gandi) :
   « unable to verify the first certificate ». Les navigateurs de bureau compensent en
   allant chercher l'intermédiaire, d'où un affichage correct, mais curl, Python, de
   nombreux clients mobiles et **tout relais ou outil de surveillance côté serveur
   échouent**. À corriger (installer la chaîne complète) avant toute solution de relais, et
   à vérifier pour `geoservice` sur le même hôte.
4. **Le pare-feu de la CPTAQ (Québec) bloque les navigateurs sans interface** : Edge en mode
   headless reçoit « Web Page Blocked! … Attack ID: 20000051 », le même Edge avec un
   user-agent normal passe. Pas de conséquence pour les utilisateurs, mais c'est le même
   type de filtrage (pare-feu applicatif d'un fournisseur) que celui de l'incident : un
   relais ou une sonde de surveillance doit se présenter comme un client ordinaire.
5. Anomalies mineures de l'ancien front : deux couches Carmen demandent `srs=EPSG:2154`
   avec une emprise en EPSG:3857 (`Reserves_Naturelles_Nationales`,
   `Perimetre_de_protection_dune_reserve_naturelle_nationale`) ; trois URL d'orthophotos IGN
   finissent par `srs=EPSG:3857}` (accolade en trop, sans effet constaté) ; les tuiles de
   sismicité `sis_test2` répondent 404 aux grands zooms (présentes au zoom 8, absentes au
   zoom 14) faute de `maxzoom` sur la source.

## Trouver le fournisseur en cause

Envoyer [`test-couches.html`](test-couches.html) à un collègue au Canada, au Luxembourg et
au Sénégal. La page s'ouvre directement depuis le fichier (double-clic, aucun compte), teste
les 50 couches depuis **sa** connexion et produit un rapport à copier dans un e-mail
(« Copier le rapport »). Une couche OK en France et KO chez eux désigne le fournisseur qui
filtre ; si tout est OK chez eux, la restriction a été levée depuis.

Pour mettre la page à jour après un changement de couches : la liste est la constante
`TESTS` en tête du script de la page (URL de tuile concrète, fournisseur, couche, territoire).
