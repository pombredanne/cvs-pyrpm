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
from hashlist import HashList
from rpmlist import RpmList
from functions import *
import base

# ----------------------------------------------------------------------------

class ProvidesList:
    """ enable search of provides """
    """ provides of packages can be added and removed by package """
    def __init__(self, config):
        self.config = config
        self.clear()

    def clear(self):
        self.provide = { }

    def _addProvide(self, name, flag, version, rpm):
        if not self.provide.has_key(name):
            self.provide[name] = [ ]
        self.provide[name].append((flag, version, rpm))

    def addPkg(self, rpm):
        for (name, flag, version) in rpm["provides"]:
            self._addProvide(name, flag, version, rpm)

    def _removeProvide(self, name, flag, version, rpm):
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

    def removePkg(self, rpm):
        for (name, flag, version) in rpm["provides"]:
            self._removeProvide(name, flag, version, rpm)

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

class ConflictsList(ProvidesList):
    def addPkg(self, rpm):
        for (name, flag, version) in rpm["conflicts"]:
            self._addProvide(name, flag, version, rpm)

    def removePkg(self, rpm):
        for (name, flag, version) in rpm["conflicts"]:
            self._removeProvide(name, flag, version, rpm)

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

class ObsoletesList(ConflictsList):
    def addPkg(self, rpm):
        for (name, flag, version) in rpm["obsoletes"]:
            self._addProvide(name, flag, version, rpm)

    def removePkg(self, rpm):
        for (name, flag, version) in rpm["obsoletes"]:
            self._removeProvide(name, flag, version, rpm)


# ----------------------------------------------------------------------------

class FilenamesList:
    """ enable search of filenames """
    """ filenames of packages can be added and removed by package """
    def __init__(self, config):
        self.config = config
        self.clear()

    def clear(self):
        self.filename = { }
        self.multi = { }        

    def addPkg(self, rpm):
        for name in rpm["filenames"]:
            if not self.filename.has_key(name):
                self.filename[name] = [ ]
            else:
                self.multi[name] = None
            self.filename[name].append(rpm)

    def removePkg(self, rpm):
        for name in rpm["filenames"]:
            f = self.filename[name]
            l = len(f)
            if   l == 1:
                if f[0] == rpm:
                    del self.filename[name]
            elif rpm in f:
                if l == 2:
                    del self.multi[name]
                f.remove(rpm)

    def search(self, name):
        l = [ ]
        for r in self.filename.get(name, [ ]):
            if r not in l:
                l.append(r)
        return l

# ----------------------------------------------------------------------------

