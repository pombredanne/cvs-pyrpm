#!/usr/bin/python
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


from gc import collect
from time import clock, time
from hashlist import HashList
from resolver import RpmResolver
from control import RpmController
from package import RpmPackage
from functions import *
from io import *


class RpmYum:
    def __init__(self, config):
        self.config = config
        # Default: Don't autoerase packages that have unresolved symbols in
        # install or update
        self.autoerase = 0
        # Default: Ask user for confirmation of complete operation
        self.confirm = 1
        # Default: No command
        self.command = None
        # List of packages to be installed/updated/removed
        self.pkgs = []
        # List of RpmRepo's
        self.repos = [ ]
        # List of repository resolvers
        self.resolvers = [ ]
        # Internal list of packages that are have to be erased
        self.erase_list = []
        # Our database
        self.pydb = None
        # Our list of package names that get installed instead of updated
        self.always_install = ["kernel", "kernel-smp", "kernel-bigmem",
            "kernel-enterprise", "kernel-debug", "kernel-unsupported"]
        # List of vaild commands
        self.command_list = ["install", "update", "upgrade", "remove", \
                             "groupinstall", "groupupdate", "groupupgrade", \
                             "groupremove"]

    def setAutoerase(self, flag):
        """Enable or disable erasing packages with unresolved dependencies
        according to flag."""

        self.autoerase = flag

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
        if self.command == "upgrade" or self.command == "groupupgrade":
            self.always_install = [ ]
        return 1

    def addRepo(self, file):
        """Read yum configuration file and add repositories it uses.

        sys.exit() on error."""

        try:
            conf = yumconfig.YumConf(self.config.relver, self.config.machine,
                                     buildarchtranslate[self.config.machine],
                                     self.config.buildroot, file, "")
        except IOError, e:
            printError("Error reading configuration: %s" % e)
            sys.exit(1)
        for key in conf.keys():
            if key == "main":
                pass
            else:
                sec = conf[key]
                if not sec.has_key("baseurl"):
                    printError("%s: No baseurl for this section in conf file." % key)
                    sys.exit(1)
                baseurl = sec["baseurl"][0]
                if not sec.has_key("exclude"):
                    excludes = ""
                else:
                    excludes = sec["exclude"]
                if self.__addSingleRepo(baseurl, excludes, key) == 0:
                    sys.exit(1)
                if self.config.compsfile == None:
                    # May stay None on download error
                    self.config.compsfile = cacheLocal(baseurl + \
                                            "/repodata/comps.xml", key)

    def __addSingleRepo(self, baseurl, excludes, reponame):
        """Add a repository at baseurl as reponame.

        Return 1 on success 0 on errror (after warning the user).  Exclude
        packages matching whitespace-separated excludes."""

        repo = RpmRepo(self.config, baseurl, self.config.buildroot, excludes,
                       reponame)
        if repo.read() == 0:
            self.config.printError("Error reading the repository at %s"
                                   % baseurl)
            return 0
        self.repos.append(repo)
        r = RpmResolver(self.config, repo.getPkgList())
        self.resolvers.append(r)
        return 1

    def processArgs(self, args):
        """Open the RPM database and process args.

        Return 1 in success, 0 on error (after warning the user)."""

        self.erase_list = []
        # Create and read db
        self.pydb = getRpmDBFactory(self.config, self.config.dbpath,
                                    self.config.buildroot)
        self.pydb.open()
        if not self.pydb.read():
            self.config.printError("Error reading the RPM database")
            return 0
        for pkg in self.pydb.getPkgList():
            if "redhat-release" in [ dep[0] for dep in pkg["provides"] ]:
                rpmconfig.relver = pkg["version"]
        if os.path.isfile(self.config.yumconf):
            self.addRepo(self.config.yumconf)
        else:
            printWarning(1, "Couldn't find given yum config file, skipping read of repos")
        self.opresolver = RpmResolver(self.config, self.pydb.getPkgList())
        return self.runArgs(args)

    def runArgs(self, args):
        """Set self.pkgs to RpmPackage's to work with, based on args.

        Return 1 on success, 0 on error (after warning the user).  Self.pkgs
        may contain several matches for a single package; in that case, the
        best matches are first."""

        if self.config.timer:
            time1 = clock()
        self.__generateObsoletesList()
        # If we do a group operation handle it accordingly
        if self.command.startswith("group"):
            if self.config.compsfile == None:
                self.config.printError("You need to specify a comps.xml file for group operations")
                return 0
            comps = RpmCompsXML(self.config, self.config.compsfile)
            comps.read() # Ignore errors
            pkgs = []
            for grp in args:
                pkgs.extend(comps.getPackageNames(grp))
            args = pkgs
            del comps
        else:
            if len(args) == 0:
                for pkg in self.pydb.getPkgList():
                    if not self.__handleObsoletes(pkg):
                        args.append(pkg["name"])
        # Look for packages we need/want to install. Arguments can either be
        # direct filenames or package nevra's with * wildcards
        repolists = []
        for repo in self.resolvers:
            repolists.append(repo.getList())
        for f in args:
            if os.path.isfile(f) and f.endswith(".rpm"):
                try:
                    pkg = readRpmPackage(self.config, f, db=self.pydb,
                                         tags=self.config.resolvertags)
                except (IOError, ValueError), e:
                    self.config.printError("%s: %s" % (f, e))
                    return 0
                if self.config.ignorearch or \
                   pkg.isSourceRPM() or \
                   archCompat(pkg["arch"], self.config.machine):
                    self.pkgs.append(pkg)
                else:
                    self.config.printWarning(1, "%s: Incompatible architecture"
                                             % f)
            elif os.path.isdir(f):
                for g in os.listdir(f):
                    fn = os.path.join(f, g)
                    if not g.endswith(".rpm") or not os.path.isfile(fn):
                        continue
                    try:
                        pkg = readRpmPackage(self.config, fn, db=self.pydb,
                                             tags=self.config.resolvertags)
                    except (IOError, ValueError), e:
                        self.config.printError("%s: %s" % (fn, e))
                        return 0
                    if self.config.ignorearch or \
                       pkg.isSourceRPM() or \
                       archCompat(pkg["arch"], self.config.machine):
                        self.pkgs.append(pkg)
            else:
                if self.command.endswith("remove"):
                    self.pkgs.extend(findPkgByNames([f,], self.pydb.getPkgList()))
                else:
                    for rlist in repolists:
                        self.pkgs.extend(findPkgByNames([f,], rlist))
                    if len(self.pkgs) == 0:
                        self.config.printError("Couldn't find package %s, skipping" % f)
        if self.config.timer:
            self.config.printInfo(0, "runArgs() took %s seconds\n" % (clock() - time1))
        return 1

    def runDepRes(self):
        """Set up self.opresolver from self.pkgs.

        Return 1."""
        # ... or 0 if __runDepResolution fails, which currently can't happen.

        if self.config.timer:
            time1 = clock()
        # "fake" Source RPMS to be noarch rpms without any reqs/deps etc.
        for pkg in self.pkgs:
            if pkg.isSourceRPM():
                pkg["arch"] = "noarch"
                pkg["requires"] = []
                pkg["provides"] = []
                pkg["conflicts"] = []
                pkg["obsoletes"] = []
        # Filter newest packages
        self.pkgs = selectNewestPkgs(self.pkgs)
        # Add packages to be processed to our operation resolver
        for pkg in self.pkgs:
            self.__appendPkg(pkg)
            if  self.command.endswith("update") or \
                self.command.endswith("upgrade") :
                self.__handleObsoletes(pkg)
        self.pkgs = []
        ret = 1
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
            self.config.printInfo(0, "Nothing to do.\n")
            return 1
        self.config.printInfo(1, "The following operations will now be run:\n")
        for (op, pkg) in ops:
            self.config.printInfo(1, "\t%s %s\n" % (op, pkg.getNEVRA()))
        i = 0
        while i < len(self.erase_list):
            if self.erase_list[i] not in self.pydb.getPkgList():
                self.erase_list.pop(i)
            else:
                i += 1
        if len(self.erase_list) > 0:
            self.config.printInfo(0, "Warning: Following packages will be automatically removed from your system:\n")
            for pkg in self.erase_list:
                self.config.printInfo(0, "\t%s\n" % pkg.getNEVRA())
        if self.confirm:
            choice = raw_input("Is this ok [y/N]: ")
            if len(choice) == 0 or (choice[0] != "y" and choice[0] != "Y"):
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

        self.__obsoleteslist = []
        for repo in self.resolvers:
            for pkg in repo.getList():
                if pkg.has_key("obsoletes"):
                    self.__obsoleteslist.append(pkg)

    def __appendPkg(self, pkg):
        """Add RpmPackage pkg to self.opresolver, depending on self.command.

        Return an RpmList error code (after warning the user)."""

        if   self.command.endswith("install"):
            return self.opresolver.install(pkg)
        elif self.command.endswith("update"):
            if pkg["name"] in self.always_install:
                return self.opresolver.install(pkg)
            else:
                return self.opresolver.update(pkg)
        elif self.command.endswith("upgrade"):
            return self.opresolver.update(pkg)
        elif self.command.endswith("remove"):
            return self.opresolver.erase(pkg)
        else:
            raise AssertionError, "Invalid command"

    def __runDepResolution(self):
        """Try to resolve all dependencies and remove all conflicts..

        Return 1 after reaching a steady state."""

        self.iteration = 1
        # Mark if we might need to reread the repositories
        if self.config.nofileconflicts:
            self.reread = 0
        else:
            self.reread = 1
        # As long as we have unresolved dependencies and need to handle some
        # conflicts continue this loop
        count = 0
        while count < 3:
            ret1 = self.__handleUnresolvedDeps()
            if ret1:
                count = 0
                continue
            ret2 = self.__handleConflicts()
            if ret2:
                count = 0
                continue
            count += 1
        if not ret1 and not ret2: # FIXME: this is always true
            return 1
        unresolved = self.opresolver.getUnresolvedDependencies()
        self.config.printInfo("Couldn't resolve all dependencies.\n")
        for pkg in unresolved.keys():
            self.config.printInfo(1, "Unresolved dependencies for %s\n" %
                                     pkg.getNEVRA())
            for dep in unresolved[pkg]:
                self.config.printInfo(1, "\t" + depString(dep)+"\n")
        return 0

    def __handleUnresolvedDeps(self):
        """Try to install/remove packages to reduce the number of unresolved
        dependencies.

        Return 1 if there were unresolved dependencies and all were resolved, 0
        otherwise (even if there are no unresolved dependencies)."""

        unresolved = self.opresolver.getUnresolvedDependencies()
        # Check special case first: If we don't do any work here anymore
        # return 0
        if len(unresolved) == 0:
            return 0
        # Otherwise get first unresolved dep and then try to solve it as long
        # as we have unresolved deps. If we fail to resolve a dep we try the
        # next one until only unresolvable deps remain.
        ppos = 0
        dpos = 0
        while len(unresolved) > 0:
            pkg = unresolved.keys()[ppos]
            dep = unresolved[pkg][dpos]
            self.config.printInfo(1, "Dependency iteration %s\n" %
                                     str(self.iteration))
            self.iteration += 1
            self.config.printInfo(1, "Resolving dependency for %s\n" %
                                     pkg.getNEVRA())
            # If we were able to resolve this dep in any way we reget the
            # deps and do the next internal iteration
            if self.__resolveDep(pkg, dep):
                unresolved = self.opresolver.getUnresolvedDependencies()
                ppos = 0
                dpos = 0
                continue
            # Try to find next unresolved dep
            dpos += 1
            if dpos >= len(unresolved[pkg]):
                dpos = 0
                ppos += 1
                # End of story: There are no more resolvable unresolved deps,
                # so we end here.
                if ppos >= len(unresolved.keys()):
                    return 0
        return 1

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
        # For all other cases we need to find packages in our repos
        # that resolve the given dependency
        pkg_list = [ ]
        self.config.printInfo(2, "\t" + depString(dep) + "\n")
        for repo in self.resolvers:
            for upkg in repo.searchDependency(dep):
                if upkg in pkg_list:
                    continue
                pkg_list.append(upkg)
        # Now add the first package that ist not in our erase list or
        # already in our opresolver to it and check afterwards if
        # there are any obsoletes for that package and handle them
        # Order the elements of the potential packages by machine
        # distance and evr
        ret = self.__handleUpdatePkglist(pkg, pkg_list)
        if ret > 0 :
            return 1
        # Ok, we didn't find any package that could fullfill the
        # missing deps. Now what we do is we look for updates of that
        # package in all repos and try to update it.
        ret = self.__findUpdatePkg(pkg)
        if ret > 0 :
            return 1
        # We had left over unresolved deps. If we didn't load the filelists
        # from the repositories we do so now and try to do more resolving
        if self.reread == 0:
            self.config.printWarning(1, "Importing filelist from repositories due to unresolved dependencies")
            self.resolvers = []
            for repo in self.repos:
                repo.importFilelist() # Ignore errors
                r = RpmResolver(self.config, repo.getPkgList())
                self.resolvers.append(r)
            self.reread = 1
            self.opresolver.reloadDependencies()
            return 1
        # OK, left over unresolved deps, but now we already have the
        # filelists from the repositories. We can now either:
        #   - Scrap it as we can't update the system without unresolved deps
        #   - Erase the packages that had unresolved deps (autoerase option)
        if self.autoerase:
            self.config.printWarning(1, "Autoerasing package %s due to unresolved symbols." % pkg.getNEVRA())
            self.__doAutoerase(pkg)
            return 1
        return 0

    def __handleConflicts(self):
        """Try to update packages to fix conflicts in self.opresolver.

        Return 1 after doing something to (hopefully) improve the situation, 0
        otherwise (even if there are no conflicts)."""

        ret = 0
        handled_conflict = 1
        conflicts = self.opresolver.getConflicts()
        while len(conflicts) > 0 and handled_conflict:
            handled_conflict = 0
            for pkg1 in conflicts:
                for (c, pkg2) in conflicts[pkg1]:
                    if   c[1] & RPMSENSE_LESS != 0:
                        if self.__findUpdatePkg(pkg2) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    elif c[1] & RPMSENSE_GREATER != 0:
                        if self.__findUpdatePkg(pkg1) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    else:
                        if   self.__findUpdatePkg(pkg1) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                        elif self.__findUpdatePkg(pkg2) > 0:
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
                        if self.__findUpdatePkg(pkg2) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                        elif self.__findUpdatePkg(pkg1) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                    if handled_fileconflict:
                        break
                conflicts = self.opresolver.getFileConflicts()
        if not (handled_conflict and handled_fileconflict) and self.autoerase:
            ret = self.__handleConflictAutoerases()
        return ret

    def __handleObsoletes(self, pkg):
        """Try to replace RpmPackage pkg in self.opresolver by a package
        obsoleting it, iterate until no obsoletes: applies.

        Return 1 if pkg was obsoleted, 0 if not."""

        # FIXME: will this loop forever on obsoletes: cycle?
        obsoleted = 0
        while 1:
            found = 0
            for opkg in self.__obsoleteslist:
                if opkg in self.opresolver or opkg in self.erase_list:
                    continue
                if pkg["name"] == opkg["name"]:
                    continue
                for u in opkg["obsoletes"]:
                    s = self.opresolver.searchDependency(u)
                    if not pkg in s:
                            continue
                    if self.opresolver.update(opkg) > 0:
                        obsoleted = 1
                        found = 1
                        break
                if found:
                    break
            if found:
                pkg = opkg
            else:
                break
        return obsoleted

    def __findUpdatePkg(self, pkg):
        """Get packages matching %name of RpmPackae pkg and choose the best one
        and add it to self.opresolver.

        Return 0 if no suitable package found, RpmList error code otherwise
        (after warning the user)."""

        pkg_list = []
        for repo in self.resolvers:
            # FIXME: Should that be
            # pkg_list.extend([p for p in repo.getList()
            #                 if p["name"] == pkg["name"]])
            # ? The current one can match packages with a different %name
            # if %name contains [-.]
            pkg_list.extend(findPkgByNames([pkg["name"],], repo.getList()))
        return self.__handleUpdatePkglist(pkg, pkg_list)

    def __handleUpdatePkglist(self, pkg, pkg_list):
        """Choose a package from a list of RpmPackage's pkg_list that has the
        same base arch as RpmPackage pkg, and add it to self.opresolver.

        Return 0 if no suitable package found, RpmList error code otherwise
        (after warning the user)."""

        # Order the elements of the potential packages by machine
        # distance and evr
        orderList(pkg_list, self.config.machine)
        ret = 0
        for upkg in pkg_list:
            if upkg in self.erase_list or upkg in self.opresolver:
                continue
            # Only try to update if the package itself or the update package
            # are noarch or if they are buildarchtranslate compatible
            if not (upkg["arch"] == "noarch" or \
                    pkg["arch"] == "noarch" or \
                    buildarchtranslate[upkg["arch"]] == buildarchtranslate[pkg["arch"]]):
                continue
            ret = self.opresolver.update(upkg)
            if ret > 0:
                self.__handleObsoletes(upkg)
                break
        return ret

    def __doAutoerase(self, pkg):
        """Try to remove RpmPackage pkg from self.opresolver to resolve a
        dependency.

        Return 1 on success, 0 on error (after warning the user)."""

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
            if self.__doConflictAutoerase(conflicts):
                ret = 1
            conflicts = self.opresolver.getConflicts()
        if not self.config.nofileconflicts:
            conflicts = self.opresolver.getFileConflicts()
            while len(conflicts) > 0:
                if self.__doConflictAutoerase(conflicts):
                    ret = 1
                conflicts = self.opresolver.getFileConflicts()
        return ret

    def __doConflictAutoerase(self, conflicts):
        """For each conflict in conflicts, try to erase one of the packages.

        Return 1 if at least one package was succesfuly chosen for erasing, 0
        otherwise.  conflicts is a HashList: RpmPackage => [(something,
        conflicting RpmPackage)]."""

        ret = 0
        for pkg1 in conflicts.keys():
            for (c, pkg2) in conflicts[pkg1]:
                self.config.printInfo(1, "Resolving conflicts for %s:%s\n" % (pkg1.getNEVRA(), pkg2.getNEVRA()))
                # FIXME?
                # if pkg1 in self.erase_list or pkg2 in self.erase_list:
                #     continue
                if   self.pydb.isInstalled(pkg1) and \
                     not pkg1 in self.erase_list:
                    pkg = pkg1
                elif self.pydb.isInstalled(pkg2) and \
                     not pkg2 in self.erase_list:
                    pkg = pkg2
                elif machineDistance(pkg2["arch"], self.config.machine) < \
                     machineDistance(pkg1["arch"], self.config.machine):
                    pkg = pkg1
                # FIXME: elif ... > ...: pkg = pkg2 ?
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
                    ret = 1
        return ret

# vim:ts=4:sw=4:showmatch:expandtab
