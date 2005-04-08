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
from config import rpmconfig
from functions import printWarning, pkgCompare, archCompat, archDuplicate
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

    def __init__(self, installed, operation):
        self.clear()
        self.__len__ = self.list.__len__
        for r in installed:
            self._install(r, 1)
            if not r["name"] in self.installed:
                self.installed[r["name"]] = [ ]
            self.installed[r["name"]].append(r)
        self.operation = operation
    # ----

    def clear(self):
        self.list = HashList()
        self.installed = HashList()
        self.appended = [ ]
    # ----

    def __getitem__(self, i):
        return self.list[i] # return rpm list
    # ----

    def append(self, pkg):
        if self.operation == OP_INSTALL:
            ret = self._install(pkg)
            if ret != self.OK:  return ret
        elif self.operation == OP_UPDATE:
            ret = self._update(pkg)
            if ret != self.OK:  return ret
        elif self.operation == OP_FRESHEN:
            # pkg in self.installed
            if not pkg["name"] in self.installed:
                return self.NOT_INSTALLED
            found = 0
            for r in self.installed[pkg["name"]]:
                if archDuplicate(pkg["arch"], r["arch"]):
                    found = 1
                    break
            if found == 0:
                return self.NOT_INSTALLED
            ret = self._update(pkg)
            if ret != self.OK:  return ret
        else: # self.operation == OP_ERASE:
            if self._erase(pkg) != 1:
                return self.NOT_INSTALLED
            self._pkgErase(pkg)
        if not self.isInstalled(pkg):
            # do not readd obsoleted or updated and readded packages
            self.appended.append(pkg)
        return self.OK
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

    def _update(self, pkg):
        key = pkg["name"]

        updates = [ ]
        if key in self.list:
            rpms = self.list[key]
            
            for r in rpms:
                ret = pkgCompare(r, pkg)
                if ret > 0: # old_ver > new_ver
                    if rpmconfig.oldpackage == 0:
                        if self.isInstalled(r):
                            msg = "%s: A newer package is already installed"
                        else:
                            msg = "%s: A newer package was already added"
                        printWarning(1, msg % pkg.getNEVRA())
                        return self.OLD_PACKAGE
                    else:
                        # old package: simulate a new package
                        ret = -1
                if ret < 0: # old_ver < new_ver
                    if rpmconfig.exactarch == 1 and \
                           self.__arch_incompat(pkg, r):
                        return self.ARCH_INCOMPAT
                    
                    if archDuplicate(pkg["arch"], r["arch"]) or \
                           pkg["arch"] == "noarch" or r["arch"] == "noarch":
                        updates.append(r)
                else: # ret == 0, old_ver == new_ver
                    if rpmconfig.exactarch == 1 and \
                           self.__arch_incompat(pkg, r):
                        return self.ARCH_INCOMPAT
                    
                    ret = self.__install_check(r, pkg)
                    if ret != 1: return ret

                    if archCompat(pkg["arch"], r["arch"]):
                        if self.isInstalled(r):
                            msg = "%s: Ignoring due to installed %s"
                            ret = self.ALREADY_INSTALLED
                        else:
                            msg = "%s: Ignoring due to already added %s"
                            ret = self.ALREADY_ADDED
                        printWarning(1, msg % (pkg.getNEVRA(), r.getNEVRA()))
                        return ret
                    else:
                        if archDuplicate(pkg["arch"], r["arch"]):
                            updates.append(r)

        ret = self._install(pkg, 1)
        if ret != self.OK:  return ret

        for r in updates:
            if self.isInstalled(r):
                msg = "%s was already installed, replacing with %s"
            else:
                msg = "%s was already added, replacing with %s"
            printWarning(1, msg % (r.getNEVRA(), pkg.getNEVRA()))
            if self._pkgUpdate(pkg, r) != self.OK:
                return self.UPDATE_FAILED

        return self.OK
    # ----

    def _erase(self, pkg):
        key = pkg["name"]
        if not key in self.list or pkg not in self.list[key]:
            return self.NOT_INSTALLED
        self.list[key].remove(pkg)
        if len(self.list[key]) == 0:
            del self.list[key]
        if pkg in self.appended:
            self.appended.remove(pkg)
        return 1
    # ----

    def _pkgUpdate(self, pkg, update_pkg):
        return self._erase(update_pkg)
    # ----

    def _pkgErase(self, pkg):
        return self.OK
    # ----

    def isInstalled(self, pkg):
        key = pkg["name"]
        if key in self.installed and pkg in self.installed[key]:
            return 1
        return 0
    # ----

    def __install_check(self, r, pkg):
        if r == pkg or r.isEqual(pkg):
            if self.isInstalled(r):
                printWarning(1, "%s: %s is already installed" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_INSTALLED
            else:
                printWarning(1, "%s: %s was already added" % \
                             (pkg.getNEVRA(), r.getNEVRA()))
                return self.ALREADY_ADDED
        return 1
    # ----

    def __arch_incompat(self, pkg, r):
        if pkg["arch"] != r["arch"] and archDuplicate(pkg["arch"], r["arch"]):
            printWarning(1, "%s does not match arch %s." % \
                         (pkg.getNEVRA(), r["arch"]))
            return 1
        return 0
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
