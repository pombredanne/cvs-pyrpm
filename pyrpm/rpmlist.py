#!/usr/bin/python
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
# Copyright 2004 Red Hat, Inc.
#
# Author: Thomas Woerner, Karel Zak
#

from hashlist import *
from functions import *

class _Provides:
    """ enable search of provides """
    """ provides of packages can be added and removed by package """
    def __init__(self):
        self.clear()
    def clear(self):
        self.p_provide = { }
    def append(self, name, flag, version, rpm):
        if not self.p_provide.has_key(name):
            self.p_provide[name] = [ ]
        self.p_provide[name].append((flag, version, rpm))
    def remove(self, name, flag, version, rpm):
        if not self.p_provide.has_key(name):
            return
        for p in self.p_provide[name]:
            if p[0] == flag and p[1] == version and p[2] == rpm:
                self.p_provide[name].remove(p)
        if len(self.p_provide[name]) == 0:
            del self.p_provide[name]
    def add_rpm(self, rpm):
        for p in rpm["provides"]:
            self.append(p[0], p[1], p[2], rpm)
    def remove_rpm(self, rpm):
        for p in rpm["provides"]:
            self.remove(p[0], p[1], p[2], rpm)
    def search(self, name, flag, version):
        if not self.p_provide.has_key(name):
            return [ ]

        ret = [ ]
        for p in self.p_provide[name]:
            if version == "":
                ret.append(p[2])
            else:
                if evrCompare(p[1], flag, version) == 1 and \
                       evrCompare(p[1], p[0], version) == 1:
                    ret.append(p[2])
                if evrCompare(evrString(p[2]["epoch"], p[2]["version"],
                                        p[2]["release"]), flag, version) == 1:
                    ret.append(p[2])
        return ret

# ----------------------------------------------------------------------------

class _Filenames:
    """ enable search of filenames """
    """ filenames of packages can be added and removed by package """
    def __init__(self):
        self.clear()
    def clear(self):
        self.provide = { }
        self.multi = [ ]
    def append(self, name, rpm):
        if not self.provide.has_key(name):
            self.provide[name] = [ ]
        else:
            self.multi.append(name)
        self.provide[name].append(rpm)
    def remove(self, name, rpm):
        if not self.provide.has_key(name):
            return
        if len(self.provide[name]) == 2:
            self.multi.remove(name)
        if rpm in self.provide[name]:
            self.provide[name].remove(rpm)
        if len(self.provide[name]) == 0:
            del self.provide[name]
    def add_rpm(self, rpm):
        for f in rpm["filenames"]:
            self.append(f, rpm)
    def remove_rpm(self, rpm):
        for f in rpm["filenames"]:
            self.remove(f, rpm)
    def search(self, name):
        if not self.provide.has_key(name):
            return [ ]
        return self.provide[name]

# ----------------------------------------------------------------------------

class RpmList:
    def __init__(self):
        self.clear()
    def clear(self):
        self.list = HashList()
        self.obsoletes = HashList()
        self.provides = _Provides()
        self.filenames = _Filenames()
    def __len__(self):
        return len(self.list)
    def __getitem__(self, i):
        return self.list[i][1] # return rpm list
    def install(self, pkg):
        if self.list.has_key(pkg["name"]):
            for r in self.list[pkg["name"]]:
                if str(pkg) == str(r):
                    printDebug(1, "Package %s is already in list" % \
                               r.getNEVRA())
                    return 0
        # remove obsolete packages
        for u in pkg["obsoletes"]:
            s = self.search_dep(u)
            for r2 in s:
                if str(r2) != str(pkg):
                    printDebug(1, "%s obsoletes %s, removing %s" % \
                               (pkg.getNEVRA(), r2.getNEVRA(), r2.getNEVRA()))
                    self.obsolete(pkg, r2)
        # add package to list
        if not self.list.has_key(pkg["name"]):
            self.list[pkg["name"]] = [ ]
        self.list[pkg["name"]].append(pkg)
        self.provides.add_rpm(pkg)
        self.filenames.add_rpm(pkg)
        return 1
    def update(self, pkg):
        if self.list.has_key(pkg["name"]):
            rpms = self.list[pkg["name"]]
            newer = 1
            for r in rpms:
                if str(pkg) == str(r):
                    printDebug(1, "Package %s is already in list" % \
                               r.getNEVRA())
                    return 0
                # TODO: disable this for old-package
                if labelCompare((pkg["epoch"], pkg["version"], pkg["release"]),
                                (r["epoch"], r["version"], r["release"])) \
                                < 0:
                    newer = 0
            if newer == 0:
                printDebug(1, "%s: A newer package is already in list" % \
                           r.getNEVRA())
                return 0
            i = 0
            while i < len(rpms):
                self.erase(rpms[0])
                i += 1
        return self.install(pkg)
    def erase(self, pkg):
        if self.list.has_key(pkg["name"]):
            found = 0
            for r in self.list[pkg["name"]]:
                if str(r) == str(pkg):
                    pkg = r
                    found = 1
            if found == 0:
                printDebug(1, "%s: Package is not in list." % \
                           pkg.getNEVRA())
                return 0
            self.provides.remove_rpm(pkg)
            self.filenames.remove_rpm(pkg)
            self.list[pkg["name"]].remove(pkg)
            if len(self.list[pkg["name"]]) == 0:
                del self.list[pkg["name"]]
            return 1
        printDebug(1, "%s: Package is not in list." % pkg.getNEVRA())
        return 0
    def obsolete(self, pkg, obsolete_pkg):
        if not pkg in self.obsoletes:
            self.obsoletes[pkg] = [ ]
        self.obsoletes[pkg].append(obsolete_pkg)
        return self.erase(obsolete_pkg)
    def search_dep(self, dep):
        (name, flag, version) = dep
        s = self.provides.search(name, flag, version)
        if name[0] == '/': # all filenames are beginning with a '/'
            s += self.filenames.search(name)
        return s

# vim:ts=4:sw=4:showmatch:expandtab
