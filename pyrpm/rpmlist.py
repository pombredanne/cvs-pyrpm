#!/usr/bin/python
#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Thomas Woerner, Karel Zak
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

from hashlist import HashList
from functions import pkgCompare, archCompat, archDuplicate
from functions import normalizeList
from base import OP_INSTALL, OP_UPDATE, OP_ERASE, OP_FRESHEN

class RpmList:
    """A list of RPM packages, allowing basic operations.

    Does not at all handles requires/obsoletes/conflicts.

    Allows "direct" access to packages: "for %name in self",
    "self[idx] => %name", "self[%name] => RpmPackage", "pkg in self."."""

    OK = 1
    ALREADY_INSTALLED = -1
    OLD_PACKAGE = -2
    NOT_INSTALLED = -3
    UPDATE_FAILED = -4
    ALREADY_ADDED = -5
    ARCH_INCOMPAT = -6
    # ----

    def __init__(self, config, installed):
        """Initialize, with the "currently installed" packages in RpmPackage
        list installed."""

        self.config = config
        self.clear()
        self.__len__ = self.list.__len__
        self.__getitem__ = self.list.__getitem__
        for r in installed:
            name = r["name"]
            self._install(r, 1) # Can't fail
            if not name in self.installed:
                self.installed[name] = [ ]
            self.installed[name].append(r)
    # ----

    def clear(self):
        """Drop all data."""

        self.list = HashList() # %name => [RpmPackage]; "current" list
        # %name => [RpmPackage]; "originally" installed packages
        self.installed = HashList()
        self.installs = [ ] # Added RpmPackage's
        # new RpmPackage
        # => ["originally" installed RpmPackage removed by update]
        self.updates = { }
        self.erases = [ ] # Removed RpmPackage's
    # ----

    def _install(self, pkg, no_check=0):
        """Add RpmPackage pkg.

        Return an RpmList error code (after warning the user).  Check whether a
        package with the same NEVRA is already in the list unless no_check.
        Unlike install() this method allows adding "originally" installed
        packages."""

        name = pkg["name"]
        if no_check == 0 and name in self.list:
            for r in self.list[name]:
                ret = self.__install_check(r, pkg)
                if ret != self.OK:
                    return ret
        if not name in self.list:
            self.list[name] = [ ]
        self.list[name].append(pkg)

        return self.OK
    # ----

    def install(self, pkg, operation=OP_INSTALL):
        """Add RpmPackage pkg as part of the defined operation.

        Return an RpmList error code (after warning the user)."""

        ret = self._install(pkg)
        if ret != self.OK:
            return ret

        if not self.isInstalled(pkg):
            self.installs.append(pkg)
        if pkg in self.erases:
            self.erases.remove(pkg)

        return self.OK
    # ----

    def update(self, pkg):
        """Add RpmPackage pkg, removing older versions.

        Return an RpmList error code (after warning the user)."""

        key = pkg["name"]

        # Valid only during OP_UPDATE: list of RpmPackage's that will be
        # removed by the current update
        self.pkg_updates = [ ]
        if key in self.list:
            for r in self.list[key]:
                ret = pkgCompare(r, pkg)
                if ret > 0: # old_ver > new_ver
                    if self.config.oldpackage == 0:
                        if self.isInstalled(r):
                            msg = "%s: A newer package is already installed"
                        else:
                            msg = "%s: A newer package was already added"
                        self.config.printWarning(1, msg % pkg.getNEVRA())
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
                            self.config.printWarning(1, msg % (pkg.getNEVRA(),
                                                   r.getNEVRA()))
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
                self.config.printWarning(2, "%s was already installed, replacing with %s" \
                                 % (r.getNEVRA(), pkg.getNEVRA()))
            else:
                self.config.printWarning(1, "%s was already added, replacing with %s" \
                                 % (r.getNEVRA(), pkg.getNEVRA()))
            if self._pkgUpdate(pkg, r) != self.OK: # Currently can't fail
                del self.pkg_updates
                return self.UPDATE_FAILED

        del self.pkg_updates

        return self.OK
    # ----

    def freshen(self, pkg):
        """Add RpmPackage pkg, removing older versions, if a package of the
        same %name and base arch is "originally" installed.

        Return an RpmList error code."""

        # pkg in self.installed
        if not pkg["name"] in self.installed:
            return self.NOT_INSTALLED
        found = 0
        for r in self.installed[pkg["name"]]:
            if archDuplicate(pkg["arch"], r["arch"]):
                found = 1
                break
        if found == 1:
            return self.update(pkg)

        return self.NOT_INSTALLED
    # ----

    def erase(self, pkg):
        """Remove RpmPackage.

        Return an RpmList error code (after warning the user)."""

        key = pkg["name"]
        if not key in self.list or pkg not in self.list[key]:
            self.config.printWarning(1, "Package %s (id %s) not found"
                                     % (pkg.getNEVRA(), id(pkg)))
            return self.NOT_INSTALLED
        self.list[key].remove(pkg)
        if len(self.list[key]) == 0:
            del self.list[key]

        if self.isInstalled(pkg):
            self.erases.append(pkg)
        if pkg in self.installs:
            self.installs.remove(pkg)
        if pkg in self.updates:
            del self.updates[pkg]

        return self.OK
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        """Remove RpmPackage update_pkg because it will be replaced by
        RpmPackage pkg.

        Return an RpmList error code."""

        if self.isInstalled(update_pkg):
            # assert update_pkg not in self.updates
            if not pkg in self.updates:
                self.updates[pkg] = [ ]
            self.updates[pkg].append(update_pkg)
        else:
            self._inheritUpdates(pkg, update_pkg)
        return self.erase(update_pkg)
    # ----

    def isInstalled(self, pkg):
        """Return True if RpmPackage pkg is an "originally" installed
        package.

        Note that having the same NEVRA is not enough, the package should
        be from self.list."""

        key = pkg["name"]
        return key in self.installed and pkg in self.installed[key]
    # ----

    def __contains__(self, pkg):
        key = pkg["name"]
        if not key in self.list or pkg not in self.list[key]:
            return None
        return pkg
    # ----

    def __install_check(self, r, pkg):
        """Check whether RpmPackage pkg can be installed when RpmPackage r
        with same %name is already in the current list.

        Return an RpmList error code (after warning the user)."""

        if r == pkg or r.isEqual(pkg):
            if self.isInstalled(r):
                self.config.printWarning(2, "%s: %s is already installed" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_INSTALLED
            else:
                self.config.printWarning(1, "%s: %s was already added" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_ADDED
        return self.OK
    # ----

    def __arch_incompat(self, pkg, r):
        """Return True (and warn) if RpmPackage's pkg and r have different
        architectures, but the same base arch.

        Warn the user before returning True."""

        if pkg["arch"] != r["arch"] and archDuplicate(pkg["arch"], r["arch"]):
            self.config.printWarning(1, "%s does not match arch %s." % \
                         (pkg.getNEVRA(), r["arch"]))
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

    def getList(self):
        """Return a list of RpmPackages in current state of the list."""

        l = [ ]
        for name in self:
            l.extend(self[name])
        return l
    # ----

    def p(self):
        """Debugging: Print NEVRAs of packages in current list."""

        for r in self.getList():
            print "\t%s" % r.getNEVRA()

# vim:ts=4:sw=4:showmatch:expandtab