class RpmResolver(RpmList):
    OBSOLETE_FAILED = -10
    CONFLICT = -11
    FILE_CONFLICT = -12
    # ----

    def __init__(self, config, installed):
        RpmList.__init__(self, config, installed)
        # fill in installed_ structures
        check_installed = self.config.checkinstalled
        self.config.checkinstalled = 1
        self.installed_unresolved = self.getUnresolvedDependencies()
        self.installed_conflicts = self.getConflicts()
        self.installed_obsoletes = self.getObsoletes()
        self.installed_file_conflicts = self.getFileConflicts()
        self.config.checkinstalled = check_installed                
    # ----

    def clear(self):
        RpmList.clear(self)
        self.provides_list = ProvidesList(self.config)
        self.obsoletes_list = ObsoletesList(self.config)
        self.filenames_list = FilenamesList(self.config)
        self.obsoletes = { }
        self.installed_unresolved = HashList()
        self.installed_conflicts = HashList()
        self.installed_obsoletes = HashList()
        self.installed_file_conflicts = HashList()
    # ----

    def _install(self, pkg, no_check=0):
        ret = RpmList._install(self, pkg, no_check)
        if ret != self.OK:  return ret

        self.provides_list.addPkg(pkg)
        self.obsoletes_list.addPkg(pkg)
        self.filenames_list.addPkg(pkg)
        
        return self.OK
    # ----

    def install(self, pkg, operation=OP_INSTALL):
        if self.config.noconflicts == 0:
            # check conflicts for provides
            for dep in pkg["provides"]:
                (name, flag, version) = dep
                s = self.obsoletes_list.search(name, flag, version,
                                               pkg["arch"])
                if self._checkObsoletes(pkg, dep, s, operation):
                    return self.CONFLICT
            # check conflicts for filenames
            for f in pkg["filenames"]:
                dep = (f, 0, "")
                s = self.obsoletes_list.search(f, 0, "", pkg["arch"])
                if self._checkObsoletes(pkg, dep, s, operation):
                    return self.CONFLICT

        ret = RpmList.install(self, pkg, operation)
        return ret
    # ----

    def update(self, pkg):
        # get obsoletes
        self.pkg_obsoletes = [ ]
        for u in pkg["obsoletes"]:
            s = self.searchDependency(u)
            for r in s:
                if r["name"] != pkg["name"]:
                    self.pkg_obsoletes.append(r)
        normalizeList(self.pkg_obsoletes)

        # update package
        ret = RpmList.update(self, pkg)
        if ret != self.OK:
            del self.pkg_obsoletes
            return ret            

        for r in self.pkg_obsoletes:
            # package is not the same and has not the same name
            if self.isInstalled(r):
                fmt = "%s obsoletes installed %s, removing %s"
            else:
                fmt = "%s obsoletes added %s, removing %s"
            if self.config.test:
                self.config.printInfo(0, fmt % (pkg.getNEVRA(), r.getNEVRA(),
                                                r.getNEVRA()+"\n"))
            else:
                self.config.printWarning(1, fmt % (pkg.getNEVRA(),
                                                   r.getNEVRA(), r.getNEVRA()))
            if self._pkgObsolete(pkg, r) != self.OK:
                del self.pkg_obsoletes
                return self.OBSOLETE_FAILED

        del self.pkg_obsoletes

        return self.OK
    # ----

    def erase(self, pkg):
        ret = RpmList.erase(self, pkg)
        if ret != self.OK:  return ret

        self.provides_list.removePkg(pkg)
        self.obsoletes_list.removePkg(pkg)
        self.filenames_list.removePkg(pkg)

        if pkg in self.obsoletes:
            del self.obsoletes[pkg]

        return self.OK
    # ----

    def _checkObsoletes(self, pkg, dep, list, operation=OP_INSTALL):
        ret = 0
        conflicts = self._getObsoletes(pkg, dep, list, operation)
        for (c,r) in conflicts:
            if operation == OP_UPDATE and \
                   (r in self.pkg_updates or r in self.pkg_obsoletes):
                continue
            if self.isInstalled(r):
                fmt = "%s conflicts with already installed %s, skipping"
            else:
                fmt = "%s conflicts with already added %s, skipping"
            self.config.printWarning(1, fmt % (pkg.getNEVRA(),
                                               r.getNEVRA()))
            ret = 1
        return ret
    # ----

    def _getObsoletes(self, pkg, dep, list, operation=OP_INSTALL):
        obsoletes = [ ]
        ret = 0
        if len(list) != 0:
            if pkg in list:
                list.remove(pkg)
            for r in list:
                if self.config.checkinstalled == 0 and \
                       pkg in self.installed_obsoletes and \
                       dep in self.installed_obsoletes[pkg]:
                    continue
                if operation == OP_UPDATE:
                    if pkg["name"] == r["name"]:
                        continue
                else:
                    if pkg.getNEVR() == r.getNEVR():
                        continue
                obsoletes.append((dep, r))
        return obsoletes
    # ----

    def _getConflicts(self, pkg, dep, list, operation=OP_INSTALL):
        conflicts = [ ]
        ret = 0
        if len(list) != 0:
            if pkg in list:
                list.remove(pkg)
            for r in list:
                if self.config.checkinstalled == 0 and \
                       ((pkg in self.installed_conflicts and \
                         dep in self.installed_conflicts[pkg]) or \
                        (pkg in self.installed_obsoletes and \
                         dep in self.installed_obsoletes[pkg])):
                    continue
                if operation == OP_UPDATE:
                    if pkg["name"] == r["name"]:
                        continue
                else:
                    if pkg.getNEVR() == r.getNEVR():
                        continue
                conflicts.append((dep, r))
        return conflicts
    # ----

    def _hasFileConflict(self, pkg1, pkg2, filename, pkg1_fi,
                         operation=OP_INSTALL):
        if self.config.checkinstalled == 0 and \
               pkg1 in self.installed_file_conflicts and \
               (filename,pkg2) in self.installed_file_conflicts[pkg1]:
            return 0
        if operation == OP_UPDATE and \
               (pkg2 in self.pkg_updates or pkg2 in self.pkg_obsoletes):
            return 0
        if operation == OP_UPDATE:
            if pkg1["name"] == pkg2["name"]:
                return 0
        else:
            if pkg1.getNEVR() == pkg2.getNEVR() and \
                   buildarchtranslate[pkg1["arch"]] != \
                   buildarchtranslate[pkg2["arch"]] and \
                   pkg1["arch"] != "noarch" and \
                   pkg2["arch"] != "noarch":
                # do not check packages with the same NEVR which are
                # not buildarchtranslate compatible
                return 0
        fi = pkg2.getRpmFileInfo(filename)
        # ignore directories
        if S_ISDIR(pkg1_fi.mode) and S_ISDIR(fi.mode):
            return 0
        # ignore links
        if S_ISLNK(pkg1_fi.mode) and S_ISLNK(fi.mode):
            return 0
        # ignore identical files
        if pkg1_fi.mode == fi.mode and \
               pkg1_fi.filesize == fi.filesize and \
               pkg1_fi.md5sum == fi.md5sum:
            return 0
        # ignore ghost files
        if pkg1_fi.flags & base.RPMFILE_GHOST or \
               fi.flags & base.RPMFILE_GHOST:
            return 0

        return 1
    # ----

    def _pkgObsolete(self, pkg, obsolete_pkg):
        if self.isInstalled(obsolete_pkg):
            if not pkg in self.obsoletes:
                self.obsoletes[pkg] = [ ]
            self.obsoletes[pkg].append(obsolete_pkg)
        else:
            self._inheritUpdates(pkg, obsolete_pkg)
            self._inheritObsoletes(pkg, obsolete_pkg)
        return self.erase(obsolete_pkg)
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        if not self.isInstalled(update_pkg):
            self._inheritObsoletes(pkg, update_pkg)
        return RpmList._pkgUpdate(self, pkg, update_pkg)
    # ----

    def _inheritObsoletes(self, pkg, old_pkg):
        if old_pkg in self.obsoletes:
            if pkg in self.obsoletes:
                self.obsoletes[pkg].extend(self.obsoletes[old_pkg])
                normalizeList(self.obsoletes[pkg])
            else:
                self.obsoletes[pkg] = self.obsoletes[old_pkg]
            del self.obsoletes[old_pkg]
    # ----

    def searchDependency(self, dep, arch=None):
        (name, flag, version) = dep
        s = self.provides_list.search(name, flag, version, arch)
        if name[0] == '/': # all filenames are beginning with a '/'
            s += self.filenames_list.search(name)
        return s
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
                if self.config.checkinstalled == 0 and \
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
        for name in self:
            for r in self[name]:
                if self.config.checkinstalled == 0 and \
                       len(self.erases) == 0 and self.isInstalled(r):
                    # do not check installed packages if no packages
                    # are getting removed (by erase, update or obsolete)
                    continue
                self.config.printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0 and self.config.debug > 1:
                    self.config.printDebug(2, "%s: resolved dependencies:" % r.getNEVRA())
                    for (u, s) in resolved:
                        s2 = ""
                        for r2 in s:
                            s2 += "%s " % r2.getNEVRA()
                        self.config.printDebug(2, "\t%s: %s" % (depString(u), s2))
                if len(unresolved) > 0:
                    no_unresolved = 0
                    self.config.printError("%s: unresolved dependencies:" % r.getNEVRA())
                    for u in unresolved:
                        self.config.printError("\t%s" % depString(u))
        return no_unresolved
    # ----

    def getResolvedDependencies(self):
        """ Get all resolved dependencies """
        all_resolved = HashList()
        for name in self:
            for r in self[name]:
                self.config.printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
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
        for name in self:
            for r in self[name]:
                self.config.printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
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

        if self.config.noconflicts:
            # conflicts turned off
            return conflicts
        if self.config.checkinstalled == 0 and len(self.installs) == 0:
            # no conflicts if there is no new package
            return conflicts

        for name in self:
            for r in self[name]:
                self.config.printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    (name, flag, version) = c
                    s = self.searchDependency(c)
                    _conflicts = self._getConflicts(r, c, s)
                    for c in _conflicts:
                        if r not in conflicts:
                            conflicts[r] = [ ]
                        if c not in conflicts[r]:
                            conflicts[r].append(c)
        return conflicts
    # ----

    def getObsoletes(self):
        """ Check for conflicts in obsoletes """

        conflicts = HashList()

        if self.config.noconflicts:
            # conflicts turned off
            return conflicts
        if self.config.checkinstalled == 0 and len(self.installs) == 0:
            # no conflicts if there is no new package
            return conflicts

        for name in self:
            for r in self[name]:
                self.config.printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["obsoletes"]:
                    (name, flag, version) = c
                    s = self.searchDependency(c)
                    _conflicts = self._getConflicts(r, c, s)
                    for c in _conflicts:
                        if r not in conflicts:
                            conflicts[r] = [ ]
                        if c not in conflicts[r]:
                            conflicts[r].append(c)
        return conflicts
    # ----

    def checkConflicts(self):
        conflicts = self.getConflicts()
        if len(conflicts) == 0:
            return self.OK

        for pkg in conflicts:
            self.config.printError("%s conflicts with:" % pkg.getNEVRA())
            if self.config.verbose > 1:
                for c,r in conflicts[pkg]:
                    self.config.printError("\t'%s' <=> %s" % (depString(c), r.getNEVRA()))
            else:
                pkgs = [ ]
                for c,r in conflicts[pkg]:
                    if r not in pkgs:
                        self.config.printError("\t%s" % r.getNEVRA())
                        pkgs.append(r)
        return -1
    # ----

    def getFileConflicts(self):
        """ Check for file conflicts """
        conflicts = HashList()

        if self.config.nofileconflicts:
            # file conflicts turned off
            return conflicts
        if self.config.checkinstalled == 0 and len(self.installs) == 0:
            # no conflicts if there is no new package
            return conflicts
        
        for filename in self.filenames_list.multi.keys():
            self.config.printDebug(1, "Checking for file conflicts for '%s'" % filename)
            s = self.filenames_list.search(filename)
            for j in xrange(len(s)):
                fi1 = s[j].getRpmFileInfo(filename)
                for k in xrange(j+1, len(s)):
                    if not self._hasFileConflict(s[j], s[k], filename, fi1):
                        continue
                    if s[j] not in conflicts:
                        conflicts[s[j]] = [ ]
                    conflicts[s[j]].append((filename, s[k]))
        return conflicts
    # ----

    def checkFileConflicts(self):
        conflicts = self.getFileConflicts()
        if len(conflicts) == 0:
            return self.OK

        for pkg in conflicts:
            self.config.printError("%s file conflicts with:" % pkg.getNEVRA())
            if self.config.verbose > 1:
                for f,r in conflicts[pkg]:
                    self.config.printError("\t'%s' <=> %s" % (f, r.getNEVRA()))
            else:
                pkgs = [ ]
                for f,r in conflicts[pkg]:
                    if r not in pkgs:
                        self.config.printError("\t%s" % r.getNEVRA())
                        pkgs.append(r)
        return -1
    # ----
    
    def reloadDependencies(self):
        self.provides_list.clear()
        self.obsoletes_list.clear()
        self.filenames_list.clear()

        for name in self:
            for pkg in self[name]:
                self.provides_list.addPkg(pkg)
                self.obsoletes_list.addPkg(pkg)
                self.filenames_list.addPkg(pkg)
    # ----

    def resolve(self):
        """ Start the resolving process
        Check dependencies and conflicts.
        Return 1 if everything is OK, a negative number if not. """

        # checking dependencies
        if self.checkDependencies() != 1:
            return -1

        if self.config.noconflicts == 0:
            # check for conflicts
            if self.checkConflicts() != 1:
                return -2

        if self.config.nofileconflicts == 0:
            # check for file conflicts
            if self.checkFileConflicts() != 1:
                return -3

        return 1

# vim:ts=4:sw=4:showmatch:expandtab
