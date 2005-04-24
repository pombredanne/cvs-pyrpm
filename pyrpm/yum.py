#!/usr/bin/python
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
# Copyright 2004, 2005 Red Hat, Inc.
#
# Author: Phil Knirsch
#


from time import clock
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
        # List of repositories
        self.repos = [ ]
        # List of repository resolvers
        self.resolvers = [ ]
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
        self.autoerase = flag

    def setConfirm(self, flag):
        self.confirm = flag

    def setCommand(self, command):
        self.command = command.lower()
        if self.command not in self.command_list:
            self.config.printError("Invalid command")
            sys.exit(1)
        if self.command == "upgrade" or self.command == "groupupgrade":
            self.always_install = [ ]

    def addRepo(self, baseurl, excludes):
        repo = RpmRepo(self.config, baseurl, self.config.buildroot, excludes)
        repo.read()
        self.repos.append(repo)
        r = RpmResolver(self.config, repo.getPkgList())
        self.resolvers.append(r)

    def processArgs(self, args):
        if self.config.timer:
            time1 = clock()
        # Create and read db
        self.pydb = RpmPyDB(self.config, self.config.dbpath,
                            self.config.buildroot)
        self.pydb.read()
        self.__generateObsoletesList()
        self.opresolver = RpmResolver(self.config, self.pydb.getPkgList())
        # If we do a group operation handle it accordingly
        if self.command.startswith("group"):
            if self.config.compsfile == None:
                self.config.printError("You need to specify a comps.xml file for group operations")
                sys.exit(1)
            comps = RpmCompsXML(self.config, self.config.compsfile)
            comps.read()
            pkgs = []
            for grp in args:
                pkgs.extend(comps.getPackageNames(grp))
            args = pkgs
            del comps
        else:
            if len(args) == 0:
                for pkg in self.pydb.getPkgList():
                    args.append(pkg["name"])
                for pkg in self.__obsoleteslist:
                    for u in pkg["obsoletes"]:
                        s = self.opresolver.searchDependency(u)
                        if len(s) > 0:
                            if not pkg in self.opresolver:
                                self.opresolver.update(pkg)
                            for ipkg in s:
                                try:
                                    args.remove(ipkg["name"])
                                except:
                                    pass
        # Look for packages we need/want to install. Arguments can either be
        # direct filenames or package nevra's with * wildcards
        self.pkgs = []
        repolists = []
        for repo in self.resolvers:
            repolists.append(repo.getList())
        for f in args:
            if os.path.isfile(f) and f.endswith(".rpm"):
                pkg = readRpmPackage(self.config, f, db=self.pydb,
                                     tags=self.config.resolvertags)
                if self.config.ignorearch or \
                   archCompat(pkg["arch"], self.config.machine):
                    self.pkgs.append(pkg)
            elif os.path.isdir(f):
                for g in os.listdir(f):
                    fn = "%s/%s" % (f, g)
                    if not g.endswith(".rpm") or not os.path.isfile(fn):
                        continue
                    pkg = readRpmPackage(self.config, fn, db=self.pydb,
                                         tags=self.config.resolvertags)
                    if self.config.ignorearch or \
                       archCompat(pkg["arch"], self.config.machine):
                        self.pkgs.append(pkg)
            else:
                if self.command.endswith("remove"):
                    self.pkgs.extend(findPkgByName(f, self.pydb.getPkgList()))
                else:
                    for rlist in repolists:
                        self.pkgs.extend(findPkgByName(f, rlist))
                    if len(self.pkgs) == 0:
                        self.config.printError("Couldn't find package %s, skipping" % f)
        if self.config.timer:
            self.config.printInfo(0, "processArgs() took %s seconds\n" % (clock() - time1))

    def runDepRes(self):
        if self.config.timer:
            time1 = clock()
        # Add packages to be updated  to our operation resolver
        self.pkgs = self.__selectNewestPkgs(self.pkgs)
        for pkg in self.pkgs:
            self.__appendPkg(pkg)
            if  self.command.endswith("update") or \
                self.command.endswith("upgrade") :
                self.__handleObsoletes(pkg)
        del self.pkgs
        self.pkgs = []
        self.__runDepResolution()
        if self.config.timer:
            self.config.printInfo(0, "runDepRes() took %s seconds\n" % (clock() - time1))

    def runCommand(self):
        if self.config.timer:
            time1 = clock()
        for repo in self.resolvers:
            del repo
        self.resolvers = []
        if self.command.endswith("remove"):
            control = RpmController(self.config, OP_ERASE, self.pydb)
        else:
            control = RpmController(self.config, OP_UPDATE, self.pydb)
        ops = control.getOperations(self.opresolver)
        if len(ops) == 0:
            self.config.printInfo(0, "Nothing to do.\n")
            sys.exit(0)
        self.config.printInfo(0, "The following operations will now be run:\n")
        for (op, pkg) in ops:
            self.config.printInfo(0, "\t%s %s\n" % (op, pkg.getNEVRA()))
        if len(self.erase_list) > 0:
            self.config.printInfo(0, "Warning: Following packages will be automatically removed from your system:\n")
            for pkg in self.erase_list:
                self.config.printInfo(0, "\t%s\n" % pkg.getNEVRA())
        if self.confirm:
            choice = raw_input("Is this ok [y/N]: ")
            if len(choice) == 0:
                sys.exit(0)
            else:
                if choice[0] != "y" and choice[0] != "Y":
                    sys.exit(0)
        if self.config.timer:
            self.config.printInfo(0, "runCommand() took %s seconds\n" % (clock() - time1))
        control.runOperations(ops)

    def __generateObsoletesList(self):
        self.__obsoleteslist = []
        for repo in self.resolvers:
            for pkg in repo.getList():
                if pkg.has_key("obsoletes"):
                    self.__obsoleteslist.append(pkg)

    def __selectNewestPkgs(self, pkglist):
        rethash = {}
        for pkg in pkglist:
            if not rethash.has_key(pkg["name"]):
                rethash[pkg["name"]] = pkg
            else:
                if pkgCompare(rethash[pkg["name"]], pkg) <= 0:
                    rethash[pkg["name"]] = pkg
        return rethash.values()

    def __appendPkg(self, pkg):
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
        # Special erase list for unresolvable package dependancies or conflicts
        self.erase_list = []
        unresolved = self.opresolver.getUnresolvedDependencies()
        iteration = 1
        # Mark if we might need to reread the repositories
        if self.config.nofileconflicts:
            reread = 0
        else:
            reread = 1
        while len(unresolved) > 0:
            self.config.printInfo(1, "Dependency iteration " + str(iteration) + "\n")
            iteration += 1
            unresolved_deps = 1
            for pkg in unresolved.keys():
                self.config.printInfo(1, "Resolving dependencies for %s\n" % pkg.getNEVRA())
                # Remove is the easy case: Just remove all packages that have
                # unresolved deps ;)
                if self.command.endswith("remove"):
                    unresolved_deps = 0
                    self.opresolver.erase(pkg)
                    continue
                # For all other cases we need to find packages in our repos
                # that resolve the given dependency
                found = 0
                pkg_list = HashList()
                for dep in unresolved[pkg]:
                    self.config.printInfo(2, "\t" + depString(dep) + "\n")
                    for repo in self.resolvers:
                        for upkg in repo.searchDependency(dep):
                            if upkg in pkg_list:
                                continue
                            pkg_list[upkg] = 1
                # Now add all packages that are not in our erase list or
                # already in our opresolver to it and check if afterwards
                # if there are any obsoletes for that package and handle them
                for upkg in pkg_list:
                    if upkg in self.erase_list:
                        continue
                    if not upkg in self.opresolver:
                        ret = self.opresolver.update(upkg)
                        if ret > 0 or ret == RpmResolver.ALREADY_ADDED:
                            found = 1
                            unresolved_deps = 0
                        self.__handleObsoletes(upkg)
                    else:
                        found = 1
                        unresolved_deps = 0
                # Ok, we didn't find any package that could fullfill the
                # missing deps. Now what we do is we look for updates of that
                # package in all repos and try to update it.
                if found == 0:
                    tmplist = []
                    for repo in self.resolvers:
                        tmplist.extend(findPkgByName(pkg["name"], repo.getList()))
                    for upkg in tmplist:
                        if upkg in self.erase_list or upkg in self.opresolver:
                            continue
                        ret = self.opresolver.update(upkg)
                        if ret > 0:
                            found = 1
                            unresolved_deps = 0
                        self.__handleObsoletes(upkg)
