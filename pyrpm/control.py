#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche
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
    """A database of triggers searchable by %name"""

    def __init__(self):
        # %name => (RPMSENSE_* flag, EVR string, interpreter, script,
        # RpmPackage containing the trigger)
        self.triggers = {}

    def append(self, name, flag, version, tprog, tscript, rpm):
        """Add tscript interpreted by tprog from RpmPackage rpm to triggers on
        (name, RPMSENSE_* flag, EVR string version)."""

        if not self.triggers.has_key(name):
            self.triggers[name] = [ ]
        self.triggers[name].append((flag, version, tprog, tscript, rpm))

    def remove(self, name, flag, version, tprog, tscript, rpm):
        """Remove tscript interpreted by tprog from RpmPackage rpm from
        triggers on (name, RPMSENSE_* flag, EVR string version), if it
        exists."""

        if not self.triggers.has_key(name):
            return
        for t in self.triggers[name]:
            if t[0] == flag and t[1] == version and t[2] == tprog and t[3] == tscript and t[4] == rpm:
                self.triggers[name].remove(t)
        if len(self.triggers[name]) == 0:
            del self.triggers[name]

    def addPkg(self, rpm):
        """Add triggers from RpmPackage rpm to the database."""

        for t in rpm["triggers"]:
            self.append(t[0], t[1], t[2], t[3], t[4], rpm)

    def removePkg(self, rpm):
        """Remove triggers from RpmPackage rpm from the database."""

        for t in rpm["triggers"]:
            self.remove(t[0], t[1], t[2], t[3], t[4], rpm)

    def search(self, name, flag, version):
        """Search for triggers with same type as RPMSENSE_TRIGGER* flag
        matching name, EVR string version.

        Return a list of (interpreter, script, RpmPackage containing the
        trigger)."""

        if not self.triggers.has_key(name):
            return [ ]
        ret = [ ]
        for t in self.triggers[name]:
            if (t[0] & RPMSENSE_TRIGGER) != (flag & RPMSENSE_TRIGGER):
                continue
            if t[1] == "":
                ret.append((t[2], t[3], t[4]))
            else:
                # FIXME: flag is RPMSENSE_TRIGGER*, the first evrCompare always
                # returns False.
                if evrCompare(version, flag, t[1]) and \
                       evrCompare(version, t[0], t[1]):
                    ret.append((t[2], t[3], t[4]))
        return ret


