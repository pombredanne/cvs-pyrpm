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
# Copyright 2004, 2005 Red Hat, Inc.
#
# Author: Thomas Woerner
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
        self.provide = { }

    def _append(self, name, flag, version, rpm):
        if not self.provide.has_key(name):
            self.provide[name] = [ ]
        self.provide[name].append((flag, version, rpm))

    def _remove(self, name, flag, version, rpm):
        if not self.provide.has_key(name):
            return
        for p in self.provide[name]:
            if p[0] == flag and p[1] == version and p[2] == rpm:
                self.provide[name].remove(p)
        if len(self.provide[name]) == 0:
            del self.provide[name]

    def addPkg(self, rpm):
        for p in rpm["provides"]:
            self._append(p[0], p[1], p[2], rpm)

    def removePkg(self, rpm):
        for p in rpm["provides"]:
            self._remove(p[0], p[1], p[2], rpm)

    def search(self, name, flag, version, arch=None):
        if not self.provide.has_key(name):
            return [ ]

        ret = [ ]
        for p in self.provide[name]:
            if version == "":
                ret.append(p[2])
            else:
                if evrCompare(p[1], flag, version) == 1 and \
                       evrCompare(p[1], p[0], version) == 1:
                    ret.append(p[2])
                evr = (p[2].getEpoch(), p[2]["version"], p[2]["release"])
                if evrCompare(evr, flag, version) == 1:
                    ret.append(p[2])

        if not arch or arch == "noarch":
            # all rpms are matching
            return ret
            
        # drop all packages which are not arch compatible
        i = 0
        while i < len(ret):
            r = ret[i]
            if r["arch"] == "noarch" or r["arch"] == arch or \
                   buildarchtranslate[arch] == \
                   buildarchtranslate[r["arch"]] or \
                   r["arch"] in arch_compats[arch] or \
                   arch in arch_compats[r["arch"]]:
                i += 1
            else:
                ret.remove(r)

        return ret

# ----------------------------------------------------------------------------

class FilenamesList:
    """ enable search of filenames """
    """ filenames of packages can be added and removed by package """
    def __init__(self):
        self.filename = { }
        self.multi = [ ]

    def _append(self, name, rpm):
        if not self.filename.has_key(name):
            self.filename[name] = [ ]
        else:
            if len(self.filename[name]) == 1:
                self.multi.append(name)
        self.filename[name].append(rpm)

    def _remove(self, name, rpm):
        if not self.filename.has_key(name):
            return
        if len(self.filename[name]) == 2:
            self.multi.remove(name)
        if rpm in self.filename[name]:
            self.filename[name].remove(rpm)
        if len(self.filename[name]) == 0:
            del self.filename[name]

    def addPkg(self, rpm):
        for f in rpm["filenames"]:
            self._append(f, rpm)

    def removePkg(self, rpm):
        for f in rpm["filenames"]:
            self._remove(f, rpm)

    def search(self, name):
        return self.filename.get(name, [ ])

# ----------------------------------------------------------------------------

