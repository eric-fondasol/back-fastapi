import pytest
from sqlalchemy import text

from tests.domains.profile.test_routes import OTHER, call, client, count  # noqa: F401

WMS = {
    "name": "  Géologie BRGM  ",
    "kind": "wms",
    "url": "https://geoservices.brgm.fr/geologie",
    "params": {"layers": "GEOLOGIE", "format": "image/png", "version": "1.3.0", "attribution": "© BRGM"},
}
WMTS = {
    "name": "Plan IGN",
    "kind": "wmts",
    "url": "https://data.geopf.fr/wmts",
    "params": {"layer": "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "style": "normal", "tileMatrixSet": "PM"},
}
XYZ = {"name": "OSM", "kind": "xyz", "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}
POINT = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.35, 48.85]}, "properties": {"nom": "SC1"}}
ZONE = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[2.3, 48.8], [2.4, 48.8], [2.4, 48.9], [2.3, 48.8]]]},
    "properties": None,
}
FILE = {
    "name": "Emprise du chantier",
    "kind": "file",
    "originalName": "emprise.kml",
    "geojson": {"type": "FeatureCollection", "crs": {"type": "name"}, "features": [POINT, {**ZONE, "style": "rouge"}]},
}


def test_adds_lists_renames_and_removes_a_stream(client, refonte_database):
    created = call(client, "POST", "/me/layers", WMS)

    assert created.status_code == 201
    layer = created.json()
    assert layer["name"] == "Géologie BRGM"
    assert layer["layerId"] == f"user:{layer['id']}"
    assert layer["params"] == {"layers": "GEOLOGIE", "format": "image/png", "version": "1.3.0", "attribution": "© BRGM"}

    assert call(client, "POST", "/me/layers", WMTS).status_code == 201
    assert call(client, "POST", "/me/layers", XYZ).status_code == 201
    assert [item["name"] for item in call(client, "GET", "/me/layers").json()] == ["Géologie BRGM", "OSM", "Plan IGN"]

    renamed = call(client, "PATCH", f"/me/layers/{layer['id']}", {"name": "Carte géologique"})
    assert (renamed.status_code, renamed.json()["name"]) == (200, "Carte géologique")

    assert call(client, "DELETE", f"/me/layers/{layer['id']}").status_code == 204
    assert [item["name"] for item in call(client, "GET", "/me/layers").json()] == ["OSM", "Plan IGN"]


def test_removing_a_layer_also_removes_it_from_favorites_and_my_layers(client, refonte_database):
    layer = call(client, "POST", "/me/layers", WMS).json()
    kept = {"layerId": "fr-cadastre", "visible": True, "opacity": 1}
    call(client, "PATCH", "/me/preferences", {"mapLayers": [{"layerId": layer["layerId"], "visible": True, "opacity": 0.5}, kept]})
    call(client, "PUT", f"/me/favorites/layers/{layer['layerId']}")
    call(client, "PUT", "/me/favorites/layers/fr-cadastre")

    call(client, "DELETE", f"/me/layers/{layer['id']}")

    assert call(client, "GET", "/me/favorites").json()["layers"] == ["fr-cadastre"]
    assert call(client, "GET", "/me/preferences").json()["mapLayers"] == [{"layerId": "fr-cadastre", "visible": True, "opacity": 1.0}]


