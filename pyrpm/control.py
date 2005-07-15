#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
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


import os, gc
from time import clock
import package
from resolver import *
from orderer import *


class _Triggers:
    """ enable search of triggers """
    """ triggers of packages can be added and removed by package """
    def __init__(self, config):
        self.config = config
        self.triggers = {}

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
    def __init__(self, config, operation, db):
        self.config = config
        self.operation = operation
        self.db = db
        self.rpms = []
        self.onlysrpms = 1
        self.db.open()
        if not self.db.read():
            raiseFatal("Couldn't read database")

    def handlePkgs(self, pkglist):
        if self.config.timer:
            time1 = clock()
        for pkg in pkglist:
            self.rpms.append(pkg)
        if len(self.rpms) == 0:
            self.config.printInfo(2, "Nothing to do.\n")
        if self.config.timer:
            self.config.printInfo(0, "handlePkgs() took %s seconds\n" % (clock() - time1))
        return 1

    def handleFiles(self, filelist):
        if self.config.timer:
            time1 = clock()
        if self.operation == OP_ERASE:
            for filename in filelist:
                self.eraseFile(filename)
        else:
            for filename in filelist:
                try:
                    self.appendFile(filename)
                except (IOError, ValueError), e:
                    self.config.printError("%s: %s" % (filename, e))
        if len(self.rpms) == 0:
            self.config.printInfo(2, "Nothing to do.\n")
        if self.config.timer:
            self.config.printInfo(0, "handleFiles() took %s seconds\n" % (clock() - time1))
        return 1

    def getOperations(self, resolver=None):
        if self.config.timer:
            time1 = clock()
        if not self.__preprocess():
            return 0
        if resolver == None:
            resolver = RpmResolver(self.config, self.db.getPkgList())
            for r in self.rpms:
                if   self.operation == OP_INSTALL:
                    resolver.install(r)
                elif self.operation == OP_UPDATE:
                    resolver.update(r)
                elif self.operation == OP_FRESHEN:
                    resolver.freshen(r)
                elif self.operation == OP_ERASE:
                    resolver.erase(r)
                else:
                    self.config.printError("Unknown operation")
        del self.rpms
        if resolver.resolve() != 1:
            sys.exit(1)
        if self.config.timer:
            self.config.printInfo(0, "resolver took %s seconds\n" % (clock() - time1))
            time1 = clock()
        orderer = RpmOrderer(self.config, resolver.installs, resolver.updates,
                             resolver.obsoletes, resolver.erases)
        del resolver
        operations = orderer.order()
        if self.config.timer:
            self.config.printInfo(0, "orderer took %s seconds\n" % (clock() - time1))
        del orderer
        if not self.config.ignoresize:
            if self.config.timer:
                time1 = clock()
            ret = getFreeDiskspace(self.config, operations)
            if self.config.timer:
                self.config.printInfo(0, "getFreeDiskspace took %s seconds\n" % \
                             (clock() - time1))
            if not ret:
                sys.exit(1)
        return operations

    def runOperations(self, operations):
        if not operations:
            if operations == []:
                self.config.printError("No updates are necessary.")
                sys.exit(0)
            self.config.printError("Errors found during package dependancy checks and ordering.")
            sys.exit(1)
        self.triggerlist = _Triggers(self.config)
        i = 0
        self.onlysrpms = 1
        for (op, pkg) in operations:
            if not pkg.isSourceRPM():
                self.onlysrpms = 0
            if op == OP_UPDATE or op == OP_INSTALL or op == OP_FRESHEN:
                self.triggerlist.addPkg(pkg)
                if pkg.source.startswith("http://"):
                    if pkg.has_key("yumreponame"):
                        reponame = pkg["yumreponame"]
                    else:
                        reponame = "default"
                    self.config.printInfo(1, "Caching network package %s\n" % \
                                          pkg.getNEVRA())
                    pkg.source = cacheLocal(pkg.source, reponame+"/packages")
        for pkg in self.db.getPkgList():
            self.triggerlist.addPkg(pkg)
        numops = len(operations)
        gc.collect()
        pkgsperfork = 100
        setCloseOnExec()
        sys.stdout.flush()
        for i in xrange(0, numops, pkgsperfork):
            subop = operations[:pkgsperfork]
            for (op, pkg) in subop:
                try:
                    pkg.close()
                    pkg.open()
                except IOError, e:
                    self.config.printError("Error reopening %s: %s"
                                       % (pkg.getNEVRA(), e))
                    sys.exit(1)
            pid = os.fork()
            if pid != 0:
                (rpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    sys.exit(1)
                for (op, pkg) in subop:
                    if op == OP_INSTALL or \
                       op == OP_UPDATE or \
                       op == OP_FRESHEN:
                        self.__addPkgToDB(pkg, nowrite=1)
                    elif op == OP_ERASE:
                        self.__erasePkgFromDB(pkg, nowrite=1)
                    try:
                        pkg.close()
                    except IOError:
                        # Shouldn't really happen when pkg is open for reading,
                        # anyway.
                        pass
                operations = operations[pkgsperfork:]
                subop = operations[:pkgsperfork]
            else:
                del operations
                gc.collect()
                if self.config.buildroot:
                    if self.onlysrpms:
                        os.chdir(self.config.buildroot)
                    else:
                        os.chroot(self.config.buildroot)
                # We're in a buildroot now, reset the buildroot in the db object
                self.db.setBuildroot(None)
                # Now reopen database
                self.db.close()
                self.db.open()
                while len(subop) > 0:
                    (op, pkg) = subop.pop(0)
                    pkg.clear()
                    try:
                        pkg.read()
                    except (IOError, ValueError), e:
                        self.config.printError("Error rereading %s: %s"
                                               % (pkg.getNEVRA(), e))
                        sys.exit(1)
                    if   op == OP_INSTALL:
                        opstring = "Install: "
                    elif op == OP_UPDATE or op == OP_FRESHEN:
                        opstring = "Update:  "
                    else:
                        if self.operation != OP_ERASE:
                            opstring = "Cleanup: "
                        else:
                            opstring = "Erase:   "
                    i += 1
                    progress = "[%d/%d] %s%s" % (i, numops, opstring, pkg.getNEVRA())
                    if self.config.printhash:
                        self.config.printInfo(0, progress)
                    else:
                        self.config.printInfo(1, progress)
                    if   op == OP_INSTALL or \
                         op == OP_UPDATE or \
                         op == OP_FRESHEN:
                        try:
                            if not self.config.justdb:
                                pkg.install(self.db)
                            else:
                                self.config.printInfo(0, "\n")
                        except (IOError, OSError, ValueError), e:
                            self.config.printError("Error installing %s: %s"
                                                   % (pkg.getNEVRA(), e))
                            sys.exit(1)
                        self.__runTriggerIn(pkg)
                        self.__addPkgToDB(pkg)
                    elif op == OP_ERASE:
                        self.__runTriggerUn(pkg)
                        try:
                            if not self.config.justdb:
                                pkg.erase(self.db)
                            else:
                                self.config.printInfo(0, "\n")
                        except (IOError, ValueError), e:
                            self.config.printError("Error erasing %s: %s"
                                                   % (pkg.getNEVRA(), e))
                            sys.exit(1)
                        self.__runTriggerPostUn(pkg)
                        self.__erasePkgFromDB(pkg)
                    try:
                        pkg.close()
                    except IOError:
                        # Shouldn't really happen when pkg is open for reading,
                        # anyway.
                        pass
                    del pkg
                if self.config.delayldconfig:
                    self.config.delayldconfig = 0
                    runScript("/sbin/ldconfig", force=1)
                self.config.printInfo(2, "number of /sbin/ldconfig calls optimized away: %d\n" % self.config.ldconfig)
                sys.exit(0)
        self.db.close()

    def appendFile(self, file):
        """Append file to self.rpms.

        Raise ValueError on invalid data, IOError."""

        pkg = readRpmPackage(self.config, file, db=self.db,
                             tags=self.config.resolvertags)
        self.rpms.append(pkg)

    def eraseFile(self, file):
        pkgs = findPkgByName(file, self.db.getPkgList())
        if len(pkgs) == 0:
            return 0
        self.rpms.append(pkgs[0])
        return 1

    def __preprocess(self):
        if self.config.ignorearch:
            return 1
        filterArchCompat(self.rpms, self.config.machine)
        return 1

    def __addPkgToDB(self, pkg, nowrite=None):
        if not pkg.isSourceRPM():
            return self.db.addPkg(pkg, nowrite)
        return 1

    def __erasePkgFromDB(self, pkg, nowrite=None):
        if not pkg.isSourceRPM():
            return self.db.erasePkg(pkg, nowrite)
        return 1

    def __runTriggerIn(self, pkg):
        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERIN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.db.getNumPkgs(pkg["name"])+1)
        # any-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.db.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                self.config.printError("%s: Error running any trigger in script." % spkg.getNEVRA())
                return 0
        # new-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                self.config.printError("%s: Error running new trigger in script." % spkg.getNEVRA())
                return 0
        return 1

    def __runTriggerUn(self, pkg):
        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.db.getNumPkgs(pkg["name"])-1)
        # old-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                self.config.printError("%s: Error running old trigger un script." % spkg.getNEVRA())
                return 0
        # any-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.db.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                self.config.printError("%s: Error running any trigger un script." % spkg.getNEVRA())
                return 0
        return 1

    def __runTriggerPostUn(self, pkg):
        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERPOSTUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(self.db.getNumPkgs(pkg["name"])-1)
        # old-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            if not runScript(prog, script, tnumPkgs, tnumPkgs):
                self.config.printError("%s: Error running old trigger postun script." % spkg.getNEVRA())
        # any-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(self.db.getNumPkgs(spkg["name"]))
            if not runScript(prog, script, snumPkgs, tnumPkgs):
                self.config.printError("%s: Error running any trigger postun script." % spkg.getNEVRA())
                return 0
        return 1

# vim:ts=4:sw=4:showmatch:expandtab
