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
    DEGREES_FEET_FACTOR = 1.0 / 6074.0 / 60.0

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
    """Represents a traverse as a collection of Positions (latitude/longitude).

    When there is terrain (significant change in altitude) over a traverse, the
    lat/long will deviate from the surveyed path. We assume Vincenty's ellipsoid,
    but surveyed ranges along steep terrain can be much larger than distances over
    the ellipsoid.

    TODO: as_centerline() does not cover the case where a range is short relative
    to the change in bearing and the inside path of the polygon is not defined by
    each point of the traverse in order (a "pinwheel corner"). We can fix this by
    calculating a rectangle corresponding to each segment of the traverse and
    then merging all those rectangles together.
    """
    def __init__(self, name, initial_position, initial_comment=''):
        self.name = name
        self.comments = [initial_comment] if initial_comment else []
        self.points = []
        self.rangeazimuths = []
        self.cursor = initial_position
        self.last_azimuth = None
        self.basis_adjustment = 0

    def authority(self, source, basis_adjustment):
        self.comments.append('&nbsp;')  # leave a blank line
        self.comments.append(f'<b>Authority: {source}</b>, basis adjusted {angle_as_dms_string(basis_adjustment)}')
        self.basis_adjustment = basis_adjustment

    def begin(self):
        """The cursor is at the True Point of Beginning."""
        self.comments.append('<b>True Point of Beginning<b>')
        if self.points:
            raise ParseError(f'beginning when already begun: while parsing {self.name} at {self.cursor}')
        self.points.append(self.cursor.copy())
        
    def thence_to(self, range_in_feet, azimuth, comment=''):
        self.comments.append(f'Thence {range_in_feet} feet bearing {angle_as_dms_string(azimuth)}{", " + comment if comment else ""}')
        azimuth += self.basis_adjustment
        self.cursor.displace(range_in_feet, azimuth)
        self.last_azimuth = azimuth
        if self.points:
            self.points.append(self.cursor.copy())
            self.rangeazimuths.append((range_in_feet, azimuth))

    def thence_chord(self, range_in_feet, delta_azimuth, comment=''):
        """A negative delta_azimuth turns to the left, otherwise right."""
        self.comments.append(f'Thence a chord {round(range_in_feet, 2)} feet with relative bearing {angle_as_dms_string(delta_azimuth)}{", " + comment if comment else ""}')
        if self.last_azimuth is None:
            raise ParseError(f'traverse cannot begin with an arc or chord')
        last_azimuth = self.last_azimuth
        self.thence_to(range_in_feet, last_azimuth + delta_azimuth/2)
        # self.last_azimuth is the azimuth tangent to the curve endpoint
        self.last_azimuth = last_azimuth + delta_azimuth

    def range_bearing_to_close(self):
        """Returns a tuple (range_in_feet, bearing_in_degrees). The bearing
        is in the coordinate system's frame of reference, which is different
        from the frame of reference of the specification if basis_adjustment
        is nonzero."""
        if len(self.points) < 3:
            raise ParseError(f'closure needs >= 3 points: {self.name}, {self.points}')
        assert len(self.points) == len(self.rangeazimuths) + 1
        (r, b, ignore_reverse) = self.points[-1].range_bearing_to(self.points[0])
        self.comments.append('Closes' if r < 0.05 else f'Range {round(r, 2)} bearing {angle_as_dms_string(b)} to close')
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
                add(point, r, left_in_feet, alpha)
            else: # centerline turns left at point
                # then the left vertex is farther away from the point
                alpha = alpha_k + alpha_diff / 2
                r = abs(left_in_feet / math.cos(alpha_diff * piD4 / 90.0))
                add(point, right_in_feet, r, alpha+180)
        add(self.points[-1], right_in_feet, left_in_feet, azimuths[-1])
        left_rev.reverse()
        return right + left_rev


def angle_as_dms(alpha):
    """Given a floating-point number of degrees, returns a tuple (degrees, min, sec)."""
    degrees = int(alpha)
    remainder = 60 * (alpha - degrees)
    minutes = int(remainder)
    seconds = 60 * (remainder - minutes)
    return (degrees, minutes, seconds)


def angle_as_dms_string(alpha, roundto=1):
    (d, m, s) = angle_as_dms(alpha)
    if s:
        return f"{d}d {m}' {round(s, roundto)}" + '"'
    if m:
        return f"{d}d {m}'"
    return f"{d}d"


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
        angle = parse_angle(tup[1])
    except ValueError:
        raise ParseError(f'second element must be angle in decimal degrees or an 8-character string in DD MM SS format, and 0 <= angle <= 90: {tup}')
    if north:
        return angle if east else 360 - angle
    else:
        return 180 - angle if east else 180 + angle


def parse_angle(elem):
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
