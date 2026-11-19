import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import solscore_api
from app.core.auth import current_user
from app.main import app

AVRIL = {"lat": 49.2668, "lon": 6.0206}
ROUTE = "/fr/environment/basol-sites"
CASIAS_ROUTE = "/fr/environment/casias-sites"
SIS_ROUTE = "/fr/environment/sis-sites"
ICPE_ROUTE = "/fr/environment/icpe-sites"


def site(connection, shape, code, wkt, name="Crassiers", town="AVRIL"):
    connection.execute(
        text(
            """
            INSERT INTO basol_sites (shape, code_metier, nom_etablissement, nom_commune, statut_instruction, date_maj, url_fiche, geometry)
            VALUES (:shape, :code, :name, :town, 'En cours', '2021-09-09', :fiche, ST_Transform(ST_GeomFromText(:wkt, 4326), 3857))
            """
        ),
        {"shape": shape, "code": code, "name": name, "town": town, "fiche": f"https://fiches-risques.brgm.fr/georisques/infosols/instruction/{code}", "wkt": wkt},
    )


@pytest.fixture
def client(refonte_database, monkeypatch):
    def no_solscore_api(*args, **kwargs):
        raise AssertionError("les sites CASIAS, BASOL, SIS et ICPE sont lus en base, pas sur l'API Solscore v2")

    monkeypatch.setattr(solscore_api, "post", no_solscore_api)
    with refonte_database.begin() as connection:
        site(connection, "point", "SSP000001", "POINT(6.0206 49.2668)")
        site(connection, "polygon", "SSP000001", "MULTIPOLYGON(((6.0206 49.2668, 6.0216 49.2668, 6.0216 49.2678, 6.0206 49.2678, 6.0206 49.2668)))")
        site(connection, "point", "SSP000002", "POINT(6.0206 49.2758)", name="Carreau de la mine", town="MOYEUVRE")
        site(connection, "point", "SSP000003", "POINT(6.0206 49.3168)", name="Trop loin")
        connection.execute(
            text(
                """
                INSERT INTO casias_sites (shape, code_metier, nom_inventaire, code_inventaire, nom_etablissement, nom_commune, etat_activite, fiche_risque, geometry)
                VALUES ('point', 'SSP4069681', 'BASIAS', 'LOR5703364', 'Garage du centre', 'AVRIL', 'En arrêt',
                        'https://fiches-risques.brgm.fr/georisques/casias/SSP4069681', ST_Transform(ST_GeomFromText('POINT(6.0206 49.2708)', 4326), 3857))
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO sis_sites (shape, code_metier, id_inventaire_classification, nom_etablissement, code_insee, nom_commune, date_ap, url_fiche, geometry)
                VALUES ('polygon', 'SSP00073030201', '57SIS00001', 'Ancienne cokerie', '57001', 'AVRIL', '2019-07-03',
                        'https://fiches-risques.brgm.fr/georisques/infosols/classification/SSP00073030201',
                        ST_Transform(ST_GeomFromText('MULTIPOLYGON(((6.0300 49.2668, 6.0310 49.2668, 6.0310 49.2678, 6.0300 49.2678, 6.0300 49.2668)))', 4326), 3857))
                """
            )
        )
        for code, name, wkt in (
            ("0005704438", "Carrières de l'Orne", "POINT(6.0206 49.2698)"),
            ("0005704805", "Laminoir", "POINT(6.0206 49.2678)"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO icpe_sites (shape, code_aiot, raison_sociale, commune, activite_principale, seveso, etat_activite, regime_vig, legende, url_fiche, geometry)
                    VALUES ('point', :code, :name, 'AVRIL', '08 - Autres industries extractives', 'Non Seveso', 'En exploitation avec titre', 'Autorisation',
                            'Carrière', :fiche, ST_Transform(ST_GeomFromText(:wkt, 4326), 3857))
                    """
                ),
                {"code": code, "name": name, "wkt": wkt, "fiche": f"https://www.georisques.gouv.fr/risques/installations/donnees/details/{code}"},
            )
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_the_sites_within_the_radius_come_from_the_table_one_per_code_its_footprint_first_by_distance(client):
    response = client.post(ROUTE, json={**AVRIL, "rayon_m": 2000})

    assert response.status_code == 200
    body = response.json()
    assert (body["mode_recherche"], body["nombre_total"], body["rayon_recherche"]) == ("point", 2, 2000)
    sites = [feature["properties"] for feature in body["data"]["features"]]
    assert [(site["code_metier"], site["type_geometrie"], site["distance_m"]) for site in sites] == [("SSP000001", "polygone", 0), ("SSP000002", "point", 1001)]
    assert sites[0]["url_fiche"] == "https://fiches-risques.brgm.fr/georisques/infosols/instruction/SSP000001"
    assert (sites[1]["nom_etablissement"], sites[1]["nom_commune"], sites[1]["statut_instruction"], sites[1]["date_maj"]) == (
        "Carreau de la mine",
        "MOYEUVRE",
        "En cours",
        "2021-09-09",
    )
    assert body["data"]["features"][1]["geometry"] == {"type": "Point", "coordinates": [6.0206, 49.2758]}


def test_the_sites_are_searched_around_the_parcels(client):
    parcel = [[6.0196, 49.2748], [6.0216, 49.2748], [6.0216, 49.2768], [6.0196, 49.2768]]

    body = client.post(ROUTE, json={"parcelles": [parcel], "rayon_m": 100}).json()

    assert body["mode_recherche"] == "parcelles"
    assert [(feature["properties"]["code_metier"], feature["properties"]["distance_m"]) for feature in body["data"]["features"]] == [("SSP000002", 0)]


def test_an_invalid_search_is_refused(client):
    assert client.post(ROUTE, json={**AVRIL, "rayon_m": 50000}).status_code == 422


def test_the_casias_sites_come_from_their_table_in_the_format_of_the_solscore_api(client):
    body = client.post(CASIAS_ROUTE, json={**AVRIL, "rayon_m": 1000}).json()

    assert (body["mode_recherche"], body["nombre_total"]) == ("point", 1)
    assert body["data"]["features"][0]["properties"] == {
        "code_metier": "SSP4069681",
        "nom_inventaire": "BASIAS",
        "code_inventaire": "LOR5703364",
        "nom_etablissement": "Garage du centre",
        "adresse": None,
        "code_insee": None,
        "nom_commune": "AVRIL",
        "etat_activite": "En arrêt",
        "nature_localisation": None,
        "fiche_risque": "https://fiches-risques.brgm.fr/georisques/casias/SSP4069681",
        "type_geometrie": "point",
        "distance_m": 445,
    }


def test_the_sis_sectors_come_from_their_table(client):
    body = client.post(SIS_ROUTE, json={**AVRIL, "rayon_m": 1000}).json()

    assert body["nombre_total"] == 1
    sector = body["data"]["features"][0]["properties"]
    assert (sector["code_metier"], sector["id_inventaire_classification"], sector["code_insee"], sector["nom_commune"], sector["type_geometrie"]) == (
        "SSP00073030201",
        "57SIS00001",
        "57001",
        "AVRIL",
        "polygone",
    )
    assert sector["url_fiche"] == "https://fiches-risques.brgm.fr/georisques/infosols/classification/SSP00073030201"
    assert 600 < sector["distance_m"] < 750


def test_the_classified_installations_come_from_their_table_one_per_aiot_code_by_distance(client):
    body = client.post(ICPE_ROUTE, json={**AVRIL, "rayon_m": 1000}).json()

    assert body["nombre_total"] == 2
    installations = [feature["properties"] for feature in body["data"]["features"]]
    assert [(installation["code_aiot"], installation["distance_m"]) for installation in installations] == [("0005704805", 111), ("0005704438", 334)]
    assert installations[1] == {
        "code_aiot": "0005704438",
        "url_fiche": "https://www.georisques.gouv.fr/risques/installations/donnees/details/0005704438",
        "raison_sociale": "Carrières de l'Orne",
        "adresse": None,
        "code_postal": None,
        "commune": "AVRIL",
        "activite_principale": "08 - Autres industries extractives",
        "seveso": "Non Seveso",
        "etat_activite": "En exploitation avec titre",
        "regime_vig": "Autorisation",
        "legende": "Carrière",
        "type_geometrie": "point",
        "distance_m": 334,
    }