def test_a_layer_belongs_to_its_owner_only(client, refonte_database):
    layer = call(client, "POST", "/me/layers", WMS).json()

    assert call(client, "GET", "/me/layers", identity=OTHER).json() == []
    assert call(client, "PATCH", f"/me/layers/{layer['id']}", {"name": "Volée"}, identity=OTHER).status_code == 404
    assert call(client, "DELETE", f"/me/layers/{layer['id']}", identity=OTHER).status_code == 404
    assert count(refonte_database, "user_layers") == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({**WMS, "kind": "shapefile"}, "kind doit valoir wms, wmts, xyz, file."),
        ({**WMS, "url": "http://geoservices.brgm.fr/geologie"}, "url doit etre une adresse https."),
        ({**WMS, "url": "javascript:alert(1)"}, "url doit etre une adresse https."),
        ({**XYZ, "url": "https://tile.openstreetmap.org/{z}/{x}.png"}, "url d'un flux XYZ doit contenir {z}, {x} et {y}."),
        ({**XYZ, "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png."}, "url ne doit pas se terminer par un signe de ponctuation."),
        ({**WMS, "name": "   "}, "name doit etre un texte de 1 a 100 caracteres."),
        ({**WMS, "params": {"format": "image/png"}}, "params.layers est requis."),
        ({**WMS, "params": {"layers": "A", "version": "2.0"}}, "params.version doit valoir 1.3.0, 1.1.1."),
        ({**WMS, "params": {"layers": "A", "script": "x"}}, "Parametre inconnu : script."),
        ({**WMTS, "params": {"layer": "A", "style": "normal"}}, "params.tileMatrixSet est requis."),
    ],
)
def test_refuses_an_invalid_stream(client, refonte_database, body, message):
    response = call(client, "POST", "/me/layers", body)

    assert (response.status_code, response.json()) == (400, {"errors": message})
    assert count(refonte_database, "user_layers") == 0


def test_refuses_more_than_fifty_layers(client, refonte_database):
    for index in range(50):
        assert call(client, "POST", "/me/layers", {**XYZ, "name": f"OSM {index}"}).status_code == 201

    refused = call(client, "POST", "/me/layers", XYZ)

    assert (refused.status_code, refused.json()) == (422, {"errors": "50 couches au plus."})


def test_unknown_or_malformed_layer_ids_answer_404(client, refonte_database):
    assert call(client, "DELETE", "/me/layers/pas-un-uuid").status_code == 404
    assert call(client, "PATCH", "/me/layers/7a2d3b4f-1c2e-4d66-8b88-2a3f4e5d6c7b", {"name": "x"}).status_code == 404


def test_the_database_refuses_a_stream_without_url(refonte_database):
    with pytest.raises(Exception, match="user_layers_source"):
        with refonte_database.begin() as connection:
            connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'a@b.c', now())"))
            connection.execute(
                text(
                    "INSERT INTO user_layers (id, user_id, name, kind, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), '6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'x', 'wms', now(), now())"
                )
            )


def test_adds_a_file_layer_whose_geojson_is_read_apart(client, refonte_database):
    created = call(client, "POST", "/me/layers", FILE)

    assert created.status_code == 201
    layer = created.json()
    assert {key: layer[key] for key in ["name", "kind", "originalName", "bounds"]} == {
        "name": "Emprise du chantier",
        "kind": "file",
        "originalName": "emprise.kml",
        "bounds": [2.3, 48.8, 2.4, 48.9],
    }
    assert "geojson" not in layer
    assert [item["kind"] for item in call(client, "GET", "/me/layers").json()] == ["file"]

    geojson = call(client, "GET", f"/me/layers/{layer['id']}/geojson")
    assert (geojson.status_code, geojson.json()) == (
        200,
        {"type": "FeatureCollection", "features": [POINT, {**ZONE, "properties": {}}]},
    )


def test_the_geojson_of_a_layer_is_read_by_its_owner_only(client, refonte_database):
    layer = call(client, "POST", "/me/layers", FILE).json()
    stream = call(client, "POST", "/me/layers", WMS).json()

    assert call(client, "GET", f"/me/layers/{layer['id']}/geojson", identity=OTHER).status_code == 404
    assert call(client, "GET", f"/me/layers/{stream['id']}/geojson").status_code == 404
    assert call(client, "GET", "/me/layers/pas-un-uuid/geojson").status_code == 404


LAMBERT_93 = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [652000, 6862000]}, "properties": {}}


