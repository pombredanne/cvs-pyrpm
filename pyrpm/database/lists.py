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

class FilenamesList:
    """A mapping from filenames to RpmPackages."""

    def __init__(self):
        self.clear()

    def clear(self):
        """Clear the mapping."""

        self.path = { } # dirname => { basename => RpmPackage }
        self.oldfilenames = { }

    def addPkg(self, pkg):
        """Add all files from RpmPackage pkg to self."""

        if pkg.has_key("oldfilenames"):
            for f in pkg["oldfilenames"]:
                self.oldfilenames.setdefault(f, [ ]).append(pkg)
            return
        basenames = pkg["basenames"]
        if basenames == None:
            return
        dirindexes = pkg["dirindexes"]
        dirnames = pkg["dirnames"]
        path = self.path
        for i in dirnames:
            path.setdefault(i, { })
        for i in xrange(len(basenames)):
            dirname = dirnames[dirindexes[i]]
            path[dirname].setdefault(basenames[i], [ ]).append(pkg)

    def removePkg(self, pkg):
        """Remove all files from RpmPackage pkg from self."""

        if pkg.has_key("oldfilenames"):
            for f in pkg["oldfilenames"]:
                if not self.oldfilenames.has_key(f) or \
                   not pkg in self.oldfilenames[f]:
                    continue
                self.oldfilenames[f].remove(pkg)
                if len(self.oldfilenames[f]) == 0:
                    del self.oldfilenames[f]
            return

        basenames = pkg["basenames"]
        if basenames == None:
            # XXX we should also support "oldfilenames"
            return
        for i in xrange (len(pkg["basenames"])):
            dirname = pkg["dirnames"][pkg["dirindexes"][i]]

            if not self.path.has_key(dirname):
                continue

            basename = pkg["basenames"][i]
            if self.path[dirname].has_key(basename):
                self.path[dirname][basename].remove(pkg)

            if len(self.path[dirname][basename]) == 0:
                del self.path[dirname][basename]

    def numDuplicates(self, filename):
        (dirname, basename) = os.path.split(filename)
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        return len(self.path.get(dirname, {}).get(basename, {}))

    def duplicates(self):
        dups = { }
        for dirname in self.path.keys():
            for filename in self.path[dirname].keys():
                dups[dirname + filename] = self.path[dirname][filename]
        return dups

    def search(self, name):
        """Return list of packages providing file with name.

        The list may point to internal structures of FilenamesList and may be
        changed by calls to addPkg() and removePkg()."""

        pkglist = [ ]
        if self.oldfilenames.has_key(name):
            pkglist.extend(self.oldfilenames[name])
        (dirname, basename) = os.path.split(name)
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        pkglist.extend(self.path.get(dirname, {}).get(basename, []))
        return pkglist


