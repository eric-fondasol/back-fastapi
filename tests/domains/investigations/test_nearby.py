from tests.domains.investigations.test_routes import client, create, send  # noqa: F401


def at(longitude, latitude):
    return f'{{"coordinates":{{"lng":{longitude},"lat":{latitude}}}}}'


def nearby(client, longitude=2.3522, latitude=48.8566):
    return send(client, "GET", f"/investigations/nearby?longitude={longitude}&latitude={latitude}")


def test_lists_the_investigations_within_200_m_nearest_first(client):
    create(client, {"projectRef": "PR.75GT.26.0001", "name": "Châtelet", "data": at(2.3532, 48.8566)})
    create(client, {"projectRef": "PR.75GT.26.0002", "data": at(2.3522, 48.8567)})
    create(client, {"projectRef": "PR.75GT.26.0003", "data": at(2.3522, 48.8600)})
    create(client, {"projectRef": "PR.75GT.26.0004", "data": '{"coordinates":null}'})

    found = nearby(client)

    assert [(item["projectRef"], item["name"], item["distance"]) for item in found] == [
        ("PR.75GT.26.0002", None, 11),
        ("PR.75GT.26.0001", "Châtelet", 73),
    ]
    assert all(len(item["uuid"]) == 36 for item in found)


def test_finds_nothing_far_from_any_investigation(client):
    create(client, {"projectRef": "PR.75GT.26.0001", "data": at(2.3522, 48.8566)})

    assert nearby(client, longitude=4.8357, latitude=45.7640) == []


def test_refuses_a_missing_position(client):
    send(client, "GET", "/investigations/nearby?longitude=2.35", expected=400)
