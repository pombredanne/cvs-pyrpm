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


import os, re, time, gc
import package, io
from resolver import *
from orderer import *

class _Triggers:
    """ enable search of triggers """
    """ triggers of packages can be added and removed by package """
    def __init__(self):
        self.clear()

    def clear(self):
        self.triggers = { }

    def append(self, name, flag, version, tprog, tscript, rpm):
        if not self.triggers.has_key(name):
            self.triggers[name] = [ ]
        self.triggers[name].append((flag, version, tprog, tscript, rpm))

    def remove(self, name, flag, version, tprog, tscript, rpm):
        if not self.triggers.has_key(name):
            return
        for t in self.triggers[name]:
            if t[0] == flag and t[1] == version and t[2] == tprog and t[3] == tscript and t[4] == rpm:
                self.triggers[name].remove(t)
        if len(self.triggers[name]) == 0:
            del self.triggers[name]

    def addPkg(self, rpm):
        for t in rpm["triggers"]:
            self.append(t[0], t[1], t[2], t[3], t[4], rpm)

    def removePkg(self, rpm):
        for t in rpm["triggers"]:
            self.remove(t[0], t[1], t[2], t[3], t[4], rpm)

    def search(self, name, flag, version):
        if not self.triggers.has_key(name):
            return [ ]
        ret = [ ]
        for t in self.triggers[name]:
            if (t[0] & RPMSENSE_TRIGGER) != (flag & RPMSENSE_TRIGGER):
                continue
            if t[1] == "":
                ret.append((t[2], t[3], t[4]))
            else:
                if evrCompare(version, flag, t[1]) == 1 and \
                       evrCompare(version, t[0], t[1]) == 1:
                    ret.append((t[2], t[3], t[4]))
        return ret