#                    if found == 0:
#                        if self.autoerase:
#                            self.config.printWarning(1, "Autoerasing package %s due to missing update package." % pkg.getNEVRA())
#                            self.__doAutoerase(pkg)
#                        else:
#                            self.config.printWarning(0, "Couldn't find update for package %s" \
#                                % pkg.getNEVRA())
#                            sys.exit(1)
            if reread == 0 and unresolved_deps:
                self.config.printWarning(0, "Importing filelist from repositories due to unresolved dependencies")
                self.resolvers = []
                for repo in self.repos:
                    repo.importFilelist()
                    r = RpmResolver(self.config, repo.getPkgList())
                    self.resolvers.append(r)
                reread = 1
                self.opresolver.reloadDependencies()
                unresolved = self.opresolver.getUnresolvedDependencies()
                continue
            if unresolved_deps:
                for pkg in unresolved.keys():
                    if self.autoerase:
                        self.config.printWarning(1, "Autoerasing package %s due to unresolved symbols." % pkg.getNEVRA())
                        self.__doAutoerase(pkg)
                    else:
                        self.config.printInfo(1, "Unresolved dependencies for "+pkg.getNEVRA()+"\n")
                        for dep in unresolved[pkg]:
                            self.config.printInfo(1, "\t" + depString(dep)+"\n")
                if not self.autoerase:
                    sys.exit(1)
            unresolved = self.opresolver.getUnresolvedDependencies()
            if not self.autoerase:
                continue
            self.__handleConflictAutoerases()
            unresolved = self.opresolver.getUnresolvedDependencies()
        if not self.autoerase:
            return 1
        return self.__handleConflictAutoerases()

    def __handleObsoletes(self, pkg):
        found = 1
        while found:
            found = 0
            for opkg in self.__obsoleteslist:
                for u in opkg["obsoletes"]:
                    s = self.opresolver.searchDependency(u)
                    if pkg in s:
                        if not pkg in self.opresolver:
                            self.opresolver.update(pkg)
                            found = 1
                            break
                if found:
                    break

    def __doAutoerase(self, pkg):
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
        conflicts = self.opresolver.getConflicts()
        while len(conflicts) > 0:
            self.__doConflictAutoerase(conflicts)
            conflicts = self.opresolver.getConflicts()
        if self.config.nofileconflicts:
            return 1
        conflicts = self.opresolver.getFileConflicts()
        while len(conflicts) > 0:
            self.__doConflictAutoerase(conflicts)
            conflicts = self.opresolver.getFileConflicts()
        return 1

    def __doConflictAutoerase(self, conflicts):
        for pkg1 in conflicts.keys():
            for (c, pkg2) in conflicts[pkg1]:
                self.config.printInfo(1, "Resolving conflicts for %s:%s\n" % (pkg1.getNEVRA(), pkg2.getNEVRA()))
                if   self.pydb.isInstalled(pkg1):
                    pkg = pkg1
                elif self.pydb.isInstalled(pkg2):
                    pkg = pkg2
                else:
                    pkg = pkg2
                self.__doAutoerase(pkg)

# vim:ts=4:sw=4:showmatch:expandtab
