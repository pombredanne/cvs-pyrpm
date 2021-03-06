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
from functions import *
import base
from logger import log

# ----------------------------------------------------------------------------

class RpmResolver:
    """A Database that handles installs, updates, etc., can check for conflicts
    and gather resolvable and unresolvable dependencies.

    Allows "direct" access to packages: "for %name in self",
    "self[idx] => %name", "self[%name] => RpmPackage", "pkg in self."."""

    OK = 1
    ALREADY_INSTALLED = -1
    OLD_PACKAGE = -2
    NOT_INSTALLED = -3
    UPDATE_FAILED = -4
    ALREADY_ADDED = -5
    ARCH_INCOMPAT = -6
    OBSOLETE_FAILED = -10
    CONFLICT = -11
    FILE_CONFLICT = -12
    # ----

    def __init__(self, config, database, nocheck=0):
        """Initialize, with the "currently installed" packages in RpmPackage
        list installed."""

        self.config = config
        self.database = database
        self.clear()

        # do no further checks
        if nocheck:
            return

        if config.checkinstalled == 0:
            self.installed_unresolved_file_requires = self.getUnresolvedFileRequires()
        else:
            self.check_installs = set(self.database.getPkgs())

    # ----

    def clear(self):
        """Clear all changed data."""

        self.installs = set() # Added RpmPackage's
        self.check_installs = set()
        # new RpmPackage
        # => ["originally" installed RpmPackage removed by update]
        self.updates = { }
        self.erases = set() # Removed RpmPackage's
        self.check_erases = set()
        self.check_file_requires = False
        # new RpmPackage =>
        # ["originally" installed RpmPackage obsoleted by update]
        self.obsoletes = { }
        self.installed_unresolved_file_requires = set()
    # ----


    def install(self, pkg, operation=OP_INSTALL):
        """Add RpmPackage pkg as part of the defined operation.

        Return an RpmList error code (after warning the user)."""

        # Add RpmPackage
        # Return an RpmList error code (after warning the user). Check whether
        # a package with the same NEVRA is already in the database.

        name = pkg["name"]
        if self.database.hasName(name):
            for r in self.database.getPkgsByName(name):
                ret = self.__install_check(r, pkg)
                if ret != self.OK:
                    return ret

        if not self.isInstalled(pkg):
            self.installs.add(pkg)
        self.erases.discard(pkg)
        self.check_installs.add(pkg)

        self.database.addPkg(pkg)

        return self.OK
    # ----

    def update(self, pkg):
        name = pkg["name"]

        # get obsoletes
        # Valid only during OP_UPDATE: list of RpmPackage's that will be
        # obsoleted by the current update
        self.pkg_obsoletes = set()
        for u in pkg["obsoletes"]:
            s = self.database.searchDependency(u[0], u[1], u[2])
            for r in s:
                if r["name"] != pkg["name"]:
                    self.pkg_obsoletes.add(r)

        # update package

        # Valid only during OP_UPDATE: list of RpmPackage's that will be
        # removed by the current update
        self.pkg_updates = [ ]
        for r in self.database.getPkgsByName(name):
            ret = pkgCompare(r, pkg)
            if ret > 0: # old_ver > new_ver
                if self.config.oldpackage == 0:
                    if self.isInstalled(r):
                        msg = "%s: A newer package is already installed"
                    else:
                        msg = "%s: A newer package was already added"
                    log.debug1(msg, pkg.getNEVRA())
                    del self.pkg_updates
                    return self.OLD_PACKAGE
                else:
                    # old package: simulate a new package
                    ret = -1
            if ret < 0: # old_ver < new_ver
                if self.config.exactarch == 1 and \
                       self.__arch_incompat(pkg, r):
                    del self.pkg_updates
                    return self.ARCH_INCOMPAT

                if archDuplicate(pkg["arch"], r["arch"]) or \
                       pkg["arch"] == "noarch" or r["arch"] == "noarch":
                    self.pkg_updates.append(r)
            else: # ret == 0, old_ver == new_ver
                if self.config.exactarch == 1 and \
                       self.__arch_incompat(pkg, r):
                    del self.pkg_updates
                    return self.ARCH_INCOMPAT

                ret = self.__install_check(r, pkg) # Fails for same NEVRAs
                if ret != self.OK:
                    del self.pkg_updates
                    return ret

                if archDuplicate(pkg["arch"], r["arch"]):
                    if archCompat(pkg["arch"], r["arch"]):
                        if self.isInstalled(r):
                            msg = "%s: Ignoring due to installed %s"
                            ret = self.ALREADY_INSTALLED
                        else:
                            msg = "%s: Ignoring due to already added %s"
                            ret = self.ALREADY_ADDED
                        log.debug1(msg, pkg.getNEVRA(), r.getNEVRA())
                        del self.pkg_updates
                        return ret
                    else:
                        self.pkg_updates.append(r)

        ret = self.install(pkg, operation=OP_UPDATE)
        if ret != self.OK:
            del self.pkg_updates
            return ret

        for r in self.pkg_updates:
            if self.isInstalled(r):
                log.debug1("%s was already installed, replacing with %s",
                           r.getNEVRA(), pkg.getNEVRA())
            else:
                log.debug1("%s was already added, replacing with %s",
                           r.getNEVRA(), pkg.getNEVRA())
            if self._pkgUpdate(pkg, r) != self.OK: # Currently can't fail
                del self.pkg_updates
                return self.UPDATE_FAILED

        del self.pkg_updates

        # handle obsoletes
        for r in self.pkg_obsoletes:
            # package is not the same and has not the same name
            if self.isInstalled(r):
                fmt = "%s obsoletes installed %s, removing %s"
            else:
                fmt = "%s obsoletes added %s, removing %s"
            log.debug1(fmt, pkg.getNEVRA(), r.getNEVRA(), r.getNEVRA())
            if self._pkgObsolete(pkg, r) != self.OK:
                del self.pkg_obsoletes
                return self.OBSOLETE_FAILED

        del self.pkg_obsoletes

        return self.OK
    # ----

    def freshen(self, pkg):
        """Add RpmPackage pkg, removing older versions, if a package of the
        same %name and base arch is "originally" installed.

        Return an RpmList error code."""

        found = 0

        for r in self.database.getPkgByName(pkg["name"]):
            if r in self.installs: continue

            if archDuplicate(pkg["arch"], r["arch"]):
                found = 1
                break
        if not found:
            # pkg already got deleted from database
            name = pkg["name"]
            for r in self.erases:
                if (r["name"] == name and
                    archDuplicate(pkg["arch"], r["arch"])):
                    found = 1
                    break

        if found == 1:
            return self.update(pkg)

        return self.NOT_INSTALLED

    # ----

    def erase(self, pkg):
        """Remove RpmPackage.

        Return an RpmList error code (after warning the user)."""

        name = pkg["name"]
        if not self.database.hasName(name) or \
               pkg not in self.database.getPkgsByName(name):
            log.warning("Package %s (id %s) not found", pkg.getNEVRA(),
                        id(pkg))
            return self.NOT_INSTALLED

        if self.isInstalled(pkg):
            self.erases.add(pkg)
        self.installs.discard(pkg)
        self.check_installs.discard(pkg)
        if pkg in self.updates:
            del self.updates[pkg]

        if pkg in self.obsoletes:
            del self.obsoletes[pkg]
        self.check_erases.add(pkg)
        self.check_file_requires = True

        self.database.removePkg(pkg)

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
            log.warning(fmt, pkg.getNEVRA(), depString(c), r.getNEVRA())
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
                del list[pkg]
            for r in list:
                if operation == OP_UPDATE:
                    if pkg["name"] == r["name"]:
                        continue
                else:
                    if pkg.getNEVR() == r.getNEVR():
                        continue
                obsoletes.append((dep, r))
        return obsoletes

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
                if pkg.getNEVR() == r.getNEVR():
                    continue
                conflicts.append((dep, r))
        return conflicts
    # ----

    def _hasFileConflict(self, pkg1, pkg2, filename):
        """RpmPackage's pkg1 and pkg2 share filename.

        Return 1 if the conflict is "real", 0 if it should be ignored.
        pkg1_fi is RpmFileInfo of filename in pkg1."""

        # pkg1_fi = pkg1.getRpmFileInfo(idx1)
        pkg1_fi = pkg1.getRpmFileInfo(filename)
        pkg2_fi = pkg2.getRpmFileInfo(filename)
        # do not check packages with the same NEVR which are
        # not buildarchtranslate compatible
        if pkg1.getNEVR() == pkg2.getNEVR() and \
               buildarchtranslate[pkg1["arch"]] != \
               buildarchtranslate[pkg2["arch"]] and \
               pkg1["arch"] != "noarch" and \
               pkg2["arch"] != "noarch" and \
               pkg1_fi.filecolor != pkg2_fi.filecolor and \
               pkg1_fi.filecolor > 0 and pkg2_fi.filecolor > 0:
            return 0

        # check if data is sufficient
        if not pkg1_fi.mode:
            raise ValueError, \
                  "Package '%s': File mode is not set for file '%s'" % \
                  (pkg1.getNEVRA(), filename)
        if not pkg2_fi.mode:
            raise ValueError, \
                  "Package '%s': File mode is not set for file '%s'" % \
                  (pkg2.getNEVRA(), filename)

        # check if user and group are identical
        if pkg1_fi.uid != pkg2_fi.uid and \
               pkg1_fi.gid != pkg2_fi.gid:
            return 1

        # ignore directories
        if S_ISDIR(pkg1_fi.mode) and S_ISDIR(pkg2_fi.mode):
            return 0
        # ignore links
        if S_ISLNK(pkg1_fi.mode) and S_ISLNK(pkg2_fi.mode) and \
               (pkg1_fi.linkto == pkg2_fi.linkto):
            return 0

        # ignore identical files
        if pkg1_fi.mode == pkg2_fi.mode and \
               pkg1_fi.filesize == pkg2_fi.filesize and \
               pkg1_fi.md5sum == pkg2_fi.md5sum:
            return 0

        # ignore ghost files
        if pkg1_fi.flags & base.RPMFILE_GHOST or \
               pkg2_fi.flags & base.RPMFILE_GHOST:
            return 0

        return 1
    # ----

    def _pkgObsolete(self, pkg, obsolete_pkg):
        """Remove RpmPackage obsolete_pkg because it will be obsoleted by
        RpmPackage pkg.

        Return an RpmList error code."""

        if self.isInstalled(obsolete_pkg):
            # assert obsolete_pkg not in self.obsoletes
            self.obsoletes.setdefault(pkg, [ ]).append(obsolete_pkg)
        else:
            self._inheritUpdates(pkg, obsolete_pkg)
            self._inheritObsoletes(pkg, obsolete_pkg)
        return self.erase(obsolete_pkg)
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        """Remove RpmPackage update_pkg because it will be replaced by
        RpmPackage pkg.

        Return an RpmList error code."""

        if not self.isInstalled(update_pkg):
            self._inheritObsoletes(pkg, update_pkg)

        if self.isInstalled(update_pkg):
            # assert update_pkg not in self.updates
            self.updates.setdefault(pkg, [ ]).append(update_pkg)
        else:
            self._inheritUpdates(pkg, update_pkg)
        return self.erase(update_pkg)
    # ----

    def isInstalled(self, pkg):
        """Return True if RpmPackage pkg is an "originally" installed
        package.

        Note that having the same NEVRA is not enough, the package should
        be from self.names."""

        if pkg in self.erases:
            return True
        if pkg in self.installs:
            return False
        return pkg in self.database

    # ----

    def __install_check(self, r, pkg):
        """Check whether RpmPackage pkg can be installed when RpmPackage r
        with same %name is already in the current list.

        Return an RpmList error code (after warning the user)."""

        if r == pkg or r.isEqual(pkg):
            if self.isInstalled(r):
                log.debug1("%s: %s is already installed", pkg.getNEVRA(),
                           r.getNEVRA())
                return self.ALREADY_INSTALLED
            else:
                log.debug1("%s: %s was already added", pkg.getNEVRA(),
                           r.getNEVRA())
                return self.ALREADY_ADDED
        return self.OK
    # ----

    def __arch_incompat(self, pkg, r):
        """Return True (and warn) if RpmPackage's pkg and r have different
        architectures, but the same base arch.

        Warn the user before returning True."""

        if pkg["arch"] != r["arch"] and archDuplicate(pkg["arch"], r["arch"]):
            log.debug1("%s does not match arch %s.", pkg.getNEVRA(), r["arch"])
            return 1
        return 0
    # ----

    def _inheritUpdates(self, pkg, old_pkg):
        """RpmPackage old_pkg will be replaced by RpmPackage pkg; inherit
        packages updated by old_pkg."""

        if old_pkg in self.updates:
            if pkg in self.updates:
                self.updates[pkg].extend(self.updates[old_pkg])
                normalizeList(self.updates[pkg])
            else:
                self.updates[pkg] = self.updates[old_pkg]
            del self.updates[old_pkg]
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

        # TODO: use db.getRequires()
        for u in pkg["requires"]:
            if u[0][:7] == "rpmlib(": # drop rpmlib requirements
                continue
            s = self.database.searchDependency(u[0], u[1], u[2])
