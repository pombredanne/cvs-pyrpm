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
        self.new = []
        self.update = []
        self.erase = []
        self.installed = []
        self.available = []
        self.oldpackages = []

    def installPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.operation = RpmResolver.OP_INSTALL
        self.db = db 
        self.buildroot = buildroot
        for filename in pkglist:
            self.newPkg(filename)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def updatePkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.operation = RpmResolver.OP_UPDATE
        self.db = db 
        self.buildroot = buildroot
        for filename in pkglist:
            self.updatePkg(filename)
        if not self.__readDB(db):
            return 0
        if not self.run():
            return 0
        return 1

    def freshenPkgs(self, pkglist, db="/var/lib/pyrpm", buildroot=None):
        self.operation = RpmResolver.OP_UPDATE
        self.db = db 
        self.buildroot = buildroot
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
        self.operation = RpmResolver.OP_ERASE
        self.db = db 
        self.buildroot = buildroot
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
        self.triggerlist = Triggers()
        for (op, pkg) in operations:
            if op == RpmResolver.OP_UPDATE or op == RpmResolver.OP_INSTALL:
                self.triggerlist.addPkg(pkg)
        for pkg in self.installed:
            self.triggerlist.addPkg(pkg)
        del self.new
        del self.update
        del self.erase
        del self.installed
        del self.available
        del self.oldpackages
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
                    elif op == RpmResolver.OP_UPDATE:
                        printInfo(0, "%s %s" % (progress, pkg.getNEVRA()))
                        if not pkg.install(self.pydb):
                            sys.exit(1)
                        self.__runTriggerIn(pkg)
                        self.__addPkgToDB(pkg)
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

    def newPkg(self, file):
        pkg = package.RpmPackage(file)
        pkg.read(tags=("name", "epoch", "version", "release", "arch", "providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "filesizes", "filemodes", "filerdevs", "filemtimes", "filemd5s", "filelinktos", "fileflags", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "filelangs", "dirindexes", "basenames", "dirnames", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
        self.new.append(pkg)
        pkg.close()
        return 1

    def updatePkg(self, file):
        pkg = package.RpmPackage(file)
        pkg.read(tags=("name", "epoch", "version", "release", "arch", "providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "filesizes", "filemodes", "filerdevs", "filemtimes", "filemd5s", "filelinktos", "fileflags", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "filelangs", "dirindexes", "basenames", "dirnames", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
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
        for pkg in flist:
            name = pkg.getNEVR()
            arch = pkg["arch"]
            if arch not in possible_archs:
                raiseFatal("%s: Unknow rpm package architecture %s" % (pkg.source, arch))
            if rpmconfig.machine not in possible_archs:
                raiseFatal("%s: Unknow rpmconfig.machine architecture %s" % (pkg.source, rpmconfig.machine))
            if arch != rpmconfig.machine and arch not in arch_compats[rpmconfig.machine]:
                raiseFatal("%s: Architecture not compatible with rpmconfig.machine %s" % (pkg.source, rpmconfig.machine))
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
