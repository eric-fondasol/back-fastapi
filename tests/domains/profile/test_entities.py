from datetime import UTC, datetime

import pytest

from app.core.errors import InvalidRequest
from app.domains.profile.entities import FavoriteAddress, MapLayerSetting, Preferences

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_only_the_preferences_sent_change():
    preferences = Preferences(locale="fr", theme="dark").revised_with({"theme": "light"})

    assert (preferences.locale, preferences.theme) == ("fr", "light")


def test_a_layer_sent_twice_is_kept_once():
    preferences = Preferences().revised_with({"mapLayers": [
        {"layerId": "fr-geologie", "visible": True, "opacity": 1},
        {"layerId": "fr-geologie", "visible": False, "opacity": 0.2},
    ]})

    assert preferences.map_layers == [MapLayerSetting("fr-geologie", True, 1.0)]


def test_null_empties_a_preference():
    preferences = Preferences(theme="dark", extra={"a": 1}).revised_with({"theme": None, "extra": None})

    assert (preferences.theme, preferences.extra) == (None, {})


@pytest.mark.parametrize(
    "changes",
    [
        {"locale": "de"},
        {"theme": "sepia"},
        {"couleur": "rouge"},
        {"mapLayers": [{"layerId": "fr-geologie", "visible": True, "opacity": 1.5}]},
        {"mapLayers": [{"layerId": "fr-geologie", "visible": True, "opacity": "1"}]},
        {"mapLayers": [{"layerId": "fr-geologie", "visible": True, "opacity": True}]},
        {"mapLayers": [{"layerId": "fr-geologie", "opacity": 1}]},
        {"mapLayers": [{"layerId": "../x", "visible": True, "opacity": 1}]},
        {"mapLayers": {"a": []}},
        {"mapLayers": [{"layerId": f"couche-{index}", "visible": True, "opacity": 1} for index in range(101)]},
        {"extra": [1, 2]},
        {"mapStyle": "a" * 101},
    ],
    ids=[
        "unknown locale",
        "unknown theme",
        "unknown preference",
        "opacity out of bounds",
        "opacity as text",
        "opacity as boolean",
        "visibility missing",
        "invalid layer identifier",
        "layers as an object",
        "too many layers",
        "extra as a list",
        "style too long",
    ],
)
def test_an_invalid_value_is_refused(changes):
    with pytest.raises(InvalidRequest):
        Preferences().revised_with(changes)


def test_an_unknown_preference_is_named_in_the_message():
    with pytest.raises(InvalidRequest, match="Preference inconnue : couleur, taille."):
        Preferences().revised_with({"couleur": "rouge", "taille": 1})


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"label": "Paris", "longitude": 2, "latitude": 48}, "externalId est requis."),
        ({"externalId": "a", "label": "  ", "longitude": 2, "latitude": 48}, "label est requis."),
        ({"externalId": "a", "label": "Paris", "longitude": "2", "latitude": 48}, "longitude et latitude sont requises."),
        ({"externalId": "a", "label": "Paris", "longitude": True, "latitude": 48}, "longitude et latitude sont requises."),
        ({"externalId": "a", "label": "Paris", "longitude": 181, "latitude": 48}, "Longitude hors bornes : 181.000000"),
        ({"externalId": "a", "label": "Paris", "longitude": 2, "latitude": -91}, "Latitude hors bornes : -91.000000"),
        ({"externalId": "a", "label": "Paris", "longitude": 2, "latitude": 48, "name": "n" * 501}, "name doit etre un texte de 500 caracteres au plus."),
    ],
)
def test_an_invalid_favorite_address_is_refused(raw, message):
    with pytest.raises(InvalidRequest) as refusal:
        FavoriteAddress.of("id", raw, NOW)

    assert str(refusal.value) == message


def test_a_favorite_address_is_rendered_in_the_api_format():
    raw = {"externalId": "a", "label": "Paris", "longitude": 2, "latitude": 48.5}

    assert FavoriteAddress.of("id", raw, NOW).to_json() == {
        "id": "id",
        "externalId": "a",
        "label": "Paris",
        "name": None,
        "context": None,
        "kind": None,
        "longitude": 2.0,
        "latitude": 48.5,
        "createdAt": "2026-10-14T12:00:00+00:00",
    }