#            # drop self script prereq and self script postun
#            # these prereqs can not be solved by the package itself
#            if len(s) > 0 and pkg in s and isLegacyPreReq(u[1]) and \
#                   (u[1] & RPMSENSE_SCRIPT_PRE != 0 or \
#                    u[1] & RPMSENSE_SCRIPT_POSTUN != 0):
#                if len(s) == 1:
#                    s = [ ]
#                else:
#                    s.remove(pkg)
            if len(s) == 0: # unresolved
                unresolved.append(u)
            else: # resolved
                if pkg in s and len(s) > 1:
                    s = [pkg]
                resolved.append((u, s))
        return (unresolved, resolved)
    # ----

    def getResolvedPkgDependencies(self, pkg):
        """Gather all dependencies of RpmPackage pkg.

        Return (unresolved, resolved). "unresolved" is a list of
        (name, RPMSENSE_* flag, EVR string); "resolved" is a list of
        ((name, RPMSENSE_* flag, EVR string),
         [relevant resolving RpmPackage's]).
        A RpmPackage is ignored (not "relevant") if it is not pkg and pkg
        itself fulfills that dependency."""

        resolved = [ ]

        # TODO: use db.getRequires()
        for u in pkg["requires"]:
            if u[0][:7] == "rpmlib(": # drop rpmlib requirements
                continue
            s = self.database.searchDependency(u[0], u[1], u[2])
            if len(s) > 0: # resolved
                if pkg in s and len(s) > 1:
                    s = [pkg]
                resolved.append((u, s))
        return resolved

    # ----

    def getUnresolvedFileRequires(self, ignore=set()):
        db = self.database
        filereqs = db.getFileRequires()
        normalizeList(filereqs)
        if ignore:
            filereqs = [f for f in filereqs if f not in ignore]
        result = set()
        for myfile in filereqs:
            if not db.searchDependency(myfile, 0, ""):
                result.add(myfile)
        return result

    # ----

    def checkDependencies(self):
        """Check dependencies, report errors.

        Return 1 if all dependencies are resolved, 0 if not (after warning the
        user)."""

        no_unresolved = 1

        if self.config.checkinstalled == 0:
            unresolved = self.getUnresolvedDependencies()
            for p in unresolved.keys():
                log.error("%s: unresolved dependencies:", p.getNEVRA())
                for u in unresolved[p]:
                    log.error("\t%s", depString(u))
            if unresolved:
                return 0
            return 1

        for name in self.database.getNames():
            for r in self.database.getPkgsByName(name):
                if self.config.checkinstalled == 0 and \
                       len(self.erases) == 0 and self.isInstalled(r):
                    # do not check installed packages if no packages
                    # are getting removed (by erase, update or obsolete)
                    continue
                log.debug1("Checking dependencies for %s", r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0:
                    log.debug2("%s: resolved dependencies:", r.getNEVRA())
                    for (u, s) in resolved:
                        s2 = ""
                        for r2 in s:
                            s2 += "%s " % r2.getNEVRA()
                        log.debug2("\t%s: %s", depString(u), s2)
                if len(unresolved) > 0:
                    no_unresolved = 0
                    log.error("%s: unresolved dependencies:", r.getNEVRA())
                    for u in unresolved:
                        log.erro("\t%s", depString(u))
        return no_unresolved
    # ----

    def getResolvedDependencies(self):
        """Get resolved dependencies.

        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string),
          [relevant resolving RpmPackage's])]."""

        all_resolved = HashList()
        for name in self.database.getNames():
            for r in self.database.getPkgsByName(name):
                log.debug1("Checking dependencies for %s", r.getNEVRA())
                (unresolved, resolved) = self.getPkgDependencies(r)
                if len(resolved) > 0:
                    all_resolved.setdefault(r, [ ]).extend(resolved)
        return all_resolved

    # ----

    def getUnresolvedDependencies(self):
        """Get all unresolved dependencies.

        Return a HashList: RpmPackage =>
        [(name, RPMSENSE_* flags, EVR string)]."""

        unresolved = HashList()

        for p, d in self.iterUnresolvedDependencies():
            unresolved.setdefault(p, [ ]).append(d)

        return unresolved

    # ----

    def iterUnresolvedDependencies(self):
        """only check changes done to the database"""
        for pkg in list(self.check_erases):
            # check if provides are required and not provided by another
            # package
            ok = True
            for dep in pkg["provides"]:
                sr = self.database.searchRequires(dep[0], dep[1], dep[2])
                for p in sr:
                    for d in sr[p]:
                        sp = self.database.searchProvides(d[0], d[1], d[2])
                        if len(sp) > 0:
                            continue
                        ok = False
                        yield p, d
            if ok and pkg in self.check_erases:
                self.check_erases.remove(pkg)

        # check new packages
        for pkg in list(self.check_installs):
            ok = True
            for u in pkg["requires"]:
                if u[0][:7] == "rpmlib(": # drop rpmlib requirements
                    continue
                s = self.database.searchDependency(u[0], u[1], u[2])
                if len(s) > 0: # found something
                    continue
                ok = False
                yield pkg, u
            if ok and pkg in self.check_installs:
                self.check_installs.remove(pkg)

        if self.check_file_requires:
            ok = True
            # check if filenames are required and not provided by another
            # package
            unresolved = self.getUnresolvedFileRequires(
                self.installed_unresolved_file_requires)
            for f in unresolved:
                sr = self.database.searchRequires(f, 0, "")
                for p, r in sr.iteritems():
                    for dep in r:
                        ok = False
                        yield p, dep
            self.check_file_requires = not ok or bool(self.check_erases)

    def getPkgConflicts(self, pkg, deps, dest):
        """Check for conflicts to pkg's deps, add results to dest[pkg].

        dest[pkg] will be
        [((name, RPMSENSE_* flags, EVR string), conflicting RpmPackage)]."""

        for c in deps:
            s = self.database.searchDependency(c[0], c[1], c[2])
            pruned = self._getConflicts(pkg, c, s)
            for c in pruned:
                if pkg not in dest:
                    dest[pkg] = [ ]
                if c not in dest[pkg]:
                    dest[pkg].append(c)
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

        if self.config.checkinstalled == 0:
            for r in self.installs:
                log.debug1("Checking for conflicts for %s", r.getNEVRA())
                self.getPkgConflicts(r, r["conflicts"] + r["obsoletes"],
                                     conflicts)
            return conflicts

        for name in self.database.getNames():
            for r in self.database.getPkgsByName(name):
                log.debug1( "Checking for conflicts for %s", r.getNEVRA())
                self.getPkgConflicts(r, r["conflicts"] + r["obsoletes"],
                                     conflicts)
        return conflicts

    def getObsoleteConflicts(self):
        """Check for conflicts from obsoletes of installed packages
        against newly installed packages.
        
        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string), conflicting RpmPackage)]."""
        conflicts = HashList()
        if self.config.checkinstalled:
            # conflicts get caught by getConflicts()
            return conflicts

        for n, f, v, pkg in self.database.iterObsoletes():
            if pkg in self.installs:
                continue
            for p in self.database.searchDependency(n, f, v):
                if not p in self.installs:
                    continue
                # if p in self.updates:
                # XXX check old pkg has already same conflict 
                conflicts.setdefault(pkg, []).append(((n, f, v), p))
        return conflicts

    # ----

    def getObsoletes(self):
        """Check for obsoletes among packages in self.database.names.

        Return a HashList: RpmPackage =>
        [((name, RPMSENSE_* flags, EVR string), obsoleted RpmPackage)]."""

        obsoletes = HashList()

        if self.config.noconflicts:
            # conflicts turned off, obsoletes are also conflicts, but in an
            # other level
            return obsoletes
        if self.config.checkinstalled == 0:
            for r in self.installs:
                log.debug1("Checking for obsoletes for %s", r.getNEVRA())
                self.getPkgConflicts(r, r["obsoletes"], obsoletes)
            return obsoletes

        for name in self.database.getNames():
            for r in self.database.getPkgsByName(name):
                log.debug1(1, "Checking for obsoletes for %s" % r.getNEVRA())
                self.getPkgConflicts(r, r["obsoletes"], obsoletes)
        return obsoletes
    # ----

    def checkConflicts(self):
        """Check for package conflicts, report errors.

        Return 1 if OK, 0 if there are conflicts (after warning the user)."""
        result = 1
        for conflicts in self.getConflicts(), self.getObsoleteConflicts():
            if len(conflicts) == 0:
                continue
            result = 0
            for pkg in conflicts:
                conf = { }
                for c,r in conflicts[pkg]:
                    if not r in conf:
                        conf[r] = [ ]
                    if not c in conf[r]:
                        conf[r].append(c)
                for r in conf.keys():
                    log.error("%s conflicts with %s on:", pkg.getNEVRA(),
                              r.getNEVRA())
                    for c in conf[r]:
                        log.error("\t%s", depString(c))
        return result
    # ----

    def getFileConflicts(self):
        """Find file conflicts among packages in self.database.names.

        Return a HashList:
        RpmPackage => [(filename, conflicting RpmPackage)]."""

        conflicts = HashList()

        db = self.database

        if self.config.nofileconflicts:
            # file conflicts turned off
            return conflicts
        if self.config.checkinstalled == 0:
            # no conflicts if there is no new package
            for pkg in self.installs:
                for name in pkg.iterFilenames():
                    dups = db.searchFilenames(name)
                    if len(dups) == 1: continue
                    log.debug1("Checking for file conflicts for '%s'", name)
                    for p in dups:
                        if p is pkg: continue
                        if self._hasFileConflict(pkg, p, name):
                            conflicts.setdefault(pkg, [ ]).append(
                                (name, p))
            return conflicts

        # duplicates: { name: [(pkg, idx),..], .. }
        duplicates = self.database.getFileDuplicates()
        for name in duplicates:
            dups = duplicates[name]
            log.debug1("Checking for file conflicts for '%s'", name)
            for j in xrange(len(dups)):
                for k in xrange(j+1, len(dups)):
                    if not self._hasFileConflict(dups[j], dups[k], name):
                        continue
                    conflicts.setdefault(dups[j], [ ]).append((name, dups[k]))
                    conflicts.setdefault(dups[k], [ ]).append((name, dups[j]))
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
                log.error("%s file conflicts with %s on:",
                            pkg.getNEVRA(), r.getNEVRA())
                for f in conf[r]:
                    log.error("\t%s", f)
        return 0

    # ----

    def getDatabase(self):
        return self.database

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
