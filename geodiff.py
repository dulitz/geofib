"""
geodiff.py

Not really diff! At least not at this point. It emits the Placemarks that are in
file1 but not in file2.
"""

import logging

from fastkml import kml, styles, geometry
from shapely.geometry import polygon

import fastkmlutils

LOGGER = logging.getLogger('geofib')


class Geo:
    def __init__(self, doc, filename=None):
        self.doc = doc
        self.filename = filename
        self.overwrites = 0

    def read(self):
        assert self.filename
        fastkmlutils.read_kml_file(self.filename, self.doc)
        self.pointmap = {}  # maps (lat, long) tuple to (elem, folder)
        self.polymap = {}   # maps (lat, long) tuple to (elem, folder)
        self.polygon_names = {}  # maps polygon name to (elem, folder)

    def _add_no_overwrite(self, themap, key, value):
        if key not in themap:
            themap[key] = value
        else:
            self.overwrites += 1
            LOGGER.debug(f'key {key} dropping later value {value}, keeping {themap[key]}')

    def build_maps(self):
        def _geomatch(name, elem, folder):
            geom = getattr(elem, 'geometry', None)
            if isinstance(geom, geometry.Point):
                self._add_no_overwrite(self.pointmap, geom.coords[0], (elem, folder))
            elif isinstance(geom, geometry.Polygon):
                for coord in geom.exterior.coords:
                    self._add_no_overwrite(self.polymap, coord, (elem, folder))
                self._add_no_overwrite(self.polygon_names, name, (elem, folder))
            elif isinstance(geom, geometry.LineString):
                for coord in geom.coords:
                    self._add_no_overwrite(self.polymap, coord, (elem, folder))
                self._add_no_overwrite(self.polygon_names, name, (elem, folder))
        fastkmlutils.Collector(_geomatch).collect(self.doc)


class Geodiff:
    def __init__(self, file1, file2):
        self.geo1 = Geo(kml.KML(), file1)
        self.geo2 = Geo(kml.KML(), file2)
        self.geo1.read()
        self.geo2.read()
        self.geo1.build_maps()
        self.geo2.build_maps()

    def minus(self):
        self.print_missing(self.geo1.pointmap, self.geo2.pointmap, 'points')
        self.print_missing(self.geo1.polymap, self.geo2.polymap, 'vertices')
        missing_polygon_names = self.geo1.polygon_names.keys() - self.geo2.polygon_names.keys()
        if missing_polygon_names:
            LOGGER.info(f'missing {len(missing_polygon_names)} polygons')
            for pname in sorted(missing_polygon_names):
                print(pname)

    def print_missing(self, map1, map2, name):
        missing = map1.keys() - map2.keys()
        if missing:
            LOGGER.info(f'missing {len(missing)} {name}')
            for m in missing:
                print(f'{m} from {map1[m][0].name} in {map1[m][1].name}')


def main(args):
    logging.basicConfig(level=logging.INFO)
    if len(args) != 3:
        LOGGER.fatal(f'Usage: {args[0]} file1 file2')
        return 1

    g = Geodiff(args[1], args[2])
    g.minus()
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
