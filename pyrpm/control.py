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
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
#


import os
from package import *


class RpmController:
    def __init__(self):
        self.db = None
        self.buildroot = None
        self.ignorearch = None
        self.new = []
        self.update = []
        self.erase = []
        self.installed = []
        self.available = []

    def installPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.setBuildroot(buildroot)
        for file in pkglist:
            self.newPkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        for file in pkglist:
            self.updatePkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        for file in pkglist:
            self.updatePkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        instlist = []
        rmlist = []
        for pkg in self.installed:
            instlist.append(pkg["name"])
        for pkg in self.update:
            if pkg["name"] not in instlist:
                rmlist.append(pkg)
        for pkg in rmlist:
            self.update.remove(pkg)
        if not self.run():
            return 0
        return 1

    def erasePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        for file in pkglist:
            self.erasePkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def setBuildroot(self, br):
        self.buildroot = br

    def setDB(self, db):
        self.db = db
        return self.readDB()

    # XXX: Write this
    def readDB(self):
        self.installed = []
        return 1

    def updateDB(self, pkg):
        
        self.installed.append(pkg)


    # XXX: Write this. Or move out to meta layer for repo handling
    def addRepo(self, file):
        return 1

    # XXX: Write this. Or move out to meta layer for repo handling
    def addAvailable(self, file):
        return 1

    def newPkg(self, file):
        pkg = RpmPackage(file)
        pkg.read()
        pkg.close()
        self.new.append(pkg)
        return 1

    def updatePkg(self, file):
        pkg = RpmPackage(file)
        pkg.read()
        pkg.close()
        self.update.append(pkg)
        return 1

    def erasePkg(self, file):
        pkg = RpmPackage(file)
        pkg.read()
        pkg.close()
        self.erase.append(pkg)
        return 1

    def filterArchList(self, list):
        duplicates = {}
        rmlist = []
        for pkg in list:
            name = pkg.getNEVR()
            arch = pkg["arch"]
            if arch not in possible_archs:
                raiseFatal("%s: Unknow architecture %s" % (pkg.source, arch))
            if duplicates.has_key(name):
                print name,arch
                if arch in arch_compats[duplicates[name][0]]:
                    printInfo("%s: removing due to arch_compat\n" % pkg.source)
                    rmlist.append(pkg)
                else:
                    printInfo("%s: removing due to arch_compat\n" % duplicates[name][1].source)
                    rmlist.append(duplicates[name][1])
                    duplicates[name] = [arch, pkg]
            else:
                duplicates[name] = [arch, pkg]
        for i in rmlist:
            list.remove(i)
        
    def filterArch(self):
        (sysname, nodename, release, version, machine) = os.uname()
        self.filterArchList(self.new)
        self.filterArchList(self.update)
        self.filterArchList(self.available)

    def preprocess(self):
        if not self.ignorearch:
            self.filterArch()
        return 1

    def run(self):
        self.preprocess()
#        depres = RpmResolver(new, update, erase, installed, available)
#        pkglist = depres.resorder()
        pkglist = self.new
        for pkg in pkglist:
            pkg.open()
            pid = os.fork()
            if pid != 0:
                os.waitpid(pid, 0)
                continue
            else:
                if self.buildroot:
                    os.chroot(self.buildroot)
                if pkg.install():
                    self.updateDB(pkg)
                pkg.close()
                sys.exit()

# vim:ts=4:sw=4:showmatch:expandtab
