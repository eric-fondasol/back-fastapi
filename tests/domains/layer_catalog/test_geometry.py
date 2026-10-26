import pytest

from app.domains.layer_catalog import geometry

SQUARE = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
HALF_PIXEL_AT_ZOOM_8 = geometry.pixel_degrees(8) / 2
WORLD = (-180.0, -90.0, 180.0, 90.0)


def near(positions):
    return [pytest.approx(position, abs=HALF_PIXEL_AT_ZOOM_8) for position in positions]


def test_close_vertices_merge_at_a_low_zoom_but_stay_apart_at_a_high_one():
    line = {"type": "LineString", "coordinates": [[2.0, 48.0], [2.0001, 48.0001], [2.5, 48.5]]}

    assert geometry.simplify(line, 8)["coordinates"] == near([[2.0, 48.0], [2.5, 48.5]])
    assert len(geometry.simplify(line, 18)["coordinates"]) == 3


def test_a_polygon_smaller_than_a_pixel_disappears_and_its_feature_is_dropped():
    tiny = {"type": "Polygon", "coordinates": [[[2.0, 48.0], [2.0, 48.00001], [2.00001, 48.00001], [2.0, 48.0]]]}
    big = {"type": "Polygon", "coordinates": [SQUARE]}

    [feature] = geometry.light_features(
        [{"geometry": tiny, "properties": {}}, {"geometry": big, "properties": {"nom": "carré"}}], WORLD, zoom=8
    )

    assert feature["properties"] == {"nom": "carré"}
    assert feature["geometry"]["coordinates"] == [near(SQUARE)]


def test_a_hole_too_small_to_see_is_removed_but_the_polygon_stays():
    hole = [[0.5, 0.5], [0.5, 0.500001], [0.500001, 0.500001], [0.5, 0.5]]

    simplified = geometry.simplify({"type": "Polygon", "coordinates": [SQUARE, hole]}, 8)

    assert simplified["coordinates"] == [near(SQUARE)]


def test_a_feature_without_geometry_is_dropped():
    assert geometry.light_features([{"geometry": None, "properties": {"nom": "x"}}], WORLD, zoom=12) == []


def test_only_plain_properties_are_kept_and_long_texts_are_cut():
    properties = {"nom": "a" * 600, "profondeur": 12.5, "actif": True, "vide": None, "codes": ["A", "B"], "lien": {"href": "x"}}

    assert geometry.plain_properties(properties) == {"nom": "a" * 500, "profondeur": 12.5, "actif": True, "vide": None}


def test_axes_are_swapped_at_every_depth():
    swapped = geometry.swap_axes({"type": "MultiPolygon", "coordinates": [[[[48.9, 1.5], [49.1, 1.7], [48.9, 1.5]]]]})

    assert swapped["coordinates"] == [[[[1.5, 48.9], [1.7, 49.1], [1.5, 48.9]]]]


def test_a_surface_is_cut_to_the_requested_extent():
    clipped = geometry.clip({"type": "Polygon", "coordinates": [SQUARE]}, (0.5, -1.0, 2.0, 0.5))

    assert sorted(map(tuple, clipped["coordinates"][0][:-1])) == [(0.5, 0.0), (0.5, 0.5), (1.0, 0.0), (1.0, 0.5)]
    assert clipped["coordinates"][0][0] == clipped["coordinates"][0][-1]


def test_a_surface_outside_the_extent_is_dropped_but_points_are_kept():
    outside = {"type": "MultiPolygon", "coordinates": [[SQUARE]]}
    point = {"type": "Point", "coordinates": [5.0, 5.0]}

    assert geometry.clip(outside, (2.0, 2.0, 3.0, 3.0)) is None
    assert geometry.clip(point, (2.0, 2.0, 3.0, 3.0)) == point


def test_a_dense_curve_keeps_its_own_vertices_instead_of_stair_steps():
    step = geometry.pixel_degrees(9) / 7
    diagonal = [[2.0 + index * step, 48.0 + index * step / 2] for index in range(200)]

    kept = geometry.simplify({"type": "LineString", "coordinates": diagonal}, 9)["coordinates"]

    assert 20 < len(kept) < 60
    assert all(abs((latitude - 48.0) - (longitude - 2.0) / 2) < 1e-6 for longitude, latitude in kept)
    assert kept[0] == pytest.approx(diagonal[0]) and kept[-1] == pytest.approx(diagonal[-1])