class PhilFilenamesList:
    """A mapping from filenames to RpmPackages."""

    def __init__(self):
        self.clear()

    def clear(self):
        """Clear the mapping."""
        self.basenames = { } # basename: { pkg: [basename_idx, ..] }
        self.cache = { }

    def addPkg(self, pkg):
        """Add all files from RpmPackage pkg to self."""

        self.cache = { }
        if pkg.has_key("oldfilenames"):
            for i in xrange(len(pkg["oldfilenames"])):
                basename = os.path.basename(pkg["oldfilenames"][i])
                self.basenames.setdefault(basename, { }).setdefault(pkg, [ ]).append(i)
                #self.basenames.setdefault(basename, { }).append((pkg, i))
            return

        if pkg["basenames"] == None:
            return

        for i in xrange(len(pkg["basenames"])):
            f = pkg["basenames"][i]
            self.basenames.setdefault(f, { }).setdefault(pkg, [ ]).append(i)
            #self.basenames.setdefault(f, [ ]).append((pkg, i))

    def removePkg(self, pkg):
        """Remove all files from RpmPackage pkg from self."""

        self.cache = { }
        if pkg.has_key("oldfilenames"):
            for i in xrange(len(pkg["oldfilenames"])):
                f = os.path.basename(pkg["oldfilenames"][i])
                if not self.basenames.has_key(f):
                    # TODO: error/warning?
                    continue
                if self.basenames[f].has_key(pkg):
                    del self.basenames[f][pkg]
            if len(self.basenames[f].keys()) == 0:
                del self.basenames[f]
            return

        if pkg["basenames"] == None:
            return
        for i in xrange(len(pkg["basenames"])):
            f = pkg["basenames"][i]
            if not self.basenames.has_key(f):
                continue
            if self.basenames[f].has_key(pkg):
                del self.basenames[f][pkg]
        if len(self.basenames[f].keys()) == 0:
            del self.basenames[f]

    def isDuplicate(self, filename):
        (dirname, basename) = os.path.split(filename)
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        list = [ ]
        if self.basenames.has_key(basename):
            for (pkg, i) in self.basenames[basename]:
                if pkg.has_key("oldfilenames"):
                    if os.path.dirname(pkg["oldfilenames"][i]) == dirname:
                        list.append(pkg)
                else:
                    if pkg["dirnames"][pkg["dirindexes"][i]] == dirname:
                        list.append(pkg)
        normalizeList(list)
        if len(list) > 1:
            return 1
        return 0

    def duplicates(self):
        dups = { }
        for basename in self.basenames:
            hash = { }
            for (pkg, i) in self.basenames[basename]:
                if pkg.has_key("oldfilenames"):
                    hash.setdefault(pkg["oldfilenames"][i],
                                    [ ]).append(pkg)
                else:
                    name = pkg["dirnames"][pkg["dirindexes"][i]] + basename
                    hash.setdefault(name, [ ]).append(pkg)
            for name in hash:
                if len(hash[name]) > 1:
                    dups[name] = hash[name]
        return dups

    def search(self, name, nocache=0):
        """Return list of packages providing file with name.

        The list may point to internal structures of FilenamesList and may be
        changed by calls to addPkg() and removePkg()."""

        if not nocache and self.cache.has_key(name):
            return self.cache[name][:]

        pkglist = [ ]
        (dirname, basename) = os.path.split(name)
        if not self.basenames.has_key(basename):
            return pkglist
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        for pkg in self.basenames[basename]:
            if pkg.has_key("oldfilenames"):
                for idx in self.basenames[basename][pkg]:
                    if pkg["oldfilenames"][idx] == name:
                        pkglist.append(pkg)
            else:
                for idx in self.basenames[basename][pkg]:
                    if pkg["dirnames"][pkg["dirindexes"][idx]] == dirname:
                        pkglist.append(pkg)
        if nocache:
            return pkglist
        self.cache[name] = pkglist
        return self.cache[name][:]

class NewFilenamesList:
    """A mapping from filenames to RpmPackages."""

    def __init__(self):
        self.clear()

    def clear(self):
        """Clear the mapping."""
        self.basenames = { } # basename: [(pkg, basename_idx), ..]
        self.cache = { }

    def addPkg(self, pkg):
        """Add all files from RpmPackage pkg to self."""

        self.cache = { }
        if pkg.has_key("oldfilenames"):
            for i in xrange(len(pkg["oldfilenames"])):
                basename = os.path.basename(pkg["oldfilenames"][i])
                self.basenames.setdefault(basename, [ ]).append((pkg, i))
            return

        if pkg["basenames"] == None:
            return
        for i in xrange(len(pkg["basenames"])):
            f = pkg["basenames"][i]
            self.basenames.setdefault(f, [ ]).append((pkg, i))

    def removePkg(self, pkg):
        """Remove all files from RpmPackage pkg from self."""

        self.cache = { }
        if pkg.has_key("oldfilenames"):
            for i in xrange(len(pkg["oldfilenames"])):
                f = pkg["oldfilenames"][i]
                if not self.basenames.has_key(f):
                    # TODO: error/warning?
                    continue
                j = 0
                while j < len(self.basenames[f]):
                    if self.basenames[f][j][0] == pkg and \
                           self.basenames[f][j][1] == i:
                        self.basenames[f].pop(j)
                    else:
                        j += 1
            if len(self.basenames[f]) == 0:
                del self.basenames[f]
            return

        if pkg["basenames"] == None:
            return
        for i in xrange(len(pkg["basenames"])):
            f = pkg["basenames"][i]
            j = 0
            nlist = []
            for (bpkg, idx) in self.basenames[f]:
                if not bpkg == pkg:
                    nlist.append((bpkg, idx))
            if len(nlist) == 0:
                del self.basenames[f]
            else:
                self.basenames[f] = nlist

    def isDuplicate(self, filename):
        (dirname, basename) = os.path.split(filename)
        if len(dirname) > 0 and dirname[-1] != "/":
            dirname += "/"
        list = [ ]
        if self.basenames.has_key(basename):
            for (pkg, i) in self.basenames[basename]:
                if pkg.has_key("oldfilenames"):
                    if os.path.dirname(pkg["oldfilenames"][i]) == dirname:
                        list.append(pkg)
                else:
                    if pkg["dirnames"][pkg["dirindexes"][i]] == dirname:
                        list.append(pkg)
        normalizeList(list)
        if len(list) > 1:
            return 1
        return 0

    def duplicates(self):
        dups = { }
        for basename in self.basenames:
            hash = { }
            for (pkg, i) in self.basenames[basename]:
                if pkg.has_key("oldfilenames"):
                    hash.setdefault(pkg["oldfilenames"][i], [ ]).append(pkg)
                else:
                    name = pkg["dirnames"][pkg["dirindexes"][i]] + basename
                    hash.setdefault(name, [ ]).append(pkg)
            for name in hash:
                if len(hash[name]) > 1:
                    dups[name] = hash[name]
        return dups

    def search(self, name, nocache=0):
        """Return list of packages providing file with name.

        The list may point to internal structures of FilenamesList and may be
        changed by calls to addPkg() and removePkg()."""

        if nocache or not self.cache.has_key(name):
            pkglist = [ ]
            (dirname, basename) = os.path.split(name)
            if not self.basenames.has_key(basename):
                return pkglist
            if len(dirname) > 0 and dirname[-1] != "/":
                dirname += "/"
            for (pkg, i) in self.basenames[basename]:
                if pkg.has_key("oldfilenames"):
                    if pkg["oldfilenames"][i] == name:
                        pkglist.append(pkg)
                else:
                    if pkg["dirnames"][pkg["dirindexes"][i]] == dirname:
                        pkglist.append(pkg)
            if nocache:
                return pkglist
            self.cache[name] = pkglist
        return self.cache[name][:]


