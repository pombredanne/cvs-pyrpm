#
# Copyright (C) 2006 Red Hat, Inc.
# Authors: Florian Festi <ffesti@redhat.com>
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

import pyrpm.openpgp as openpgp
import db

try:
    from itertools import chain
except ImportError:

    def chain(*iterables):
        for it in iterables:
            for element in it:
                yield element


class JointDB(db.RpmDatabase):

    def __init__(self, config, source, buildroot=''):
        self.dbs = []

        self.config = config
        self.source = source
        self.buildroot = buildroot
        self.clear()
        self.keyring = openpgp.PGPKeyRing()
        self.is_read = 0                # 1 if the database was already read

    def __contains__(self, pkg):
        for db in self.dbs:
            if pkg in db:
                return True
        return False

    def isIdentitySave(self):
        """return if package objects that are added are in the db afterwards
        (.__contains__() returns True and the object are return from searches)
        """
        return False # does not support .addPkg()

    def addDB(self, db):
        self.dbs.append(db)

    def removeDB(self, db):
        self.dbs.remove(db)

    def removeAllDBs(self):
        self.dbs[:] = []

    # clear all structures
    def clear(self):
        for db in self.dbs:
            db.clear()

    def clearPkgs(self, tags=None, ntags=None):
        for db in self.dbs:
            db.clearPkgs(tags, ntags)

    def setBuildroot(self, buildroot):
        """Set database chroot to buildroot."""
        self.buildroot = buildroot

    def open(self):
        """If the database keeps a connection, prepare it."""
        for db in self.dbs:
            result = db.open()
            if result != self.OK:
                return result
        return self.OK

    def close(self):
        """If the database keeps a connection, close it."""
        for db in self.dbs:
            result = db.close()
            if result != self.OK:
                return result
        return self.OK

    def read(self):
        """Read the database in memory."""
        for db in self.dbs:
            result = db.read()
            if result != self.OK:
                return result
        return self.OK

    def _merge_search_results(self, dicts):
        result = {}
        for result_dict in dicts:
            for key, pkgs in result_dict.iteritems():
                if result.has_key(key):
                    result[key].extend(pkgs)
                else:
                    result[key] = pkgs
        return result

    # add package
    def addPkg(self, pkg):
        raise NotImplementedError

    # remove package
    def removePkg(self, pkg):
        raise NotImplementedError

    def searchName(self, name):
        result = []
        for db in self.dbs:
            result.extend(db.searchName(name))
        return result

    def getPkgs(self):
        result = []
        for db in self.dbs:
            result.extend(db.getPkgs())
        return result

    def getNames(self):
        result = []
        for db in self.dbs:
            result.extend(db.getNames())
        return result

    def hasName(self, name):
        for db in self.dbs:
            if db.hasName(name):
                return True
        return False

    def getPkgsByName(self, name):
        result = []
        for db in self.dbs:
            result.extend(db.getPkgsByName(name))
        return result

    def getProvides(self):
        result = []
        for db in self.dbs:
            result.extend(db.getProvides())
        return result

    def getFilenames(self):
        result = []
        for db in self.dbs:
            result.extend(db.getfilenames())
        return result

    def numFileDuplicates(self, filename):
        result = 0
        for db in self.dbs:
            result += db.getFileDuplicates()
        return result

    def getFileDuplicates(self): # XXXXXXXXXX
        raise NotImplementedError
        result = {}
        for db in self.dbs:
            files = db.getFileDuplicates()
            for file, pkgs in files.iteritems():
                if result.has_key(file):
                    result[file].extend(pkgs)
                else:
                    result[file] = pkgs
        return result

    def getFileRequires(self):
        result = []
        for db in self.dbs:
            result.extend(db.getFileRequires())
        return result

    def getPkgsFileRequires(self):
        result = {}
        for db in self.dbs:
            result.update(db.getPkgsFileRequires())
        return result

    def iterProvides(self):
        return chain(*[db.iterProvides() for db in self.dbs])

    def iterRequires(self):
        return chain(*[db.iterRequires() for db in self.dbs])

    def iterConflicts(self):
        return chain(*[db.iterConflicts() for db in self.dbs])

    def iterObsoletes(self):
        return chain(*[db.iterObsoletes() for db in self.dbs])

    def iterTriggers(self):
        return chain(*[db.iterTriggers() for db in self.dbs])

    def reloadDependencies(self):
        for db in self.dbs: db.reloadDependencies()

    def searchPkgs(self, names):
        result = []
        for db in self.dbs:
            result.extend(db.searchPkgs(names))
        return result

    def search(self, names):
        result = []
        for db in self.dbs:
            result.extend(db.search(names))
        return result

    def searchProvides(self, name, flag, version):
        return self._merge_search_results(
            [db.searchProvides(name, flag, version)
             for db in self.dbs])

    def searchFilenames(self, filename):
        result = []
        for db in self.dbs:
            result.extend(db.searchFilenames(filename))
        return result

    def searchRequires(self, name, flag, version):
        return self._merge_search_results(
            [db.searchRequires(name, flag, version)
             for db in self.dbs])

    def searchConflicts(self, name, flag, version):
        return self._merge_search_results(
            [db.searchConflicts(name, flag, version)
             for db in self.dbs])

    def searchObsoletes(self, name, flag, version):
        return self._merge_search_results(
            [db.searchObsoletes(name, flag, version)
             for db in self.dbs])

    def searchTriggers(self, name, flag, version):
        return self._merge_search_results(
            [db.searchTriggers(name, flag, version)
             for db in self.dbs])

    def searchDependencies(self, name, flag, version):
        return self._merge_search_results(
            [db.searchDependencies(name, flag, version)
             for db in self.dbs])

    def _getDBPath(self):
        raise NotImplementedError

# vim:ts=4:sw=4:showmatch:expandtab