class RpmController:
    """RPM state manager, handling package installation and deinstallation."""

    def __init__(self, config, operation, db):
        """Initialize for base.OP_* operation on RpmDatabase db.

        Raise ValueError if db can't read."""

        self.config = config
        self.operation = operation
        self.db = db
        self.rpms = []                  # List of RpmPackage's to act upon
        self.db.open()
        if not self.db.read():
            raise ValueError, "Fatal: Couldn't read database"

    def handleFiles(self, args):
        """Add packages with names (for OP_ERASE) or "URI"s (for other
        operations) from args, to be acted upon.

        Report errors to the user, not to the caller."""

        if self.config.timer:
            time1 = clock()
        if self.operation == OP_ERASE:
            for pkgname in args:
                if self.erasePackage(pkgname) == 0:
                    self.config.printError("No package matching %s found"
                                           % pkgname)
        else:
            for uri in args:
                try:
                    self.appendUri(uri)
                except (IOError, ValueError), e:
                    self.config.printError("%s: %s" % (uri, e))
        if len(self.rpms) == 0:
            self.config.printInfo(2, "Nothing to do.\n")
        if self.config.timer:
            self.config.printInfo(0, "handleFiles() took %s seconds\n" % (clock() - time1))

    def getOperations(self, resolver=None):
        """Return an ordered list of (operation, RpmPackage).

        If resolver is None, use packages previously added to be acted upon;
        otherwise use the operations from resolver.

        Return None on error (after warning the user).

        New packages to be acted upon can't be added after calling this
        function, neither before nor after performing the current
        operations."""

        if self.config.timer:
            time1 = clock()
        self.__preprocess()
        # hack: getOperations() is called from yum.py where deps are already
        # and from scripts/pyrpminstall where we still need todo dep checking.
        # This should get re-worked to clean this up.
        nodeps = 1
        if resolver == None:
            nodeps = 0
            resolver = RpmResolver(self.config, self.db.getPkgs())
            for r in self.rpms:
                # Ignore errors from RpmResolver, the functions already warn
                # the user if necessary.
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
        if not self.config.nodeps and not nodeps and resolver.resolve() != 1:
            return None
        if self.config.timer:
            self.config.printInfo(0, "resolver took %s seconds\n" % (clock() - time1))
            time1 = clock()
        self.config.printInfo(1, "Ordering transaction...\n")
        orderer = RpmOrderer(self.config, resolver.installs, resolver.updates,
                             resolver.obsoletes, resolver.erases)
        del resolver
        operations = orderer.order()
        if operations is None: # Currently can't happen
            self.config.printError("Errors found during package dependency "
                                   "checks and ordering.")
            return None
        if self.config.timer:
            self.config.printInfo(0, "orderer took %s seconds\n" % (clock() - time1))
        del orderer
        if not self.config.ignoresize:
            if self.config.timer:
                time1 = clock()
            ret = getFreeCachespace(self.config, operations)
            if self.config.timer:
                self.config.printInfo(0, "getFreeCachespace took %s seconds\n" % \
                             (clock() - time1))
            if not ret:
                return None
        self.triggerlist = _Triggers()
        if not self.config.nocache:
            self.config.printInfo(1, "Caching network packages\n")
        for (op, pkg) in operations:
            if op == OP_UPDATE or op == OP_INSTALL or op == OP_FRESHEN:
                self.triggerlist.addPkg(pkg)
                if not self.config.nocache and \
                   (pkg.source.startswith("http://") or \
                    pkg.yumrepo != None):
                    if pkg.yumrepo != None:
                        nc = pkg.yumrepo.getNetworkCache()
                    else:
                        nc = NetworkCache("/", os.path.join(self.config.cachedir, "default"))
                    self.config.printInfo(2, "Caching network package %s\n" % pkg.getNEVRA())
                    cached = nc.cache(pkg.source)
                    if cached is None:
                        self.config.printError("Error downloading %s"
                                               % pkg.source)
                        return 0
                    pkg.source = cached
                if not self.config.nosignature:
                    try:
                        pkg.reread()
                    except Exception, e:
                        self.config.printError("Error rereading package: %s" % e)
                        return 0
                    # Check packages if we have turned on signature checking
                    if pkg.verifyOneSignature() == -1:
                        self.config.printError("Signature verification failed for package %s" % pkg.getNEVRA())
                        raise ValueError
                    else:
                        self.config.printInfo(2, "Signature of package %s correct\n" % pkg.getNEVRA())
                    pkg.close()
                    pkg.clear(ntags=self.config.resolvertags)
        if not self.config.ignoresize:
            if self.config.timer:
                time1 = clock()
            ret = getFreeDiskspace(self.config, operations)
            if self.config.timer:
                self.config.printInfo(0, "getFreeDiskspace took %s seconds\n" %\
                            (clock() - time1))
            if not ret:
                return None
        return operations

    def runOperations(self, operations):
        """Perform (operation, RpmPackage) from list operation.

        Return 1 on success, 0 on error (after warning the user)."""

        if operations == []:
            self.config.printError("No updates are necessary.")
            return 1
        for pkg in self.db.getPkgs():
            self.triggerlist.addPkg(pkg)
        numops = len(operations)
        numops_chars = len("%d" % numops)
        gc.collect()
        pkgsperfork = 100
        setCloseOnExec()
        sys.stdout.flush()
        for i in xrange(0, numops, pkgsperfork):
            subop = operations[i:i+pkgsperfork]
            for (op, pkg) in subop:
                try:
                    pkg.close()
                    pkg.open()
                except IOError, e:
                    self.config.printError("Error reopening %s: %s"
                                       % (pkg.getNEVRA(), e))
                    return 0
            try:
                pid = os.fork()
            except OSError, e:
                self.config.printError("fork(): %s" % e)
                return 0
            if pid != 0:
                (rpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    if os.WIFSIGNALED(status):
                        self.config.printError("Child killed with signal %d"
                                               % os.WTERMSIG(status))
                    return 0
                for (op, pkg) in subop:
                    if op == OP_INSTALL or \
                       op == OP_UPDATE or \
                       op == OP_FRESHEN:
                        try:
                            pkg.reread(self.config.resolvertags)
                        except Exception, e:
                            self.config.printError("Error rereading package: %s" % e)
                            return 0
                        if not self.__addPkgToDB(pkg, nowrite=1):
                            self.config.printError("Couldn't add package %s to parent database." % pkg.getNEVRA())
                            return 0
                        pkg.close()
                    elif op == OP_ERASE:
                        if not self.__erasePkgFromDB(pkg, nowrite=1):
                            self.config.printError("Couldn't erase package %s from parent database." % pkg.getNEVRA())
                            return 0
                    try:
                        pkg.close()
                    except IOError:
                        # Shouldn't really happen when pkg is open for reading,
                        # anyway.
                        pass
            else:
                del operations
                gc.collect()
                if self.config.buildroot:
                    os.chroot(self.config.buildroot)
                # We're in a buildroot now, reset the buildroot in the db object
                self.db.setBuildroot(None)
                # Now reopen database
                self.db.close()
                self.db.open()
                while len(subop) > 0:
                    (op, pkg) = subop.pop(0)
                    nevra = pkg.getNEVRA()
                    pkg.clear()
                    # Disable verify in child/buildroot, can go wrong horribly.
                    pkg.verifySignature = None
                    try:
                        pkg.read()
                    except (IOError, ValueError), e:
                        self.config.printError("Error rereading %s: %s"
                                               % (nevra, e))
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
                    progress = "[%*d/%d] %s%s" % (numops_chars, i, numops, opstring, pkg.getNEVRA())
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
                                if self.config.printhash:
                                    self.config.printInfo(0, "\n")
                                else:
                                    self.config.printInfo(1, "\n")
                        except (IOError, OSError, ValueError), e:
                            self.config.printError("Error installing %s: %s"
                                                   % (pkg.getNEVRA(), e))
                            sys.exit(1)
                        self.__runTriggerIn(pkg) # Ignore errors
                        if self.__addPkgToDB(pkg) == 0:
                            self.config.printError("Couldn't add package %s "
                                                   "to database."
                                                   % pkg.getNEVRA())
                            sys.exit(1)
                    elif op == OP_ERASE:
                        self.__runTriggerUn(pkg) # Ignore errors
                        try:
                            if not self.config.justdb:
                                pkg.erase(self.db)
                            else:
                                if self.config.printhash:
                                    self.config.printInfo(0, "\n")
                                else:
                                    self.config.printInfo(1, "\n")
                        except (IOError, ValueError), e:
                            self.config.printError("Error erasing %s: %s"
                                                   % (pkg.getNEVRA(), e))
                            sys.exit(1)
                        self.__runTriggerPostUn(pkg) # Ignore errors
                        if self.__erasePkgFromDB(pkg) == 0:
                            self.config.printError("Couldn't erase package %s "
                                                   "from database."
                                                   % pkg.getNEVRA())
                            sys.exit(1)
                    try:
                        pkg.close()
                    except IOError:
                        # Shouldn't really happen when pkg is open for reading,
                        # anyway.
                        pass
                    del pkg
                if self.config.delayldconfig:
                    self.config.delayldconfig = 0
                    try:
                        runScript("/sbin/ldconfig", force=1)
                    except (IOError, OSError), e:
                        self.config.printWarning(0, "Error running "
                                                 "/sbin/ldconfig: %s" % e)
                self.config.printInfo(2, "number of /sbin/ldconfig calls optimized away: %d\n" % self.config.ldconfig)
                self.db.close()
                sys.exit(0)
        self.db.close()
        for (op, pkg) in operations:
            if op == OP_UPDATE or op == OP_INSTALL or op == OP_FRESHEN:
                if pkg.yumrepo != None and pkg.yumhref != None:
                    pkg.yumrepo.getNetworkCache().clear(pkg.yumhref)
        return 1

    def appendUri(self, uri):
        """Append package from "URI" uri to self.rpms.

        Raise ValueError on invalid data, IOError."""

        pkg = readRpmPackage(self.config, uri, db=self.db,
                             tags=self.config.resolvertags)
        self.rpms.append(pkg)

    def erasePackage(self, pkgname):
        """Append the best match for pkgname to self.rpms.

        Return 1 if found, 0 if not."""

        pkgs = findPkgByNames([pkgname,], self.db.getPkgs())
        if len(pkgs) == 0:
            return 0
        self.rpms.append(pkgs[0])
        return 1

    def __preprocess(self):
        """Modify self.rpms to contain only packages that we can use.

        Warn the user about dropped packages."""

        if not self.config.ignorearch:
            filterArchCompat(self.rpms, self.config.machine)

    def __addPkgToDB(self, pkg, nowrite=None):
        """Add RpmPackage pkg to self.db if necesary: to memory and
        persistently if not nowrite."""

        if not pkg.isSourceRPM():
            return self.db.addPkg(pkg, nowrite)
        return 1

    def __erasePkgFromDB(self, pkg, nowrite=None):
        """Remove RpmPackage pkg from self.db if necesary: from memory and
        persistently if not nowrite."""

        if not pkg.isSourceRPM():
            return self.db.erasePkg(pkg, nowrite)
        return 1

    def __runTriggerIn(self, pkg):
        """Run %triggerin scripts after installation of RpmPackage pkg.

        Return 1 on success, 0 on failure."""

        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERIN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(len(self.db.getPkgsByName(pkg["name"]))+1)
        # any-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(len(self.db.getPkgsByName(spkg["name"])))
            try:
                runScript(prog, script, [snumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running any trigger in script: %s" % (spkg.getNEVRA(), e))
                return 0
        # new-%triggerin
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            try:
                runScript(prog, script, [tnumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running new trigger in script: %s" % (spkg.getNEVRA(), e))
                return 0
        return 1

    def __runTriggerUn(self, pkg):
        """Run %triggerun scripts before removal of RpmPackage pkg.

        Return 1 on success, 0 on failure."""

        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(len(self.db.getPkgsByName(pkg["name"]))-1)
        # old-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            try:
                runScript(prog, script, [tnumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running old trigger un script: %s" % (spkg.getNEVRA(), e))
                return 0
        # any-%triggerun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(len(self.db.getPkgsByName(spkg["name"])))
            try:
                runScript(prog, script, [snumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running any trigger un script: %s" % (spkg.getNEVRA(), e))
                return 0
        return 1

    def __runTriggerPostUn(self, pkg):
        """Run %triggerpostun scripts after removal of RpmPackage pkg.

        Return 1 on success, 0 on failure."""

        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        tlist = self.triggerlist.search(pkg["name"], RPMSENSE_TRIGGERPOSTUN, pkg.getEVR())
        # Set umask to 022, especially important for scripts
        os.umask(022)
        tnumPkgs = str(len(self.db.getPkgsByName(pkg["name"]))-1)
        # old-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg != pkg:
                continue
            try:
                runScript(prog, script, [tnumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running old trigger postun script: %s" % (spkg.getNEVRA(), e))
                return 0
        # any-%triggerpostun
        for (prog, script, spkg) in tlist:
            if spkg == pkg:
                continue
            snumPkgs = str(len(self.db.getPkgsByName(spkg["name"])))
            try:
                runScript(prog, script, [snumPkgs, tnumPkgs])
            except (IOError, OSError), e:
                self.config.printError("%s: Error running any trigger postun script: %s" % (spkg.getNEVRA(), e))
                return 0
        return 1

# vim:ts=4:sw=4:showmatch:expandtab
