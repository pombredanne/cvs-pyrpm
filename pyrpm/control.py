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
import package
import io
from resolver import *


class RpmController:
    def __init__(self):
        self.db = None
        self.pydb = None
        self.buildroot = None
        self.ignorearch = None
        self.operation = None
        self.new = []
        self.update = []
        self.erase = []
        self.installed = []
        self.available = []

    def installPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.setBuildroot(buildroot)
        self.operation = "install"
        for file in pkglist:
            self.newPkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.setBuildroot(buildroot)
        self.operation = "update"
        for file in pkglist:
            self.updatePkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.setBuildroot(buildroot)
        self.operation = "update"
        for file in pkglist:
            self.updatePkg(file)
        if not self.setDB(db):
            return 0
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
        self.setBuildroot(buildroot)
        self.operation = "erase"
        for file in pkglist:
            self.erasePkg(file)
        self.setDB(db)
        if not self.readDB():
            return 0
        if not self.run():
            return 0
        return 1

    def setDB(self, db):
        self.db = db
        return 1

    def setBuildroot(self, br):
        self.buildroot = br

    def readDB(self):
        if self.db == None:
            return 0
        if self.pydb != None:
            return 1
        self.installed = []
        if self.buildroot != None:
            self.pydb = io.RpmPyDB(self.buildroot+self.db)
        else:
            self.pydb = io.RpmPyDB(self.db)
        self.installed = self.pydb.getPkgList()
        if self.installed == None:
            self.installed = []
            return 0
        return 1

    def addPkgToDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.addPkg(pkg)

    def erasePkgFromDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.erasePkg(pkg)

    # XXX: Write this. Or move out to meta layer for repo handling
    def addRepo(self, file):
        return 1

    # XXX: Write this. Or move out to meta layer for repo handling
    def addAvailable(self, file):
        return 1

    def newPkg(self, file):
        pkg = package.RpmPackage(file)
        pkg.read()
        pkg.close()
        self.new.append(pkg)
        return 1

    def updatePkg(self, file):
        pkg = package.RpmPackage(file)
        pkg.read()
        pkg.close()
        self.update.append(pkg)
        return 1

    def erasePkg(self, file):
        pkg = package.RpmPackage(file)
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
                if arch in arch_compats[duplicates[name][0]]:
                    printInfo(2, "%s: removing due to arch_compat\n" % pkg.source)
                    rmlist.append(pkg)
                else:
                    printInfo(2, "%s: removing due to arch_compat\n" % duplicates[name][1].source)
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

    def checkInstall(self):
        list = {}
        for pkg in self.installed:
            if not list.has_key(pkg["name"]):
                list[pkg["name"]] = []
            list[pkg["name"]].append(pkg)
        for pkg in self.new:
            if not list.has_key(pkg["name"]):
                continue
            for ipkg in list[pkg["name"]]:
                if pkgCompare(pkg, ipkg) <= 0:
                    return 0
        return 1

    def preprocess(self):
        if not self.ignorearch:
            self.filterArch()
        if self.operation == "install":
            if not self.checkInstall():
                printError("Can't install older or same packages.")
                sys.exit(1)
        return 1

    def run(self):
        self.preprocess()
        if self.operation == "install":
            rpms = self.new
        if self.operation == "update":
            rpms = self.update
        if self.operation == "erase":
            rpms = self.erase
        resolver = RpmResolver(rpms, self.installed, self.operation)
        operations = resolver.resolve()
        if not operations:
            printError("Errors found during package dependancy checks and ordering.")
            sys.exit(1)
        for (op, pkg) in operations:
            pkg.open()
            printInfo(0, "Installing package %s\n" % pkg.getNEVR())
            pid = os.fork()
            if pid != 0:
                foo = os.waitpid(pid, 0)
                if foo[1] != 0:
                    printError("Errors during package installation.")
                    sys.exit(1)
                if op == "install":
                    self.addPkgToDB(pkg)
                if op == "update":
                    self.addPkgToDB(pkg)
#                    self.erasePkgFromDB(pkg)
                if op == "erase":
                    self.erasePkgFromDB(pkg)
                pkg.close()
                continue
            else:
                if self.buildroot:
                    os.chroot(self.buildroot)
                if op == "install":
                    if not pkg.install():
                        sys.exit(1)
                # XXX: Handle correct removal of package that gets updated
                if op == "update":
                    if not pkg.install():
                        sys.exit(1)
                # XXX: Handle correct erase of files etc (duplicate files etc)
                if op == "erase":
                    if not pkg.erase():
                        sys.exit(1)
                sys.exit()

# vim:ts=4:sw=4:showmatch:expandtab
