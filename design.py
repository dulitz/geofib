"""
design.py - 

"""

import itertools, logging, math, shapely.ops, time

from fastkml import kml, styles, geometry
from shapely.geometry import polygon

import fastkmlutils, vincenty

from cogo import Position, angle_as_dms_string

LOGGER = logging.getLogger('geofib.design')


class GeofibDesignError(Exception):
    pass


def get_vincenty_length(coords):
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



class Vault:
    """Represents a vault.

    The parent of a vault is the vault closer to the head end. Does not support more than
    one path between a vault and the head end.
    """
    def __init__(self, name, coords):
        """We have a name and coordinates representing our location.
        """
        self.name, self.coords = name, coords
        self.parent, self.path_to_parent, self.microducts = None, None, 0
        self.name_to_child = {}
        self.splices = set()        # demarcs spliced at this vault
        self.trunk_carries = set()  # demarcs carried upstream on trunk fiber
        self.duct_carries = set()   # demarcs carried upstream in drop microduct

    def _nearest_vertex_in(self, alignment_geo):
        return shapely.ops.snap(geometry.Point(self.coords), alignment_geo, 0)

    def set_parent(self, parent, alignment_geo, microducts):
        """Set our parent, which must be a Vault instance. Alignment_coords is a sequence
        of coordinates representing vertices along a path by which we are connected to parent.
        Microducts is the width (number of microducts) available along that path.
        """
        if self.parent:
            raise GeofibDesignError(f'vault {self.name} has parent {self.parent.name} now {parent.name}')
        self.parent, self.microducts = parent, microducts
        ours = self._nearest_vertex_in(alignment_geo)
        theirs = parent._nearest_vertex_in(alignment_geo)
        ours_dist = alignment_geo.project(ours)
        theirs_dist = alignment_geo.project(theirs)
        self.path_to_parent = shapely.ops.substring(alignment_geo, ours_dist, theirs_dist)

    def add_child(self, child):
        if child.name in self.name_to_child:
            raise GeofibDesignError(f'vault {self.name} already has child {child.name}')
        self.name_to_child[child.name] = child

    def set_splicepoint_for(self, name):
        self.splices.add(name)
        upstream = self
        while upstream:
            upstream.trunk_carries.add(name)
            upstream = upstream.parent

    def set_duct_carries(self, name):
        self.duct_carries.add(name)

    def ancestors(self, stop_set=set(), for_each=lambda v: v):
        if self.name in stop_set:
            return []
        return [for_each(self)] + (self.parent.ancestors(stop_set, for_each) if self.parent else [])


class FiberManager:
    def __init__(self, name_to_coords):
        self.name_to_coords = name_to_coords
        self.name_to_vault = {}

    def _get_vault(self, name, parent, alignment_geo, microducts):
        v = self.name_to_vault.get(name, None)
        if not v:
            v = Vault(name, self.name_to_coords[name][0])
            self.name_to_vault[name] = v
        if parent:
            v.set_parent(parent, alignment_geo, microducts)
            parent.add_child(v)
        return v

    def set_alignment(self, alignmentname, microducts, vaultlist):
        alignment_geo = geometry.LineString(self.name_to_coords[alignmentname])
        parent = None
        for name in vaultlist:
            parent = self._get_vault(name, parent, alignment_geo, microducts)

    def get_head_end(self):
        head_end = None
        for vault in self.name_to_vault.values():
            if not vault.parent:
                if head_end:
                    raise GeofibDesignError(f'multiple head-end vaults {head_end.name} and {vault.name}')
                else:
                    head_end = vault
        assert head_end
        return head_end

    def get_max_trunk_width(self):
        return max([len(vault.trunk_carries) for vault in self.name_to_vault.values()])

    def get_splicepoints(self):
        return [vault for vault in self.name_to_vault.values() if vault.splices]

    # the drop fiber runs from the demarc
    #   to whichever end of the drop duct alignment is closest, as the crow flies
    #   along the drop duct alignment to the other end
    #   to the bbvault, as the crow flies
    #   to the splicevault, along the backbone duct alignment

    def add_fiber_drop(self, demarcname, alignment, bbvaultname, splicevaultname):
        coords = [self.name_to_coords[demarcname][0]]
        if alignment:
            first = get_vincenty_length([coords[0], alignment[0]])
            last = get_vincenty_length([coords[0], alignment[-1]])
            coords.extend(alignment if first < last else reversed(alignment))
        bbvault = self.name_to_vault[bbvaultname]
        splicevault = self.name_to_vault[splicevaultname]
        splicevault.set_splicepoint_for(demarcname)
        bba_names = { v.name for v in bbvault.ancestors() }
        sva_names = { v.name for v in splicevault.ancestors() }
        common = bba_names.intersection(sva_names)
        bbvault.ancestors(stop_set=common, for_each=lambda v: (v.set_duct_carries(demarcname) or 1) and coords.extend(v.path_to_parent.coords))
        revme = []
        splicevault.ancestors(stop_set=common, for_each=lambda v: (v.set_duct_carries(demarcname) or 1) and revme.extend(v.path_to_parent.coords))
        return [(x, y, z[0] if z else 0) for (x, y, *z) in itertools.chain(coords, reversed(revme))]


