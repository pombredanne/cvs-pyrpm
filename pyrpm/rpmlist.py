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
# Author: Thomas Woerner, Karel Zak
#

from hashlist import HashList
from functions import buildarchtranslate, printWarning

class RpmList:
    OP_INSTALL = "install"
    OP_UPDATE = "update"
    OP_ERASE = "erase"
    OP_FRESHEN = "freshen"

    OK = 1
    ALREADY_INSTALLED = -1
    OLD_PACKAGE = -2
    NOT_INSTALLED = -3
    UPDATE_FAILED = -4
    ALREADY_ADDED = -5
    # ----

    def __init__(self, installed, operation):
        self.clear()
        for r in installed:
            self._install(r)
            if not self.installed.has_key(r["name"]):
                self.installed[r["name"]] = [ ]
            self.installed[r["name"]].append(r)
        self.operation = operation
    # ----

    def clear(self):
        self.list = HashList()
        self.installed = HashList()
        self.appended = []
    # ----

    def __len__(self):
        return len(self.list)
    # ----

    def __getitem__(self, i):
        return self.list[i][1] # return rpm list
    # ----

    def append(self, pkg):
        if self.operation == self.OP_INSTALL:
            ret = self._install(pkg)
            if ret != self.OK:  return ret
        elif self.operation == self.OP_UPDATE:
            ret = self._update(pkg)
            if ret != self.OK:  return ret
        elif self.operation == self.OP_FRESHEN:
            # pkg in self.installed
            if not self.installed.has_key(pkg["name"]):
                return self.NOT_INSTALLED
            found = 0
            for r in self.installed[pkg["name"]]:
                if pkg["arch"] == r["arch"] or \
                       buildarchtranslate[pkg["arch"]] == \
                       buildarchtranslate[r["arch"]]:
                    found = 1
                    break
            if found == 0:
                return self.NOT_INSTALLED
            ret = self._update(pkg)
            if ret != self.OK:  return ret
        else: # self.operation == self.OP_ERASE:
            if self._erase(pkg) != 1:
                return self.NOT_INSTALLED
            self._pkgErase(pkg)
        self.appended.append(pkg)
        return self.OK
    # ----

    def _install(self, pkg):
        key = pkg["name"]
        if self.installed.has_key(key):
            for r in self.installed[key]:
                if r == pkg or \
                   (r.getNEVR() == pkg.getNEVR() and \
                    (pkg["arch"] == r["arch"] or \
                     buildarchtranslate[pkg["arch"]] == \
                     buildarchtranslate[r["arch"]])):
                    printWarning(1, "%s: %s is already installed" % \
                                 (pkg.getNEVRA(), r.getNEVRA()))
                    return self.ALREADY_INSTALLED
        if not self.list.has_key(key):
            self.list[key] = [ ]
        self.list[key].append(pkg)

        return self.OK
    # ----

    def _update(self, pkg):
        key = pkg["name"]

        ret = self._install(pkg)
        if ret != self.OK:  return ret

        if self.list.has_key(key):
            i = 0
            while self.list[key] != None and i < len(self.list[key]):
                r = self.list[key][i]
                if r != pkg and (pkg["arch"] == r["arch"] or \
                                 buildarchtranslate[pkg["arch"]] == \
                                 buildarchtranslate[r["arch"]]):
                        if self._pkgUpdate(pkg, r) != self.OK:
                            return self.UPDATE_FAILED
                else:
                    i += 1

        return self.OK
    # ----

    def _erase(self, pkg):
        key = pkg["name"]
        if not self.list.has_key(key) or pkg not in self.list[key]:
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
        if self.installed.has_key(pkg["name"]) and \
               pkg in self.installed[pkg["name"]]:
            return 1
        return 0
    # ----

    def getList(self):
        l = []
        for i in xrange(len(self)):
            l.extend(self[i])
            #rlist = self[i]
            #for r in rlist:
            #    l.append(r)
        return l
    # ----

    def p(self):
        for i in xrange(len(self)):
            rlist = self[i]
            for r in rlist:
                print "\t%s" % r.getNEVRA()

# vim:ts=4:sw=4:showmatch:expandtab