@pytest.mark.parametrize(
    ("geojson", "message"),
    [
        ({"type": "Feature", "geometry": POINT["geometry"]}, "geojson doit etre une FeatureCollection."),
        ({"type": "FeatureCollection", "features": []}, "geojson doit contenir de 1 a 50000 objets."),
        (
            {"type": "FeatureCollection", "features": [LAMBERT_93]},
            "geojson.features[0] a des coordonnees hors WGS 84 (longitude, latitude en degres).",
        ),
        (
            {"type": "FeatureCollection", "features": [{**POINT, "geometry": {"type": "GeometryCollection", "geometries": []}}]},
            "geojson.features[0].geometry doit valoir Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon.",
        ),
        (
            {"type": "FeatureCollection", "features": [{**POINT, "geometry": {"type": "Point", "coordinates": ["2", "48"]}}]},
            "geojson.features[0] a des coordonnees hors WGS 84 (longitude, latitude en degres).",
        ),
        ({"type": "FeatureCollection", "features": [{**POINT, "properties": [1]}]}, "geojson.features[0].properties doit etre un objet."),
    ],
)
def test_refuses_an_invalid_geojson(client, refonte_database, geojson, message):
    response = call(client, "POST", "/me/layers", {**FILE, "geojson": geojson})

    assert (response.status_code, response.json()) == (400, {"errors": message})
    assert count(refonte_database, "user_layers") == 0


def test_refuses_a_file_layer_without_its_original_name(client, refonte_database):
    response = call(client, "POST", "/me/layers", {**FILE, "originalName": " "})

    assert (response.status_code, response.json()) == (400, {"errors": "originalName doit etre un texte de 1 a 255 caracteres."})


def test_the_database_refuses_a_file_without_geojson(refonte_database):
    with pytest.raises(Exception, match="user_layers_source"):
        with refonte_database.begin() as connection:
            connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'a@b.c', now())"))
            connection.execute(
                text(
                    "INSERT INTO user_layers (id, user_id, name, kind, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), '6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'x', 'file', now(), now())"
                )
            )


def test_changes_the_style_of_a_file_layer_without_touching_its_name(client, refonte_database):
    layer = call(client, "POST", "/me/layers", FILE).json()
    assert layer["style"] == {}

    style = {"color": "#1F9A48", "lineWidth": 3.5, "pointRadius": 8, "labelField": "nom"}
    revised = call(client, "PATCH", f"/me/layers/{layer['id']}", {"style": style})

    assert revised.status_code == 200
    assert (revised.json()["name"], revised.json()["style"]) == ("Emprise du chantier", {**style, "color": "#1f9a48"})
    assert call(client, "GET", "/me/layers").json()[0]["style"] == {**style, "color": "#1f9a48"}

    renamed = call(client, "PATCH", f"/me/layers/{layer['id']}", {"name": "Emprise"}).json()
    assert (renamed["name"], renamed["style"]["pointRadius"]) == ("Emprise", 8)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "name ou style est requis."),
        ({"style": "rouge"}, "style doit etre un objet."),
        ({"style": {"color": "red"}}, "style.color doit etre une couleur #rrggbb."),
        ({"style": {"lineWidth": 50}}, "style.lineWidth doit etre un nombre de 0.5 a 10."),
        ({"style": {"pointRadius": True}}, "style.pointRadius doit etre un nombre de 1 a 20."),
        ({"style": {"labelField": ""}}, "style.labelField doit etre un texte de 1 a 100 caracteres, ou null."),
        ({"style": {"opacity": 1}}, "Reglage de style inconnu : opacity."),
    ],
)
def test_refuses_an_invalid_style(client, refonte_database, body, message):
    layer = call(client, "POST", "/me/layers", FILE).json()

    response = call(client, "PATCH", f"/me/layers/{layer['id']}", body)

    assert (response.status_code, response.json()) == (400, {"errors": message})
