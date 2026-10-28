import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.domains.investigations import queries
from app.domains.investigations.entities import SurveyCounts
from tests.domains.investigations.test_routes import SPIKE, client, create, scalar, send  # noqa: F401

PARIS = {"lng": 2.3522, "lat": 48.8566}
DATA_AT_PARIS = '{"coordinates":{"lng":2.3522,"lat":48.8566}}'


def pressio(count):
    return SurveyCounts(pressiometric=count, penetrometric=0, total=count)


@pytest.fixture
def surveys(monkeypatch):
    found = {"counts": pressio(0), "calls": []}

    def around(longitude, latitude, radius_m):
        found["calls"].append((longitude, latitude, radius_m))
        return found["counts"]

    monkeypatch.setattr(queries, "reliable_surveys_around", around)
    return found


def as_agent_of(client, refonte_database, department):
    with refonte_database.begin() as connection:
        connection.execute(text("INSERT INTO business_lines (code, label_fr) VALUES ('GT', 'GT'), ('EN', 'EN') ON CONFLICT DO NOTHING"))
        connection.execute(
            text("INSERT INTO business_units (code, libelle, business_line) VALUES ('31GT', '31GT', 'GT'), ('44EN', '44EN', 'EN') ON CONFLICT DO NOTHING")
        )
    client.caller["identity"] = SPIKE
    assert client.put("/me/sign-in", json={"department": department}).status_code == 204


def offer(client, longitude=2.3522, latitude=48.8566):
    return send(client, "GET", f"/investigations/fuseau-offer?longitude={longitude}&latitude={latitude}")


@pytest.mark.parametrize(
    ("counts", "expected", "fuseau_types"),
    [
        (SurveyCounts(40, 0, 40), "A00196", ["pressiometric"]),
        (SurveyCounts(25, 0, 25), "A00196", ["pressiometric"]),
        (SurveyCounts(0, 25, 30), "A00196", ["penetrometric"]),
        (SurveyCounts(30, 26, 45), "A00196", ["pressiometric", "penetrometric"]),
        (SurveyCounts(20, 10, 30), "A00195", []),
        (SurveyCounts(24, 24, 40), "A00195", []),
        (SurveyCounts(0, 0, 5), "A00195", []),
        (SurveyCounts(0, 0, 4), None, []),
        (SurveyCounts(0, 0, 0), None, []),
    ],
)
def test_a_fuseau_needs_25_surveys_of_one_test_type_and_a_valorisation_5_surveys_of_any_type(client, surveys, counts, expected, fuseau_types):
    surveys["counts"] = counts

    answer = offer(client)

    assert (answer["offer"], answer["fuseauTypes"]) == (expected, fuseau_types)
    assert answer["surveys"] == {"pressiometric": counts.pressiometric, "penetrometric": counts.penetrometric, "total": counts.total}
    assert surveys["calls"] == [(2.3522, 48.8566, 1000)]


@pytest.mark.parametrize(
    ("department", "count", "required"),
    [("31GT", 25, True), ("31GT", 24, False), ("44EN", 40, False), ("GFIT", 40, False), (None, 40, False)],
)
def test_only_a_gt_agent_must_answer_when_a_fuseau_is_possible(client, refonte_database, surveys, department, count, required):
    as_agent_of(client, refonte_database, department)
    surveys["counts"] = pressio(count)

    assert offer(client)["answerRequired"] is required


@pytest.mark.parametrize("query", ["", "?longitude=2.35", "?longitude=abc&latitude=48", "?longitude=200&latitude=48", "?longitude=2&latitude=-91"])
def test_refuses_a_missing_or_invalid_position(client, surveys, query):
    client.caller["identity"] = SPIKE
    assert client.get(f"/investigations/fuseau-offer{query}").status_code == 400
    assert surveys["calls"] == []


def test_a_gt_agent_cannot_save_without_answer_when_a_fuseau_is_possible(client, refonte_database, surveys):
    as_agent_of(client, refonte_database, "31GT")
    surveys["counts"] = pressio(25)

    refused = send(client, "POST", "/investigations", {"projectRef": "31GT.26.0134", "data": DATA_AT_PARIS}, expected=422)

    assert "A00196" in refused["errors"]
    assert scalar(refonte_database, "SELECT count(*) FROM saved_pages") == 0
    assert surveys["calls"] == [(PARIS["lng"], PARIS["lat"], 1000)]


def test_the_answer_is_kept_with_each_version_and_asked_again_for_the_next(client, refonte_database, surveys):
    as_agent_of(client, refonte_database, "31GT")
    surveys["counts"] = pressio(30)

    created = create(client, {"projectRef": "31GT.26.0134", "data": DATA_AT_PARIS, "fuseauAnalysis": "later"})
    path = f"/investigations/{created['uuid']}"
    send(client, "POST", f"{path}/versions", {"data": DATA_AT_PARIS}, expected=422)
    send(client, "POST", f"{path}/versions", {"data": DATA_AT_PARIS, "fuseauAnalysis": "sold_a00196"}, expected=201)
    send(client, "PUT", f"{path}/versions/2", {"data": DATA_AT_PARIS}, expected=422)
    send(client, "PUT", f"{path}/versions/2", {"data": DATA_AT_PARIS, "fuseauAnalysis": "not_suitable"})

    with refonte_database.connect() as connection:
        answers = connection.execute(text("SELECT version, fuseau_analysis FROM saved_page_versions ORDER BY version")).all()
    assert answers == [(1, "later"), (2, "not_suitable")]


@pytest.mark.parametrize(
    ("department", "count", "data"),
    [
        ("44EN", 40, DATA_AT_PARIS),
        ("31GT", 24, DATA_AT_PARIS),
        ("31GT", 40, '{"coordinates":null}'),
        ("31GT", 40, "contenu sans position"),
    ],
)
def test_saves_without_answer_when_the_rule_does_not_apply(client, refonte_database, surveys, department, count, data):
    as_agent_of(client, refonte_database, department)
    surveys["counts"] = pressio(count)

    created = create(client, {"projectRef": "31GT.26.0134", "data": data})

    assert scalar(refonte_database, "SELECT fuseau_analysis FROM saved_page_versions WHERE version = 1") is None
    assert created["version"]["version"] == 1


def test_saves_without_answer_when_the_warehouse_cannot_count(client, refonte_database, monkeypatch):
    as_agent_of(client, refonte_database, "31GT")

    def unreachable(*_):
        raise OperationalError("SELECT", {}, Exception("entrepot injoignable"))

    monkeypatch.setattr(queries, "reliable_surveys_around", unreachable)

    create(client, {"projectRef": "31GT.26.0134", "data": DATA_AT_PARIS})


def test_refuses_an_unknown_answer(client, refonte_database, surveys):
    refused = send(client, "POST", "/investigations", {"projectRef": "31GT.26.0134", "data": DATA_AT_PARIS, "fuseauAnalysis": "peut-etre"}, expected=400)

    assert "fuseauAnalysis" in refused["errors"]
