import pytest

from app.domains.layer_catalog import gml

GML2_POLYGON_WITH_HOLE = """<?xml version='1.0' encoding="UTF-8" ?>
<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver" xmlns:wfs="http://www.opengis.net/wfs"
    xmlns:gml="http://www.opengis.net/gml">
  <gml:featureMember>
    <ms:ZICO>
      <gml:boundedBy><gml:Box srsName="EPSG:4326"><gml:coordinates>48.9,1.5 49.1,1.7</gml:coordinates></gml:Box></gml:boundedBy>
      <ms:msGeometry>
        <gml:Polygon srsName="EPSG:4326">
          <gml:outerBoundaryIs><gml:LinearRing><gml:coordinates>48.9,1.5 49.1,1.5 49.1,1.7 48.9,1.5</gml:coordinates></gml:LinearRing></gml:outerBoundaryIs>
          <gml:innerBoundaryIs><gml:LinearRing><gml:coordinates>49.0,1.55 49.05,1.55 49.05,1.6 49.0,1.55</gml:coordinates></gml:LinearRing></gml:innerBoundaryIs>
        </gml:Polygon>
      </ms:msGeometry>
      <ms:ID_SPN>IF01</ms:ID_SPN>
      <ms:NOM>Vallée de la Seine</ms:NOM>
      <ms:URL></ms:URL>
    </ms:ZICO>
  </gml:featureMember>
</wfs:FeatureCollection>"""

GML2_MULTIPOLYGON = """<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver" xmlns:wfs="http://www.opengis.net/wfs"
    xmlns:gml="http://www.opengis.net/gml">
  <gml:featureMember><ms:RNN><ms:msGeometry><gml:MultiPolygon>
    <gml:polygonMember><gml:Polygon><gml:outerBoundaryIs><gml:LinearRing><gml:coordinates>1,1 1,2 2,2 1,1</gml:coordinates></gml:LinearRing></gml:outerBoundaryIs></gml:Polygon></gml:polygonMember>
    <gml:polygonMember><gml:Polygon><gml:outerBoundaryIs><gml:LinearRing><gml:coordinates>3,3 3,4 4,4 3,3</gml:coordinates></gml:LinearRing></gml:outerBoundaryIs></gml:Polygon></gml:polygonMember>
  </gml:MultiPolygon></ms:msGeometry><ms:NOM>Réserve</ms:NOM></ms:RNN></gml:featureMember>
</wfs:FeatureCollection>"""

GML3_POINTS = """<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:x="urn:x">
  <wfs:member><x:station><x:the_geom><gml:Point><gml:pos>2.35 48.85</gml:pos></gml:Point></x:the_geom><x:code>A1</x:code></x:station></wfs:member>
  <wfs:member><x:station><x:the_geom><gml:LineString><gml:posList>2 48 3 49</gml:posList></gml:LineString></x:the_geom></x:station></wfs:member>
</wfs:FeatureCollection>"""


def test_a_gml2_polygon_keeps_its_hole_and_its_plain_properties():
    [feature] = gml.features(GML2_POLYGON_WITH_HOLE.encode())

    assert feature["geometry"] == {
        "type": "Polygon",
        "coordinates": [
            [[48.9, 1.5], [49.1, 1.5], [49.1, 1.7], [48.9, 1.5]],
            [[49.0, 1.55], [49.05, 1.55], [49.05, 1.6], [49.0, 1.55]],
        ],
    }
    assert feature["properties"] == {"ID_SPN": "IF01", "NOM": "Vallée de la Seine", "URL": None}


def test_a_gml2_multipolygon_keeps_each_polygon():
    [feature] = gml.features(GML2_MULTIPOLYGON.encode())

    assert feature["geometry"]["type"] == "MultiPolygon"
    assert len(feature["geometry"]["coordinates"]) == 2
    assert feature["properties"] == {"NOM": "Réserve"}


def test_gml3_points_and_lines_are_read_from_pos_and_pos_list():
    point, line = gml.features(GML3_POINTS.encode())

    assert point == {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.35, 48.85]}, "properties": {"code": "A1"}}
    assert line["geometry"] == {"type": "LineString", "coordinates": [[2.0, 48.0], [3.0, 49.0]]}


@pytest.mark.parametrize(
    "document",
    [b"pas du xml", b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows"><ows:Exception/></ows:ExceptionReport>'],
)
def test_an_unreadable_answer_or_a_wfs_exception_is_an_error(document):
    with pytest.raises(gml.GmlError):
        gml.features(document)
