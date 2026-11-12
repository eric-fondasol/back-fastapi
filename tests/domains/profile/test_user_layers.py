import pytest
from sqlalchemy import text

from tests.domains.profile.test_routes import OTHER, SPIKE, call, client, count  # noqa: F401

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
FILE = {"name": "Emprise du chantier", "kind": "file", "originalName": "emprise.kml"}


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


def import_file(client, body=FILE, features=None, identity=SPIKE):
    layer = call(client, "POST", "/me/layers", body, identity=identity).json()
    call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": features or [POINT, {**ZONE, "style": "rouge"}]}, identity=identity)
    return call(client, "POST", f"/me/layers/{layer['id']}/complete", identity=identity).json()


def test_a_file_layer_is_created_empty_receives_its_features_in_batches_then_is_completed(client, refonte_database):
    created = call(client, "POST", "/me/layers", FILE)

    assert created.status_code == 201
    layer = created.json()
    assert (layer["kind"], layer["bounds"], layer["featureCount"]) == ("file", None, 0)
    assert call(client, "GET", "/me/layers").json() == []

    assert call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [POINT]}).status_code == 204
    assert call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [{**ZONE, "style": "rouge"}]}).status_code == 204
    completed = call(client, "POST", f"/me/layers/{layer['id']}/complete")

    assert completed.status_code == 200
    assert {key: completed.json()[key] for key in ["name", "originalName", "fields", "featureCount"]} == {
        "name": "Emprise du chantier",
        "originalName": "emprise.kml",
        "fields": ["nom"],
        "featureCount": 2,
    }
    assert completed.json()["bounds"] == pytest.approx([2.3, 48.8, 2.4, 48.9])
    assert call(client, "GET", "/me/layers").json()[0]["featureCount"] == 2
    assert call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [POINT]}).status_code == 409
    assert call(client, "POST", f"/me/layers/{layer['id']}/complete").status_code == 409


def test_serves_the_features_of_a_file_layer_as_mapbox_vector_tiles(client, refonte_database):
    layer = import_file(client)

    tile = call(client, "GET", f"/me/layers/{layer['id']}/tiles/0/0/0")
    with refonte_database.connect() as connection:
        decoded = connection.execute(
            text("SELECT count(*) FROM user_layer_features WHERE layer_id = :id"), {"id": layer["id"]}
        ).scalar_one()

    assert tile.status_code == 200
    assert tile.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert tile.headers["cache-control"] == "private, max-age=86400"
    assert b"features" in tile.content and b"nom" in tile.content and b"SC1" in tile.content
    assert decoded == 2

    far = call(client, "GET", f"/me/layers/{layer['id']}/tiles/10/0/0")
    assert (far.status_code, far.content) == (200, b"")


def test_the_tiles_and_batches_of_a_layer_belong_to_its_owner_only(client, refonte_database):
    layer = import_file(client)
    unfinished = call(client, "POST", "/me/layers", FILE).json()
    stream = call(client, "POST", "/me/layers", WMS).json()

    assert call(client, "GET", f"/me/layers/{layer['id']}/tiles/0/0/0", identity=OTHER).status_code == 404
    assert call(client, "GET", f"/me/layers/{unfinished['id']}/tiles/0/0/0").status_code == 404
    assert call(client, "GET", f"/me/layers/{stream['id']}/tiles/0/0/0").status_code == 404
    assert call(client, "GET", f"/me/layers/{layer['id']}/tiles/1/2/0").status_code == 404
    assert call(client, "GET", "/me/layers/pas-un-uuid/tiles/0/0/0").status_code == 404
    assert call(client, "POST", f"/me/layers/{unfinished['id']}/features", {"features": [POINT]}, identity=OTHER).status_code == 404
    assert call(client, "POST", f"/me/layers/{stream['id']}/features", {"features": [POINT]}).status_code == 404


def test_removing_a_file_layer_removes_its_features(client, refonte_database):
    layer = import_file(client)

    call(client, "DELETE", f"/me/layers/{layer['id']}")

    assert count(refonte_database, "user_layer_features") == 0


