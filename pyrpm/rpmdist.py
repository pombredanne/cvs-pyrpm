#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Karel Zak
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Library General Public License as published by
# the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#


# classes: RpmDistribution, RpmDistributionCollection
#
# config file format:
#
#   [distribution]
#   name=Fedora Code 3
#   abbreviation=FC-3
#   collections=base,updates
#
#   [base]
#   name=Fedora Code 3 (base)
#   abbreviation=FC-3
#   i386=/path/to/arch/rpms
#   ia64=/path/to/arch/rpms
#
#   [updates]
#   ... like 'base'..
#

import ConfigParser, os
from functions import *
from package import *

class RpmDistribution:

    CONF_MAIN = 'distribution'
    CONF_NAME = 'name'
    CONF_ABBR = 'abbreviation'
    CONF_COLL = 'collections'

    def __init__(self, name=None, abbr=None, config=None):
        self.colls = []     # collections (GA, updates, ...)
        if config:
            self.readConfig(config)
            return
        self.abbr = abbr
        self.name = name

    def readConfig(self, filename):
        """read distribution definition from config file"""
        config = ConfigParser.ConfigParser()
        config.readfp(open(filename))
        self.name = config.get(self.CONF_MAIN, self.CONF_NAME)
        self.abbr = config.get(self.CONF_MAIN, self.CONF_ABBR)
        if len(self.name)==0 or len(self.abbr)==0:
            raise ParsingError, '%s: [%s] missing %s or %s' % \
                    (filename, self.CONF_MAIN, self.CONF_NAME, self.CONF_ABBR)
        r = config.get(self.CONF_MAIN, self.CONF_COLL)
        if r==None or len(r)==0:
            return
        collnames = r.split(',')
        for x in collnames:
            if not config.has_section(x):
                raise ParsingError, "%s: section '%s' missing" % (filename, x)
            name = config.get(x, self.CONF_NAME)
            abbr = config.get(x, self.CONF_ABBR)
            if len(name)==0 or len(abbr)==0:
                raise ParsingError, '%s: [%s] missing %s or %s' % \
                    (filename, x, self.CONF_NAME, self.CONF_ABBR)
            coll = RpmDistributionCollection(self, name, abbr)
            for o in config.options(x):
                if o in [self.CONF_NAME, self.CONF_ABBR]:
                    continue
                coll.appendDirectory(o, config.get(x, o))
            self.appendCollection(coll)
        del config

    def appendCollection(self, coll):
        """add next collection to distribution"""
        if coll not in self.colls:
            self.colls.append(coll)

    def getArchs(self):
        """returns list of supported architectures"""
        return self.getGA().getArchs()

    def getCollections(self):
        """returns list of collections"""
        return self.colls

    def getGA(self):
        """returns GA colllection"""
        return self.colls[0]

    def getCollectionLast(self):
        """returns the latest coll"""
        return self.colls[-1]

    def getCollectionByAbbr(self, abbr):
        """search and returns coll by abbreviation"""
        for c in self.colls:
            if c.abbr == abbr:
                return c
        return None

    def getCollectionByIndex(self, idx):
        return self.colls[idx]

    def getCollectionIndex(self, coll):
        """returns index of collelection"""
        return self.colls.index(coll)

    def getCollectionsTo(self, coll):
        """return list with the collections from GA to 'coll'"""
        colls = []
        for c in self.colls:
            colls.append(c)
            if c.name == coll.name:
                break
        return colls

    def getRpmPackages(self, arch, tags=None):
        pkgs = []
        for c in self.colls:
            pkgs.extend(c.getRpmPackages(arch, tags))
        return pkgs

    def getRpmPackagesLists(self, arch, tags=None):
        pkgs = []
        for c in self.colls:
            pkgs.append(c.getRpmPackages(arch, tags))
        return pkgs


class RpmDistributionCollection:
    """part of distribution, for example GA, updates, extras ..."""

    def __init__(self, distribution, name, abbr):
        self.name = name
        self.abbr = abbr
        self.dirs = {}
        self.dist = distribution

    def getArchDirs(self, arch):
        """returns dirs specific for architecture"""
        if not self.dirs.has_key(arch):
            return []
        return self.dirs[arch]

    def getDirs(self):
        """returns all dirs"""
        return self.dirs.values()

    def getArchFiles(self, arch):
        """returns names of files in architecture"""
        files = []
        for d in self.getArchDirs(arch):
            files.extend( listRpmDir(d) )
        return files

    def getArchFilepaths(self, arch):
        """returns full paths to files"""
        files = []
        for d in self.getArchDirs(arch):
            fs = listRpmDir(d)
            for f in fs:
                files.append(d+'/'+f)
        return files

    def appendDirectory(self, arch, path):
        """add directory with files to collection"""
        if not self.dirs.has_key(arch):
            self.dirs[arch] = []
        if path not in self.dirs[arch]:
            self.dirs[arch].append(path)

    def getArchs(self):
        """returns list of architectures"""
        return self.dirs.keys()

    def getRpmPackages(self, arch, tags=None):
        files = self.getArchFilepaths(arch)
        pkgs = []
        for f in files:
            printDebug(2, "%04d: reading %s" % (len(pkgs), f))
            pkg = readRpmPackage('file:/'+f, tags = tags)
            pkgs.append(pkg)
        return pkgs

# vim:ts=4:sw=4:showmatch:expandtab
