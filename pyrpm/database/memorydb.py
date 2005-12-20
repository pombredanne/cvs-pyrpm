#!/usr/bin/python
#
# (c) 2004, 2005 Red Hat, Inc.
#
# AUTHOR: Thomas Woerner <twoerner@redhat.com>
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
# Copyright 2004, 2005 Red Hat, Inc.
#

import db
import lists

#
# RpmMemoryDB holds all data in memory (lists)
#
class RpmMemoryDB(db.RpmDatabase):

    def __init__(self, config, source, buildroot=None):
        db.RpmDatabase.__init__(self, config, source, buildroot)
        self.config = config
        self.source = source
        self.buildroot = buildroot
        self.pkgs = [ ]   # [pkg, ..]
        self.clear()
        self.__len__ = self.pkgs.__len__
        self.__getitem__ = self.pkgs.__getitem__
        
    def __contains__(self, pkg):
        name = pkg["name"]
        if self.names.has_key(name) and pkg in self.names[name]:
            return pkg
        return None

    # clear all structures
    def clear(self):
        self.pkgs = [ ]   # [pkg, ..]
        self.names = { }  # name: [pkg, ..]

        self.provides_list = lists.ProvidesList(self.config)
        self.filenames_list = lists.FilenamesList()
        self.requires_list = lists.RequiresList(self.config)
        self.conflicts_list = lists.ConflictsList(self.config)
        self.obsoletes_list = lists.ObsoletesList(self.config)
        self.triggers_list = lists.TriggersList(self.config)

    def open(self):
        """If the database keeps a connection, prepare it."""
        return self.OK

    def close(self):
        """If the database keeps a connection, close it."""
        return self.OK

    def read(self):
        """Read the database in memory."""
        return self.OK

    # add package
    def addPkg(self, pkg):
        name = pkg["name"]
        if self.names.has_key(name) and pkg in self.names[name]:
            return self.ALREADY_INSTALLED
        self.pkgs.append(pkg)
        self.names.setdefault(name, [ ]).append(pkg)

        self.provides_list.addPkg(pkg)
        self.filenames_list.addPkg(pkg)
        self.requires_list.addPkg(pkg)
        self.conflicts_list.addPkg(pkg)
        self.obsoletes_list.addPkg(pkg)
        self.triggers_list.addPkg(pkg)

        return self.OK

    # add package list
    def addPkgs(self, pkgs):
        for pkg in pkgs:
            self.addPkg(pkg)

    # remove package
    def removePkg(self, pkg):
        name = pkg["name"]
        if not self.names.has_key(name) or not pkg in self.names[name]:
            return self.NOT_INSTALLED
        self.pkgs.remove(pkg)
        self.names[name].remove(pkg)
        if len(self.names[name]) == 0:
            del self.names[name]

        self.provides_list.removePkg(pkg)
        self.filenames_list.removePkg(pkg)
        self.requires_list.removePkg(pkg)
        self.conflicts_list.removePkg(pkg)
        self.obsoletes_list.removePkg(pkg)
        self.triggers_list.removePkg(pkg)

        return self.OK

    def searchName(self, name):
        if self.names.has_key(name):
            return self.names[name]
        return [ ]
    
    def getPkgs(self):
        return self.pkgs
    
    def getNames(self):
        return self.names.keys()

    def hasName(self, name):
        return self.names.has_key(name)

    def getPkgsByName(self, name):
        if self.names.has_key(name):
            return self.names[name]
        return [ ]

    def getProvides(self):
        return self.provides_list
    
    def getFilenames(self):
        return self.filenames_list

    def isFileDuplicate(self, filename):
        return self.filenames_list.isDuplicate(filename)

    def getFileDuplicates(self):
        return self.filenames_list.duplicates()

    def getRequires(self):
        return self.requires_list
    
    def getConflicts(self):
        return self.conflicts_list

    def getObsoletes(self):
        return self.obsoletes_list

    def getTriggers(self):
        return self.triggers_list

    # reload dependencies: provides, filenames, requires, conflicts, obsoletes
    # and triggers
    def reloadDependencies(self):
        self.provides_list.clear()
        self.filenames_list.clear()
        self.requires_list.clear()
        self.conflicts_list.clear()
        self.obsoletes_list.clear()
        self.triggers_list.clear()

        for pkg in self.pkgs:
            self.provides_list.addPkg(pkg)
            self.filenames_list.addPkg(pkg)
            self.requires_list.addPkg(pkg)
            self.conflicts_list.addPkg(pkg)
            self.obsoletes_list.addPkg(pkg)
            self.triggers_list.addPkg(pkg)

    def searchProvides(self, name, flag, version):
        return self.provides_list.search(name, flag, version)
    
    def searchFilenames(self, filename):
        return self.filenames_list.search(filename)

    def searchRequires(self, name, flag, version):
        return self.requires_list.search(name, flag, version)

    def searchConflicts(self, name, flag, version):
        return self.conflicts_list.search(name, flag, version)

    def searchObsoletes(self, name, flag, version):
        return self.obsoletes_list.search(name, flag, version)

    def searchTriggers(self, name, flag, version):
        return self.trigger_list.search(name, flag, version)

    def searchDependency(self, name, flag, version):
        """Return list of RpmPackages from self.names providing
        (name, RPMSENSE_* flag, EVR string) dep."""
        s = self.searchProvides(name, flag, version)
        if name[0] == '/': # all filenames are beginning with a '/'
            s += self.searchFilenames(name)
        return s

    def _getDBPath(self):
        """Return a physical path to the database."""

        if   self.source[:6] == 'pydb:/':
            tsource = self.source[6:]
        elif self.source[:7] == 'rpmdb:/':
            tsource = self.source[7:]
        else:
            tsource = self.source
        if self.buildroot != None:
            return self.buildroot + tsource
        else:
            return tsource

# ----------------------------------------------------------------------------
