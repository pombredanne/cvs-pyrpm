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
        self.oldpackages = []

    def installPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = RpmResolver.OP_INSTALL
        for filename in pkglist:
            self.newPkg(filename)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = RpmResolver.OP_UPDATE
        for filename in pkglist:
            self.updatePkg(filename)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = RpmResolver.OP_UPDATE
        for filename in pkglist:
            self.updatePkg(filename)
        if not self.__readDB(db):
            return 0
        insthash = {}
        rmlist = []
        # Create hashlist of installed packages
        for pkg in self.installed:
            name = pkg["name"]
            if not insthash.has_key(name):
                insthash[name] = []
            insthash[name].append(pkg)
        # Remove all packages that weren't installed or that are already
        # installed with same or newer version
        for pkg in self.update:
            if not insthash.has_key(pkg["name"]):
                rmlist.append(pkg)
                continue
            for ipkg in insthash[pkg["name"]]:
                if pkgCompare(pkg, ipkg) <= 0:
                    rmlist.append(pkg)
                    break
        # Remove collected packages
        for pkg in rmlist:
            self.update.remove(pkg)
        if not self.run():
            return 0
        return 1

    def erasePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.buildroot = buildroot
        self.operation = RpmResolver.OP_ERASE
        if not self.__readDB(db):
            return 0
        for filename in pkglist:
            if not self.erasePkg(filename):
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
        if   self.operation == RpmResolver.OP_INSTALL:
            rpms = self.new
        elif self.operation == RpmResolver.OP_UPDATE:
            rpms = self.update
        elif self.operation == RpmResolver.OP_ERASE:
            rpms = self.erase
        resolver = RpmResolver(rpms, self.installed, self.operation)
        operations = resolver.resolve()
        del resolver
        if not operations:
            printError("Errors found during package dependancy checks and ordering.")
            sys.exit(1)
        # Handle updates by doing an install for the new package and adding
        # operations to erase all all updated packages directly afterwards
        for i in xrange(len(operations)-1, -1, -1):
            (op, pkg) = operations[i]
            if op != RpmResolver.OP_UPDATE:
                continue
            if not self.oldpackages.has_key(pkg["name"]):
                continue
            for upkg in self.oldpackages[pkg["name"]]:
                operations.insert(i+1, (RpmResolver.OP_ERASE, upkg))
        # Now we need to look for duplicate operations and remove the later
        # ones (can happen due to obsoletes and automatic erase operations)
        for i in xrange(len(operations)-1, -1, -1):
            for j in xrange(i-1, -1, -1):
                if operations[i][0] == operations[j][0] and \
                   operations[i][1] == operations[j][1]:
                    operations.pop(i)
                    break
        del self.new
        del self.update
        del self.erase
        del self.installed
        del self.available
        del self.oldpackages
        i = 1
        for (op, pkg) in operations:
            progress = "[%d/%d]" % (i, len(operations))
            i += 1
            if   op == RpmResolver.OP_INSTALL:
                printInfo(0, "%s %s" % (progress, pkg.getNEVR()))
            elif op == RpmResolver.OP_UPDATE:
                printInfo(0, "%s %s" % (progress, pkg.getNEVR()))
            elif op == RpmResolver.OP_ERASE:
                printInfo(0, "%s %s" % (progress, pkg.getNEVR()))
            pkg.open()
            pid = os.fork()
            if pid != 0:
                (cpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    printError("Errors during package installation.")
                    sys.exit(1)
                if   op == RpmResolver.OP_INSTALL:
                    self.__addPkgToDB(pkg)
                elif op == RpmResolver.OP_UPDATE:
                    self.__addPkgToDB(pkg)
                elif op == RpmResolver.OP_ERASE:
                    self.__erasePkgFromDB(pkg)
                pkg.close()
            else:
                if self.buildroot:
                    os.chroot(self.buildroot)
                if   op == RpmResolver.OP_INSTALL:
                    if not pkg.install(self.pydb):
                        sys.exit(1)
                elif op == RpmResolver.OP_UPDATE:
                    if not pkg.install(self.pydb):
                        sys.exit(1)
                elif op == RpmResolver.OP_ERASE:
                    if not pkg.erase(self.pydb):
                        sys.exit(1)
                sys.exit(0)
            printInfo(0, "\n")
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
        for i in xrange(len(self.update)):
            if not pkg["name"] == self.update[i]["name"]:
                continue
            if pkgCompare(pkg, self.update[i]) > 0:
                printInfo(1, "Replacing update %s with newer package %s\n" % (self.update[i].getNEVRA(), pkg.getNEVRA()))
                self.update[i] = pkg
            else:
                printInfo(1, "Newer package %s already in update set\n" % self.update[i].getNEVRA())
            return
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
        self.installed = self.pydb.getPkgList().values()
        if self.installed == None:
            self.installed = []
            return 0
        return 1

    def __preprocess(self):
        if not self.ignorearch:
            self.__filterArch()
        if self.operation == RpmResolver.OP_INSTALL:
            if not self.__checkInstall():
                printError("Can't install older or same packages.")
                return 0
        if self.operation == RpmResolver.OP_UPDATE:
            self.oldpackages = self.__findUpdatePkgs()
            if self.oldpackages == None:
                printError("Can't update to older or same packages.")
                return 0
        return 1

    def __filterArch(self):
        self.__filterArchList(self.new)
        self.__filterArchList(self.update)
        self.__filterArchList(self.available)

    def __filterArchList(self, flist):
        duplicates = {}
        rmlist = []
        (sysname, nodename, release, version, machine) = os.uname()
        for pkg in flist:
            name = pkg.getNEVR()
            arch = pkg["arch"]
            if arch not in possible_archs:
                raiseFatal("%s: Unknow rpm package architecture %s" % (pkg.source, arch))
            if machine not in possible_archs:
                raiseFatal("%s: Unknow machine architecture %s" % (pkg.source, machine))
            if arch != machine and arch not in arch_compats[machine]:
                raiseFatal("%s: Architecture not compatible with machine %s" % (pkg.source, machine))
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
            flist.remove(i)

    def __checkInstall(self):
        clist = {}
        for pkg in self.installed:
            if not clist.has_key(pkg["name"]):
                clist[pkg["name"]] = []
            clist[pkg["name"]].append(pkg)
        for pkg in self.new:
            if not clist.has_key(pkg["name"]):
                continue
            for ipkg in clist[pkg["name"]]:
                if pkgCompare(pkg, ipkg) <= 0:
                    return 0
        return 1

    def __findUpdatePkgs(self):
        phash = {}
        for pkg in self.update:
            name = pkg["name"]
            phash[name] = []
            for upkg in self.installed:
                if upkg["name"] != name:
                    continue
                if pkgCompare(upkg, pkg) < 0:
                    phash[name].append(upkg)
                else:
                    printError("Can't install older or same package %s" % pkg.getNEVR())
                    return None
        return phash

    def __addPkgToDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.addPkg(pkg)

    def __erasePkgFromDB(self, pkg):
        if self.pydb == None:
            return 0
        return self.pydb.erasePkg(pkg)

# vim:ts=4:sw=4:showmatch:expandtab
