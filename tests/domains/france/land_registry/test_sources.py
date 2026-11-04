import pytest

from app.domains.france.land_registry import sources
from app.domains.france.land_registry.schemas import ParcelSearch


def reference(code_insee, section="AB", parcelle="0004", com_abs="000"):
    return ParcelSearch(code_insee=code_insee, section=section, parcelle=parcelle, com_abs=com_abs).reference()


def test_an_ordinary_municipality_is_sent_as_is():
    assert sources.api_carto_params(reference("84129")) == {"code_insee": "84129", "section": "AB", "numero": "0004", "com_abs": "000"}


@pytest.mark.parametrize(
    ("district", "municipality", "code_arr"),
    [("75105", "75056", "105"), ("75120", "75056", "120"), ("69382", "69123", "382"), ("13202", "13055", "202")],
)
def test_a_district_of_paris_lyon_or_marseille_is_sent_as_its_municipality_with_the_district_apart(district, municipality, code_arr):
    params = sources.api_carto_params(reference(district, section="BM", parcelle="3"))

    assert params == {"code_insee": municipality, "code_arr": code_arr, "section": "BM", "numero": "0003", "com_abs": "000"}


@pytest.mark.parametrize("code_insee", ["75100", "75121", "69380", "13217", "2A004", "75056"])
def test_codes_outside_the_districts_are_left_alone(code_insee):
    assert "code_arr" not in sources.api_carto_params(reference(code_insee))


def test_the_land_registry_is_queried_with_these_parameters(monkeypatch):
    calls = []

    class Answer:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": [{"id": "trouvée"}]}

    monkeypatch.setattr(sources.httpx, "get", lambda url, params, timeout: calls.append(params) or Answer())

    assert sources.parcel_features(reference("75105", section="BM", parcelle="3")) == [{"id": "trouvée"}]
    assert calls[0]["code_insee"] == "75056" and calls[0]["code_arr"] == "105"
