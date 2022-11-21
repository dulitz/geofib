"""
design.py - 

"""

import itertools, logging, math

from fastkml import kml, styles, geometry
from shapely.geometry import polygon

import fastkmlutils, vincenty

from cogo import Position

LOGGER = logging.getLogger('geofib.design')


class GeofibDesignError(Exception):
    pass


class Splicepoints:
    def __init__(self):
        self.name_to_tuple = {}

    def add(self, dropname, bbvault, splicevault):
        return

class Design:
    def __init__(self, config, surveydoc):
        self.config = config
        self.allduct = None
        self.surveydoc = surveydoc
        self.design = kml.KML()
        self.design.append(kml.Document())
        self.designdoc = next(self.design.features())
        self.bbductfolder = kml.Folder(name='BB Duct')
        self.designdoc.append(self.bbductfolder)
        self.bbvaultsfolder = kml.Folder(name='BB Vaults')
        self.designdoc.append(self.bbvaultsfolder)
        self.dropductfolder = kml.Folder(name='Drop Duct')
        self.designdoc.append(self.dropductfolder)
        self.roadsfolder = kml.Folder(name='Roads, Monuments, & Rights')
        self.designdoc.append(self.roadsfolder)

        kmliconprefix = self.config.get('kmliconprefix', 'icons/')
        def _add(name, color, normwidth, highwidth):
            self.designdoc.append_style(styles.Style(id=f'{name}norm', styles=[styles.LineStyle(color=color, width=normwidth)]))
            self.designdoc.append_style(styles.Style(id=f'{name}high', styles=[styles.LineStyle(color=color, width=highwidth)]))
            self.designdoc.append_style(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{name}norm'), highlight=styles.StyleUrl(url=f'#{name}high')))
        bbductwidth = self.config.get('bbductwidth', 2)
        _add('bbduct', self.config.get('bbductcolor', '#ff0080ff'), bbductwidth, 2*bbductwidth)
        dropductwidth = self.config.get('dropductwidth', 2)
        _add('dropduct', self.config.get('dropductcolor', '#ff00ff00'), dropductwidth, 2*dropductwidth)
        fiberwidth = self.config.get('fiberwidth', 1)
        _add('fiber', self.config.get('fibercolor', '#ffffff00'), fiberwidth, 2*fiberwidth)
        def _addicon(name, file, iconscale, labelscale):
            self.designdoc.append_style(styles.Style(id=f'{name}norm', styles=[styles.IconStyle(scale=iconscale, icon_href=f'{kmliconprefix}{file}'), styles.LabelStyle(scale=0)]))
            self.designdoc.append_style(styles.Style(id=f'{name}high', styles=[styles.IconStyle(scale=iconscale, icon_href=f'{kmliconprefix}{file}'), styles.LabelStyle(scale=labelscale)]))
            self.designdoc.append_style(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{name}norm'), highlight=styles.StyleUrl(url=f'#{name}high')))
        _addicon('vault', self.config.get('vaulticon', 'square.png'), self.config.get('iconscale', 0.5), 1.0)
        _addicon('monument', self.config.get('monumenticon', 'triangle.png'), self.config.get('iconscale', 0.5), 1.0)

    def _add_allduct(self, geo):
        # unary_union() would be more efficient, doing them all at once, but not needed
        if not isinstance(geo, geometry.LineString):
            raise GeofibDesignError(f'duct must be geometry.LineString: {geo}')
        if self.allduct is None:
            self.allduct = geometry.LineString(geo)
        else:
            self.allduct = self.allduct.union(geo)

    def calculate(self):
        self.designdoc.name = self.config.get('designname', '')
        self.designdoc.description = self.config.get('designdescription', '')
        self.designdoc.author = self.config.get('designauthor', '')
        all_vaults = set()
        fiberonly_segments = set()
        splicepoints = Splicepoints()
        for (name, duct, installmethod, *vaults) in self.config['backbone']:
            self.copy_segment(self.bbductfolder, name, '#bbduct', duct, installmethod)
            assert vaults
            all_vaults.update(vaults)
        for name in sorted(all_vaults):
            self.copy_vault(self.bbvaultsfolder, name, '#vault')
        for (demarc, address_suffix, alignment, bbvault, splicevault) in self.config['drops']:
            newname = f'{" ".join(demarc.strip().split()[:-1])}{" " if address_suffix else ""}{address_suffix}'
            splicepoints.add(newname, bbvault, splicevault)
            if alignment:
                low = alignment.lower()
                if 'fiber' in low or 'existing' in low or 'empty' in low:
                    fiberonly_segments.add(alignment)
                else:
                    self.copy_segment(self.dropductfolder, alignment, '#dropduct', newname=newname)
            else:
                self._add_fiber_segment('#fiber', newname=newname)

        pass
        self._copy_polygons_near(self.config.get('design_polygon_proximity', 20))

    def _add_fiber_segment(self, styleurl, newname=None):
        pass

    def _copy_polygons_near(self, distance_feet):
        """Copys any polygon within distance_feet of self.allduct."""
        dilated = self.allduct.buffer(distance_feet * Position.DEGREES_FEET_FACTOR)
        def _find(name, elem, folder):
            g = getattr(elem, 'geometry', None)
            return (name, elem) if isinstance(g, polygon.Polygon) and dilated.intersects(g) else None
        styles_by_id = { style.id: style for style in self.surveydoc.styles() }
        styleids_needed = set()
        polygons = fastkmlutils.Collector(_find).collect(self.surveydoc)
        with_colon = sorted([(name, elem) for (name, elem) in polygons if ':' in name])
        no_colon = sorted([(name, elem) for (name, elem) in polygons if ':' not in name])
        for (name, elem) in (with_colon + no_colon):
            styleids_needed |= self.copy_polygon(self.roadsfolder, name, elem)
        styleids_present = set()
        while styleids_needed - styleids_present:
            for style in self.surveydoc.styles():
                if style.id in styleids_needed and style.id not in styleids_present:
                    self.designdoc.append_style(style)
                    styleids_present.add(style.id)
                    if isinstance(style, styles.StyleMap):
                        styleids_needed.add(style.normal.url[1:])
                        styleids_needed.add(style.highlight.url[1:])
        tienames = { self.config.get('polygons', {}).get(n, [[None]])[0][0] for (n, e) in (with_colon + no_colon) }
        ties = fastkmlutils.Collector(lambda n, e, f: e if n and n in tienames else None).collect(self.surveydoc)
        notfound = tienames - { e.name for e in ties } - {None}
        assert not notfound, notfound
        for elem in ties:
            self._copy_placemark(elem, self.roadsfolder, elem.name, styleUrl='#monument')

    def copy_polygon(self, folder, name, elem):
        if elem.description and ('OBSTACLE' in elem.description or 'NODESIGN' in elem.description):
            return set()
        newpmark = kml.Placemark(name=name, styleUrl=elem.styleUrl)
        newpmark.description = elem.description
        newpmark.geometry = elem.geometry
        folder.append(newpmark)
        return { elem.styleUrl[1:] } if elem.styleUrl else set()

    def copy_segment(self, folder, pmarkname, styleUrl, duct=None, method=None, newname=None):
        pmark = fastkmlutils.Collector(lambda n, e, f: e if n == pmarkname else None).first(self.surveydoc)
        if not pmark:
            raise GeofibDesignError(f'missing segment {pmarkname}')
        d = pmark.description
        if d:
            if duct and duct not in d:
                d += f'<br>Product: {duct}'
            if method and method not in d:
                d += f'<br>Installation method: {method}'
        elif duct or method:
            d = f'Product: {duct}<br>Installation method: {method}'
            self._add_allduct(pmark.geometry)
        if isinstance(pmark.geometry, geometry.LineString):
            lenspec = f' - {self.get_vincenty_length(pmark.geometry.coords)} FT'
        else:
            lenspec = ''
        fullname = (newname if newname else pmarkname) + lenspec
        newpmark = kml.Placemark(name=fullname, styleUrl=styleUrl)
        newpmark.description = d
        newpmark.geometry = pmark.geometry
        folder.append(newpmark)

    def get_vincenty_length(self, coords):
        """Given a coordinate sequence, use Vincenty's inverse to find the length
        in feet of each segment, sum the lengths, and return the sum.
        """
        total = 0
        a, b = itertools.tee(coords)
        next(b, None)
        for (pos1, pos2) in zip(a, b):
            (r, bearing, reverse) = vincenty.rangebearing_from_positions(pos1[1], pos1[0], pos2[1], pos2[0])
            total += r * Position.FEET_METERS_FACTOR
        return 10 * math.ceil(total/10)

    def copy_vault(self, folder, pmarkname, styleUrl):
        pmark = fastkmlutils.Collector(lambda n, e, f: e if n == pmarkname else None).first(self.surveydoc)
        if not pmark:
            raise GeofibDesignError(f'missing vault {pmarkname}')
        self._copy_placemark(pmark, folder, pmarkname, styleUrl)

    def _copy_placemark(self, pmark, folder, pmarkname, styleUrl):
        newpmark = kml.Placemark(name=pmarkname, styleUrl=styleUrl)
        newpmark.description = pmark.description
        newpmark.geometry = pmark.geometry
        folder.append(newpmark)

    def emit(self, filename=None):
        if filename is None:
            return self.emit(self.config['designoutput'])
        if filename.endswith('.kml'):
            fastkmlutils.write_kml_file(filename, self.design, prettyprint=True)
        elif filename.endswith('.kmz'):
            fastkmlutils.write_kmz_file(filename, self.design, prettyprint=True)
        else:
            raise GeofibDesignError(f'unknown format for {filename}')

        LOGGER.info(f'wrote design to {filename}')
