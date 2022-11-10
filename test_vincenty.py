"""
test_vincenty.py

"""

import logging

# uncomment this to get more logs
# logging.basicConfig(level=logging.DEBUG)

import vincenty

def assert_within(v, center, tolerance):
    assert center - tolerance <= v, (center - tolerance, v)
    assert center + tolerance >= v, (center + tolerance, v)

epsilon = 0.000000001
    
longitude, latitude = -123.175722, 37.343150
azimuth = 0 # straight north
distance = 100 # meters
(lat, lon, rev) = vincenty.position_from_rangebearing(latitude, longitude, azimuth, distance)
assert_within(lat, 37.344051, 0.0000001)
assert_within(lon, longitude, epsilon)
assert_within(rev, 180.0, epsilon)

(s, alpha1, alpha2) = vincenty.rangebearing_from_positions(latitude, longitude, lat, lon)
assert_within(s, distance, 0.00000001)
assert_within(alpha1, 0.0, epsilon)
assert_within(alpha2, 180.0, epsilon)

print('success')
