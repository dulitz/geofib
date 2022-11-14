"""
cogo.py
"""

import math

import vincenty


class ParseError(Exception):
    pass

def chord_from_arc(r, delta):
    """Given a radius and delta azimuth (central angle in degrees),
    return the chord length = 2r sin(theta/2)
    """
    piD4 = math.atan(1.0)
    theta = delta * piD4 / 45.0
    if theta < 0:
        theta += piD4 * 8
    return 2 * r * math.sin(theta / 2.0)


class Position:
    FEET_METERS_FACTOR = 3.2808398950131

    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude

    def copy(self):
        return Position(self.latitude, self.longitude)

    def __eq__(self, other):
        return self.latitude == other.latitude and self.longitude == other.longitude

    def __repr__(self):
        ew = 'E' if self.longitude >= 0 else 'W'
        return f'[Position: {self.latitude} N, {abs(self.longitude)} {ew}]'

    def displace(self, range_in_feet, azimuth):
        range_in_meters = range_in_feet / self.FEET_METERS_FACTOR
        (self.latitude, self.longitude, ignore_reverse_bearing) = vincenty.position_from_rangebearing(self.latitude, self.longitude, azimuth, range_in_meters)

    def range_bearing_to(self, other):
        (range_in_meters, azimuth, reverse_azimuth) = vincenty.rangebearing_from_positions(self.latitude, self.longitude, other.latitude, other.longitude)
        range_in_feet = range_in_meters * self.FEET_METERS_FACTOR
        return (range_in_feet, azimuth, reverse_azimuth)


class Traverse:
    def __init__(self, name, initial_position, source=None):
        self.name = name
        self.source = source
        self.points = []
        self.rangeazimuths = []
        self.cursor = initial_position

    def begin(self):
        """The cursor is at the True Point of Beginning."""
        if self.points:
            raise ParseError(f'beginning when already begun: while parsing {self.name} at {self.cursor}')
        self.points.append(self.cursor.copy())
        
    def thence_to(self, range_in_feet, azimuth):
        self.cursor.displace(range_in_feet, azimuth)
        if self.points:
            self.points.append(self.cursor.copy())
            self.rangeazimuths.append((range_in_feet, azimuth))

    def range_bearing_to_close(self):
        if len(self.points) < 3:
            raise ParseError(f'closure needs >= 3 points: {self.name}, {self.points}')
        assert len(self.points) == len(self.rangeazimuths) + 1
        (r, b, ignore_reverse) = self.points[-1].range_bearing_to(self.points[0])
        return (r, b)

    def as_polygon(self):
        """Returns Positions forming a polygon bounded by the traverse. If the
        last point in the traverse is not equal to the first point, the polygon
        will include an additional edge between the last point and the first.

        If the traverse crosses itself, the result is undefined.
        """
        if len(self.points) < 3:
            raise ParseError(f'polygon needs >= 3 points: {self.name}, {self.points}')
        assert len(self.points) == len(self.rangeazimuths) + 1
        closure = [] if self.points[0] == self.points[-1] else self.points[0].copy()
        return [p.copy() for p in self.points] + [closure]

    def as_centerline(self, right_in_feet, left_in_feet):
        """Treating the traverse as a centerline, returns Positions forming
        a polygon displaced to the right (+90 degrees) and left (-90 degrees)
        of the traverse. The Positions are in counterclockwise order.

        If the traverse crosses itself, the result is undefined.
        """
        if len(self.points) < 2:
            raise ParseError(f'centerline needs >= 2 points: {self.name}, {self.points}')
        assert len(self.points) == len(self.rangeazimuths) + 1
        piD4 = math.atan(1.0)
        right = []
        left_rev = []
        azimuths = [alpha for (r, alpha) in self.rangeazimuths]
        def displace(point, range_f, bearing):
            if range_f == 0:
                return point
            pt = point.copy()
            pt.displace(range_f, bearing % 360)
            return pt
        def add(point, right_in_feet, left_in_feet, azimuth):
            right.append(displace(point, right_in_feet, azimuth+90))
            left_rev.append(displace(point, left_in_feet, azimuth-90))

        add(self.points[0], right_in_feet, left_in_feet, azimuths[0])
        for (alpha_k, point, alpha_kP1) in zip(azimuths, self.points[1:], azimuths[1:]):
            alpha_diff = (alpha_kP1 - alpha_k) % 360
            if alpha_diff > 175 and alpha_diff < 185:
                raise ParseError(f'angle {alpha_diff} too acute: {self.name}, {point}')
            if alpha_diff < 180: # centerline turns right at point
                # then the right vertex is farther away from the point
                alpha = alpha_k + alpha_diff / 2
                r = abs(right_in_feet / math.cos(alpha_diff * piD4 / 90.0))
                right.append(displace(point, r, alpha+90))
                left_rev.append(displace(point, left_in_feet, alpha-90))
            else: # centerline turns left at point
                # then the left vertex is farther away from the point
                alpha = alpha_k + alpha_diff / 2
                r = abs(left_in_feet / math.cos(alpha_diff * piD4 / 90.0))
                left_rev.append(displace(point, r, alpha+90))
                right.append(displace(point, right_in_feet, alpha-90))
        add(self.points[-1], right_in_feet, left_in_feet, azimuths[-1])
        left_rev.reverse()
        return right + left_rev


def parse_azimuth(tup):
    """Given a list or tuple with at least 3 elements, return the azimuth
    in floating-point degrees. Elements beyond the third, if any, are ignored.

    The first element is either 'N' or 'S', the third element is either 'E'
    or 'W', and the second element may be an angle in one of these formats:
      - floating-point degrees
      - an 8-character string in DD MM SS format
    """
    if len(tup) < 3:
        raise ParseError(f'must have at least 3 elements: {tup}')
    ns = tup[0].upper()
    north = ns == 'N'
    if ns != 'S' and not north:
        raise ParseError(f'first element must be N or S: {tup}')
    ew = tup[2].upper()
    east = ew == 'E'
    if ew != 'W' and not east:
        raise ParseError(f'third element must be E or W: {tup}')
    try:
        angle = _parse_angle(tup[1])
    except ValueError:
        raise ParseError(f'second element must be angle in decimal degrees or an 8-character string in DD MM SS format, and 0 <= angle <= 90: {tup}')
    if north:
        return angle if east else 360 - angle
    else:
        return 180 - angle if east else 180 + angle

def _parse_angle(elem):
    try:
        degrees = float(elem)
        if degrees < 0 or degrees > 90:
            raise ParseError(f'angle must be between 0 and 90: {elem}')
        return degrees
    except ValueError:
        if len(elem) != 8 or elem[2] != ' ' or elem[5] != ' ':
            raise ValueError
        degrees = int(elem[0:2])
        minutes = int(elem[3:5])
        seconds = int(elem[6:8])
        if degrees < 0 or minutes < 0 or seconds < 0 or degrees > 90 or minutes > 59 or seconds > 59:
            raise ValueError
        return degrees + minutes/60.0 + seconds/3600.0