class Design:
    def __init__(self, config, surveydoc, source_to_basis_adjustmentlist):
        self.config, self.surveydoc = config, surveydoc
        self.source_to_basis_adjustmentlist = source_to_basis_adjustmentlist
        self.allduct = None
        self.design = kml.KML()
        self.design.append(kml.Document())
        self.designdoc = next(self.design.features())
        self.bbductfolder = kml.Folder(name='BB Duct')
        self.designdoc.append(self.bbductfolder)
        self.bbvaultsfolder = kml.Folder(name='BB Vaults')
        self.designdoc.append(self.bbvaultsfolder)
        self.dropductfolder = kml.Folder(name='Drop Duct')
        self.designdoc.append(self.dropductfolder)
        self.splicefolders_by_name = {}
        self.roadsfolder = kml.Folder(name='Roads, Monuments, & Rights')

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

    def _get_splicefolder(self, name):
        f = self.splicefolders_by_name.get(name, None)
        if not f:
            f = kml.Folder(name=name)
            self.splicefolders_by_name[name] = f
        return f

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

        def _coords(name, elem, folder):
            g = getattr(elem, 'geometry', None)
            if isinstance(g, polygon.Polygon):
                return (name, g.exterior.coords)
            return (name, g.coords) if g else None
        geoelements = fastkmlutils.Collector(_coords).collect(self.surveydoc)
        name_to_coords = { n: coords for (n, coords) in geoelements }

        fm = FiberManager(name_to_coords)
        distance_by_installmethod = {}
        distance_by_ducttype = {}
        for (name, duct, installmethod, microducts, *vaults) in self.config['backbone']:
            try:
                int(microducts)
            except ValueError:
                raise GeofibDesignError(f'backbone segment {name} has bad duct count {microducts}')
            fm.set_alignment(name, microducts, vaults)
            length = self.copy_segment(self.bbductfolder, name, '#bbduct', duct, installmethod)
            assert vaults
            all_vaults.update(vaults)
            def _update(map, key, val):
                map[key] = map.get(key, 0) + val
            _update(distance_by_ducttype, duct, length)
            _update(distance_by_installmethod, installmethod, length)

        for name in sorted(all_vaults):
            self.copy_vault(self.bbvaultsfolder, name, '#vault')

        drop_fiber_segments = []
        for (demarc, address_suffix, alignment, bbvault, splicevault) in self.config['drops']:
            cleaned = [v for v in demarc.strip().strip('!~?*').split() if v != 'FDEMARC']
            if address_suffix:
                cleaned = cleaned[1:] + cleaned[0:1] + [address_suffix]
            newname = ' '.join(cleaned)
            if alignment:
                low = alignment.lower()
                if not ('fiber' in low or 'existing' in low or 'empty' in low):
                    self.copy_segment(self.dropductfolder, alignment, '#dropduct', newname=newname)
            if demarc not in name_to_coords:
                raise GeofibDesignError(f'demarc {demarc} not in survey')
            if alignment and alignment not in name_to_coords:
                raise GeofibDesignError(f'drop alignment {alignment} not in survey')
            fa = fm.add_fiber_drop(demarc, name_to_coords[alignment] if alignment else [], bbvault, splicevault)
            vlen = get_vincenty_length(fa)
            drop_fiber_segments.append(vlen)
            pmark = kml.Placemark(name=f'{newname} - {vlen} FT', styleUrl='#fiber')
            pmark.geometry = geometry.LineString(fa)
            self._get_splicefolder(f'Drop Cables {splicevault}').append(pmark)

        self._copy_polygons_near(self.config.get('design_polygon_proximity', 20))

        for (name, folder) in sorted(self.splicefolders_by_name.items()):
            self.designdoc.append(folder)
        self.designdoc.append(self.roadsfolder)

        vaults = fm.name_to_vault.values()
        splices = [(len(v.splices), v.name, v) for v in vaults if v.splices]
        print()
        print(f'Design Characteristics')
        print(f'{self.designdoc.name}, generated {time.ctime()}')
        print()
        print(f'{len(vaults)} vaults including head-end {fm.get_head_end().name}')
        print(f'{sum([len(v.splices) for v in vaults])} backbone splices at {len(splices)} splice points: {" ".join(sorted([s[1] for s in splices]))}')
        print(f'max trunk width: {max([len(v.trunk_carries) for v in vaults if v.parent])} strands')
        #for v in vaults:
        #    print(f'{v.name} ({v.microducts} microducts and {len(v.trunk_carries)} trunk strands):\t\t{", ".join(v.duct_carries)}')
        ductwidth = [((len(v.duct_carries) + (1 if v.trunk_carries else 0)), v.name, v) for v in vaults if v.parent]
        maxdw = max(ductwidth)[0]
        print(f'max duct width: {maxdw} microducts at {" ".join(sorted([n for (w, n, v) in ductwidth if w == maxdw]))}')
        minfree = min([(v.microducts - w) for (w, n, v) in ductwidth])
        print(f'min microducts free: {minfree} at {" ".join([n for (w, n, v) in ductwidth if v.microducts - w == minfree])}')
        print(f'{len(drop_fiber_segments)} drops, total {sum(drop_fiber_segments)} feet of drop fiber, longest fiber drop {max(drop_fiber_segments)} feet')

        print(f'\nBackbone duct lengths by type')
        for (dtype, dist) in sorted(distance_by_ducttype.items()):
            print(f'\t{dtype}: {dist} feet')
        print(f'\nBackbone lengths by install method')
        for (method, dist) in sorted(distance_by_installmethod.items()):
            print(f'\t{method}: {dist} feet')

        print(f'\nTable of Rights')
        for (name, elem) in sorted(self.polygons):
            if ':' in name:
                print('\t' + self._rights_for(elem))
        print(f'\nTable of Authorities')
        for (source, adjustmentlist) in sorted(self.source_to_basis_adjustmentlist.items()):
            if len(adjustmentlist) != 1:
                raise GeofibDesignError(f'{source} has multiple basis adjustments: {", ".join(adjustmentlist)}')
            adj = adjustmentlist[0]
            if adj:
                print(f'\t{source}\t\tBasis adjusted by {angle_as_dms_string(adj)}')
            else:
                print(f'\t{source}\t\tBasis not adjusted')

    def _rights_for(self, elem):
        cogospec = self.config.get('polygons', {}).get(elem.name, [])
        if not cogospec:
            d = elem.description if elem.description else 'drawn manually'
            return f'{elem.name}\t{d}'
        (tie_name, *topcomment) = cogospec[0]
        authorities = [a[1] for a in cogospec[1:] if a[0].lower() == 'authority']
        return f'{elem.name}\t\t{", ".join(authorities)}\t{tie_name}'

    def _copy_polygons_near(self, distance_feet):
        """Copys any polygon within distance_feet of self.allduct."""
        dilated = self.allduct.buffer(distance_feet * Position.DEGREES_FEET_FACTOR)
        def _find(name, elem, folder):
            g = getattr(elem, 'geometry', None)
            return (name, elem) if isinstance(g, polygon.Polygon) and dilated.intersects(g) else None
        styles_by_id = { style.id: style for style in self.surveydoc.styles() }
        styleids_needed = set()
        self.polygons = fastkmlutils.Collector(_find).collect(self.surveydoc)
        with_colon = sorted([(name, elem) for (name, elem) in self.polygons if ':' in name])
        no_colon = sorted([(name, elem) for (name, elem) in self.polygons if ':' not in name])
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
            length = get_vincenty_length(pmark.geometry.coords)
            lenspec = f' - {length} FT'
        else:
            length = 0
            lenspec = ''
        fullname = (newname if newname else pmarkname) + lenspec
        newpmark = kml.Placemark(name=fullname, styleUrl=styleUrl)
        newpmark.description = d
        newpmark.geometry = pmark.geometry
        folder.append(newpmark)
        return length

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
