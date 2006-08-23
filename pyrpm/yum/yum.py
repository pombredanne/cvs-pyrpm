#
# Copyright 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch
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


import fnmatch, re
from time import clock
from pyrpm.resolver import RpmResolver
from pyrpm.control import RpmController
from pyrpm.package import RpmPackage
from pyrpm.functions import *
from pyrpm.io import *
import pyrpm.database as database, yumconfig


class RpmYum:
    def __init__(self, config):
        self.config = config
        # Default: Don't autoerase packages that have unresolved symbols in
        # install or update
        self.autoerase = 0
        # package names/globs to be excluded from autoerasing of autoerase is
        # enabled.
        self.autoeraseexclude = [ ]
        # Default: Ask user for confirmation of complete operation
        self.confirm = 1
        # Default: No command
        self.command = None
        # List of RpmRepo's
        self.repos = [ ]
        # List of languages we want to install for.
        self.langs = [ ]
        # Internal list of packages that are have to be erased
        self.erase_list = [ ]
        # Our database
        self.pydb = None
        # Flag wether we already read all the repos
        self.repos_read = 0
        # Our list of package names that get installed instead of updated
        self.always_install = ["kernel", "kernel-devel", "kernel-smp",
            "kernel-smp-devel", "kernel-bigmem", "kernel-bigmem-devel",
            "kernel-enterprise", "kernel-enterprise-devel", "kernel-debug",
            "kernel-unsupported"]
        # List of valid commands
        self.command_list = ["install", "update", "upgrade", "remove", \
                             "groupinstall", "groupupdate", "groupupgrade", \
                             "groupremove"]

    def setAutoerase(self, flag):
        """Enable or disable erasing packages with unresolved dependencies
        according to flag."""

        self.autoerase = flag

    def setAutoeraseExclude(self, exlist):
        """Sets the names/globs to be excluded from autoerasing."""
        nlist = []
        for name in exlist:
            name = fnmatch.translate(name)
            regex = re.compile(name)
            nlist.append(regex)
        self.autoeraseexclude = nlist

    def setConfirm(self, flag):
        """Enable or disable asking the user for confirmation according to
        flag."""

        self.confirm = flag

    def setCommand(self, command):
        """Set the command to perform to commmand.

        Return 1 on success, 0 on error (after warning the user)."""

        self.command = command.lower()
        if self.command not in self.command_list:
            self.config.printError("Invalid command")
            return 0
        #if self.command == "upgrade" or self.command == "groupupgrade":
        #    self.always_install = [ ]
        return 1

    def addRepo(self, file):
        """Read yum configuration file and add repositories it uses.

        sys.exit() on error."""

        try:
            conf = yumconfig.YumConf(self.config.relver, self.config.machine,
                                     buildarchtranslate[self.config.machine],
                                     self.config.buildroot, file)
        except IOError, e:
            printError("Error reading configuration: %s" % e)
            return 0
        erepo = []
        for ritem in self.config.enablerepo:
            ritem = fnmatch.translate(ritem)
            regex = re.compile(ritem)
            erepo.append(regex)
        drepo = []
        for ritem in self.config.disablerepo:
            ritem = fnmatch.translate(ritem)
            regex = re.compile(ritem)
            drepo.append(regex)
        for key in conf.keys():
            sec = conf[key]
            if key == "main":
                # exactarch can only be found in main section. Default False
                if sec.has_key("exactarch") and sec["exactarch"] == "1":
                    self.config.exactarch = True
                # keepcache can only be found in main section. Default True
                if sec.has_key("keepcache") and sec["keepcache"] == "0":
                    self.config.exactarch = False
            else:
                # Check if the current repo should be enabled or disabled
                enabled = True      # Default is enabled
                if sec.has_key("enabled") and sec["enabled"] == "0":
                    enabled = False
                for regex in erepo:
                    if regex.match(key):
                        enabled = True
                        break
                for regex in drepo:
                    if regex.match(key):
                        enabled = False
                        break
                # Repo is not enabled: skip it.
                if not enabled:
                    continue
                if sec.has_key("baseurl"):
                    baseurls = sec["baseurl"][:]
                else:
                    baseurls = []
                if self.config.timer:
                    time1 = clock()
                self.config.printInfo(1, "Reading repository %s\n" % key)
                if self.__addSingleRepo(baseurls, conf, key) == 0:
                    return 0
                if self.config.timer:
                    self.config.printInfo(0, "Reading repository took %s seconds\n" % (clock() - time1))
        return 1

    def __addSingleRepo(self, baseurls, conf, reponame):
        """Add a repository at baseurl as reponame.

        Return 1 on success 0 on errror (after warning the user).  Exclude
        packages matching whitespace-separated excludes."""

        #repo = database.repodb.RpmRepoDB(self.config, baseurls,
        #                  self.config.buildroot, conf, reponame)
        repo = database.sqlitedb.SqliteDB(self.config, baseurls,
                   self.config.buildroot, conf, reponame)
        if repo.read() == 0:
            self.config.printError("Error reading repository %s" % reponame)
            return 0
        self.repos.append(repo)
        return 1

    def prepareTransaction(self, localDb = None):
        """Open the RPM database and prepare the transaction.

        Return 1 in success, 0 on error (after warning the user).  If localDb
        is not None, use it as a local RPM database instead of reading the
        database again."""

        self.erase_list = []
        if localDb is not None:
            self.pydb = localDb
        else:
            if self.config.timer:
                time1 = clock()
            # Create and read db
            self.config.printInfo(1, "Reading local RPM database\n")
            self.pydb = database.getRpmDBFactory(self.config,
                                                 self.config.dbpath,
                                                 self.config.buildroot)
            self.pydb.open()
            if not self.pydb.read():
                self.config.printError("Error reading the RPM database")
                return 0
            if self.config.timer:
                self.config.printInfo(0, "Reading local RPM database took %s seconds\n" % (clock() - time1))
        if self.config.timer:
            time1 = clock()

        db = self.pydb.getMemoryCopy()

        for pkg in db.searchProvides("redhat-release", 0, ""):
            rpmconfig.relver = pkg["version"]

        for yumconf in self.config.yumconf:
            if os.path.isfile(yumconf):
                if not self.repos_read and not self.command == "remove":
                    if not self.addRepo(yumconf):
                        return 0
            else:
                printWarning(1, "Couldn't find given yum config file, skipping read of repo %s" % yumconf)
        self.repos_read = 1
        self.opresolver = RpmResolver(self.config, db)
        self.__generateObsoletesList()
        if self.config.timer:
            self.config.printInfo(0, "Preparing transaction took %s seconds\n" % (clock() - time1))

        return 1

    def getGroupPackages(self, name):
        """Return a list of package names from all repositories matching that
        group"""

        pkglist = []
        for repo in self.repos:
            if repo.comps != None:
                pkglist.extend(repo.comps.getPackageNames(name))
        return pkglist

    def install(self, name):
        pkglist = self.__findPkgs(name)
        return self.__handleBestPkg("install", pkglist)

    def groupInstall(self, name):
        args = self.getGroupPackages(name)
        ret = 0
        for pkgname in args:
            ret |= self.install(pkgname)
        return ret

    def installByDep(self, dname, dflags, dversion):
        pkglist = self.__findPkgsByDep(dname, dflags, dversion)
        return self.__handleBestPkg("install", pkglist)

    def update(self, name, exact=False, do_obsolete=True):
        # First find all matching packages. Remember, name can be a glob, too,
        # so we might get a list of packages with different names.
        if exact:
            pkglist = self.__findPkgsByExactName(name)
        else:
            pkglist = self.__findPkgs(name)
        # Next we generate two temporary hashes. One with just a list of
        # packages for each name and a second with a subhash for each package
        # for each arch. Both are needed for speed reasons. The first one for
        # the general case where we either have:
        #  - install only package
        #  - no previously installed package
        #  - previously installed packages but exactarch in yum.conf is False.
        # The second one is needed for exactarch updates to find matching
        # updates fast for specific installed archs of packages.
        pkgnamehash = {}
        pkgnamearchhash = {}
        for pkg in pkglist:
            pkgnamehash.setdefault(pkg["name"], []).append(pkg)
            pkgnamearchhash.setdefault(pkg["name"], {}).setdefault(pkg["arch"], []).append(pkg)
        # Now go over all package names we found and find the correct update
        # packages.
        ret = 0
        for name in pkgnamehash.keys():
            # Get a copy of the current db packages for the given name
            dbpkgs = self.opresolver.getDatabase().getPkgsByName(name)[:]
            # If the package name is either in our always_install list, no
            # package with that name was installed we simply try to select the
            # best matching package update for this arch.
            if name in self.always_install or len(dbpkgs) == 0:
                ret |= self.__handleBestPkg("update", pkgnamehash[name], do_obsolete=do_obsolete)
                continue
            # Next trick: We now know that this is an update package and we
            # have at least 1 package with that name installed. In order to
            # updated 32 and 64 bit archs properly we now have to determine
            # how and what needs to be updated properly in case exactarch
            # isn't set.
            if not self.config.exactarch:
                arch = None
                is_multi = False
                # Check if all packages share them same buildarch translation.
                for ipkg in dbpkgs:
                    if arch != None and arch != buildarchtranslate[ipkg["arch"]]:
                        is_multi = True
                        break
                    arch = buildarchtranslate[ipkg["arch"]]
                # If not and we're not exactarch then just find the best
                # matching package again as we allow arch switches to 64bit
                # for updates.
                if not is_multi:
                    l = self._filterPkgVersion(max(dbpkgs), pkgnamehash[name])
                    ret |= self.__handleBestPkg("update", l,
                                                do_obsolete=do_obsolete)
                    continue
                # OK, we have several archs for this package installed, we now
                # need to filter them to 32bit and 64bit buckets and later
                # use our standard algorithm to select the best matching
                # package for each arch.
                for arch in pkgnamearchhash[name].keys():
                    if buildarchtranslate[arch] == arch:
                        continue
                    pkgnamearchhash[name].setdefault(buildarchtranslate[arch], []).extend(pkgnamearchhash[name][arch])
                    del pkgnamearchhash[name][arch]
            # Ok, now we have to find matching updates for all installed archs.
            for ipkg in dbpkgs:
                # First see if we're dealing with a noarch package. Just allow
                # any package to be used then.
                if   ipkg["arch"] == "noarch":
                    arch = "noarch"
                    march = self.config.machine
                    for a in pkgnamearchhash[name].keys():
                        if a == arch:
                            continue
                        pkgnamearchhash[name][arch].extend(pkgnamearchhash[name][a])
                # Now for exactarch we really need to find a perfect arch match.
                elif self.config.exactarch:
                    arch = ipkg["arch"]
                    march = arch
                    # Add all noarch packages for arch -> noarch transitions
                    pkgnamearchhash[name].setdefault(arch, []).extend(pkgnamearchhash[name].setdefault("noarch", {}))
                # If we are not doing exactarch we allow archs to be switched
                # inside of the given buildarch translation.
                else:
                    arch = buildarchtranslate[ipkg["arch"]]
                    march = self.config.machine
                    # Add all noarch packages for arch -> noarch transitions
                    pkgnamearchhash[name].setdefault(arch, []).extend(pkgnamearchhash[name].setdefault("noarch", {}))
                if not pkgnamearchhash[name].has_key(arch):
                    self.config.printError("Can't find update package with matching arch for package %s" % ipkg.getNEVRA())
                    return 0

                # Filter packages with lower versions from our final list
                l = self._filterPkgVersion(ipkg, pkgnamearchhash[name][arch])
                # Find the best matching package for the given list of packages
                # and archs.
                r = self.__handleBestPkg("update", l, march, self.config.exactarch, do_obsolete=do_obsolete)
                # In case we had a successfull update make sure we erase the
                # package we just updated. Otherwise cross arch switches won't
                # work properly.
                if r > 0 and ipkg in self.opresolver.getDatabase():
                    self.opresolver.erase(ipkg)
                ret |= r
                # Trick to avoid multiple adds for same arch, after handling
                # it once we clear the update package list.
                pkgnamearchhash[name][arch] = []
        return ret

    def _filterPkgVersion(self, pkg, pkglist):
        l = []
        for p in pkglist:
            if pkgCompare(pkg, p) < 0:
                l.append(p)
        return l

    def groupUpdate(self, name):
        args = self.getGroupPackages(name)
        ret = 0
        for pkgname in args:
            ret |= self.update(pkgname)
        return ret

    def updateByDep(self, dname, dflags, dversion):
        pkglist = self.__findPkgsByDep(dname, dflags, dversion)
        return self.__handleBestPkg("update", pkglist)

    def remove(self, name):
        self.__handleBestPkg("remove", self.pydb.searchPkgs([name, ]))

    def groupRemove(self, name):
        args = self.getGroupPackages(name)
        for pkgname in args:
            self.remove(pkgname)

    def removeByDep(self, dname, dflags, dversion, all=True):
        pkglist = self.pydb.searchDependency(dname, dflags, dversion)
        return self.__handleBestPkg("remove", pkglist)

    def __readPackage(self, name):
        try:
            pkg = readRpmPackage(self.config, name, db=self.pydb,
                                 tags=self.config.resolvertags)
        except (IOError, ValueError), e:
            self.config.printError("%s: %s" % (name, e))
            return None
        if self.config.ignorearch or \
           pkg.isSourceRPM() or \
           archCompat(pkg["arch"], self.config.machine):
            return pkg
        self.config.printWarning(1, "%s: Package excluded because of arch incompatibility" % name)
        return None

    def __findPkgs(self, name):
        if name[0] != "/":
            return self.__findPkgsByName(name)
        else:
            return self.__findPkgsByDep(name, 0, "")

    def __findPkgsByName(self, name):
        pkglist = []
        for repo in self.repos:
            pkglist.extend(repo.searchPkgs([name,]))
        normalizeList(pkglist)
        return pkglist

    def __findPkgsByDep(self, dname, dflags, dversion):
        pkglist = []
        for repo in self.repos:
            pkglist.extend(repo.searchDependency(dname, dflags, dversion))
        return pkglist

    def __findPkgsByExactName(self, name):
        pkglist = []
        for repo in self.repos:
            pkglist.extend(repo.getPkgsByName(name))
        normalizeList(pkglist)
        return pkglist


    def __handleBestPkg(self, cmd, pkglist, arch=None, exactarch=False, is_filereq=0, do_obsolete=True):
        # Handle removes directly here, they don't need any special handling.
        if cmd.endswith("remove"):
            for upkg in pkglist:
                self.opresolver.erase(upkg)
            return 1
        # If no arch has been set use the one of our current machine
        if arch == None:
            arch = self.config.machine
        # Order the elements of the potential packages by machine
        # distance and evr
        orderList(pkglist, arch)
        # Prepare a pkg name hash for possibly newer packages that have "higher"
        # ranked packages via the comps with lower version in other repos.
        pkgnamehash = {}
        # Also have a hash for package names that have already been handled.
        donehash = {}
        ret = 0
        upkg = None
        for type in ["mandatory", "default", "optional", None]:
            for upkg in pkglist:
                # Skip package names that have already been handled.
                if donehash.has_key(upkg["name"]):
                    continue
                # Skip all packages that are either blocked via our erase_list
                # or that are already in the opresolver
                if upkg in self.erase_list or \
                   upkg in self.opresolver.getDatabase():
                    continue
                # If exactarch is set skip all packages that don't match
                # the arch exactly.
                if exactarch and upkg["arch"] != arch and \
                                 upkg["arch"] != "noarch":
                    continue
                # If no package with the same name has already been found enter
                # it in the pkgnamehash. That way pkgnamehash will always
                # contain the newest not-blocked available package for each
                # name.
                if not pkgnamehash.has_key(upkg["name"]):
                    pkgnamehash[upkg["name"]] = upkg
                # If the compstype doesn't fit, skip it for now.
                if upkg.compstype != type:
                    continue
                # Now we need to replace the fitting package with the newest
                # version available (which could be the same).
                upkg = pkgnamehash[upkg["name"]]
                # "fake" Source RPMS to be noarch rpms without any reqs/deps
                # etc. except if we want pyrpmyum to install the buildprereqs
                # from the srpm.
                if upkg.isSourceRPM():
                    upkg["arch"] = "noarch"
                    upkg["provides"] = []
                    upkg["conflicts"] = []
                    upkg["obsoletes"] = []
                # Only try to update if the package itself or the update package
                # are noarch or if they are buildarchtranslate or arch
                # compatible. Some exception needs to be done for
                # filerequirements.
                if not (is_filereq or \
                        archDuplicate(upkg["arch"], arch) or \
                        archCompat(upkg["arch"], arch) or \
                        archCompat(arch, upkg["arch"])):
                    continue
                # Depending on the command we gave to handle we need to either
                # install, update or remove the package now.
                if   cmd.endswith("install"):
                    r = self.opresolver.install(upkg)
                elif cmd.endswith("update") or cmd.endswith("upgrade"):
                    if upkg["name"] in self.always_install:
                        r = self.opresolver.install(upkg)
                    else:
                        r = self.opresolver.update(upkg)
                donehash[upkg["name"]] = 1
                # We just handled one package, make sure we handle it's
                # obsoletes and language related packages
                if upkg and r > 0:
                    l = []
                    for repo in self.repos:
                        if repo.comps:
                            for lang in self.langs:
                                l.extend(repo.comps.getLangOnlyPackageNames(lang, upkg["name"]))
                    normalizeList(l)
                    for name in l:
                        self.update(name)
                    if do_obsolete:
                        self.__handleObsoletes(upkg)
                ret |= r
        return ret

    def runArgs(self, args):
        """Find all packages that match the args and run the given command on
        them.

        Return 1 on success, 0 on error (after warning the user)."""

        if self.config.timer:
            time1 = clock()
        self.config.printInfo(1, "Selecting packages for operation\n")
        # We unfortunatly still need to special case the argless remove
        if len(args) == 0:
            if self.command == "update" or self.command == "upgrade":
                # For complete updates we need to do a full obsoletes run, not
                # on a specific package.
                self.__handleObsoletes()
                for name in self.opresolver.getDatabase().getNames():
                    self.update(name, exact=True, do_obsolete=False)
        # Select proper function to be called for every argument. We have
        # a fixed operation for runArgs(), so use a reference to the
        # corresponding function.
        func_hash = {"groupremove": self.groupRemove,
                    "groupinstall": self.groupInstall,
                    "groupupdate":  self.groupUpdate,
                    "groupupgrade": self.groupUpdate,
                    "remove":       self.remove,
                    "install":      self.install,
                    "update":       self.update,
                    "upgrade":      self.update}
        op_func = func_hash.get(self.command)
        if op_func == None:
            return 0
        # First pass through our args to find any directories and/or binary
        # rpms and create a memory repository from them to avoid special
        # cases.
        memory_repo = database.repodb.RpmRepoDB(self.config, [], self.config.buildroot, None, "pyrpmyum-memory-repo")
        new_args = []
        for name in args:
            if   os.path.isfile(name) and name.endswith(".rpm"):
                pkg = self.__readPackage(name)
                if pkg != None:
                    memory_repo.addPkg(pkg)
                    new_args.append(pkg.getNVRA())
            elif os.path.isdir(name):
                pkglist = []
                functions.readDir(name, pkglist)
                for pkg in pkglist:
                    memory_repo.addPkg(pkg)
                    new_args.append(pkg.getNVRA())
            else:
                new_args.append(name)
        # Append our new temporary repo to our internal repositories
        self.repos.append(memory_repo)
        args = new_args
        # Loop over all args and call the appropriate handler function for each
        for name in new_args:
            # We call our operation function which will handle all the
            # details for each specific case.
            op_func(name)
        if self.config.timer:
            self.config.printInfo(0, "runArgs() took %s seconds\n" % (clock() - time1))
        return 1

    def runDepRes(self):
        """Run the complete depresolution.

        Return 1."""
        # ... or 0 if __runDepResolution fails, which currently can't happen.
        ret = 1
        if self.config.timer:
            time1 = clock()
        if not self.config.nodeps:
            ret = self.__runDepResolution()
        if self.config.timer:
            self.config.printInfo(0, "runDepRes() took %s seconds\n" % (clock() - time1))
        return ret

    def runCommand(self):
        """Perform operations from self.opresolver.

        Return 1 on success, 0 on error (after warning the user)."""

        if self.config.timer:
            time1 = clock()
        if self.command.endswith("remove"):
            control = RpmController(self.config, OP_ERASE, self.pydb)
        else:
            control = RpmController(self.config, OP_UPDATE, self.pydb)
        ops = control.getOperations(self.opresolver)
        if ops is None:
            return 0
        if len(ops) == 0:
            self.config.printInfo(1, "Nothing to do.\n")
            return 1
        self.config.printInfo(1, "The following operations will now be run:\n")
        ipkgs = 0
        upkgs = 0
        epkgs = 0
        for (op, pkg) in ops:
            if   op == OP_INSTALL:
                ipkgs += 1
            elif op == OP_UPDATE:
                upkgs += 1
            elif op == OP_ERASE:
                epkgs += 1
            self.config.printInfo(1, "\t%s %s\n" % (op, pkg.getNEVRA()))

        self.erase_list = [pkg for pkg in self.erase_list
                           if pkg in self.pydb]

        if len(self.erase_list) > 0:
            self.config.printInfo(0, "Warning: Following packages will be automatically removed from your system:\n")
            for pkg in self.erase_list:
                self.config.printInfo(0, "\t%s\n" % pkg.getNEVRA())
        if self.confirm:
            self.config.printInfo(0, "Installing %d packages, updating %d packages, erasing %d packages\n" % (ipkgs, upkgs, epkgs))
        if self.confirm and not self.config.test:
            if not is_this_ok():
                return 1
        if self.config.timer:
            self.config.printInfo(0, "runCommand() took %s seconds\n" % (clock() - time1))
        if self.config.test:
            self.config.printInfo(0, "Test run stopped\n")
        else:
            if control.runOperations(ops) == 0:
                return 0
        self.pydb.close()
        return 1

    def __generateObsoletesList(self):
        """Generate a list of all installed/available RpmPackage's that
        obsolete something and store it in self.__obsoleteslist."""

        obsoletes = {}
        self.__obsoleteslist = [ ]
        for repo in self.repos:
            for entry in repo.iterObsoletes():
                 obsoletes[entry[-1]] = None
        self.__obsoleteslist = obsoletes.keys()
        orderList(self.__obsoleteslist, self.config.machine)
        nhash = { }
        nlist = [ ]
        for pkg in self.__obsoleteslist:
            if nhash.has_key(pkg["name"]):
                continue
            nlist.append(pkg)
            nhash[pkg["name"]] = 1
        self.__obsoleteslist = nlist

    def __runDepResolution(self):
        """Try to resolve all dependencies and remove all conflicts..

        Return 1 after reaching a steady state."""

        self.config.printInfo(1, "Resolving dependencies...\n")
        # List of filereqs we already checked
        self.filereqs = []
        self.iteration = 1

        # As long as either __handleUnresolvedDeps() or __handleConflicts()
        # changes something to the package set we need to continue the loop.
        # Afterwards there may still be unresolved deps or conflicts for which
        # we then have to check.
        nowork_count = 0
        while nowork_count < 3: # XXX Why not 2???
            if not self.__handleUnresolvedDeps():
                nowork_count += 1
            else:
                nowork_count = 0
            unresolved = None
            if not self.__handleConflicts():
                nowork_count += 1
            else:
                nowork_count = 0
        unresolved = self.opresolver.getUnresolvedDependencies()
        conflicts = self.opresolver.getConflicts()
        if len(unresolved) > 0:
            self.config.printError("Unresolvable dependencies:")
            for pkg in unresolved.keys():
                self.config.printError("Unresolved dependencies for %s" %
                                       pkg.getNEVRA())
                for dep in unresolved[pkg]:
                    self.config.printError("\t" + depString(dep))
        if len(conflicts) > 0:
            self.config.printError("Unresolvable conflicts:")
            for pkg in conflicts.keys():
                self.config.printError("Unresolved conflicts for %s" %
                                       pkg.getNEVRA())
                for (dep, r) in conflicts[pkg]:
                    self.config.printError("\t" + depString(dep))
        if len(unresolved) == 0 and len(conflicts) == 0:
            return 1
        return 0

    def __handleUnresolvedDeps(self):
        """Try to install/remove packages to reduce the number of unresolved
        dependencies.

        Return 1 if some package changes have been done, 0 otherwise."""

        # Otherwise get first unresolved dep and then try to solve it as long
        # as we have unresolved deps. If we fail to resolve a dep we try the
        # next one until only unresolvable deps remain.
        ret = 0
        unresolved = self.opresolver.iterUnresolvedDependencies()
        # Store our unresolvable deps in here.
        unresolvable = []
        while True:
            for pkg, dep in unresolved:
                # Have we already tried to resolve this dep? If yes, skip it
                if dep in unresolvable:
                    continue
                self.config.printInfo(2, "Dependency iteration %s\n" %
                                      str(self.iteration))
                self.iteration += 1
                self.config.printInfo(2, "Resolving dependency for %s\n" %
                                      pkg.getNEVRA())
                # If we were able to resolve this dep in any way we reget the
                # deps and do the next internal iteration
                if self.__resolveDep(pkg, dep):
                    ret = 1
                    unresolved = self.opresolver.iterUnresolvedDependencies()
                    break
                # Add this dep to the ones we can't resolve at the moment
                unresolvable.append(dep)
            else: # exit while loop if we got through the for loop
                break
        return ret

    def __resolveDep(self, pkg, dep):
        """Attempt to resolve (name, RPMSENSE_* flag, EVR string) dependency of
        RpmPackage pkg.

        Return 1 after doing something that might have improved the situation,
        0 otherwise."""

        # Remove is the easy case: Just remove all packages that have
        # unresolved deps ;)
        if self.command.endswith("remove"):
            self.opresolver.erase(pkg)
            return 1
        # We need to first check if we might need to load the complete filelist
        # in case of file requirements for every repo.
        # In order to do so efficently we remember which filerequirements we
        # already handled and only handle each one once.
        modified_repo = 0
        if dep[0][0] == "/" and not dep[0] in self.filereqs:
            self.filereqs.append(dep[0])
            for i in xrange(len(self.repos)):
                if self.repos[i].isFilelistImported():
                    continue
                if not self.repos[i]._matchesFile(dep[0]):
                    self.config.printWarning(1, "Importing filelist from repository %s for filereq %s" % (self.repos[i].reponame, dep[0]))
                    if self.config.timer:
                        time1 = clock()
                    self.repos[i].importFilelist()
                    self.repos[i].reloadDependencies()
                    if self.config.timer:
                        self.config.printInfo(1, "Importing filelist took %s seconds\n" % (clock() - time1))
                    modified_repo = 1
            if modified_repo:
                self.opresolver.getDatabase().reloadDependencies()
                if len(self.opresolver.getDatabase().searchDependency(dep[0], dep[1], dep[2])) > 0:
                    return 1
        # Now for all other cases we need to find packages in our repos
        # that resolve the given dependency
        pkg_list = [ ]
        self.config.printInfo(2, "\t" + depString(dep) + "\n")
        for repo in self.repos:
            for upkg in repo.searchDependency(dep[0], dep[1], dep[2]):
                if upkg in pkg_list:
                    continue
                pkg_list.append(upkg)
        # Now add the first package that ist not in our erase list or
        # already in our opresolver to it and check afterwards if
        # there are any obsoletes for that package and handle them
        # Order the elements of the potential packages by machine
        # distance and evr.
        # Special handling of filerequirements need to be done here in order to
        # allow cross buildarchtranslate compatible package updates.
        ret = self.__handleBestPkg("update", pkg_list, None, False, dep[0][0] == "/")
        if ret > 0:
            return 1
        # Ok, we didn't find any package that could fullfill the
        # missing deps. Now what we do is we look for updates of that
        # package in all repos and try to update it.
        ret = self.update(pkg["name"])
        if ret > 0:
            return 1
        # OK, left over unresolved deps, but now we already have the
        # filelists from the repositories. We can now either:
        #   - Scrap it as we can't update the system without unresolved deps
        #   - Erase the packages that had unresolved deps (autoerase option)
        if self.autoerase:
            self.config.printWarning(1, "Autoerasing package %s due to unresolved symbols." % pkg.getNEVRA())
            if not self.__doAutoerase(pkg):
                return 0
            return 1
        return 0

    def __handleConflicts(self):
        """Try to update packages to fix conflicts in self.opresolver.

        Return 1 if all conflicts have been resolved or no more conflicts are
        there, otherwise return 0."""

        conflicts = self.opresolver.getConflicts()
        handled_conflict = 1
        ret = 0
        while len(conflicts) > 0 and handled_conflict:
            handled_conflict = 0
            for pkg1 in conflicts:
                for (c, pkg2) in conflicts[pkg1]:
                    if   c[1] & RPMSENSE_LESS != 0:
                        if self.update(pkg2["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    elif c[1] & RPMSENSE_GREATER != 0:
                        if self.update(pkg1["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    else:
                        if   self.update(pkg1["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                        elif self.update(pkg2["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                if handled_conflict:
                    break
            conflicts = self.opresolver.getConflicts()
        handled_fileconflict = 1
        if not self.config.nofileconflicts:
            conflicts = self.opresolver.getFileConflicts()
            while len(conflicts) > 0 and handled_fileconflict:
                handled_fileconflict = 0
                for pkg1 in conflicts:
                    for (c, pkg2) in conflicts[pkg1]:
                        if self.update(pkg2["name"]) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                        elif self.update(pkg1["name"]) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                    if handled_fileconflict:
                        break
                conflicts = self.opresolver.getFileConflicts()
        if not (handled_conflict and handled_fileconflict) and self.autoerase:
            return self.__handleConflictAutoerases()
        return ret

    def __handleObsoletes(self, pkg=None):
        """Try to replace RpmPackage pkg in self.opresolver by a package
        obsoleting it, iterate until no obsoletes: applies.

        Return 1 if pkg was obsoleted, 0 if not."""

        obsoleted = 0
        pkglist = []        # List of packages we have used for obsoleting,
                            # needed for endless loop detection and prevention.
        # Loop until we have found the end of the obsolete chain
        while 1:
            found = 0
            # Go over all packages we know have obsoletes
            for opkg in self.__obsoleteslist:
                # If the package has already been tried once or is in our
                # erase_list skip it.
                if opkg in pkglist or opkg in self.erase_list:
                    continue
                # Never add obsolete packages for packages with the same name.
                if pkg != None and pkg["name"] == opkg["name"]:
                    continue
                # Go through all obsoletes
                for u in opkg["obsoletes"]:
                    # Look in our current database for matches
                    s = self.opresolver.getDatabase().searchDependency(u[0], u[1], u[2])
                    # If the package for which we're checking the obsoletes
                    # right now isn't in the list skip it.
                    if not pkg in s:
                        continue
                    # Found a matching obsoleting package. Try adding it to
                    # our opresolver with an update so it obsoletes the
                    # installed package
                    ret = self.opresolver.update(opkg)
                    # If it has already been added before readd it by erasing
                    # it and adding it again. This will ensure that the
                    # obsoleting will occur.
                    if ret == self.opresolver.ALREADY_ADDED:
                        self.opresolver.erase(opkg)
                        ret = self.opresolver.update(opkg)
                    # If everything went well note this and terminate the
                    # inner obsoletes loop
                    if ret > 0:
                        obsoleted = 1
                        found = 1
                        break
                # If we found and handled one obsolete proplerly break the
                # loop over the obsoletes packages and restart
                if found:
                    break
            # In case we found an obsolete in the last round replace the package
            # we're trying to obsolete with the one we just added and make
            # another run. Otherwise we're finished and can return.
            if found:
                pkg = opkg
                pkglist.append(pkg)
            else:
                break
        # Return wether we obsoleted any package this time or not.
        return obsoleted

    def __doAutoerase(self, pkg):
        """Try to remove RpmPackage pkg from self.opresolver to resolve a
        dependency.

        Return 1 on success, 0 on error (after warning the user)."""

        for reex in self.autoeraseexclude:
            if reex.match(pkg["name"]) and \
             len(self.opresolver.getDatabase().getPkgsByName(pkg["name"])) == 1:
                self.erase_list.append(pkg)
                self.config.printWarning(1, "No autoerase of package %s due to exclude list." % pkg.getNEVRA())
                return 0
        if self.opresolver.updates.has_key(pkg):
            updates = self.opresolver.updates[pkg]
        else:
            updates = [ ]
        ret = self.opresolver.erase(pkg)
        if ret > 0:
            self.erase_list.append(pkg)
            for upkg in updates:
                if upkg in self.erase_list:
                    continue
                self.opresolver.update(upkg)
        else:
            return 0
        return 1

    def __handleConflictAutoerases(self):
        """Erase packages from self.opresolver to get rid of all conflicts.

        Return 1 if at least one package was successfuly chosen for erasing."""

        ret = 0
        # The loops will finish because __doConflictAutoerase() always removes
        # at least one of the conflicting packages for each conflict.
        conflicts = self.opresolver.getConflicts()
        while len(conflicts) > 0:
            pkg1 = conflicts.keys()[0]
            (c, pkg2) = conflicts[pkg1][0]
            if self.__doConflictAutoerase(pkg1, pkg2):
                ret = 1
            conflicts = self.opresolver.getConflicts()
        if not self.config.nofileconflicts:
            conflicts = self.opresolver.getFileConflicts()
            while len(conflicts) > 0:
                pkg1 = conflicts.keys()[0]
                (c, pkg2) = conflicts[pkg1][0]
                if self.__doConflictAutoerase(pkg1, pkg2):
                    ret = 1
                conflicts = self.opresolver.getFileConflicts()
        return ret

    def __doConflictAutoerase(self, pkg1, pkg2):
        """Resolve one single conflict by semi intelligently selecting one of
        the two packages to be autoereased.

        Return 1 if one package was successfully removed, 0 otherwise."""

        ret = 0
        self.config.printInfo(1, "Resolving conflicts for %s:%s\n" % (pkg1.getNEVRA(), pkg2.getNEVRA()))
        if   pkg1 in self.erase_list:
            pkg = pkg2
        elif pkg2 in self.erase_list:
            pkg = pkg1
        elif pkg1 in self.pydb and \
             not pkg1 in self.erase_list:
            pkg = pkg1
        elif pkg2 in self.pydb and \
             not pkg2 in self.erase_list:
            pkg = pkg2
        elif machineDistance(pkg2["arch"], self.config.machine) < \
             machineDistance(pkg1["arch"], self.config.machine):
            pkg = pkg1
        elif machineDistance(pkg2["arch"], self.config.machine) > \
             machineDistance(pkg1["arch"], self.config.machine):
            pkg = pkg2
        elif pkg1.has_key("sourcerpm") and \
             pkg2.has_key("sourcerpm") and \
             envraSplit(pkg1["sourcerpm"])[1] == envraSplit(pkg2["sourcerpm"])[1]:
            (e1, n1, v1, r1, a1) = envraSplit(pkg1["sourcerpm"])
            (e2, n2, v2, r2, a2) = envraSplit(pkg2["sourcerpm"])
            cmp = labelCompare((e1, v1, r1), (e2, v2, r2))
            if   cmp < 0:
                pkg = pkg1
            elif cmp > 0:
                pkg = pkg2
            else:
                if len(pkg1.getNEVRA()) < len(pkg2.getNEVRA()):
                    pkg = pkg2
                else:
                    pkg = pkg1
        elif len(pkg1.getNEVRA()) < len(pkg2.getNEVRA()):
            pkg = pkg2
        else:
            pkg = pkg1
        # Returns 0 if pkg was already erased - but warns the user
        if self.__doAutoerase(pkg):
            self.config.printInfo(1, "Autoerasing package %s due to conflicts\n" % pkg.getNEVRA())
            ret = 1
        return ret

# vim:ts=4:sw=4:showmatch:expandtab
