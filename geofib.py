"""
geofib.py


"""

import logging
import yaml

from zipfile import ZipFile
from fastkml import kml

LOGGER = logging.getLogger('geofib')


class GeofibError(Exception):
    pass


class Geofib:
    def __init__(self, config=None):
        self.config = config or {}
        self.doc = kml.KML()

    @property
    def fixnames(self):
        structname = 'Structures, Fences, and Edges'
        drivename = 'Driveways, Roads, and Monuments'
        elecname = 'Electric'
        wgwname = 'Water, Gas, and Wastewater'
        commname = 'Communications'
        return {
            'FENCE': (structname, ),
            'BLDG': (structname, ),
            'tree': (structname, ),
            
            'EOP': (drivename, ),
            'DWY': (drivename, ),
            'CROWN': (drivename, ),
            'MONSTR': (drivename, ),
            
            'WWLAT': (wgwname, ),
            'WWMH': (wgwname, ),
            'WWCO': (wgwname, ),
            'WTMAIN': (wgwname, ),
            'WTTEE': (wgwname, ),
            'WTSVC': (wgwname, ),
            'WTFH': (wgwname, ),
            'WTFS': (wgwname, ), # fire standpipe
            'WTVMAIN': (wgwname, ),
            'WTVFH': (wgwname, ),
            'WTVFS': (wgwname, ),
            'WTVSVC': (wgwname, ),
            'WTVBLDG': (wgwname, ),
            'WTV': (wgwname, ),
            'WTLINESTOP': (wgwname, ),
            'WTM': (wgwname, ),
            'WTANOBOX': (wgwname, ),
            'STIN': (wgwname, ),
            'gas ': (wgwname, ),
            'propane': (wgwname, ),
            'storm': (wgwname, ),
            'irrig': (wgwname, ),
            
            'ELVLT': (elecname, ),
            'ELSVC': (elecname, ),
            'XFRMR': (elecname, ),
            'electric': (elecname, ),
            
            'TELVAULT': (commname, ),
            'FVAULT': (commname, ),
            'FDEMARC': (commname, )
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
        if getattr(elem, 'features', None):
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
            return 0
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
        (first, sep, quality) = elem.description.partition('Fix Quality: ')
        if not sep:
            return 0
        def fix(e, prefix):
            suffix = e.name.lstrip('*!?')
            e.name = prefix + suffix
        if quality.startswith('DGPS'):
            if not elem.name.startswith('!'):
                fix(elem, '!')
                LOGGER.info(f'{elem.name} set prefix for DGPS')
        elif quality.startswith('RTK Fix'):
            if not elem.name.startswith('*'):
                fix(elem, '*')
                LOGGER.info(f'{elem.name} set prefix for RTK Fix')
        elif quality.startswith('RTK Float'):
            if elem.name.startswith('*') or elem.name.startswith('!'):
                fix(elem, '')
                LOGGER.info(f'{elem.name} set prefix for RTK Float')
        elif quality.startswith('Single'):
            if not elem.name.startswith('?'):
                fix(elem, '?')
                LOGGER.info(f'{elem.name} set prefix for Single')
        else:
            LOGGER.warning(f'{elem.name} unknown quality {quality}')
        return 1

    def emit(self, filename=None, prettyprint=None):
        if filename is None:
            return self.emit(self.config['output'], prettyprint)
        if prettyprint is None:
            return self.emit(filename, self.config.get('prettyprint', False))
        if filename.endswith('.kml'):
            with open(filename, 'wt') as f:
                f.write(self.doc.to_string(prettyprint=prettyprint))
        elif filename.endswith('.kmz'):
            LOGGER.fatal('.kmz format not implemented yet')
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
    if config.get('output'):
        g.emit()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