class RpmResolver(RpmList):
    OBSOLETE_FAILED = -10
    # ----

    def __init__(self, installed, operation, check_installed=0):
        RpmList.__init__(self, installed, operation)
        self.check_installed = check_installed

    def clear(self):
        RpmList.clear(self)
        self.provides = ProvidesList()
        self.filenames = FilenamesList()
        self.lost_provides = ProvidesList()
        self.lost_filenames = FilenamesList()
        self.obsoletes = {}
        self.updates = {}
        self.erased = {}
    # ----

    def _install(self, pkg):
        ret = RpmList._install(self, pkg)
        if ret != self.OK:  return ret
        
        self.provides.addPkg(pkg)
        self.filenames.addPkg(pkg)
        return self.OK
    # ----
    
    def _erase(self, pkg):
        ret = RpmList._erase(self, pkg)
        if ret != self.OK:  return ret
        
        self.provides.removePkg(pkg)
        self.filenames.removePkg(pkg)
        if self.isInstalled(pkg):
            self.lost_provides.addPkg(pkg)
            self.lost_filenames.addPkg(pkg)
        return self.OK
    # ----

    def _pkgObsolete(self, pkg, obsolete_pkg):
        if self.isInstalled(obsolete_pkg):
            if not pkg in self.obsoletes:
                self.obsoletes[pkg] = [ ]
            self.obsoletes[pkg].append(obsolete_pkg)
        return self._erase(obsolete_pkg)
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        if self.isInstalled(update_pkg):
            if not pkg in self.updates:
                self.updates[pkg] = [ ]
            if update_pkg in self.updates:
                self.updates[pkg] = self.updates[update_pkg]
                del self.updates[update_pkg]
            else:
                self.updates[pkg].append(update_pkg)
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
            s += self.filenames.search(name)
        normalizeList(s)
        return s
    # ----

    def searchLostDependency(self, dep, arch=None):
        (name, flag, version) = dep
        s = self.lost_provides.search(name, flag, version, arch)
        if name[0] == '/': # all filenames are beginning with a '/'
            s += self.lost_filenames.search(name)
        normalizeList(s)
        return s
    # ----

    def doObsoletes(self):
        """ Do obsoletes for new packages """

        if self.operation == OP_INSTALL or \
               self.operation == OP_ERASE:
            # no obsoletes for install or erase
            return self.OK
        
        i = 0
        while i < len(self):
            rlist = self[i]
            for pkg in rlist:
                if self.isInstalled(pkg):
                    # obsoletes only for new packages
                    continue
                # remove obsolete packages
                for u in pkg["obsoletes"]:
                    s = self.searchDependency(u)
                    for r in s:
                        if r != pkg and r["name"] != pkg["name"]:
                            # package is not the same and has not the same name
                            if self.isInstalled(r):
                                fmt = "%s obsoletes installed %s, removing %s"
                            else:
                                fmt = "%s obsoletes added %s, removing %s"
                            printWarning(0, fmt % (pkg.getNEVRA(),
                                                   r.getNEVRA(),
                                                   r.getNEVRA()))

                            if self._pkgObsolete(pkg, r) != self.OK:
                                return self.OBSOLETE_FAILED
                            else:
                                i -= 1
            i += 1
        return self.OK
    # ----

    def getPkgDependencies(self, pkg):
        """ Check dependencies for a rpm package """
        unresolved = [ ]
        resolved = [ ]
        for u in pkg["requires"]:
            if u[0].startswith("rpmlib("): # drop rpmlib requirements
                continue
            #if u[0].startswith("config("): # drop config requirements
            #    continue
            s = self.searchDependency(u, pkg["arch"])
            if len(s) > 1 and pkg in s:
                # prefer self dependencies if there are others, too
                s = [pkg]
            if len(s) == 0: # found nothing
                if self.check_installed == 1 or \
                       len(self.searchLostDependency(u)) == 0:
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
        all_resolved = [ ]
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0:
                    all_resolved.append((r, resolved))
        return all_resolved
    # ----

    def getUnresolvedDependencies(self):
        """ Get all unresolved dependencies """
        all_unresolved = [ ]
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(unresolved) > 0:
                    all_unresolved.append((r, unresolved))
        return all_unresolved
    # ----

    def getConflicts(self):
        """ Check for conflicts in conflicts and and obsoletes """

        if self.operation == OP_ERASE:
            # no conflicts for erase
            return None

        conflicts = [ ]
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    s = self.searchDependency(c)
                    if len(s) > 0:
                        # the package does not conflict with itself
                        if r in s: s.remove(r)
                    if len(s) > 0:
                        for r2 in s:
                            if r.getNEVR() != r2.getNEVR():
                                if not (self.check_installed == 0 and \
                                        self.isInstalled(c[0]) and \
                                        self.isInstalled(c[2])):
                                    conflicts.append((r, c, r2))
        return conflicts
    # ----

    def checkConflicts(self):
        conflicts = self.getConflicts()
        if conflicts == None or len(conflicts) == 0:
            return self.OK

        for c in conflicts:
            printError("%s conflicts for '%s' with %s" % \
                       (c[0].getNEVRA(), depString(c[1]), c[2].getNEVRA()))
        return -1
    # ----
        
    def getFileConflicts(self):
        """ Check for file conflicts """

        if self.operation == OP_ERASE:
            # no conflicts for erase
            return None

        conflicts = [ ]
        for filename in self.filenames.multi:
            printDebug(1, "Checking for file conflicts for '%s'" % filename)
            s = self.filenames.search(filename)
            for j in xrange(len(s)):
                fi1 = s[j].getRpmFileInfo(filename)
                for k in xrange(j+1, len(s)):
                    fi2 = s[k].getRpmFileInfo(filename)
                    if s[j].getNEVR() == s[k].getNEVR() and \
                           buildarchtranslate[s[j]["arch"]] != \
                           buildarchtranslate[s[k]["arch"]]:
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
        if conflicts == None or len(conflicts) == 0:
            return self.OK

        for c in conflicts:
            printError("%s: File conflict for '%s' with %s" % \
                       (c[0].getNEVRA(), c[1], c[2].getNEVRA()))
        return -1
    # ----

    def resolve(self):
        """ Start the resolving process
        Handle obsoletes, check dependencies and conflicts.
        Return 1 if everything is OK, a negative number if not. """

        # checking obsoletes for new packages
        if self.doObsoletes() != 1:
            return -1

        # checking dependencies
        if self.checkDependencies() != 1:
            return -1

        # check for conflicts
        if self.checkConflicts() != 1:
            return -2

        # check for file conflicts
        if self.checkFileConflicts() != 1:
            return -3

        return 1

# vim:ts=4:sw=4:showmatch:expandtab
