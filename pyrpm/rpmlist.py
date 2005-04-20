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
    OK = 1
    ALREADY_INSTALLED = -1
    OLD_PACKAGE = -2
    NOT_INSTALLED = -3
    UPDATE_FAILED = -4
    ALREADY_ADDED = -5
    ARCH_INCOMPAT = -6
    # ----

    def __init__(self, config, installed):
        self.config = config
        self.clear()
        self.__len__ = self.list.__len__
        for r in installed:
            self._install(r, 1)
            if not r["name"] in self.installed:
                self.installed[r["name"]] = [ ]
            self.installed[r["name"]].append(r)
        self.__getitem__ = self.list.__getitem__
    # ----

    def clear(self):
        self.list = HashList(self.config)
        self.installed = HashList(self.config)
        self.installs = [ ]
        self.updates = { }
        self.erases = [ ]
    # ----

    #def __getitem__(self, i):
    #    return self.list[i] # return rpm list
    # ----

    def _install(self, pkg, no_check=0):
        key = pkg["name"]
        if no_check == 0 and key in self.list:
            for r in self.list[key]:
                ret = self.__install_check(r, pkg)
                if ret != 1: return ret
        if not key in self.list:
            self.list[key] = [ ]
        self.list[key].append(pkg)

        return self.OK
    # ----

    def install(self, pkg):
        ret = self._install(pkg)
        if ret != self.OK:  return ret

        if not self.isInstalled(pkg):
            self.installs.append(pkg)
        if pkg in self.erases:
            self.erases.remove(pkg)

        return self.OK
    # ----

    def update(self, pkg):
        key = pkg["name"]

        updates = [ ]
        if key in self.list:
            rpms = self.list[key]
            
            for r in rpms:
                ret = pkgCompare(r, pkg)
                if ret > 0: # old_ver > new_ver
                    if self.config.oldpackage == 0:
                        if self.isInstalled(r):
                            msg = "%s: A newer package is already installed"
                        else:
                            msg = "%s: A newer package was already added"
                        self.config.printWarning(1, msg % pkg.getNEVRA())
                        return self.OLD_PACKAGE
                    else:
                        # old package: simulate a new package
                        ret = -1
                if ret < 0: # old_ver < new_ver
                    if self.config.exactarch == 1 and \
                           self.__arch_incompat(pkg, r):
                        return self.ARCH_INCOMPAT
                    
                    if archDuplicate(pkg["arch"], r["arch"]) or \
                           pkg["arch"] == "noarch" or r["arch"] == "noarch":
                        updates.append(r)
                else: # ret == 0, old_ver == new_ver
                    if self.config.exactarch == 1 and \
                           self.__arch_incompat(pkg, r):
                        return self.ARCH_INCOMPAT
                    
                    ret = self.__install_check(r, pkg)
                    if ret != 1: return ret

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
                            return ret
                        else:
                            updates.append(r)

        ret = self.install(pkg)
        if ret != self.OK:  return ret

        for r in updates:
            if self.isInstalled(r):
                self.config.printWarning(2, "%s was already installed, replacing with %s" \
                                 % (r.getNEVRA(), pkg.getNEVRA()))
            else:
                self.config.printWarning(1, "%s was already added, replacing with %s" \
                                 % (r.getNEVRA(), pkg.getNEVRA()))
            if self._pkgUpdate(pkg, r) != self.OK:
                return self.UPDATE_FAILED

        return self.OK
    # ----

    def freshen(self, pkg):
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
        key = pkg["name"]
        if not key in self.list or pkg not in self.list[key]:
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
        if self.isInstalled(update_pkg):
            if not pkg in self.updates:
                self.updates[pkg] = [ ]
            self.updates[pkg].append(update_pkg)
        else:
            self._inheritUpdates(pkg, update_pkg)
        return self.erase(update_pkg)
    # ----

    def isInstalled(self, pkg):
        key = pkg["name"]
        if key in self.installed and pkg in self.installed[key]:
            return 1
        return 0
    # ----

    def __contains__(self, pkg):
        key = pkg["name"]
        if not key in self.list or pkg not in self.list[key]:
            return None
        return pkg
    # ----

    def __install_check(self, r, pkg):
        if r == pkg or r.isEqual(pkg):
            if self.isInstalled(r):
                self.config.printWarning(1, "%s: %s is already installed" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_INSTALLED
            else:
                self.config.printWarning(1, "%s: %s was already added" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_ADDED
        return 1
    # ----

    def __arch_incompat(self, pkg, r):
        if pkg["arch"] != r["arch"] and archDuplicate(pkg["arch"], r["arch"]):
            self.config.printWarning(1, "%s does not match arch %s." % \
                         (pkg.getNEVRA(), r["arch"]))
            return 1
        return 0
    # ----

    def _inheritUpdates(self, pkg, old_pkg):
        if old_pkg in self.updates:
            if pkg in self.updates:
                self.updates[pkg].extend(self.updates[old_pkg])
                normalizeList(self.updates[pkg])
            else:
                self.updates[pkg] = self.updates[old_pkg]
            del self.updates[old_pkg]
    # ----

    def getList(self):
        l = [ ]
        for name in self:
            l.extend(self[name])
        return l
    # ----

    def p(self):
        for name in self:
            for r in self[name]:
                print "\t%s" % r.getNEVRA()

# vim:ts=4:sw=4:showmatch:expandtab