def test_an_unfinished_import_is_removed_after_a_day_when_another_layer_is_added(client, refonte_database):
    old = call(client, "POST", "/me/layers", FILE).json()
    recent = call(client, "POST", "/me/layers", FILE).json()
    with refonte_database.begin() as connection:
        connection.execute(text("UPDATE user_layers SET created_at = now() - interval '25 hours' WHERE id = :id"), {"id": old["id"]})

    call(client, "POST", "/me/layers", WMS)

    with refonte_database.connect() as connection:
        kept = set(connection.execute(text("SELECT id::text FROM user_layers WHERE kind = 'file'")).scalars())
    assert kept == {recent["id"]}


def test_refuses_to_complete_a_layer_without_features(client, refonte_database):
    layer = call(client, "POST", "/me/layers", FILE).json()

    response = call(client, "POST", f"/me/layers/{layer['id']}/complete")

    assert (response.status_code, response.json()) == (422, {"errors": "La couche n'a recu aucun objet."})


def test_refuses_more_than_the_maximum_number_of_features(client, refonte_database, monkeypatch):
    monkeypatch.setattr("app.domains.profile.services.MAX_LAYER_FEATURES", 2)
    layer = call(client, "POST", "/me/layers", FILE).json()
    call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [POINT, POINT]})

    response = call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [POINT]})

    assert (response.status_code, response.json()) == (422, {"errors": "2 objets au plus par couche."})


def test_keeps_the_part_of_a_feature_within_the_latitudes_of_web_mercator(client, refonte_database):
    polar = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 89.9]}, "properties": {}}
    layer = call(client, "POST", "/me/layers", FILE).json()

    assert call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [POINT, polar]}).status_code == 204
    assert count(refonte_database, "user_layer_features") == 1


def test_keeps_the_features_of_a_kml_with_altitudes_in_two_dimensions(client, refonte_database):
    with_altitude = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.35, 48.85, 35.2]}, "properties": {}}
    layer = call(client, "POST", "/me/layers", FILE).json()

    assert call(client, "POST", f"/me/layers/{layer['id']}/features", {"features": [with_altitude]}).status_code == 204
    with refonte_database.connect() as connection:
        assert connection.execute(text("SELECT ST_NDims(geometry) FROM user_layer_features")).scalar_one() == 2


LAMBERT_93 = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [652000, 6862000]}, "properties": {}}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"features": {"type": "Feature"}}, "features doit etre une liste de 1 a 5000 objets."),
        ({"features": []}, "features doit etre une liste de 1 a 5000 objets."),
        ({"features": [LAMBERT_93]}, "features[0] a des coordonnees hors WGS 84 (longitude, latitude en degres)."),
        (
            {"features": [{**POINT, "geometry": {"type": "GeometryCollection", "geometries": []}}]},
            "features[0].geometry doit valoir Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon.",
        ),
        (
            {"features": [{**POINT, "geometry": {"type": "Point", "coordinates": ["2", "48"]}}]},
            "features[0] a des coordonnees hors WGS 84 (longitude, latitude en degres).",
        ),
        ({"features": [{**POINT, "properties": [1]}]}, "features[0].properties doit etre un objet."),
    ],
)
def test_refuses_an_invalid_batch(client, refonte_database, body, message):
    layer = call(client, "POST", "/me/layers", FILE).json()

    response = call(client, "POST", f"/me/layers/{layer['id']}/features", body)

    assert (response.status_code, response.json()) == (400, {"errors": message})
    assert count(refonte_database, "user_layer_features") == 0


def test_refuses_a_file_layer_without_its_original_name(client, refonte_database):
    response = call(client, "POST", "/me/layers", {**FILE, "originalName": " "})

    assert (response.status_code, response.json()) == (400, {"errors": "originalName doit etre un texte de 1 a 255 caracteres."})


def test_the_database_refuses_a_file_with_an_url(refonte_database):
    with pytest.raises(Exception, match="user_layers_source"):
        with refonte_database.begin() as connection:
            connection.execute(text("INSERT INTO users (id, email, created_at) VALUES ('6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'a@b.c', now())"))
            connection.execute(
                text(
                    "INSERT INTO user_layers (id, user_id, name, kind, url, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), '6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a', 'x', 'file', 'https://a.b', now(), now())"
                )
            )


def test_changes_the_style_of_a_file_layer_without_touching_its_name(client, refonte_database):
    layer = import_file(client)
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
