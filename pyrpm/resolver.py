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
    """A database of Provides:

    Files are represented as (filename, 0, "")."""

    def __init__(self, config):
        self.config = config            # FIXME: write-only
        self.clear()

    def clear(self):
        """Discard all stored data"""

        # %name => [(flag, EVR string, providing RpmPackage)]
        self.provide = { }

    def _addProvide(self, name, flag, version, rpm):
        """Add Provides: (name, RPMSENSE_* flag, EVR string) by RpmPackage rpm
        to database"""

        self.provide.setdefault(name, []).append((flag, version, rpm))

    def addPkg(self, rpm):
        """Add Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm["provides"]:
            self._addProvide(name, flag, version, rpm)

    def _removeProvide(self, name, flag, version, rpm):
        """Remove Provides: (name, RPMSENSE_* flag, EVR string) by RpmPackage
        rpm."""

        provide = self.provide[name]
        i = 0
        while i < len(provide):
            p = provide[i]
            if p[0] == flag and p[1] == version and p[2] == rpm:
                del provide[i]
                break
            else:
                i += 1
        if len(provide) == 0:
            del self.provide[name]

    def removePkg(self, rpm):
        """Remove Provides: by RpmPackage rpm"""

        for (name, flag, version) in rpm["provides"]:
            self._removeProvide(name, flag, version, rpm)

    def search(self, name, flag, version):
        """Return a list of RpmPackage's matching the Requires:
        (name, RPMSENSE_* flag, EVR string)."""

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
            if v == "": # compare with package version for unversioned provides
                evr2 = (rpm.getEpoch(), rpm["version"], rpm["release"])
                if evrCompare(evr2, flag, evr):
                    ret.append(rpm)

        return ret

# ----------------------------------------------------------------------------

class ConflictsList(ProvidesList):
    """A database of Conflicts:"""

    def addPkg(self, rpm):
        """Add Conflicts: by RpmPackage rpm"""

        for (name, flag, version) in rpm["conflicts"]:
            self._addProvide(name, flag, version, rpm)

    def removePkg(self, rpm):
        """Remove Conflicts: by RpmPackage rpm"""

        for (name, flag, version) in rpm["conflicts"]:
            self._removeProvide(name, flag, version, rpm)

    def search(self, name, flag, version):
        # s/Conflicts/Obsoletes/ in ObsoletesList
        """Return a list of RpmPackage's with Conflicts: matching
        (name, RPMSENSE_* flag, EVR string)."""

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

        return ret

# ----------------------------------------------------------------------------

class ObsoletesList(ConflictsList):
    """A database of Obsoletes:"""

    def addPkg(self, rpm):
        """Add Obsoletes: by RpmPackage rpm"""

        for (name, flag, version) in rpm["obsoletes"]:
            self._addProvide(name, flag, version, rpm)

    def removePkg(self, rpm):
        """Remove Conflicts: by RpmPackage rpm"""

        for (name, flag, version) in rpm["obsoletes"]:
            self._removeProvide(name, flag, version, rpm)

# ----------------------------------------------------------------------------

class RpmResolver(RpmList):
    """A RpmList that also handles obsoletes, can check for conflicts
    and gather resolvable and unresolvable dependencies."""

    OBSOLETE_FAILED = -10
    CONFLICT = -11
    FILE_CONFLICT = -12
    # ----

    def __init__(self, config, installed, is_repo = None):
        RpmList.__init__(self, config, installed)
        if is_repo:
            return
        # fill in installed_ structures
        check_installed = self.config.checkinstalled
        self.config.checkinstalled = 1
        # HashList: RpmPackage => [(name, RPMSENSE_* flags, EVR string)].
        # unresolved dependencies among "originally" installed packages
        self.installed_unresolved = self.getUnresolvedDependencies()
        # HashList: RpmPackage =>
        # [((name, RPMSENSE_* flags, EVR string), matching RpmPackage)].
        # conflicts among "originally" installed packages
        self.installed_conflicts = self.getConflicts()
        # HashList: RpmPackage =>
        # [((name, RPMSENSE_* flags, EVR string), matching RpmPackage)].
        # obsoletes among "originally" installed packages
        self.installed_obsoletes = self.getObsoletes()
        # HashList: RpmPackage => [(filename, conflicting RpmPackage)].
        # Each pair of packages is represented only once, the first added to
        # self.filenames_list is the HashList key.
        self.installed_file_conflicts = self.getFileConflicts()
        self.config.checkinstalled = check_installed
    # ----

    def clear(self):
        RpmList.clear(self)
        self.provides_list = ProvidesList(self.config) # Provides by self.list
        # Obsoletes by self.list
        self.obsoletes_list = ObsoletesList(self.config)
        # Files in self.list
        self.filenames_list = base.FilenamesList()
        # new RpmPackage =>
        # ["originally" installed RpmPackage obsoleted by update]
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
            # check Obsoletes: for our Provides:
            for dep in pkg["provides"]:
                (name, flag, version) = dep
                s = self.obsoletes_list.search(name, flag, version)
                if self._checkObsoletes(pkg, dep, s, operation):
                    return self.CONFLICT
            # check conflicts for filenames
            for f in pkg["filenames"]:
                dep = (f, 0, "")
                s = self.obsoletes_list.search(f, 0, "")
                if self._checkObsoletes(pkg, dep, s, operation):
                    return self.CONFLICT

        return RpmList.install(self, pkg, operation)
    # ----

    def update(self, pkg):
        # get obsoletes

        # Valid only during OP_UPDATE: list of RpmPackage's that will be
        # obsoleted by the current update
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
            msg = fmt % (pkg.getNEVRA(), r.getNEVRA(), r.getNEVRA())
            if self.config.test:
                self.config.printInfo(0, msg+"\n")
            else:
                self.config.printWarning(1, msg)
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
        """RpmPackage pkg to be newly installed during operation provides dep,
        which is obsoleted by RpmPackage's in list.

        Filter out irrelevant obsoletes and return 1 if pkg remains obsoleted,
        0 otherwise. dep is (name, RPMSENSE_* flag, EVR string) or
        (filename, 0, "")."""

        ret = 0
        conflicts = self._getObsoletes(pkg, dep, list, operation)
        for (c,r) in conflicts:
            if operation == OP_UPDATE and \
                   (r in self.pkg_updates or r in self.pkg_obsoletes):
                continue
            if self.isInstalled(r):
                fmt = "%s conflicts with already installed %s on %s, skipping"
            else:
                fmt = "%s conflicts with already added %s on %s, skipping"
            self.config.printWarning(1, fmt % (pkg.getNEVRA(), depString(c),
                                               r.getNEVRA()))
            ret = 1
        return ret
    # ----

    def _getObsoletes(self, pkg, dep, list, operation=OP_INSTALL):
        """RpmPackage pkg to be newly installed during operation provides dep,
        which is obsoleted by RpmPackage's in list.

        Return a pruned list of
        ((name, RPMSENSE_* flags, EVR string), RpmPackage): handle
        config.checkinstalled, always allow updates and multilib packages.  dep
        is (name, RPMSENSE_* flag, EVR string) or (filename, 0, "")."""

        obsoletes = [ ]
        if len(list) != 0:
            if pkg in list:
                list.remove(pkg)
            for r in list:
                if self.config.checkinstalled == 0 and \
                       self._hasConflict(dep, self.installed_obsoletes):
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

    def _hasConflict(self, dep, conflicts_list):
        """Return 1 if (name, RPMSENSE_*flag, EVR string) dep is already
        present in self.installed_{obsoletes_conflicts} conflicts_list."""

        found = 0
        for pkg in conflicts_list:
            for (c,r) in conflicts_list[pkg]:
                if c == dep:
                    found = 1
                    break
        return found
    # ----

    def _getConflicts(self, pkg, dep, list):
        """RpmPackage pkg Conflicts: or Obsoletes: (name, RPMSENSE_* flag,
        EVR string) dep, with RpmPackage's in list matching that.

        Return a pruned list of (dep, matching RpmPackage): handle
        config.checkinstalled, always allow updates and multilib packages."""

        conflicts = [ ]
        if len(list) != 0:
            if pkg in list:
                list.remove(pkg)
            for r in list:
                if self.config.checkinstalled == 0 and \
                       (self._hasConflict(dep, self.installed_conflicts) or \
                        self._hasConflict(dep, self.installed_obsoletes)):
                    continue
                if pkg.getNEVR() == r.getNEVR():
                    continue
                conflicts.append((dep, r))
        return conflicts
    # ----

    def _hasFileConflict(self, pkg1, pkg2, filename, pkg1_fi):
        """RpmPackage's pkg1 and pkg2 share filename.

        Return 1 if the conflict is "real", 0 if it should be ignored.
        pkg1_fi is RpmFileInfo of filename in pkg1."""
        # it is ok if there is a file conflict which is in
        # installed_file_conflicts and not checkinstalled
        if self.config.checkinstalled == 0 and \
               pkg1 in self.installed_file_conflicts and \
               (filename,pkg2) in self.installed_file_conflicts[pkg1]:
            return 0
        fi = pkg2.getRpmFileInfo(filename)
        # do not check packages with the same NEVR which are
        # not buildarchtranslate compatible
        if pkg1.getNEVR() == pkg2.getNEVR() and \
               buildarchtranslate[pkg1["arch"]] != \
               buildarchtranslate[pkg2["arch"]] and \
               pkg1["arch"] != "noarch" and \
               pkg2["arch"] != "noarch" and \
               pkg1_fi.filecolor != fi.filecolor and \
               pkg1_fi.filecolor > 0 and fi.filecolor > 0:
            return 0
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
        """Remove RpmPackage obsolete_pkg because it will be obsoleted by
        RpmPackage pkg.

        Return an RpmList error code."""

        if self.isInstalled(obsolete_pkg):
            # assert obsolete_pkg not in self.obsoletes
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
        """RpmPackage old_pkg will be replaced by RpmPackage pkg; inherit
        packages obsoleted by old_pkg."""

        if old_pkg in self.obsoletes:
            if pkg in self.obsoletes:
                self.obsoletes[pkg].extend(self.obsoletes[old_pkg])
                normalizeList(self.obsoletes[pkg])
            else:
                self.obsoletes[pkg] = self.obsoletes[old_pkg]
            del self.obsoletes[old_pkg]
    # ----

    def searchDependency(self, dep):
        """Return list of RpmPackages from self.list providing
        (name, RPMSENSE_* flag, EVR string) dep."""
        (name, flag, version) = dep
        s = self.provides_list.search(name, flag, version)
        if name[0] == '/': # all filenames are beginning with a '/'
            s += self.filenames_list.search(name)
        return s
    # ----

    def getPkgDependencies(self, pkg):
        """Gather all dependencies of RpmPackage pkg.

        Return (unresolved, resolved). "unresolved" is a list of
        (name, RPMSENSE_* flag, EVR string); "resolved" is a list of
        ((name, RPMSENSE_* flag, EVR string),
         [relevant resolving RpmPackage's]).
        A RpmPackage is ignored (not "relevant") if it is not pkg and pkg
        itself fulfills that dependency."""

        unresolved = [ ]
        resolved = [ ]

        for u in pkg["requires"]:
            if u[0].startswith("rpmlib("): # drop rpmlib requirements
                continue
            s = self.searchDependency(u)
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
        """Check dependencies, report errors.

        Return 1 if all dependencies are resolved, 0 if not (after warning the
        user)."""

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
        """Get resolved dependencies.

        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string),
          [relevant resolving RpmPackage's])]."""

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
        """Get all unresolved dependencies.

        Return a HashList: RpmPackage =>
        [(name, RPMSENSE_* flags, EVR string)]."""

        all_unresolved = HashList()

        for name in self:
            for pkg in self[name]:
                unresolved = [ ]
                for u in pkg["requires"]:
                    if u[0].startswith("rpmlib("): # drop rpmlib requirements
                        continue
                    s = self.searchDependency(u)
                    if len(s) > 0: # found something
                        continue
                    if self.config.checkinstalled == 0 and \
                           pkg in self.installed_unresolved and \
                           u in self.installed_unresolved[pkg]:
                        continue
                    unresolved.append(u)
                if len(unresolved) > 0:
                    if pkg not in all_unresolved:
                        all_unresolved[pkg] = [ ]
                    all_unresolved[pkg].extend(unresolved)
        return all_unresolved
    # ----

    def getConflicts(self):
        """Check for conflicts in conflicts and obsoletes among currently
        installed packages.

        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string), conflicting RpmPackage)]."""

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
        """Check for obsoletes among packages in self.list.

        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string), obsoleted RpmPackage)]."""

        obsoletes = HashList()

        if self.config.noconflicts:
            # conflicts turned off, obsoletes are also conflicts, but in an
            # other level
            return obsoletes
        if self.config.checkinstalled == 0 and len(self.installs) == 0:
            # no obsoletes if there is no new package
            return obsoletes

        for name in self:
            for r in self[name]:
                self.config.printDebug(1, "Checking for obsoletes for %s" % r.getNEVRA())
                for c in r["obsoletes"]:
                    (name, flag, version) = c
                    s = self.searchDependency(c)
                    _obsoletes = self._getConflicts(r, c, s)
                    for c in _obsoletes:
                        if r not in obsoletes:
                            obsoletes[r] = [ ]
                        if c not in obsoletes[r]:
                            obsoletes[r].append(c)
        return obsoletes
    # ----

    def checkConflicts(self):
        """Check for package conflicts, report errors.

        Return 1 if OK, 0 if there are conflicts (after warning the user)."""

        conflicts = self.getConflicts()
        if len(conflicts) == 0:
            return 1

        for pkg in conflicts:
            conf = { }
            for c,r in conflicts[pkg]:
                if not r in conf:
                    conf[r] = [ ]
                if not c in conf[r]:
                    conf[r].append(c)
            for r in conf.keys():
                self.config.printError("%s conflicts with %s on:" % \
                                       (pkg.getNEVRA(), r.getNEVRA()))
                for c in conf[r]:
                    self.config.printError("\t%s" % depString(c))
        return 0
    # ----

    def getFileConflicts(self):
        """Find file conflicts among packages in self.list.

        Return a HashList:
        RpmPackage => [(filename, conflicting RpmPackage)]."""

        conflicts = HashList()

        if self.config.nofileconflicts:
            # file conflicts turned off
            return conflicts
        if self.config.checkinstalled == 0 and len(self.installs) == 0:
            # no conflicts if there is no new package
            return conflicts

        if self.config.timer:
            time1 = time.clock()
        for (dirname, dirhash) in self.filenames_list.path.iteritems():
            for _filename in dirhash.keys():
                if len(dirhash[_filename]) < 2:
                    continue
                filename = dirname + _filename
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

        if self.config.timer:
            self.config.printInfo(0, "fileconflict checking took %s seconds\n" % (time.clock() - time1))

        return conflicts
    # ----

    def checkFileConflicts(self):
        """Check file conflicts, report errors.

        Return 1 if OK, 0 if there are file conflicts (after warning the
        user)."""

        conflicts = self.getFileConflicts()
        if len(conflicts) == 0:
            return 1

        for pkg in conflicts:
            conf = { }
            for f,r in conflicts[pkg]:
                if not r in conf:
                    conf[r] = [ ]
                if not f in conf[r]:
                    conf[r].append(f)
            for r in conf.keys():
                self.config.printError("%s file conflicts with %s on:" % \
                                       (pkg.getNEVRA(), r.getNEVRA()))
                for f in conf[r]:
                    self.config.printError("\t%s" % f)
        return 0
    # ----

    def reloadDependencies(self):
        """Reread cached databases of provides, obsolets and file lists.

        Note that installed_* are not affected."""

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
        """Check dependencies and conflicts.

        Return 1 if everything is OK, a negative number if not (after warning
        the user)."""

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
