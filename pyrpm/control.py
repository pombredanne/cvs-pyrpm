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


import os, re
import package, io
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
        self.buildroot = buildroot
        self.operation = "install"
        for file in pkglist:
            self.newPkg(file)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = "update"
        for file in pkglist:
            self.updatePkg(file)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = "update"
        for file in pkglist:
            self.updatePkg(file)
        if not self.__readDB(db):
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
        self.buildroot = buildroot
        self.operation = "erase"
        if not self.__readDB(db):
            return 0
        for file in pkglist:
            if not self.erasePkg(file):
                return 0
        if len(self.erase) == 0:
            printInfo(0, "No installed packages found to be removed.\n")
            sys.exit(0)
        if not self.run():
            return 0
        return 1

    def run(self):
        if not self.__preprocess():
            return 0
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
        # Handle updates by doing an install for the new package and adding
        # operations to erase all all updated packages directly afterwards
        for i in xrange(len(operations)-1, -1, -1):
            (op, pkg) = operations[i]
            print op, pkg.getNEVRA()
            if op != "update":
                continue
            if not self.oldpackages.has_key(pkg["name"]):
                continue
            for upkg in self.oldpackages[pkg["name"]]:
                operations.insert(i+1, ("erase", upkg))
        for (op, pkg) in operations:
            if op == "install":
                printInfo(0, "Installing package %s\n" % pkg.getNEVR())
            if op == "update":
                printInfo(0, "Updating package %s\n" % pkg.getNEVR())
            if op == "erase":
                printInfo(0, "Removing package %s\n" % pkg.getNEVR())
            pkg.open()
            pid = os.fork()
            if pid != 0:
                (cpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    printError("Errors during package installation.")
                    sys.exit(1)
                if op == "install":
                    self.__addPkgToDB(pkg)
                if op == "update":
                    self.__addPkgToDB(pkg)
                if op == "erase":
                    self.__erasePkgFromDB(pkg)
                pkg.close()
                continue
            else:
                if self.buildroot:
                    os.chroot(self.buildroot)
                if op == "install":
                    if not pkg.install(self.pydb):
                        sys.exit(1)
                if op == "update":
                    if not pkg.install(self.pydb):
                        sys.exit(1)
                if op == "erase":
                    if not pkg.erase(self.pydb):
                        sys.exit(1)
                sys.exit(0)

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
        if self.pydb == None:
            if not self.__readDB():
                return 0
        (epoch, name, version, release, arch) = envraSplit(file)
        # First check is against nvra as name
        n = name
        if version != None:
            n += "-"+version
        if release != None:
            n += "-"+release
        if arch != None:
            n += "."+arch
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == n:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # Next check is against nvr as name, a as arch
        n = name
        if version != None:
            n += "-"+version
        if release != None:
            n += "-"+release
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == n and pkg["arch"] == arch:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # Next check is against nv as name, ra as version
        n = name
        if version != None:
            n += "-"+version
        v = ""
        if release != None:
            v += release
        if arch != None:
            v += "."+arch
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == n and pkg["version"] == v:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # Next check is against nv as name, r as version, a as arch
        n = name
        if version != None:
            n += "-"+version
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == n and pkg["version"] == release and pkg["arch"] == arch:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # Next check is against n as name, v as version, ra as release
        r = ""
        if release != None:
            r = release
        if arch != None:
            r += "-"+arch
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == name and pkg["version"] == version and pkg["release"] == r:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # Next check is against n as name, v as version, r as release, a as arch
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == name and pkg["version"] == version and pkg["release"] == release and pkg["arch"] == arch:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.erase.append(pkg)
                return 1
        # No matching package found
        return 0

    def __readDB(self, db="/var/lib/pyrpm"):
        if self.db == None:
            self.db = db
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

    def __preprocess(self):
        if not self.ignorearch:
            self.__filterArch()
        if self.operation == "install":
            if not self.__checkInstall():
                printError("Can't install older or same packages.")
                return 0
        if self.operation == "update":
            self.oldpackages = self.__findUpdatePkgs()
            if self.oldpackages == None:
                printError("Can't update to older or same packages.")
                return 0
        return 1

    def __filterArch(self):
        self.__filterArchList(self.new)
        self.__filterArchList(self.update)
        self.__filterArchList(self.available)

    def __filterArchList(self, list):
        duplicates = {}
        rmlist = []
        (sysname, nodename, release, version, machine) = os.uname()
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

    def __checkInstall(self):
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

    def __findUpdatePkgs(self):
        hash = {}
        for pkg in self.update:
            name = pkg["name"]
            hash[name] = []
            for upkg in self.installed:
                if upkg["name"] != name:
                    continue
                if pkgCompare(upkg, pkg) < 0:
                    hash[name].append(upkg)
                else:
                    printError("Can't install older or same package %s" % pkg.getNEVR())
                    return None
        return hash

    def __addPkgToDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.addPkg(pkg)

    def __erasePkgFromDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.erasePkg(pkg)

# vim:ts=4:sw=4:showmatch:expandtab