class RpmController:
    def __init__(self):
        self.db = None
        self.pydb = None
        self.ignorearch = None
        self.operation = None
        self.buildroot = None
        self.rpms = []
        self.installed = []

    def handlePkgs(self, operation, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.operation = operation
        self.db = db
        self.buildroot = buildroot
        if not self.__readDB(db):
            return 0
        if operation == RpmResolver.OP_ERASE:
            for filename in pkglist:
                self.erasePkg(filename)
        else: 
            for filename in pkglist:
                self.appendPkg(filename)
        if len(self.rpms) == 0:
            printInfo(0, "Nothing to do.\n")
            sys.exit(0)
        if not self.run():
            return 0
        return 1

    def installPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        return self.handlePkgs(RpmResolver.OP_INSTALL, pkglist, db, buildroot)

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        return self.handlePkgs(RpmResolver.OP_UPDATE, pkglist, db, buildroot)

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        return self.handlePkgs(RpmResolver.OP_FRESHEN, pkglist, db, buildroot)

    def erasePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        return self.handlePkgs(RpmResolver.OP_ERASE, pkglist, db, buildroot)

    def run(self):
        if not self.__preprocess():
            return 0
        resolver = RpmResolver(self.installed, self.operation)
        for r in self.rpms:
            ret = resolver.append(r)
        if resolver.resolve() != 1:
            sys.exit(1)
        a = resolver.appended
        o = resolver.obsoletes
        u = resolver.updates
        del resolver
        orderer = RpmOrderer(a, o, self.operation)
        operations = orderer.order()
        del o
        del a
        if not operations:
            printError("Errors found during package dependancy checks and ordering.")
            sys.exit(1)
        self.triggerlist = _Triggers()
        for (op, pkg) in operations:
            if op == RpmResolver.OP_UPDATE or op == RpmResolver.OP_INSTALL:
                self.triggerlist.addPkg(pkg)
        for pkg in self.installed:
            self.triggerlist.addPkg(pkg)
        del self.rpms
        del self.installed
        i = 1
        gc.collect()
        numops = len(operations)
        for i in xrange(0, numops, 100):
            subop = operations[:100]
            for (op, pkg) in subop:
                pkg.open()
            pid = os.fork()
            if pid != 0:
                (rpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    sys.exit(1)
                operations = operations[100:]
                continue
            else:
                del operations
                if self.buildroot:
                    os.chroot(self.buildroot)
                while len(subop) > 0:
                    (op, pkg) = subop.pop(0)
                    i += 1
                    progress = "[%d/%d]" % (i, numops)
                    if   op == RpmResolver.OP_INSTALL:
                        printInfo(0, "%s %s" % (progress, pkg.getNEVRA()))
                        if not pkg.install(self.pydb):
                            sys.exit(1)
                        self.__runTriggerIn(pkg)
                        self.__addPkgToDB(pkg)
                    elif op == RpmResolver.OP_UPDATE or op == RpmResolver.OP_FRESHEN:
                        printInfo(0, "%s %s" % (progress, pkg.getNEVRA()))
                        if not pkg.install(self.pydb):
                            sys.exit(1)
                        self.__runTriggerIn(pkg)
                        self.__addPkgToDB(pkg)
                        if u.has_key(pkg):
                            for opkg in u[pkg]:
                                self.__runTriggerUn(opkg)
                                if not opkg.erase(self.pydb):
                                    sys.exit(1)
                                self.__runTriggerPostUn(opkg)
                                self.__erasePkgFromDB(opkg)
                    elif op == RpmResolver.OP_ERASE:
                        printInfo(0, "%s %s" % (progress, pkg.getNEVRA()))
                        self.__runTriggerUn(pkg)
                        if not pkg.erase(self.pydb):
                            sys.exit(1)
                        self.__runTriggerPostUn(pkg)
                        self.__erasePkgFromDB(pkg)
                    pkg.close()
                    del pkg
                    gc.collect()
                    printInfo(0, "\n")
            return 1

    def appendPkg(self, file):
        pkg = package.RpmPackage(file)
        pkg.read(tags=("name", "epoch", "version", "release", "arch", "providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "filesizes", "filemodes", "filerdevs", "filemtimes", "filemd5s", "filelinktos", "fileflags", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "filelangs", "dirindexes", "basenames", "dirnames", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
        self.rpms.append(pkg)
        pkg.close()
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
                self.rpms.append(pkg)
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
                self.rpms.append(pkg)
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
                self.rpms.append(pkg)
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
                self.rpms.append(pkg)
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
                self.rpms.append(pkg)
                return 1
        # Next check is against n as name, v as version, r as release, a as arch
        for pkg in self.installed:
            # If we have an epoch we need to check it
            if epoch != None and pkg["epoch"][0] != epoch:
                continue
            nevra = pkg.getNEVRA()
            if pkg["name"] == name and pkg["version"] == version and pkg["release"] == release and pkg["arch"] == arch:
                printInfo(3, "Adding %s to package to be removed.\n" % nevra)
                self.rpms.append(pkg)
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
            if rpmconfig.machine not in possible_archs:
                raiseFatal("Unknow rpmconfig.machine architecture %s" % rpmconfig.machine)
            filterArchList(self.rpms)
        else:
            filterArchList(self.rpms, rpmconfig.machine)
        return 1

    def __addPkgToDB(self, pkg):
        if self.pydb == None:
            return 0
        self.pydb.setSource(self.db)
        return self.pydb.addPkg(pkg)

    def __erasePkgFromDB(self, pkg):
        if self.pydb == None:
            return 0
        self.pydb.setSource(self.db)
        return self.pydb.erasePkg(pkg)

    def __runTriggerIn(self, pkg):
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERIN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.pydb.getNumPkgs(pkg["name"])+1)
        # any-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.pydb.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                printError("%s: Error running any trigger in script." % spkg.getNEVRA())
                return 0
        # new-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                printError("%s: Error running new trigger in script." % spkg.getNEVRA())
                return 0
        return 1

    def __runTriggerUn(self, pkg):
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.pydb.getNumPkgs(pkg["name"])-1)
        # old-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                printError("%s: Error running old trigger un script." % spkg.getNEVRA())
                return 0
        # any-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.pydb.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                printError("%s: Error running any trigger un script." % spkg.getNEVRA())
                return 0
        return 1

    def __runTriggerPostUn(self, pkg):
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERPOSTUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.pydb.getNumPkgs(pkg["name"])-1)
        # old-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                printError("%s: Error running old trigger postun script." % spkg.getNEVRA())
        # any-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.pydb.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                printError("%s: Error running any trigger postun script." % spkg.getNEVRA())
                return 0
        return 1

# vim:ts=4:sw=4:showmatch:expandtab