"""
design.py - 

"""

import logging

from fastkml import kml, styles, geometry
from shapely.geometry import polygon

import fastkmlutils

LOGGER = logging.getLogger('geofib.design')


class GeofibDesignError(Exception):
    pass


class Design:
    def __init__(self, config, surveydoc):
        self.config = config
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

        kmliconprefix = self.config.get('kmliconprefix', 'icons/')
        def _add(name, color, normwidth, highwidth):
            self.designdoc.append_style(styles.Style(id=f'{name}norm', styles=[styles.LineStyle(color=color, width=normwidth)]))
            self.designdoc.append_style(styles.Style(id=f'{name}high', styles=[styles.LineStyle(color=color, width=highwidth)]))
            self.designdoc.append_style(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{name}norm'), highlight=styles.StyleUrl(url=f'#{name}high')))
        bbductwidth = self.config.get('bbductwidth', 1)
        _add('bbduct', self.config.get('bbductcolor', '#ff0080ff'), bbductwidth, 2*bbductwidth)
        dropductwidth = self.config.get('dropductwidth', 1)
        _add('dropduct', self.config.get('dropductcolor', 'green'), dropductwidth, 2*dropductwidth)
        fiberwidth = self.config.get('fiberwidth', 1)
        _add('fiber', self.config.get('fibercolor', 'blue'), fiberwidth, 2*fiberwidth)
        def _addicon(name, file, iconscale, labelscale):
            self.designdoc.append_style(styles.Style(id=f'{name}norm', styles=[styles.IconStyle(scale=iconscale, icon_href=f'{kmliconprefix}{file}'), styles.LabelStyle(scale=0)]))
            self.designdoc.append_style(styles.Style(id=f'{name}high', styles=[styles.IconStyle(scale=iconscale, icon_href=f'{kmliconprefix}{file}'), styles.LabelStyle(scale=labelscale)]))
            self.designdoc.append_style(styles.StyleMap(id=name, normal=styles.StyleUrl(url=f'#{name}norm'), highlight=styles.StyleUrl(url=f'#{name}high')))
        _addicon('vault', self.config.get('vaulticon', 'square.png'), self.config.get('iconscale', 0.5), 1.0)

    def calculate(self):
        self.designdoc.name = self.config.get('designname', '')
        self.designdoc.description = self.config.get('designdescription', '')
        self.designdoc.author = self.config.get('designauthor', '')
        all_vaults = set()
        for (name, duct, installmethod, *vaults) in self.config['backbone']:
            self.copy_segment(self.bbductfolder, name, '#bbduct', duct, installmethod)
            assert vaults
            all_vaults.update(vaults)
        for name in sorted(all_vaults):
            self.copy_vault(self.bbvaultsfolder, name, '#vault')
        for (demarc, alignment, bbvault, splicevault) in self.config['drops']:
            if alignment:
                low = alignment.lower()
                if 'fiber' in low or 'existing' in low or 'empty' in low:
                    # it's fiber, not duct, and we don't handle that yet
                    pass
                else:
                    self.copy_segment(self.dropductfolder, alignment, '#dropduct', newname=alignment.strip().split()[0])

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
        newpmark = kml.Placemark(name=newname if newname else pmarkname, styleUrl=styleUrl)
        newpmark.description = d
        newpmark.geometry = pmark.geometry
        folder.append(newpmark)

    def copy_vault(self, folder, pmarkname, styleUrl):
        pmark = fastkmlutils.Collector(lambda n, e, f: e if n == pmarkname else None).first(self.surveydoc)
        if not pmark:
            raise GeofibDesignError(f'missing vault {pmarkname}')
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
