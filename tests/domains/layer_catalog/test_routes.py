import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import current_user
from app.main import app

ROUTE = "/layer-catalog"
MIGRATION = Path(__file__).parents[3] / "migrations" / "versions" / "0007_layer_catalog.py"


def migration():
    spec = importlib.util.spec_from_file_location("layer_catalog_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(refonte_database):
    app.dependency_overrides[current_user] = lambda: "test@fondasol.fr"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def add_category(engine, code, position, label_en=None):
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO layer_categories (code, label_fr, label_en, position) VALUES (:code, :label, :label_en, :position)"),
            {"code": code, "label": code.capitalize(), "label_en": label_en, "position": position},
        )


def add_layer(engine, code, category, position, **columns):
    values = {"country": "fr", "kind": "wms", "url": "https://example.test/wms", "params": '{"layers": "A"}', "enabled": True, "renderer": None, **columns}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO catalog_layers (code, category_id, country, label_fr, kind, url, params, attribution, position, enabled, renderer)
                SELECT :code, id, :country, :code, :kind, :url, CAST(:params AS jsonb), '© Test', :position, :enabled, :renderer
                FROM layer_categories WHERE code = :category
                """
            ),
            {"code": code, "category": category, "position": position, **values},
        )


def test_the_migration_seeds_the_six_layers_once_held_by_the_front(client, refonte_database):
    with refonte_database.begin() as connection:
        migration().seed(connection)

    catalog = client.get(ROUTE).json()

    assert catalog["categories"] == [
        {"code": "geologie", "label": {"fr": "Géologie", "en": "Geology"}},
        {"code": "cadastre", "label": {"fr": "Cadastre et foncier", "en": "Cadastre and land"}},
    ]
    assert [(layer["code"], layer["category"], layer["country"]) for layer in catalog["layers"]] == [
        ("fr-geologie", "geologie", "fr"),
        ("lu-geologie", "geologie", "lu"),
        ("ca-cadastre-lots", "cadastre", "ca"),
        ("fr-cadastre", "cadastre", "fr"),
        ("ca-cptaq-demandes", "cadastre", "ca"),
        ("fr-cadastre-etalab", "cadastre", "fr"),
    ]
    by_code = {layer["code"]: layer for layer in catalog["layers"]}
    assert by_code["fr-cadastre"] == {
        "code": "fr-cadastre",
        "category": "cadastre",
        "country": "fr",
        "label": {"fr": "Cadastre (IGN)", "en": "Cadastre (IGN)"},
        "description": {
            "fr": "Parcellaire Express (PCI) de l'IGN, Géoplateforme. Limites de communes dès le zoom 12, parcelles à partir du zoom 15.",
            "en": "IGN Parcellaire Express (PCI), Géoplateforme. Municipal boundaries from zoom 12, parcels from zoom 15.",
        },
        "kind": "wmts",
        "url": "https://data.geopf.fr/wmts",
        "params": {"layer": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS", "style": "PCI vecteur", "tileMatrixSet": "PM_0_19"},
        "attribution": "© IGN",
        "legendUrl": "https://data.geopf.fr/annexes/ressources/legendes/CADASTRALPARCELS.PARCELLAIRE_EXPRESS-legend.png",
        "minZoom": 12.0,
        "maxZoom": 19.0,
        "renderer": None,
    }
    assert (by_code["fr-cadastre-etalab"]["kind"], by_code["fr-cadastre-etalab"]["renderer"]) == ("vector", "cadastre")
    assert by_code["ca-cadastre-lots"]["params"] == {"tileSize": 512, "fullScaleZoom": 15}
    assert by_code["ca-cadastre-lots"]["renderer"] == "quebecLots"


def test_the_seed_can_run_twice_without_duplicates(client, refonte_database):
    with refonte_database.begin() as connection:
        migration().seed(connection)
        migration().seed(connection)

    assert len(client.get(ROUTE).json()["layers"]) == 6


def test_layers_are_ordered_by_category_then_position_and_disabled_ones_are_hidden(client, refonte_database):
    add_category(refonte_database, "risques", 2)
    add_category(refonte_database, "geologie", 1, label_en="Geology")
    add_layer(refonte_database, "fr-argiles", "risques", 1)
    add_layer(refonte_database, "fr-geologie-2", "geologie", 2)
    add_layer(refonte_database, "fr-geologie-1", "geologie", 1)
    add_layer(refonte_database, "fr-ancienne", "geologie", 3, enabled=False)

    catalog = client.get(ROUTE).json()

    assert [category["code"] for category in catalog["categories"]] == ["geologie", "risques"]
    assert catalog["categories"][1]["label"] == {"fr": "Risques", "en": None}
    assert [layer["code"] for layer in catalog["layers"]] == ["fr-geologie-1", "fr-geologie-2", "fr-argiles"]
    assert catalog["layers"][0]["description"] is None


@pytest.mark.parametrize(
    "columns",
    [
        {"kind": "vector"},
        {"kind": "wms", "renderer": "cadastre"},
        {"kind": "file"},
        {"url": "http://example.test/wms"},
        {"country": "FRA"},
    ],
)
def test_the_database_refuses_an_inconsistent_layer(client, refonte_database, columns):
    add_category(refonte_database, "geologie", 1)

    with pytest.raises(Exception):
        add_layer(refonte_database, "fr-incoherente", "geologie", 1, **columns)


def test_a_request_without_token_is_refused(client):
    app.dependency_overrides.clear()

    assert client.get(ROUTE).status_code == 401


FRANCE_MIGRATION = Path(__file__).parents[3] / "migrations" / "versions" / "0008_layer_catalog_france.py"


def france_migration():
    spec = importlib.util.spec_from_file_location("layer_catalog_france_migration", FRANCE_MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_both(engine):
    with engine.begin() as connection:
        migration().seed(connection)
        france_migration().seed(connection)


def test_the_france_migration_adds_its_layers_after_the_existing_ones(client, refonte_database):
    seed_both(refonte_database)

    catalog = client.get(ROUTE).json()

    assert [category["code"] for category in catalog["categories"]] == [
        "geologie",
        "cadastre",
        "topographie",
        "eau-surface",
        "eau-souterraine",
        "geothermie",
        "environnement",
    ]
    assert len(catalog["layers"]) == 6 + 32
    geologie = [layer["code"] for layer in catalog["layers"] if layer["category"] == "geologie"]
    assert geologie == [
        "fr-geologie",
        "lu-geologie",
        "fr-brgm-bss-tous-ouvrages",
        "fr-brgm-carte-geol-50k-imprimee",
        "fr-brgm-carte-geol-50k-harmonisee",
    ]
    by_code = {layer["code"]: layer for layer in catalog["layers"]}
    assert by_code["fr-brgm-carte-geol-50k-imprimee"]["params"] == {"layers": "SCAN_GEOL50", "format": "image/png", "version": "1.1.1"}
    assert by_code["fr-brgm-carte-geol-50k-imprimee"]["legendUrl"] == (
        "https://mapsref.brgm.fr/wxs/referentiel/geologie?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetLegendGraphic"
        "&FORMAT=image/png&LAYER=SCAN_GEOL50&SLD_VERSION=1.1.0"
    )
    assert by_code["fr-ign-carte-etat-major-40k"]["params"] == {
        "layer": "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40",
        "style": "normal",
        "tileMatrixSet": "PM_6_15",
        "format": "image/jpeg",
    }
    assert (by_code["fr-ign-carte-etat-major-40k"]["minZoom"], by_code["fr-ign-carte-etat-major-40k"]["maxZoom"]) == (6.0, 15.0)
    assert by_code["fr-brgm-gmi-ouvert-50-100"]["description"] == {
        "fr": "Zonage réglementaire GMI, nappe 50-100 m.",
        "en": "Minor geothermal regulatory zoning, open loop 50-100 m.",
    }


def test_the_france_migration_only_adds_layers_the_front_can_display(client, refonte_database):
    seed_both(refonte_database)

    added = [layer for layer in client.get(ROUTE).json()["layers"] if layer["code"] in {l["code"] for l in france_migration().LAYERS}]

    assert len(added) == 32
    assert {layer["kind"] for layer in added} == {"wms", "wmts"}
    assert all(layer["country"] == "fr" and layer["renderer"] is None for layer in added)
    assert all("apikey" not in layer["params"] and "/private/" not in layer["url"] for layer in added)
    assert all(layer["params"].get("layers") or layer["params"].get("layer") for layer in added)


def test_the_france_seed_can_run_twice_without_duplicates(client, refonte_database):
    seed_both(refonte_database)
    with refonte_database.begin() as connection:
        france_migration().seed(connection)

    assert len(client.get(ROUTE).json()["layers"]) == 38
