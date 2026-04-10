import pytest
import math
from unittest.mock import MagicMock, patch
from dataProcessor import get_unprocessed_points, calculate_distance, proximity_check


@pytest.fixture
def mock_db():
    with patch('dataProcessor.db') as mock:
        yield mock


def make_point(**kwargs):
    defaults = {
        'icao24': '3b7b39',
        'timestamp': 1000,
        'altitude_agl_ft': 500.0,
        'baro_altitude_ft': 600.0,
        'is_processed': False,
        'on_ground': False,
    }
    defaults.update(kwargs)
    point = MagicMock()
    for k, v in defaults.items():
        setattr(point, k, v)
    return point


def test_returns_unprocessed_points(mock_db):
    expected = [make_point(), make_point(icao24='3b7b63', timestamp=2000)]
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = expected

    result = get_unprocessed_points()

    assert result == expected
    assert len(result) == 2


def test_returns_empty_when_no_points(mock_db):
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    result = get_unprocessed_points()

    assert result == []


def test_excludes_already_processed(mock_db):
    unprocessed = make_point(is_processed=False)
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [unprocessed]

    result = get_unprocessed_points()

    assert all(not p.is_processed for p in result)


def test_excludes_high_altitude_points(mock_db):
    low = make_point(altitude_agl_ft=500.0)
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [low]

    result = get_unprocessed_points()

    assert all(p.altitude_agl_ft < 60000 for p in result)


def test_includes_on_ground_points(mock_db):
    on_ground = make_point(on_ground=True, altitude_agl_ft=0.0, baro_altitude_ft=None)
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [on_ground]

    result = get_unprocessed_points()

    assert result[0].on_ground is True


def test_includes_airborne_with_valid_altitudes(mock_db):
    airborne = make_point(on_ground=False, altitude_agl_ft=1000.0, baro_altitude_ft=1200.0)
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [airborne]

    result = get_unprocessed_points()

    assert result[0].altitude_agl_ft == pytest.approx(1000.0)
    assert result[0].baro_altitude_ft == pytest.approx(1200.0)


def test_query_called_on_flight_telemetry(mock_db):
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    get_unprocessed_points()

    mock_db.query.assert_called_once_with(migrate.FlightTelemetry)


def test_same_point_returns_zero():
    assert calculate_distance(48.8566, 2.3522, 48.8566, 2.3522) == pytest.approx(0.0)


def test_known_distance_paris_marseille():
    # Paris to Marseille ~660 km
    dist = calculate_distance(48.8566, 2.3522, 43.2965, 5.3698)
    assert dist == pytest.approx(660.0, rel=0.05)


def test_known_distance_paris_london():
    # Paris to London ~340 km
    dist = calculate_distance(48.8566, 2.3522, 51.5074, -0.1278)
    assert dist == pytest.approx(340.0, rel=0.05)


def test_symmetry():
    # Distance A→B should equal B→A
    d1 = calculate_distance(48.8566, 2.3522, 43.2965, 5.3698)
    d2 = calculate_distance(43.2965, 5.3698, 48.8566, 2.3522)
    assert d1 == pytest.approx(d2)


def test_returns_positive_value():
    dist = calculate_distance(44.0, 4.0, 45.0, 5.0)
    assert dist > 0


def test_short_distance():
    # ~1 km apart
    dist = calculate_distance(44.0, 4.0, 44.009, 4.0)
    assert dist == pytest.approx(1.0, rel=0.05)


def test_equator_crossing():
    dist = calculate_distance(-1.0, 0.0, 1.0, 0.0)
    assert dist == pytest.approx(222.4, rel=0.05)


def test_result_in_km():
    # Paris to Nimes ~570 km
    dist = calculate_distance(48.8566, 2.3522, 43.8367, 4.3601)

def make_point(lat, lon, altitude_agl_ft=100.0, on_ground=False):
    point = MagicMock()
    point.lat = lat
    point.lon = lon
    point.altitude_agl_ft = altitude_agl_ft
    point.on_ground = on_ground
    return point


def make_airfield(lat, lon, icao='LFXX'):
    af = MagicMock()
    af.lat = lat
    af.lon = lon
    af.icao = icao
    return af


def test_returns_airfield_when_within_radius_and_below_alt():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=500.0)
    af = make_airfield(48.8600, 2.3600)  # very close

    result = proximity_check(point, [af], radius_km=10.0, alt_threshold_ft=1500)

    assert result == af


def test_returns_none_when_outside_radius():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=500.0)
    af = make_airfield(43.2965, 5.3698)  # Paris to Marseille ~660km

    result = proximity_check(point, [af], radius_km=10.0, alt_threshold_ft=1500)

    assert result is None


def test_returns_none_when_above_alt_threshold():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=2000.0, on_ground=False)
    af = make_airfield(48.8600, 2.3600)

    result = proximity_check(point, [af], radius_km=10.0, alt_threshold_ft=1500)

    assert result is None


def test_returns_airfield_when_on_ground_regardless_of_altitude():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=9999.0, on_ground=True)
    af = make_airfield(48.8600, 2.3600)

    result = proximity_check(point, [af], radius_km=10.0, alt_threshold_ft=1500)

    assert result == af


def test_returns_none_when_no_airfields():
    point = make_point(48.8566, 2.3522)

    result = proximity_check(point, [], radius_km=10.0, alt_threshold_ft=1500)

    assert result is None


def test_returns_first_matching_airfield():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=500.0)
    af1 = make_airfield(48.8600, 2.3600, icao='LFPG')
    af2 = make_airfield(48.8610, 2.3610, icao='LFPB')

    result = proximity_check(point, [af1, af2], radius_km=10.0, alt_threshold_ft=1500)

    assert result == af1


def test_returns_correct_airfield_when_multiple_only_one_matches():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=500.0)
    far_af  = make_airfield(43.2965, 5.3698, icao='LFML')  # Marseille, far
    near_af = make_airfield(48.8600, 2.3600, icao='LFPG')  # very close

    result = proximity_check(point, [far_af, near_af], radius_km=10.0, alt_threshold_ft=1500)

    assert result == near_af


def test_exactly_at_radius_boundary():
    point = make_point(48.8566, 2.3522, altitude_agl_ft=500.0)
    af = make_airfield(48.8600, 2.3600)

    dist = pytest.approx  # just to import
    from dataProcessor import calculate_distance
    actual_dist = calculate_distance(point.lat, point.lon, af.lat, af.lon)

    result = proximity_check(point, [af], radius_km=actual_dist, alt_threshold_ft=1500)

    assert result == af