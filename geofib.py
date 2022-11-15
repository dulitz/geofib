"""
geofib.py

Process survey fixes taken by a GNSS survey tool in KML/KMZ format.
  - Merges fixes from multiple files into one.
  - Cleans fix names exported from the SW Maps data capture app.
  - Categorizes fixes into layers based on type, and sets styles accordingly.
"""

import logging, os
import yaml

from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from fastkml import kml, styles, geometry
from shapely.geometry import polygon

import cogo

LOGGER = logging.getLogger('geofib')


class GeofibError(Exception):
    pass


class Geofib:
    def __init__(self, config=None, iconscale=None):
        self.config = config or {}
        self.doc = kml.KML()
        self.new_polystyles, self.new_iconstyles = {}, {}
        self.iconscale = iconscale if iconscale else float(self.config.get('iconscale', 1.0))

    @property
    def DEFAULT_FOLDER(self):
        return 'Vertices and Plow/Bore Controls'

    @property
    def fixnames(self):
        structname = 'Structures, Fences, and Edges'
        drivename = 'Driveways, Roads, and Monuments'
        elecname = 'Electric'
        wgwname = 'Water, Gas, and Wastewater'
        commname = 'Communications'
        archivename = self.DEFAULT_FOLDER
        return {
            'FENCE': (structname, 'fence-black.png'),
            'BLDG': (structname, 'house-black.png'),
            'tree': (structname, 'tree-black.png'),

            'EOP': (drivename, 'flag-black.png'),
            'DWY': (drivename, 'door-black.png'),
            'JCT': (drivename, 'door-black.png'),
            'CROWN': (drivename, 'flag-black.png'),
            'MONSTR': (drivename, 'peg-black.png'),
            'monument': (drivename, 'peg-black.png'),
            'survey': (drivename, 'peg-black.png'),
            'corner': (drivename, 'peg-black.png'),

            'WWLAT': (wgwname, 'whirl-green.png'),
            'WWMH': (wgwname, 'whirl-green.png'),
            'WWCO': (wgwname, 'whirl-green.png'),
            'WW ': (wgwname, 'whirl-green.png'),
            'storm': (wgwname, 'peg-green.png'),
            'SDIN': (wgwname, 'peg-green.png'),
            
            'WTMAIN': (wgwname, 'water-blue.png'),
            'WTTEE': (wgwname, 'water-blue.png'),
            'WTSVC': (wgwname, 'water-blue.png'),
            'WTFH': (wgwname, 'fire-blue.png'),
            'WTFS': (wgwname, 'fire-blue.png'), # fire standpipe
            'WTVMAIN': (wgwname, 'water-blue.png'),
            'WTVFH': (wgwname, 'fire-blue.png'),
            'WTVFS': (wgwname, 'fire-blue.png'),
            'WTVSVC': (wgwname, 'water-blue.png'),
            'WTVBLDG': (wgwname, 'water-blue.png'),
            'WTV': (wgwname, 'water-blue.png'),
            'WTLINESTOP': (wgwname, 'water-blue.png'),
            'WTM': (wgwname, 'water-blue.png'),
            'WTANOBOX': (wgwname, 'water-blue.png'),
            
            'GSVC': (wgwname, 'peg-yellow.png'),
            'GVSVC': (wgwname, 'peg-yellow.png'),
            'gas ': (wgwname, 'peg-yellow.png'),
            'propane': (wgwname, 'peg-yellow.png'),
            'irrig': (wgwname, 'peg-blue.png'),
            
            'ELVLT': (elecname, 'electric-red.png'),
            'EMH': (elecname, 'electric-red.png'),
            'ELSVC': (elecname, 'electric-red.png'),
            'XFRMR': (elecname, 'electric-red.png'),
            'CPAU pole': (elecname, 'electric-red.png'),
            'CPAU guy': (elecname, 'peg-red.png'),
            'PG&E': (elecname, 'electric-red.png'),
            'electric': (elecname, 'electric-red.png'),
            'primary': (elecname, 'electric-red.png'),
            'secondary': (elecname, 'electric-red.png'),
            
            'TELVAULT': (commname, 'phone-orange.png'),
            'TELDMARC': (commname, 'phone-orange.png'),
            'TELMH': (commname, 'phone-orange.png'),
            'FVAULT': (commname, 'phone-orange.png'),
            'FMH': (commname, 'phone-orange.png'),
            'FDEMARC': (commname, 'phone-orange.png'),
            'AT&T pole': (commname, 'phone-orange.png'),

            'plow': (archivename, 'peg-orange.png'),
            }
    
    def read_bases(self):
        bases = self.config.get('bases', [])
        if not bases:
            LOGGER.info('config has no bases')
        for filename in bases:
            self.read(filename)
        
    def read(self, filename):
        if filename.endswith('.kmz'):
            kmz = ZipFile(filename, 'r')
            with kmz.open('doc.kml', 'r') as kml:
                self.doc.from_string(kml.read())
        else:
            with open(filename, encoding='utf-8') as kml:
                self.doc.from_string(kml.read())

    def verify(self, elem=None):
        if elem is None:
            return self.verify(self.doc)
        if hasattr(elem, 'features'):
            # we don't verify interior (non-leaf) nodes
            return sum([self.verify(e) for e in elem.features()])
        if 'wtlat' in elem.name.lower():
            LOGGER.warning(f'{elem.name} ambiguous: use WWLAT or WTSVC')
        if 'TELVAULT' not in elem.name:
            newname = elem.name.replace('ELVAULT', 'ELVLT').replace('FDMARC', 'FDEMARC').replace('TELDEMARC', 'TELDMARC')
            if newname != elem.name:
                LOGGER.info(f'renamed {elem.name} to {newname}')
                elem.name = newname
        if elem.description is None:
            # then this isn't a type of object that we might modify
            return 0
        self._verify_element_name(elem)
        v = self._verify_element_description(elem)
        self._verify_element_style(elem, self.iconscale)
        return v

    def _verify_element_name(self, elem):
        def upper(s):
            for f in self.fixnames.keys():
                s = s.replace(f.lower(), f)
            return s
        (drop, sep, rest) = elem.description.partition('<p>Remarks: ')
        if sep:
            rest2 = rest.replace('</p>', '')
            (remarks, sep, rest) = rest2.partition('<p>')
            newname = upper(remarks)
            LOGGER.info(f'set name to {newname}')
            elem.name = newname
            elem.description = rest

    def _verify_element_description(self, elem):
        (first, sep, quality) = elem.description.partition('Fix Quality: ')
        if not sep:
            return 0
        def stripit(name):
            return name.lstrip('*!?~')
        if quality.startswith('DGPS'):
            if not elem.name.startswith('!'):
                elem.name = '!' + stripit(elem.name)
                LOGGER.info(f'set prefix for DGPS: {elem.name}')
        elif quality.startswith('RTK Fix'):
            stripped = stripit(elem.name)
            #if not elem.name.startswith('*'):
            if elem.name != stripped:
                elem.name = stripit(elem.name)
                LOGGER.info(f'set prefix for RTK Fix: {elem.name}')
        elif quality.startswith('RTK Float'):
            if not elem.name.startswith('~'):
                elem.name = '~' + stripit(elem.name)
                LOGGER.info(f'set prefix for RTK Float: {elem.name}')
        elif quality.startswith('Single'):
            if not elem.name.startswith('?'):
                elem.name = '?' + stripit(elem.name)
                LOGGER.info(f'set prefix for Single: {elem.name}')
        else:
            LOGGER.warning(f'{elem.name} has unknown fix quality {quality}')
        return 1

    def _verify_element_style(self, elem, iconscale):
        if isinstance(getattr(elem, 'geometry', None), geometry.Point):
            for (n, spec) in self.fixnames.items():
                if n in elem.name:
                    (layername, iconname, *rest) = spec
                    styleid = n.lower()
                    styleurl = f'#{styleid}'
                    if elem.styleUrl != styleurl:
                        elem.styleUrl = styleurl
                    color = rest[0] if rest else None
                    scale = rest[1] if rest and len(rest) > 1 else iconscale
                    self.new_iconstyles[styleid] = (iconname, color, scale)
                    return

    def move_layers(self, default_folder=None):
        if default_folder is None:
            default_folder = self.config.get('default_folder', self.DEFAULT_FOLDER)
        folder_by_foldername = {}  # in the first document only
        def _find_toplevel_folders(elem):
            if isinstance(elem, kml.Folder):
                folder_by_foldername[elem.name] = elem
            elif hasattr(elem, 'features'):
                for f in elem.features():
                    _find_toplevel_folders(f)
        dociter = self.doc.features()
        firstdoc = next(dociter)
        _find_toplevel_folders(firstdoc)

        newfolders = []
        def _get_folder_for(foldername):
            f = folder_by_foldername.get(foldername, None)
            if not f:
                f = kml.Folder(name=foldername)
                folder_by_foldername[foldername] = f
                newfolders.append(f)
                LOGGER.info(f'adding layer {f.name}')
            return f

        def _move(elem, foldernames_to_ignore, parent_foldername):
            if isinstance(elem, kml.Folder):
                if elem.name not in foldernames_to_ignore:
                    any_deleted = False
                    notdeleted = []
                    for f in elem.features():
                        if _move(f, foldernames_to_ignore, parent_foldername):
                            any_deleted = True
                        else:
                            notdeleted.append(f)
                    if any_deleted:
                        elem._features = notdeleted
            elif hasattr(elem, 'features'):
                for f in elem.features():
                    _move(f, foldernames_to_ignore, elem.name)
            elif parent_foldername and isinstance(getattr(elem, 'geometry', None), geometry.Point):
                # we are a leaf Point within a folder
                for (k, props) in self.fixnames.items():
                    if k in elem.name:
                        if parent_foldername != props[0] or (not foldernames_to_ignore):
                            LOGGER.info(f'moving {elem.name} from {parent_foldername} to {props[0]}')
                            _get_folder_for(props[0]).append(elem)
                            return True
                        break
                else:  # we don't match any of the predefined fix types
                    LOGGER.info(f'moving {elem.name} from {parent_foldername} to {default_folder}')
                    _get_folder_for(default_folder).append(elem)
                    return True
            return False

        folders_to_ignore = { v[0] for v in self.fixnames.values() }
        folders_to_ignore.add('Locator Fixes and Plow/Bore Controls') ### FIXME
        _move(firstdoc, folders_to_ignore, '')
        for otherdoc in dociter:
            _move(otherdoc, {}, '')
        for f in newfolders:
            # now that we are done with the iterator, add the new layers
            firstdoc.append(f)

    def replace_styles(self, defaulticon=None, kmliconprefix=None):
        """Adds to the first document the styles defined in
        self.new_polystyles and self.new_iconstyles. Systematically
        creates highlight and normal styles. Then replaces any styleurls that
        aren't in new_polystyles or new_iconstyles with a default style.
        """
        if defaulticon is None:
            defaulticon = self.config.get('defaulticon', 'triangle.png')
        if kmliconprefix is None:
            kmliconprefix = self.config.get('kmliconprefix', 'icons/')
        firstdoc = next(self.doc.features())
        self._clean_unused_styles(firstdoc)
        def append(s):
            firstdoc.append_style(s)

        self.new_polystyles['defaultpoly'] = ('FF000000', '50000000')
        for (name, properties) in self.new_polystyles.items():
            (linecolor, polycolor) = properties
            polystyle = styles.PolyStyle(color=polycolor, fill=1, outline=1)
            def _makestyles(width):
                return [styles.LineStyle(color=linecolor, width=width), polystyle]
            namenorm = f'{name}-normal'
            namehigh = f'{name}-highlight'
            append(styles.Style(id=namenorm, styles=_makestyles(width=2.0)))
            append(styles.Style(id=namehigh, styles=_makestyles(width=3.0)))
            append(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{namenorm}'),
                                   highlight=styles.StyleUrl(url=f'#{namehigh}')))

        self.new_iconstyles['defaulticon'] = (
            defaulticon, 'FF000000', self.config.get('iconscale', 0.5))
        for (name, properties) in self.new_iconstyles.items():
            (iconfile, iconcolor, iconscale) = properties
            def _makestyles(labelscale):
                return [styles.IconStyle(color=iconcolor, scale=iconscale,
                                         icon_href=f'{kmliconprefix}{iconfile}'),
                        styles.LabelStyle(scale=labelscale)]
            namenorm = f'{name}-normal'
            namehigh = f'{name}-highlight'
            append(styles.Style(id=namenorm, styles=_makestyles(labelscale=0.0)))
            append(styles.Style(id=namehigh, styles=_makestyles(labelscale=1.0)))
            append(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{namenorm}'),
                                   highlight=styles.StyleUrl(url=f'#{namehigh}')))

        newstyleids = set(self.new_iconstyles).union(self.new_polystyles)
        self._fix_bad_styleurls(self.doc, newstyleids)

    def _clean_unused_styles(self, doc):
        """Removes IconStyle elements and associated stylemaps from doc._styles."""
        def _contains_iconstyle(s):
            if hasattr(s, 'styles'):
                for s in s.styles():
                    if isinstance(s, styles.IconStyle):
                        return True
                    if _contains_iconstyle(s):
                        return True
            return False

        ids_to_remove = set()
        for s in doc.styles():
            if _contains_iconstyle(s):
                ids_to_remove.add(s.id)
        for s in doc.styles():
            if isinstance(s, styles.StyleMap):
                if s.normal.url[0] == '#' and s.normal.url[1:] in ids_to_remove:
                    ids_to_remove.add(s.id)
                if s.highlight.url[0] == '#' and s.highlight.url[1:] in ids_to_remove:
                    ids_to_remove.add(s.id)

        previous = len(doc._styles)
        doc._styles = [s for s in doc._styles if s.id not in ids_to_remove]
        if previous != len(doc._styles):
            LOGGER.info(f'removed {previous - len(doc._styles)} unused styles')

    def _fix_bad_styleurls(self, elem, newstyleids):
        k = 0
        styleUrl = getattr(elem, 'styleUrl', None)
        if styleUrl and styleUrl[1:] not in newstyleids:
            if isinstance(getattr(elem, 'geometry', None), geometry.Point):
                elem.styleUrl = '#defaulticon'
                LOGGER.info(f'set default style for {elem.name} replacing {styleUrl}')
            elif False: ### TODO: someday we might do this
                elem.styleUrl = '#defaultpoly'
                LOGGER.info(f'set default poly style for {elem.name}')
            k += 1
        if hasattr(elem, 'features'):
            # not a leaf node
            k += sum([self._fix_bad_styleurls(e, newstyleids) for e in elem.features()])
        return k

    def add_cogo(self):
        for (name, spec) in self.config.get('polygons', {}).items():
            self.add_polygon(name, spec)
        for (name, spec) in self.config.get('polylines', {}).items():
            self.add_polyline(name, spec)

    def folder_element(self, placemark_name, elem=None):
        """Returns a 2-tuple of elements, the second being the Placemark with the
        specified name, and the first being the Folder enclosing the Placemark.
        """
        if elem is None:
            return self.folder_element(placemark_name, next(self.doc.features()))
        if hasattr(elem, 'features'):
            for f in elem.features():
                tup = self.folder_element(placemark_name, f)
                if tup:
                    return tup if len(tup) == 2 else (elem, tup[0])
        elif isinstance(elem, kml.Placemark) and elem.name == placemark_name:
            return (elem,)
        else:
            return []

    def add_polyline(self, name, spec):
        (traverse, coords, comments) = self._add_poly(name, spec, polytype='polyline')
        pline = geometry.LineString([(pos.longitude, pos.latitude) for pos in traverse.points])
        tup = self.folder_element(name)  # existing polyline of this name?
        if tup:
            polyline_elem = tup[1]
        else:
            polyline_elem = kml.Placemark(name=name, styleUrl='#defaultpoly')
            (tie_folder, tie_elem) = self.folder_element(spec[0][0])
            tie_folder.append(polyline_elem)
        polyline_elem.geometry = pline
        polyline_elem.description = f'Authority: {traverse.source}<br>' + '<br>'.join(comments)
        LOGGER.info(f'created polyline {name}')

    def add_polygon(self, name, spec, polytype='polygon'):
        (traverse, coords, comments) = self._add_poly(name, spec, polytype='polygon')
        if not coords:
            coords = [(pos.longitude, pos.latitude) for pos in traverse.as_polygon()]
        pgon = polygon.orient(polygon.Polygon(coords))
        tup = self.folder_element(name)  # existing polygon of this name?
        if tup:
            polygon_elem = tup[1]
        else:
            polygon_elem = kml.Placemark(name=name, styleUrl='#defaultpoly')
            (tie_folder, tie_elem) = self.folder_element(spec[0][0])
            tie_folder.append(polygon_elem)
        polygon_elem.geometry = pgon
        polygon_elem.description = f'Authority: {traverse.source}<br>' + '<br>'.join(comments)
        LOGGER.info(f'created polygon {name}')

    def _add_poly(self, name, spec, polytype='polygon'):
        if len(spec) < 2:
            raise GeofibError(f'{polytype} {name} specification too short')
        (tie_name, tie_authority) = spec[0]
        tup = self.folder_element(tie_name)
        if not tup:
            raise GeofibError(f'{polytype} {name} nonexistent tie fix: {tie_name}')
        (tie_folder, tie_elem) = tup
        tie_geometry = getattr(tie_elem, 'geometry', None) 
        if not isinstance(tie_geometry, geometry.Point):
            raise GeofibError(f'{polytype} {name}: tie fix {tie_name} does not have Point geometry')

        position = cogo.Position(tie_geometry.y, tie_geometry.x)
        traverse = cogo.Traverse(name, position, source=tie_authority)
        coords = []
        comments = []
        for specitem in spec[1:]:
            if coords:
                raise GeofibError(f'{polytype} {name} already complete but read {specitem}')
            if specitem == 'closes':
                (range_f, bearing) = traverse.range_bearing_to_close()
                if range_f > 0.5:
                    LOGGER.warning(f'{polytype} {name} does not close by {range_f} feet bearing {bearing}')
                coords = [(pos.longitude, pos.latitude) for pos in traverse.as_polygon()]
            elif specitem == 'beginning':
                traverse.begin()
            elif specitem[0].lower() == 'centerline':
                (centerline, right_f, left_f) = specitem
                coords = [(pos.longitude, pos.latitude) for pos in traverse.as_centerline(right_f, left_f)]
            else:
                (dir1, alpha, dir2, distance, *comment) = specitem
                azimuth = cogo.parse_azimuth(specitem)
                distance = specitem[3]
                traverse.thence_to(distance, azimuth)
                if comment:
                    comments.append(comment[0])
        return (traverse, coords, comments)

    def add_poly_from_fixes(self, projector_elem=None):
        def _collect_projectors(elem, accum):
            if hasattr(elem, 'features'):
                for f in elem.features():
                    self._collect_projectors(f, accum)
            if ' PARTITION ' in elem.name or ' PROJECTOR ' in elem.name:
                accum.append(elem)
        if projector_elem is None:
            accum = []
            _collect_projectors(self.doc, accum)
            for elem in accum:
                self.add_poly_from_fixes(projector_elem=elem)
            return
        projector_geo = projector_elem.geometry
        assert isinstance(projector_geo, geometry.LineString), name
        desc = projector_elem.description.split()
        distance_f = int(desc[0]) if desc else 20.0
        distance_deg = distance_f / 6074 / 60  # approximate is fine if not at poles
        (name, sep, selector_spec) = projector_elem.name.partition(' PARTITION ')
        if sep:
            left_geo = projector_geo.buffer(distance_deg, single_sided=True)
            right_geo = projector_geo.buffer(-distance_deg, single_sided=True)
            assert right is not None, name
        else:
            (name, sep, selector_spec) = projector_elem.name.partition(' PROJECTOR ')
            if not sep:
                raise GeofibError(f'{elem.name} must contain PARTITION or PROJECTOR')
            left_geo = projector_geo.buffer(distance_deg)
            right_geo = None
        selectors = selector_spec.split()

        def _select_points(elem, left_accum, right_accum):
            if hasattr(elem, 'features'):
                for f in elem.features():
                    _select_points(elem, left_accum, right_accum)
            elif isinstance(getattr(elem, 'geometry', None), geometry.Point):
                # we are a leaf Point
                for s in selectors:
                    if s in elem.name:
                        if left_geo.contains(elem.geometry):
                            left_accum.append((projector_geo.project(elem.geometry), elem))
                        elif right_geo and right_geo.contains(elem.geometry):
                            right_accum.append((projector_geo.project(elem.geometry), elem))
                        break
        left_accum, right_accum = [], []
        _select_points(self.doc, left_accum, right_accum)
        left_accum.sort()
        if right_accum:
            right_accum.sort(key=lambda p: -1*p[0])
        # create geo, put it in the appropriate Placemark (possibly create one)
        # move the vertices to the archive layer if they aren't already there
        # (except for DWY which should not be moved).

    def set_properties(self, name=None, description=None, author=None):
        if name is None:
            name = self.config.get('name', None)
        if description is None:
            description = self.config.get('description', None)
        if author is None:
            author = self.config.get('author', None)
        firstdoc = next(self.doc.features())
        if name is not None:
            firstdoc.name = name
        if description is not None:
            firstdoc.description = description
        if author is not None:
            firstdoc.author = author

    def emit(self, filename=None, prettyprint=None, defaulticonpath=None):
        if filename is None:
            return self.emit(self.config['output'], prettyprint, defaulticonpath)
        if prettyprint is None:
            return self.emit(filename, self.config.get('prettyprint', False), defaulticonpath)
        if defaulticonpath is None:
            icon = self.config.get('defaulticon', '')
            dip = self.config.get('kmliconprefix', '') + icon
            return self.emit(filename, prettyprint, dip if icon else '')
        # remove all but the first document
        self.doc._features = [next(self.doc.features())]
        if filename.endswith('.kml'):
            with open(filename, 'wt') as f:
                f.write(self.doc.to_string(prettyprint=prettyprint))
        elif filename.endswith('.kmz'):
            def _get_iconnames(elem, accum):
                if hasattr(elem, 'styles'):
                    for s in elem.styles():
                        if isinstance(s, styles.IconStyle):
                            accum.add(s.icon_href)
                        _get_iconnames(s, accum)
                if hasattr(elem, 'features'):
                    for e in elem.features():
                        _get_iconnames(e, accum)

            iconnames = set()
            _get_iconnames(self.doc, iconnames)
            with ZipFile(filename, mode='w', compression=ZIP_DEFLATED) as zipf:
                with zipf.open('doc.kml', mode='w') as f:
                    f.write(self.doc.to_string(prettyprint=prettyprint).encode())
                for iconname in iconnames:
                    if os.path.exists(iconname):
                        zipf.write(iconname, iconname,
                                   compress_type=ZIP_STORED)
                    elif not defaulticonpath:
                        raise GeofibError(f'no file {iconname} and no default icon')
                    else:
                        LOGGER.warning(f'{iconname} not in filesystem; using default '
                                       + defaulticonpath)
                        zipf.write(defaulticonpath, iconname,
                                   compress_type=ZIP_STORED)
        else:
            raise GeofibError(f'unknown format for {filename}')

def main(args):
    logging.basicConfig(level=logging.INFO)
    configfile = 'geofib.yml'
    if len(args) > 1:
        configfile = args[1]

    config = yaml.safe_load(open(configfile)) or {}
    if config:
        LOGGER.info(f'using configuration file {configfile}')
    else:
        LOGGER.info(f'configuration file {configfile} was empty; ignored')
    g = Geofib(config)
    g.read_bases()
    count = g.verify()
    LOGGER.info(f'verified {count} items')
    g.move_layers()
    g.replace_styles()
    g.add_cogo()
    g.set_properties()
    if config.get('output'):
        g.emit()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
