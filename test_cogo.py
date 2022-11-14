"""
test_cogo.py

"""

import logging

# uncomment this to get more logs
# logging.basicConfig(level=logging.DEBUG)

import cogo

chord = cogo.chord_from_arc(100, 90)
assert chord > 141.421, chord
assert chord < 141.42136, chord

assert 20.45 == cogo._parse_angle(20.45)
try:
    cogo._parse_angle('-26')
    assert False
except cogo.ParseError:
    pass

assert 45.5 == cogo._parse_angle('45 30 00')

azimuth = cogo.parse_azimuth(['N', '30 10 10', 'W'])
assert azimuth > 329.83055, azimuth
assert azimuth < 329.83056, azimuth

azimuth = cogo.parse_azimuth(['S', '30 10 10', 'E'])
assert azimuth > 329.83055-180, azimuth
assert azimuth < 329.83056-180, azimuth

azimuth = cogo.parse_azimuth(['S', '30 10 10', 'W'])
assert azimuth > 210.16944, azimuth
assert azimuth < 210.16945, azimuth

azimuth = cogo.parse_azimuth(['N', '30 10 10', 'E'])
assert azimuth > 30.16944, azimuth
assert azimuth < 30.16945, azimuth

print('success')
