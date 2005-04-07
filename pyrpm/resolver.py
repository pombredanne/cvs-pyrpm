#!/usr/bin/python
#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Thomas Woerner
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

""" The Resolver
...
"""

from stat import S_ISLNK, S_ISDIR
from config import rpmconfig
from hashlist import HashList
from rpmlist import RpmList
from functions import *

# ----------------------------------------------------------------------------

class ProvidesList:
    """ enable search of provides """
    """ provides of packages can be added and removed by package """
    def __init__(self):
        self.provide = {}

    def addPkg(self, rpm):
        for (name, flag, version) in rpm["provides"]:
            if not self.provide.has_key(name):
                self.provide[name] = []
            self.provide[name].append((flag, version, rpm))

    def removePkg(self, rpm):
        for (name, flag, version) in rpm["provides"]:
            provide = self.provide[name]
            i = 0
            while i < len(provide):
                p = provide[i]
                if p[0] == flag and p[1] == version and p[2] == rpm:
                    provide.pop(i)
                    break
                else:
                    i += 1
            if len(provide) == 0:
                del self.provide[name]

    def search(self, name, flag, version, arch=None):
        if not self.provide.has_key(name):
            return [ ]
        evr = evrSplit(version)
        ret = [ ]
        for (f, v, rpm) in self.provide[name]:
            if rpm in ret:
                continue
            if version == "":
                ret.append(rpm)
                continue
            if rangeCompare(flag, evr, f, evrSplit(v)):
                ret.append(rpm)
                continue
            evr2 = (rpm.getEpoch(), rpm["version"], rpm["release"])
            if evrCompare(evr2, flag, evr) == 1:
                ret.append(rpm)

        if not arch or arch == "noarch":   # all rpms are matching
            return ret

        # drop all packages which are not arch compatible
        i = 0
        while i < len(ret):
            r = ret[i]
            if r["arch"] == "noarch" or archDuplicate(r["arch"], arch) or \
                   archCompat(r["arch"], arch) or archCompat(arch, r["arch"]):
                i += 1
            else:
                ret.pop(i)

        return ret

# ----------------------------------------------------------------------------

class FilenamesList:
    """ enable search of filenames """
    """ filenames of packages can be added and removed by package """
    def __init__(self):
        self.filename = {}
        self.multi = {}

    def addPkg(self, rpm):
        for name in rpm["filenames"]:
            if not self.filename.has_key(name):
                self.filename[name] = []
            else:
                self.multi[name] = None
            self.filename[name].append(rpm)

    def removePkg(self, rpm):
        for name in rpm["filenames"]:
            f = self.filename[name]
            if len(f) == 2:
                del self.multi[name]
            f.remove(rpm)
            if len(f) == 0:
                del self.filename[name]

    def search(self, name, l):
        for r in self.filename.get(name, []):
            if r not in l:
                l.append(r)

# ----------------------------------------------------------------------------

