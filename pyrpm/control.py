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


import os
from time import clock
import package
from resolver import *
from orderer import *
from logger import log
from pyrpm.cache import NetworkCache
from pyrpm import functions

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
                    log.error("No package matching %s found", pkgname)
        else:
            for uri in args:
                try:
                    self.appendUri(uri)
                except (IOError, ValueError), e:
                    log.error("%s: %s", uri, e)
        if len(self.rpms) == 0:
            log.info1("Nothing to do.")
        if self.config.timer:
            log.info2("handleFiles() took %s seconds", (clock() - time1))

    def getOperations(self, resolver=None, installdb=None, erasedb=None):
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
            db = self.db.getMemoryCopy()

            resolver = RpmResolver(self.config, db)
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
                    log.error("Unknown operation")
        del self.rpms
        if not self.config.nodeps and not nodeps and resolver.resolve() != 1:
            return None
        if self.config.timer:
            log.info2("resolver took %s seconds", (clock() - time1))
            time1 = clock()
        log.info2("Ordering transaction...")
        orderer = RpmOrderer(self.config, resolver.installs, resolver.updates,
                             resolver.obsoletes, resolver.erases,
                             installdb=installdb, erasedb=erasedb)
        del resolver
        operations = orderer.order()
        if operations is None: # Currently can't happen
            log.error("Errors found during package dependency "
                      "checks and ordering.")
            return None

        # replace repodb pkgs by binaryrpm instances
        for idx, (op, pkg) in enumerate(operations):
            if op in (OP_UPDATE, OP_INSTALL, OP_FRESHEN):
                nc = None
                if not self.config.nocache and \
                       (pkg.source.startswith("http://") or \
                        pkg.source.startswith("https://") or \
                        pkg.yumrepo != None):
                    if pkg.yumrepo != None:
                        nc = pkg.yumrepo.getNetworkCache()
                    else:
                        nc = NetworkCache("/", os.path.join(self.config.cachedir, "default"))
                p = package.RpmPackage(pkg.config, pkg.source,
                                       pkg.verifySignature, db=self.db)
                if pkg.yumrepo != None:
                    p.source = os.path.join(pkg.yumrepo.getNetworkCache().getBaseURL(), p.source)
                p.nc = nc
                p.yumhref = pkg.yumhref
                p.issrc = pkg.issrc
                # copy NEVRA
                for tag in self.config.nevratags:
                    p[tag] = pkg[tag]
                operations[idx] = (op, p)

        if self.config.timer:
            log.info2("orderer took %s seconds", (clock() - time1))
        del orderer
        if not self.config.ignoresize:
            if self.config.timer:
                time1 = clock()
            ret = getFreeCachespace(self.config, operations)
            if self.config.timer:
                log.info2("getFreeCachespace took %s seconds",
                          (clock() - time1))
            if not ret:
                return None
            if self.config.timer:
                time1 = clock()
            ret = getFreeDiskspace(self.config, operations)
            if self.config.timer:
                log.info2("getFreeDiskspace took %s seconds",
                          (clock() - time1))
            if not ret:
                return None
        return operations

    opstrings = {
        OP_INSTALL : "Install: ",
        OP_UPDATE : "Update:  ",
        OP_FRESHEN : "Update:  ",
        OP_ERASE : "Erase:   ",
        }

    def runOperations(self, operations):
        """Perform (operation, RpmPackage) from list operation.

        Return 1 on success, 0 on error (after warning the user)."""
        result = 1
        if operations == []:
            log.error("No updates are necessary.")
            return 1
        # Cache the packages
        if not self.config.nocache:
            log.info2("Caching network packages")
        new_operations = []
        for (op, pkg) in operations:
            if op in (OP_UPDATE, OP_INSTALL, OP_FRESHEN):
                source = pkg.source
                # cache remote pkgs to disk
                if not self.config.nocache and \
                   (pkg.source.startswith("http://") or \
                    pkg.source.startswith("https://") or \
                    pkg.yumrepo != None):
                    log.info3("Caching network package %s", pkg.getNEVRA())
                    source = pkg.nc.cache(pkg.source)
                    if source is None:
                        log.error("Error downloading %s", pkg.source)
                        return 0
                pkg.source = source

                # check signature
                if not self.config.nosignature:
                    try:
                        pkg.reread()
                    except Exception, e:
                        log.error("Error rereading package: %s", e)
                        return 0
                    # Check packages if we have turned on signature checking
                    if pkg.verifyOneSignature() == -1:
                        log.error("Signature verification failed for "
                                  "package %s", pkg.getNEVRA())
                        raise ValueError
                    else:
                        log.info3("Signature of package %s correct",
                                  pkg.getNEVRA())
                    pkg.close()
                    pkg.clear(ntags=self.config.nevratags)
            new_operations.append((op, pkg))
            if pkg["pretransprog"] != None and not self.config.noscripts:
                try:
                    (status, rusage, output) = functions.runScript(
                        pkg["pretransprog"], pkg["pretrans"], [0],
                        rusage=self.config.rusage, pkg=pkg,
                        chroot=self.config.buildroot)
                except (IOError, OSError), e:
                    log.error("\n%s: Error running pre transaction script: %s",
                              pkg.getNEVRA(), e)
                else:
                    if rusage != None and len(rusage):
                        sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (pkg.getNEVRA(), "pretrans", str(rusage[0]), str(rusage[1])))
                    if output or status != 0:
                        log.error("Output running pre transaction script for "
                                  "package %s", pkg.getNEVRA())
                        log.error(output, nofmt=1)

        operations = new_operations
        numops = len(operations)
        numops_chars = len("%d" % numops)
        setCloseOnExec()
        sys.stdout.flush()
        i = 0
        # TODO: Make sure this is always correct. Needed to save memory for
        # now for RpmDB due to obsoletes caching.
        self.db.obsoletes_list = None
        for (op, pkg) in operations:
            # Progress
            opstring = self.opstrings.get(op, "Cleanup: ")
            i += 1
            progress = "[%*d/%d] %s%s"
            log.info2(progress, numops_chars, i, numops,
                      opstring, pkg.getNEVRA(), nl=0, nofmt=1)

            # install
            if op in (OP_INSTALL, OP_UPDATE, OP_FRESHEN):
                # reread pkg
                try:
                    pkg.close()
                    pkg.open()
                except IOError, e:
                    log.error("Error reopening %s: %s", pkg.getNEVRA(), e)
                    result = 0
                    break
                nevra = pkg.getNEVRA()
                pkg.clear()
                # Disable verify, already done
                pkg.verifySignature = None
                try:
                    pkg.read()
                except (IOError, ValueError), e:
                    log.error("Error rereading %s: %s", nevra, e)
                    result = 0
                    break
                # install on disk
                try:
                    if not self.config.justdb:
                        pkg.install(self.db, buildroot=self.config.buildroot)
                        self.__runTriggerIn(pkg, self.config.buildroot)
                        # Ignore errors
                    else:
                        log.info2("", nofmt=1) # newline may be after hashes
                except (IOError, OSError, ValueError), e:
                    log.error("Error installing %s: %s", pkg.getNEVRA(), e)
                    result = 0
                    break
                # update DB
                if self.__addPkgToDB(pkg) == 0:
                    log.error("Couldn't add package %s to database.",
                              pkg.getNEVRA())
                    result = 0
                    break
                pkg.clear()
                try:
                    pkg.close()
                except IOError:
                    # Shouldn't really happen when pkg is open for reading,
                    # anyway.
                    pass
                if not self.config.keepcache and \
                       pkg.nc != None and pkg.yumhref != None:
                    pkg.nc.clear(pkg.yumhref)
            # erase
            elif op == OP_ERASE:
                try:
                    if not self.config.justdb:
                        self.__runTriggerUn(pkg, self.config.buildroot)
                        # Ignore errors
                        pkg.erase(self.db, buildroot=self.config.buildroot)
                        self.__runTriggerPostUn(pkg, self.config.buildroot)
                        # Ignore errors
                    else:
                        log.info2("", nofmt=1) # newline may be after hashes
                except (IOError, ValueError), e:
                    log.error("Error erasing %s: %s", pkg.getNEVRA(), e)
                    result = 0
                    break
                # update DB
                if self.__erasePkgFromDB(pkg) == 0:
                    log.error("Couldn't erase package %s from database.",
                              pkg.getNEVRA())
                    result = 0
                    break

        for (op, pkg) in operations:
            if pkg["posttransprog"] != None and not self.config.noscripts:
                try:
                    (status, rusage, output) = functions.runScript(
                        pkg["posttransprog"], pkg["posttrans"], [0],
                        rusage=self.config.rusage, pkg=pkg,
                        chroot=self.config.buildroot)
                except (IOError, OSError), e:
                    log.error("\n%s: Error running post transaction script: %s",
                              pkg.getNEVRA(), e)
                else:
                    if rusage != None and len(rusage):
                        sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (pkg.getNEVRA(), "posttrans", str(rusage[0]), str(rusage[1])))
                    if output or status != 0:
                        log.error("Output running post transaction script for "
                                  "package %s", pkg.getNEVRA())
                        log.error(output, nofmt=1)

        if self.config.delayldconfig:
            self.config.delayldconfig = 0
            try:
                runScript("/sbin/ldconfig", force=1,
                          chroot=self.config.buildroot)
            except (IOError, OSError), e:
                log.warning("Error running /sbin/ldconfig: %s", e)
            log.info2("number of /sbin/ldconfig calls optimized away: %d",
                      self.config.ldconfig)
        self.db.close()
        return result

    def appendUri(self, uri):
        """Append package from "URI" uri to self.rpms.

        Raise ValueError on invalid data, IOError."""

        pkg = readRpmPackage(self.config, uri, db=self.db,
                             tags=self.config.resolvertags)
        self.rpms.append(pkg)

    def erasePackage(self, pkgname):
        """Append the best match for pkgname to self.rpms.

        Return 1 if found, 0 if not."""

        pkgs = self.db.searchPkgs([pkgname,])
        if len(pkgs) == 0:
            return 0
        self.rpms.append(pkgs[0])
        return 1

    def __preprocess(self):
        """Modify self.rpms to contain only packages that we can use.

        Warn the user about dropped packages."""

        if not self.config.ignorearch:
            filterArchCompat(self.rpms, self.config.machine)

    def __addPkgToDB(self, pkg):
        """Add RpmPackage pkg to self.db"""
        if not pkg.isSourceRPM():
            return self.db.addPkg(pkg)
        return 1

    def __erasePkgFromDB(self, pkg):
        """Remove RpmPackage pkg from self.db."""
        if not pkg.isSourceRPM():
            return self.db.removePkg(pkg)
        return 1

    # Triggers

    def __runTriggerIn(self, pkg, buildroot=''):
        """Run %triggerin scripts after installation of RpmPackage pkg.
        Return 1 on success, 0 on failure."""
        return self.__runTrigger(pkg, RPMSENSE_TRIGGERIN, False,
                                 "in", buildroot)

    def __runTriggerUn(self, pkg, buildroot=''):
        """Run %triggerun scripts before removal of RpmPackage pkg.
        Return 1 on success, 0 on failure."""
        return self.__runTrigger(pkg, RPMSENSE_TRIGGERUN, True,
                                 "un", buildroot)

    def __runTriggerPostUn(self, pkg, buildroot=''):
        """Run %triggerpostun scripts after removal of RpmPackage pkg.
        Return 1 on success, 0 on failure."""
        return self.__runTrigger(pkg, RPMSENSE_TRIGGERPOSTUN, True,
                                 "postun", buildroot)

    def __runTrigger(self, pkg, flag, selffirst, triggername, buildroot=''):
        """Run "flag" trigger scripts for RpmPackage pkg.
        Return 1 on success, 0 on failure."""

        if self.config.justdb or self.config.notriggers or pkg.isSourceRPM():
            return 1
        triggers = self.db.searchTriggers(pkg["name"], flag, pkg.getEVR())
        triggers.pop(pkg, None) # remove this package
        # Set umask to 022, especially important for scripts
        os.umask(022)

        tnumPkgs = str(len(self.db.getPkgsByName(pkg["name"]))+1)

        if selffirst:
            r1 = self.__executePkgTriggers(pkg, flag, triggername,
                                           tnumPkgs, buildroot)
            r2 = self.__executeTriggers(triggers, triggername,
                                        tnumPkgs, buildroot)
        else:
            r2 = self.__executeTriggers(triggers, triggername,
                                        tnumPkgs, buildroot)
            r1 = self.__executePkgTriggers(pkg, flag, triggername,
                                           tnumPkgs, buildroot)
        return r1 and r2

    def __executeTriggers(self, tlist, triggername, tnumPkgs, buildroot=''):
        """execute a list of given triggers
        Return 1 on success, 0 on failure."""

        result = 1
        for spkg, l in tlist.iteritems():
            snumPkgs = str(len(self.db.getPkgsByName(spkg["name"])))
            for name, f, v, prog, script in l:
                try:
                    runScript(prog, script, [snumPkgs, tnumPkgs],
                              chroot=buildroot)
                except (IOError, OSError), e:
                    log.error("%s: Error running trigger %s script: %s",
                              spkg.getNEVRA(), triggername, e)
                    result = 0
        return result

    def __executePkgTriggers(self, pkg, flag, triggername,
                             tnumPkgs, buildroot=''):
        """Execute all triggers of matching "flag" of a package
        that are tiggered by the package itself
        Return 1 on success, 0 on failure."""

        result = 1
        evr = (pkg.getEpoch(), pkg["version"], pkg["release"])
        for name, f, v, prog, script in pkg["triggers"]:
            if (functions.rangeCompare(flag, evr, f, functions.evrSplit(v)) or
                v == ""):
                try:
                    runScript(prog, script, [tnumPkgs, tnumPkgs],
                              chroot=buildroot)
                except (IOError, OSError), e:
                    log.error("%s: Error running trigger %s script: %s",
                              pkg.getNEVRA(), triggername, e)
                    result = 0
        return result

# vim:ts=4:sw=4:showmatch:expandtab
