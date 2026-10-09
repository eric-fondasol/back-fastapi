import pytest

from app.domains.france.land_registry.schemas import ParcelSearch
from app.domains.france.land_registry.services import geodesic_area_m2, to_parcel

SORGUES_AB_0004 = {
    "type": "Feature",
    "geometry": {
        "type": "MultiPolygon",
        "coordinates": [[[[4.85121667, 44.03656517], [4.85332212, 44.03673597], [4.8533611, 44.03649188], [4.85135722, 44.03629758], [4.85121667, 44.03656517]]]],
    },
    "properties": {
        "gid": 55805902,
        "numero": "0004",
        "feuille": 1,
        "section": "AB",
        "code_dep": "84",
        "nom_com": "Sorgues",
        "code_com": "129",
        "com_abs": "000",
        "code_arr": "000",
        "idu": "84129000AB0004",
        "contenance": 5070,
        "code_insee": "84129",
    },
}


def test_a_search_completes_the_parcel_reference_with_leading_zeros():
    reference = ParcelSearch(code_insee="2a004", section="a", parcelle="11", com_abs="0").reference()

    assert reference.idu == "2A0040000A0011"


def test_a_square_of_one_hundredth_of_a_degree_at_the_equator_measures_about_1_24_km2_on_the_sphere():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]}

    assert geodesic_area_m2(square) == pytest.approx(1_239_193, rel=1e-3)


def test_a_hole_is_removed_from_the_area():
    with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]],
            [[0.002, 0.002], [0.004, 0.002], [0.004, 0.004], [0.002, 0.004], [0.002, 0.002]],
        ],
    }

    assert geodesic_area_m2(with_hole) == pytest.approx(1_239_193 * 0.96, rel=1e-3)


def test_an_ign_feature_becomes_a_parcel_with_its_official_and_computed_areas():
    parcel = to_parcel(SORGUES_AB_0004)

    assert (parcel.idu, parcel.commune_name, parcel.section, parcel.number, parcel.sheet) == ("84129000AB0004", "Sorgues", "AB", "0004", 1)
    assert parcel.official_area_m2 == 5070
    assert 4000 < parcel.computed_area_m2 < 6000
