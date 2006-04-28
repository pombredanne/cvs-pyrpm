#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Thomas Woerner <twoerner@redhat.com>
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

import os
import pyrpm.functions as functions
from pyrpm.base import RPMSENSE_EQUAL

def genBasenames2(oldfilenames):
    (basenames, dirnames) = ([], [])
    for filename in oldfilenames:
        (dirname, basename) = os.path.split(filename)
        if dirname[-1:] != "/":
            dirname += "/"
        basenames.append(basename)
        dirnames.append(dirname)
    return (basenames, dirnames)

class FilenamesList:
    """A mapping from filenames to RpmPackages."""

    def __init__(self):
        self.clear()

    def clear(self):
        """Clear the mapping."""
        self.path = { } # dirname => { basename => RpmPackage }

    def addPkg(self, pkg):
        """Add all files from RpmPackage pkg to self."""
        path = self.path
        basenames = pkg["basenames"]
        if basenames != None:
            dirindexes = pkg["dirindexes"]
            dirnames = pkg["dirnames"]
            for dirname in dirnames:
                path.setdefault(dirname, {})
            dirnames = [ dirnames[di] for di in dirindexes ]
        else:
            if pkg["oldfilenames"] == None:
                return
            (basenames, dirnames) = genBasenames2(pkg["oldfilenames"])
            for dirname in dirnames:
                path.setdefault(dirname, {})
        for i in xrange(len(basenames)):
            path[dirnames[i]].setdefault(basenames[i], []).append(pkg)

    def removePkg(self, pkg):
        """Remove all files from RpmPackage pkg from self."""
        basenames = pkg["basenames"]
        if basenames != None:
            dirindexes = pkg["dirindexes"]
            dirnames = pkg["dirnames"]
            dirnames = [ dirnames[di] for di in dirindexes ]
        else:
            if pkg["oldfilenames"] == None:
                return
            (basenames, dirnames) = genBasenames2(pkg["oldfilenames"])
        for i in xrange(len(basenames)):
            self.path[dirnames[i]][basenames[i]].remove(pkg)

    def numDuplicates(self, filename):
        (dirname, basename) = os.path.split(filename)
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        return len(self.path.get(dirname, {}).get(basename, {}))

    def duplicates(self):
        dups = { }
        for dirname in self.path.keys():
            for filename in self.path[dirname].keys():
                if len(self.path[dirname][filename]) > 1:
                    dups[dirname + filename] = self.path[dirname][filename]
        return dups

    def search(self, name):
        """Return list of packages providing file with name.

        The list may point to internal structures of FilenamesList and may be
        changed by calls to addPkg() and removePkg()."""
        (dirname, basename) = os.path.split(name)
        if dirname[-1:] != "/":
            dirname += "/"
        return self.path.get(dirname, {}).get(basename, [])


class ProvidesList:
    """A database of Provides:

    Files are represented as (filename, 0, "")."""
    TAG = "provides"

    # TODO: add key, __getitem__, ..

    def __init__(self):
        self.hash = { }
        ProvidesList.clear(self)
        self.__len__ = self.hash.__len__
        self.__getitem__ = self.hash.__getitem__
        self.has_key = self.hash.has_key
        self.keys = self.hash.keys

    def clear(self):
        """Discard all stored data"""

        # %name => [(flag, EVR string, providing RpmPackage)]
        self.hash.clear()

    def addPkg(self, rpm):
        """Add Provides: by RpmPackage rpm. If no self provide is done it will
        be added automatically."""

        for (name, flag, version) in rpm[self.TAG]:
            self.hash.setdefault(name, [ ]).append((flag, version, rpm))
        sver = rpm.getEVR()
        if (rpm["name"], RPMSENSE_EQUAL, sver) not in rpm[self.TAG]:
            self.hash.setdefault(rpm["name"], [ ]).append((RPMSENSE_EQUAL, sver, rpm))

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm[self.TAG]:
            list = self.hash[name]
            list.remove( (flag, version, rpm) )
            if len(list) == 0:
                del self.hash[name]
        sname = rpm["name"]
        if not self.hash.has_key(sname):
            return
        list = self.hash[sname]
        sver = rpm.getEVR()
        if (RPMSENSE_EQUAL, sver, rpm) in list:
            list.remove( (RPMSENSE_EQUAL, sver, rpm) )
        if len(list) == 0:
            del self.hash[name]

    def search(self, name, flag, version):
        """Return a list of RpmPackage's matching the Requires:
        (name, RPMSENSE_* flag, EVR string)."""

        if not self.hash.has_key(name):
            return { }
        evr = functions.evrSplit(version)
        ret = { }
        for (f, v, rpm) in self.hash[name]:
            if rpm in ret:
                continue
            if version == "":
                ret.setdefault(rpm, [ ]).append((name, f, v))
                continue
            if functions.rangeCompare(flag, evr, f, functions.evrSplit(v)):
                ret.setdefault(rpm, [ ]).append((name, f, v))
                continue
            if v == "": # compare with package version for unversioned provides
                evr2 = (rpm.getEpoch(), rpm["version"], rpm["release"])
                if functions.evrCompare(evr2, flag, evr):
                    ret.setdefault(rpm, [ ]).append((name, f, v))

        return ret


class ConflictsList(ProvidesList):
    """A database of Conflicts:"""
    TAG = "conflicts"

    def addPkg(self, rpm):
        """Add Provides: by RpmPackage rpm. If no self provide is done it will
        be added automatically."""

        for (name, flag, version) in rpm[self.TAG]:
            self.hash.setdefault(name, [ ]).append((flag, version, rpm))

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm[self.TAG]:
            list = self.hash[name]
            list.remove( (flag, version, rpm) )
            if len(list) == 0:
                del self.hash[name]

    def search(self, name, flag, version):
        # s/Conflicts/Obsoletes/ in ObsoletesList
        """Return a list of RpmPackage's with Conflicts: matching
        (name, RPMSENSE_* flag, EVR string)."""

        if not self.hash.has_key(name):
            return { }
        evr = functions.evrSplit(version)
        ret = { }
        for (f, v, rpm) in self.hash[name]:
            if rpm in ret:
                continue
            if version == "":
                ret.setdefault(rpm, [ ]).append((name, f, v))
                continue
            if functions.rangeCompare(flag, evr, f, functions.evrSplit(v)):
                ret.setdefault(rpm, [ ]).append((name, f, v))
                continue

        return ret


class RequiresList(ConflictsList):
    """A database of Requires:"""
    TAG = "requires"


class ObsoletesList(ConflictsList):
    """A database of Obsoletes:"""
    TAG = "obsoletes"


class TriggersList(ConflictsList):
    """A database of Triggers:"""
    TAG = "triggers"

    def addPkg(self, rpm):
        """Add Provides: by RpmPackage rpm"""

        for (name, flag, version, scriptprog, scripts) in rpm[self.TAG]:
            self.hash.setdefault(name, [ ]).append((flag, version, rpm))

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version, scriptprog, scripts) in rpm[self.TAG]:
            list = self.hash[name]
            list.remove( (flag, version, rpm) )
            if len(list) == 0:
                del self.hash[name]

# vim:ts=4:sw=4:showmatch:expandtab