class ProvidesList:
    """A database of Provides:

    Files are represented as (filename, 0, "")."""
    TAG = "provides"

    # TODO: add key, __getitem__, ..

    def __init__(self, config):
        self.config = config            # FIXME: write-only
        self.hash = { }
        self.clear()
        self.__len__ = self.hash.__len__
        self.__getitem__ = self.hash.__getitem__
        self.has_key = self.hash.has_key
        self.keys = self.hash.keys

    def clear(self):
        """Discard all stored data"""

        # %name => [(flag, EVR string, providing RpmPackage)]
        self.hash = { }

    def addPkg(self, rpm):
        """Add Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm[self.TAG]:
            self._add(name, flag, version, rpm)

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm[self.TAG]:
            self._remove(name, flag, version, rpm)

    def _add(self, name, flag, version, rpm):
        """Add Provides: (name, RPMSENSE_* flag, EVR string) by RpmPackage rpm
        to database"""

        self.hash.setdefault(name, [ ]).append((flag, version, rpm))

    def _remove(self, name, flag, version, rpm):
        """Remove Provides: (name, RPMSENSE_* flag, EVR string) by RpmPackage
        rpm."""

        list = self.hash[name]
        i = 0
        while i < len(list):
            p = list[i]
            if p[0] == flag and p[1] == version and p[2] == rpm:
                del list[i]
                break
            else:
                i += 1
        if len(list) == 0:
            del self.hash[name]

    def search(self, name, flag, version):
        """Return a list of RpmPackage's matching the Requires:
        (name, RPMSENSE_* flag, EVR string)."""

        if not self.hash.has_key(name):
            return [ ]
        evr = functions.evrSplit(version)
        ret = [ ]
        for (f, v, rpm) in self.hash[name]:
            if rpm in ret:
                continue
            if version == "":
                ret.append(rpm)
                continue
            if functions.rangeCompare(flag, evr, f, functions.evrSplit(v)):
                ret.append(rpm)
                continue
            if v == "": # compare with package version for unversioned provides
                evr2 = (rpm.getEpoch(), rpm["version"], rpm["release"])
                if functions.evrCompare(evr2, flag, evr):
                    ret.append(rpm)

        return ret


class ConflictsList(ProvidesList):
    """A database of Conflicts:"""
    TAG = "conflicts"

    def search(self, name, flag, version):
        # s/Conflicts/Obsoletes/ in ObsoletesList
        """Return a list of RpmPackage's with Conflicts: matching
        (name, RPMSENSE_* flag, EVR string)."""

        if not self.hash.has_key(name):
            return [ ]
        evr = functions.evrSplit(version)
        ret = [ ]
        for (f, v, rpm) in self.hash[name]:
            if rpm in ret:
                continue
            if version == "":
                ret.append(rpm)
                continue
            if functions.rangeCompare(flag, evr, f, functions.evrSplit(v)):
                ret.append(rpm)
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
            self._add(name, flag, version, rpm)

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version, scriptprog, scripts) in rpm[self.TAG]:
            self._remove(name, flag, version, rpm)

# vim:ts=4:sw=4:showmatch:expandtab
