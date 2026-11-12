import json

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

ALEMBIC = AlembicConfig("alembic.ini")
USER = "6f1c2a3e-0b1d-4c55-9a77-1f2e3d4c5b6a"
LAYER = "0b8a4c2e-5d1f-4a3b-9c7d-2e6f8a0b1c3d"
GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.35, 48.85, 35.2]}, "properties": {"nom": "SC1", "prof": 12}},
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[2.3, 48.8], [2.4, 48.8], [2.4, 48.9], [2.3, 48.8]]]},
            "properties": {"fill": "#ffcc00", "liste": [1]},
        },
    ],
}


def add_file_layer(database):
    with database.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, created_at) VALUES (:id, 'a@b.c', now())"), {"id": USER})
        connection.execute(
            text(
                "INSERT INTO user_layers (id, user_id, name, kind, original_name, geojson, created_at, updated_at) "
                "VALUES (:id, :user, 'Emprise', 'file', 'emprise.kml', CAST(:geojson AS jsonb), now(), now())"
            ),
            {"id": LAYER, "user": USER, "geojson": json.dumps(GEOJSON)},
        )


def test_copies_the_geojson_of_existing_file_layers_into_postgis(schema_at):
    database = schema_at("0042")
    add_file_layer(database)

    command.upgrade(ALEMBIC, "0043")

    with database.connect() as connection:
        layer = connection.execute(text("SELECT bounds, fields, feature_count, imported_at IS NOT NULL FROM user_layers")).one()
        features = connection.execute(
            text("SELECT GeometryType(geometry), ST_SRID(geometry), properties FROM user_layer_features ORDER BY id")
        ).all()
        columns = set(connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user_layers'")).scalars())

    assert [round(value, 6) for value in layer[0]] == [2.3, 48.8, 2.4, 48.9]
    assert layer[1:] == (["fill", "nom", "prof"], 2, True)
    assert [(kind, srid) for kind, srid, _ in features] == [("POINT", 3857), ("POLYGON", 3857)]
    assert features[0][2] == {"nom": "SC1", "prof": 12}
    assert "geojson" not in columns


def test_downgrade_rebuilds_the_geojson_from_the_features(schema_at):
    database = schema_at("0042")
    add_file_layer(database)
    command.upgrade(ALEMBIC, "0043")

    command.downgrade(ALEMBIC, "0042")

    with database.connect() as connection:
        geojson = connection.execute(text("SELECT geojson FROM user_layers")).scalar_one()
    assert [feature["properties"] for feature in geojson["features"]] == [feature["properties"] for feature in GEOJSON["features"]]
    assert geojson["features"][0]["geometry"] == {"type": "Point", "coordinates": [2.35, 48.85]}
