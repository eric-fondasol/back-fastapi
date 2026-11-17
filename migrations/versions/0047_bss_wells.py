"""Ouvrages de la Banque du Sous-Sol (BSS) en base, à la place du flux WMS du BRGM (demande du métier du
17/11/2026 ; ADR-0066 du front).

La couche « Données sur les sols - ouvrages BSS » (fr-brgm-bss-tous-ouvrages) affichait le WMS
BSS_TOTAL_AVEC_LABEL du BRGM. Ses ouvrages viennent désormais de l'extrait BSS_TOTAL.gpkg (946 130 points en
France et outre-mer au 16/11/2026), importé dans une table dédiée par app/domains/layer_catalog/bss.py
(procédure dans docs/couches/couches-en-base.md), et servis en tuiles vectorielles (MVT) par la route des tuiles
du catalogue.

Table dédiée plutôt que catalog_layer_features : le volume (près d'un million de points contre moins de
6 000 objets pour les autres couches en base), des colonnes au lieu d'un jsonb lu à chaque tuile, et un
remplacement d'un bloc à chaque nouvel extrait. Toutes les colonnes du fichier sont gardées (demande du
responsable du projet), en texte comme dans le GeoPackage, sous leur nom d'origine (SOURCE_COLUMNS) ; une chaîne
vide devient NULL. Deux colonnes calculées à l'import s'y ajoutent :
- sheet_url, la fiche InfoTerre, tirée du champ lien (une formule Excel LIEN_HYPERTEXTE) ;
- geometry en EPSG:3857, comme les couches fichier (migration 0043) : les tuiles se calculent sans reprojection.

code_log (1 à 6) donne la classe de la légende du BRGM : géologie vérifiée, initiale ou absente, avec ou sans
documents. Le champ label, cité par la demande, n'a que cinq valeurs qui ne correspondent pas à cette légende.

La couche passe au type bss, sans adresse : couleur par classe (params.classes, propriété code_log des tuiles),
point noir au centre pour les classes « et documents » (dot), contour sombre (outline) pour que les points
crème restent visibles sur un fond clair. Couleurs relevées sur la légende du WMS. symbol = point : le front
dessine la légende à partir des classes, en ronds comme sur la carte (et non en carrés comme l'image du BRGM,
demande du responsable du projet) ; legend_url est vidé.

Retour arrière : la couche redevient le WMS du BRGM, la table est supprimée.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

CODE = "fr-brgm-bss-tous-ouvrages"

SOURCE_COLUMNS = (
    "gml_id", "gis", "reference", "indice", "designation", "bss_id", "bss_id_txt", "nom_local", "carte8x", "x_l2e",
    "y_l2e", "x_local", "y_local", "projection", "metropole", "x_ref06", "y_ref06", "ref06", "longitude", "latitude",
    "sgr", "confidentialite", "numcart", "num_departement", "nom_departement", "nom_commune", "insee_commune",
    "lieu_dit", "nom_region_geologique", "bassin_versant", "nature", "prof_atteinte", "diametre_tubage",
    "date_realisation", "zsol", "precision_z", "mode_execution", "etat_ouvrage", "recherche", "exploitation",
    "reconnaissance", "utilisation", "prof_eau_sol", "date_eau_sol", "z_origine_coupe", "precision_z_coupe",
    "auteur_coupe", "date_coupe", "gisement", "echantillon", "documents", "reference_biblio", "auteur_dossier",
    "date_dossier", "importance", "reseau_piezo", "coupe_geologique", "niveau_eau", "piezometre", "nb_mesures_piezo",
    "nb_analyses_eau", "coupe_simplifiee", "coupe_simplifiee_hors_gtc", "coupe_gtc", "ouvrage_eau", "gitologie",
    "nb_images", "prof_max_coupe", "date_maj_dossier", "date_maj_ouvrage", "date_maj_piezo", "date_maj_niveau",
    "date_maj_ana", "code", "code_log", "code_mapserver", "symbole", "label", "ouvrage_mini", "point_eau",
    "date_deb_piezo", "date_fin_piezo", "log_geol_valide", "precision_xy", "qual_position", "projection_ref06",
    "x_saisie", "y_saisie", "projection_saisie", "unite_saisie", "lien", "carte", "num_commune", "carte_topo",
    "nb_observations", "z_bdalti", "nb_scans_coupe", "nb_scans_recap", "nb_scans_autres", "organisme", "code_minier",
    "police_des_eaux", "hors_declaration", "date_dern_maj", "code_liaison", "num_liaison", "reseau", "date_public",
    "temperature", "usage_thermique", "nature_aquif", "categorie", "type_sonde", "marque_sonde", "modele_sonde",
    "diametre_sonde", "ecarteur", "fluide", "quantite_fluide", "marque_ciment", "composition_laitier",
    "tige_injection", "comment_cimentation", "mep_reception_sonde", "mep_avant_ciment", "mep_apres_ciment",
    "pression_mep_apres_ciment", "duree_mep_apres_ciment", "protocol_recep_sond_chantier", "tubage_sout_retire",
    "tubage_raison", "comment_finalisation_sonde", "relations", "geom_l2e", "statut", "maille", "date_scraping",
)

KINDS_BEFORE = ("wms", "wmts", "xyz", "vector", "wfs", "geojson", "database", "database-tiles")
ADDRESSLESS_BEFORE = ("database", "database-tiles")
KINDS = (*KINDS_BEFORE, "bss")
ADDRESSLESS = (*ADDRESSLESS_BEFORE, "bss")

VERIFIED = "#8a4519"
INITIAL = "#f1c20a"
WITHOUT_GEOLOGY = "#fdf4d5"
OUTLINE = "#3f3f3f"


def geology_class(value, color, dot, label_fr, label_en):
    return {"value": value, "color": color, "dot": dot, "label": {"fr": label_fr, "en": label_en}}


PARAMS = {
    "symbol": "point",
    "outline": OUTLINE,
    "classes": {
        "property": "code_log",
        "values": [
            geology_class("1", VERIFIED, True, "Ouvrages avec géologie vérifiée et documents", "Wells with verified geology and documents"),
            geology_class(
                "2", VERIFIED, False, "Ouvrages avec géologie vérifiée mais aucun document", "Wells with verified geology but no document"
            ),
            geology_class("3", INITIAL, True, "Ouvrages avec géologie initiale et documents", "Wells with initial geology and documents"),
            geology_class(
                "4", INITIAL, False, "Ouvrages avec géologie initiale mais aucun document", "Wells with initial geology but no document"
            ),
            geology_class(
                "5",
                WITHOUT_GEOLOGY,
                True,
                "Ouvrages sans géologie mais documents disponibles",
                "Wells without geology but with documents",
            ),
            geology_class("6", WITHOUT_GEOLOGY, False, "Ouvrages sans géologie ni document", "Wells without geology or document"),
        ],
    },
}

WMS_URL = "https://geoservices.brgm.fr/geologie"
WMS_PARAMS = {"format": "image/png", "layers": "BSS_TOTAL_AVEC_LABEL", "version": "1.3.0"}
WMS_LEGEND = (
    f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=BSS_TOTAL_AVEC_LABEL&SLD_VERSION=1.1.0"
)


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _constraints(kinds, addressless):
    return (
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_kind_check",
        f"ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_kind_check CHECK (kind IN ({_quoted(kinds)}))",
        "ALTER TABLE catalog_layers DROP CONSTRAINT IF EXISTS catalog_layers_url_check",
        f"""
        ALTER TABLE catalog_layers ADD CONSTRAINT catalog_layers_url_check CHECK (
            CASE WHEN kind IN ({_quoted(addressless)}) THEN url IS NULL
                 ELSE coalesce(url LIKE 'https://%' OR (kind IN ('wfs', 'geojson') AND url LIKE 'http://%'), false)
            END
        )
        """,
    )


def upgrade() -> None:
    connection = op.get_bind()
    for statement in (
        f"""
        CREATE TABLE bss_wells (
            {", ".join(f'"{column}" text' for column in SOURCE_COLUMNS)},
            sheet_url text NOT NULL CHECK (sheet_url LIKE 'http%'),
            geometry geometry(Point, 3857) NOT NULL,
            PRIMARY KEY (bss_id),
            CHECK (code_log IN ('1', '2', '3', '4', '5', '6'))
        )
        """,
        "CREATE INDEX bss_wells_geometry ON bss_wells USING gist (geometry)",
        *_constraints(KINDS, ADDRESSLESS),
    ):
        connection.execute(sa.text(statement))
    switch_to_database(connection)


# Séparée de upgrade pour que les tests, qui vident les tables, puissent la rejouer.
def switch_to_database(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET kind = 'bss', url = NULL, params = CAST(:params AS jsonb), legend_url = NULL, updated_at = now()
            WHERE code = :code
            """
        ),
        {"code": CODE, "params": json.dumps(PARAMS, ensure_ascii=False)},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE catalog_layers
            SET kind = 'wms', url = :url, params = CAST(:params AS jsonb), legend_url = :legend_url, updated_at = now()
            WHERE code = :code
            """
        ),
        {"code": CODE, "url": WMS_URL, "params": json.dumps(WMS_PARAMS), "legend_url": WMS_LEGEND},
    )
    for statement in ("DROP TABLE bss_wells", *_constraints(KINDS_BEFORE, ADDRESSLESS_BEFORE)):
        connection.execute(sa.text(statement))