class RpmResolver(RpmList):
    OBSOLETE_FAILED = -10
    # ----

    def __init__(self, installed, operation, check_installed=0):
        RpmList.__init__(self, installed, operation)
        self.check_installed = check_installed
        self.installed_unresolved = self.getUnresolvedDependencies()
    # ----

    def clear(self):
        RpmList.clear(self)
        self.provides = ProvidesList()
        self.filenames = FilenamesList()
        self.obsoletes = { }
        self.updates = { }
        self.erased = { }
        self.check_installed = 0
        self.installed_unresolved = HashList()
    # ----

    def _install(self, pkg, no_check=0):
        ret = RpmList._install(self, pkg, no_check)
        if ret != self.OK:  return ret

        self.provides.addPkg(pkg)
        self.filenames.addPkg(pkg)
        
        return self.OK
    # ----

    def _update(self, pkg):
        obsoletes = [ ]
        for u in pkg["obsoletes"]:
            s = self.searchDependency(u)
            for r in s:
                if r["name"] != pkg["name"]:
                    obsoletes.append(r)

        ret = RpmList._update(self, pkg)
        if ret != self.OK:  return ret

        normalizeList(obsoletes)
        for r in obsoletes:
            # package is not the same and has not the same name
            if self.isInstalled(r):
                fmt = "%s obsoletes installed %s, removing %s"
            else:
                fmt = "%s obsoletes added %s, removing %s"
            printWarning(0, fmt % (pkg.getNEVRA(), r.getNEVRA(), r.getNEVRA()))
            if self._pkgObsolete(pkg, r) != self.OK:
                return self.OBSOLETE_FAILED

        return self.OK
    # ----

    def _erase(self, pkg):
        ret = RpmList._erase(self, pkg)
        if ret != self.OK:  return ret

        self.provides.removePkg(pkg)
        self.filenames.removePkg(pkg)

        return self.OK
    # ----

    def _pkgObsolete(self, pkg, obsolete_pkg):
        if self.isInstalled(obsolete_pkg):
            if not pkg in self.obsoletes:
                self.obsoletes[pkg] = [ ]
            self.obsoletes[pkg].append(obsolete_pkg)
        else:
            if obsolete_pkg in self.obsoletes:
                if pkg in self.obsoletes:
                    self.obsoletes[pkg].extend(self.obsoletes[obsolete_pkg])
                    normalizeList(self.obsoletes[pkg])
                else:
                    self.obsoletes[pkg] = self.obsoletes[obsolete_pkg]
                del self.obsoletes[obsolete_pkg]
        if obsolete_pkg in self.updates:
            if pkg in self.updates:
                self.updates[pkg].extend(self.updates[obsolete_pkg])
                normalizeList(self.updates[pkg])
            else:
                self.updates[pkg] = self.updates[obsolete_pkg]
            del self.updates[obsolete_pkg]
        return self._erase(obsolete_pkg)
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        if self.isInstalled(update_pkg):
            if not pkg in self.updates:
                self.updates[pkg] = [ ]
            self.updates[pkg].append(update_pkg)
        elif update_pkg in self.updates:
            if pkg in self.updates:
                self.updates[pkg].extend(self.updates[update_pkg])
                normalizeList(self.updates[pkg])
            else:
                self.updates[pkg] = self.updates[update_pkg]
            del self.updates[update_pkg]
        if update_pkg in self.obsoletes:
            if pkg in self.obsoletes:
                self.obsoletes[pkg].extend(self.obsoletes[update_pkg])
                normalizeList(self.obsoletes[pkg])
            else:
                self.obsoletes[pkg] = self.obsoletes[update_pkg]
            del self.obsoletes[update_pkg]
        return RpmList._pkgUpdate(self, pkg, update_pkg)
    # ----

    def _pkgErase(self, pkg):
        self.erased[pkg] = 1
        return RpmList._pkgErase(self, pkg)
    # ----

    def searchDependency(self, dep, arch=None):
        (name, flag, version) = dep
        s = self.provides.search(name, flag, version, arch)
        if name[0] == '/': # all filenames are beginning with a '/'
            self.filenames.search(name, s)
        return s
    # ----

    def doObsoletes(self):
        raise Exception, "deprecated"
    # ----

    def getPkgDependencies(self, pkg):
        """ Check dependencies for a rpm package """
        unresolved = [ ]
        resolved = [ ]

        for u in pkg["requires"]:
            if u[0].startswith("rpmlib("): # drop rpmlib requirements
                continue
            s = self.searchDependency(u, pkg["arch"])
            if len(s) > 1 and pkg in s:
                # prefer self dependencies if there are others, too
                s = [pkg]
            if len(s) == 0: # found nothing
                if self.check_installed == 0 and \
                       pkg in self.installed_unresolved and \
                       u in self.installed_unresolved[pkg]:
                    continue
                unresolved.append(u)
            else: # resolved
                resolved.append((u, s))
        return (unresolved, resolved)
    # ----

    def checkDependencies(self):
        """ Check dependencies """
        no_unresolved = 1
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                if self.check_installed == 0 and \
                    len(self.erased) == 0 and len(self.obsoletes) == 0 and \
                    len(self.updates) == 0 and self.isInstalled(r):
                    # do not check installed packages if no packages
                    # are getting removed by erase or obsolete
                    continue
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0 and rpmconfig.debug_level > 1:
                    printDebug(2, "%s: resolved dependencies:" % r.getNEVRA())
                    for (u, s) in resolved:
                        s2 = ""
                        for r2 in s:
                            s2 += "%s " % r2.getNEVRA()
                        printDebug(2, "\t%s: %s" % (depString(u), s2))
                if len(unresolved) > 0:
                    no_unresolved = 0
                    printError("%s: unresolved dependencies:" % r.getNEVRA())
                    for u in unresolved:
                        printError("\t%s" % depString(u))
        return no_unresolved
    # ----

    def getResolvedDependencies(self):
        """ Get all resolved dependencies """
        all_resolved = HashList()
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0:
                    if r not in all_resolved:
                        all_resolved[r] = [ ]
                    all_resolved[r].extend(resolved)
        return all_resolved
    # ----

    def getUnresolvedDependencies(self):
        """ Get all unresolved dependencies """
        all_unresolved = HashList()
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(unresolved) > 0:
                    if r not in all_unresolved:
                        all_unresolved[r] = [ ]
                    all_unresolved[r].extend(unresolved)
        return all_unresolved
    # ----

    def getConflicts(self):
        """ Check for conflicts in conflicts and and obsoletes """

        conflicts = HashList()

        if self.operation == OP_ERASE:
            # no conflicts for erase
            return conflicts

        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    s = self.searchDependency(c)
                    if len(s) == 0:
                        continue
                    # the package does not conflict with itself
                    if r in s:
                        s.remove(r)
                    for r2 in s:
                        if r.getNEVR() != r2.getNEVR():
                            #if not (self.check_installed == 0 and \
                            #        self.isInstalled(c[0]) and \
                            #        self.isInstalled(c[2])):
                            if r not in conflicts:
                                conflicts[r] = [ ]
                            conflicts[r].append((c, r2))
        return conflicts
    # ----

    def checkConflicts(self):
        conflicts = self.getConflicts()
        if len(conflicts) == 0:
            return self.OK

        for pkg in conflicts.keys():
            printError("%s conflicts with:" % pkg.getNEVRA())
            for c,r in conflicts[pkg]:
                printError("\t'%s' <=> %s" % (depString(c), r.getNEVRA()))
        return -1
    # ----

    def getFileConflicts(self):
        """ Check for file conflicts """
        if self.operation == OP_ERASE:
            return []       # no conflicts for erase
        conflicts = []
        for filename in self.filenames.multi.keys():
            printDebug(1, "Checking for file conflicts for '%s'" % filename)
            s = []
            self.filenames.search(filename, s)
            for j in xrange(len(s)):
                fi1 = s[j].getRpmFileInfo(filename)
                for k in xrange(j+1, len(s)):
                    fi2 = s[k].getRpmFileInfo(filename)
                    if s[j].getNEVR() == s[k].getNEVR() and \
                           buildarchtranslate[s[j]["arch"]] != \
                           buildarchtranslate[s[k]["arch"]] and \
                           s[j]["arch"] != "noarch" and \
                           s[k]["arch"] != "noarch":
                        # do not check packages with the same NEVR which are
                        # not buildarchtranslate same
                        continue
                    # ignore directories
                    if S_ISDIR(fi1.mode) and S_ISDIR(fi2.mode):
                        continue
                    # ignore links
                    if S_ISLNK(fi1.mode) and S_ISLNK(fi2.mode):
                        continue
                    if fi1.mode != fi2.mode or \
                           fi1.filesize != fi2.filesize or \
                           fi1.md5sum != fi2.md5sum:
                        if not (self.check_installed == 0 and \
                                self.isInstalled(s[j]) and \
                                self.isInstalled(s[k])):
                            conflicts.append((s[j], filename, s[k]))
        return conflicts
    # ----

    def checkFileConflicts(self):
        conflicts = self.getFileConflicts()
        if len(conflicts) == 0:
            return self.OK

        for c in conflicts:
            printError("%s: File conflict for '%s' with %s" % \
                       (c[0].getNEVRA(), c[1], c[2].getNEVRA()))
        return -1
    # ----

    def resolve(self):
        """ Start the resolving process
        Check dependencies and conflicts.
        Return 1 if everything is OK, a negative number if not. """

        # checking dependencies
        if self.checkDependencies() != 1:
            return -1

        if rpmconfig.noconflicts == 0:
            # check for conflicts
            if self.checkConflicts() != 1:
                return -2

        if rpmconfig.nofileconflicts == 0:
            # check for file conflicts
            if self.checkFileConflicts() != 1:
                return -3

        return 1

# vim:ts=4:sw=4:showmatch:expandtab
