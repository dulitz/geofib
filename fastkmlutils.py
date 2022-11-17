"""
fastkmlutils.py

"""

import logging, os

from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from fastkml import kml, styles, geometry
from shapely.geometry import polygon

LOGGER = logging.getLogger('fastkmlutils')

class FastkmlError(Exception):
    pass

def read_kml_file(filename, kml):
    """Read filename and append it to kml."""
    if filename.endswith('.kmz'):
        kmz = ZipFile(filename, 'r')
        with kmz.open('doc.kml', 'r') as kmlfile:
            kml.from_string(kmlfile.read())
    else:
        with open(filename, encoding='utf-8') as kmlfile:
            kml.from_string(kmlfile.read())

def write_kml_file(filename, kml, prettyprint=False):
    """Write kml to filename as a KML file."""
    with open(filename, 'wt') as f:
        f.write(kml.to_string(prettyprint=prettyprint))

def write_kmz_file(filename, kml, icon_not_found=None, prettyprint=False):
    """Write kml to filename as a KMZ file."""
    iconnames = set()
    def _get_iconnames(elem):
        if hasattr(elem, 'styles'):
            for s in elem.styles():
                if isinstance(s, styles.IconStyle):
                    iconnames.add(s.icon_href)
                _get_iconnames(s)
        if hasattr(elem, 'features'):
            for f in elem.features():
                _get_iconnames(f)
    _get_iconnames(kml)

    with ZipFile(filename, mode='w', compression=ZIP_DEFLATED) as zipf:
        with zipf.open('doc.kml', mode='w') as f:
            f.write(kml.to_string(prettyprint=prettyprint).encode())
        for iconname in iconnames:
            if os.path.exists(iconname):
                zipf.write(iconname, iconname, compress_type=ZIP_STORED)
            elif icon_not_found == '':
                raise FastkmlError(f'no file {iconname} and no default icon')
            elif icon_not_found is not None:
                LOGGER.warning(f'{iconname} not in filesystem, using {icon_not_found}')
                zipf.write(icon_not_found, iconname, compress_type=ZIP_STORED)


class Collector:
    def __init__(self, leaf_mapper, interior_mapper=None):
        self.leaf_mapper = leaf_mapper
        self.interior_mapper = interior_mapper  # interior nodes only

    def collect(self, kml):
        accum = []
        def visitor(elem, folder):
            n = getattr(elem, 'name', None)
            if hasattr(elem, 'features'):
                for f in elem.features():
                    visitor(f, elem)
                r = self.interior_mapper(n, elem, folder) if self.interior_mapper else None
            else:
                r = self.leaf_mapper(n, elem, folder)
            if r is not None:
                accum.append(r)
        visitor(kml, None)
        return accum

    def first(self, kml):
        def visitor(elem, folder):
            n = getattr(elem, 'name', '')
            if hasattr(elem, 'features'):
                for f in elem.features():
                    r = visitor(f, elem)
                    if r is not None:
                        return r
                r = self.interior_mapper(n, elem, folder) if self.interior_mapper else None
            else:
                r = self.leaf_mapper(n, elem, folder)
            return r
        return visitor(kml, None)


class LeafDeleter:
    """Calls predicate on every leaf. If predicate is true, the leaf is deleted.
    Predicate may perform other functions (such as adding the leaf to a different
    part of the tree) before returning true.
    """
    def __init__(self, predicate):
        self.predicate = predicate

    def operate(self, node):
        def visitor(elem, folder):
            if isinstance(elem, kml.Folder):
                any_deleted = False
                notdeleted = []
                for f in elem.features():
                    if visitor(f, elem):
                        any_deleted = True
                    else:
                        notdeleted.append(f)
                if any_deleted:
                    elem._features = notdeleted
            elif hasattr(elem, 'features'):
                for f in elem.features():
                    visitor(f, folder)
            elif self.predicate(getattr(elem, 'name', None), elem, folder):
                return True
            return False
        visitor(node, None)
