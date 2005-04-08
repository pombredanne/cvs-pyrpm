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


from functions import *
from io import *
from resolver import RpmResolver
from control import RpmController
from package import RpmPackage


class RpmYum:
    def __init__(self):
        # Default: Don't autoerase packages that have unresolved symbols in
        # install or update
        self.autoerase = 0
        # Default: Ask user for confirmation of complete operation
        self.confirm = 1
        # Default: No command
        self.command = None
        # List of repository resolvers
        self.repos = []
        # List of installed packages
        self.installed = []

    def setAutoerase(self, flag):
        self.autoerase = flag

    def setConfirm(self, flag):
        self.confirm = flag

    def setCommand(self, command):
        self.command = command

    def processArgs(self, args):
        # Read db and store list of installed rpms
        if rpmconfig.buildroot:
            pydb = RpmPyDB(rpmconfig.buildroot + rpmconfig.dbpath)
        else:
            pydb = RpmPyDB(rpmconfig.dbpath)
        self.installed = pydb.getPkgList().values()
        del pydb
        # If we do a group operation handle it accordingly
        if self.command.startswith("group"):
            if rpmconfig.compsfile == None:
                printError("You need to specify a comps.xml file for group operations")
                usage()
                sys.exit(1)
            comps = RpmCompsXMLIO(rpmconfig.compsfile)
            comps.read()
            pkgs = []
            for grp in args:
                pkgs.extend(comps.getPackageNames(grp))
            args = pkgs
            del comps
        else:
            if len(args) == 0:
                for pkg in self.installed:
                    args.append(pkg["name"])
        # Look for packages we need/want to install. Arguments can either be
        # direct filenames or package nevra's with * wildcards
        self.pkgs = []
        for f in args:
            if os.path.isfile(f) and f.endswith(".rpm"):
                pkg = self.__readRpmPackage(f)
                if rpmconfig.ignorearch or archCompat(pkg["arch"], rpmconfig.machine):
                    self.pkgs.append(pkg)
            elif os.path.isdir(f):
                for g in os.listdir(f):
                    fn = "%s/%s" % (f, g)
                    if not g.endswith(".rpm") or not os.path.isfile(fn):
                        continue
                    pkg = self.__readRpmPackage(fn)
                    if rpmconfig.ignorearch or archCompat(pkg["arch"], rpmconfig.machine):
                        self.pkgs.append(pkg)
            else:
                for repo in self.repos:
                    self.pkgs.extend(findPkgByName(f, repo.getList()))
                if len(self.pkgs) == 0:
                    printError("Couldn't find package %s, skipping" % f)

    def runDepRes(self):
        # Add packages to be updated  to our operation resolver
        self.opresolver = RpmResolver(self.installed, OP_UPDATE)
        for pkg in self.pkgs:
            if self.command in ("update", "upgrade", "groupupdate", "groupupgrade"):
                name = pkg["name"]
                for ipkg in self.installed:
                    if ipkg["name"] == name:
                        self.opresolver.append(pkg)
                        break
            else:
                self.opresolver.append(pkg)
        del self.pkgs
        self.pkgs = []
        # Look for obsoletes and add them to our update packages
        for repo in self.repos:
            for pkg in repo.getList():
                for u in pkg["obsoletes"]:
                    s = self.opresolver.searchDependency(u)
                    if len(s) > 0:
                        self.opresolver.append(pkg)
        self.__runDepResolution()

    def __runDepResolution(self):
        # Special erase list for unresolvable package dependancies or conflicts
        self.erase_list = []
        unresolved = self.opresolver.getUnresolvedDependencies()
        iteration = 1
        while len(unresolved) > 0:
            printInfo(1, "Dependency iteration " + str(iteration) + "\n")
            iteration += 1
            unresolved_deps = 1
            for pkg in unresolved.keys():
                printInfo(1, "Resolving dependencies for %s\n" % pkg.getNEVRA())
                found = 0
                for dep in unresolved[pkg]:
                    printInfo(2, "\t" + depString(dep) + "\n")
                    for repo in self.repos:
                        for upkg in repo.searchDependency(dep):
                            if upkg in self.erase_list:
                                continue
                            ret = self.opresolver.append(upkg)
                            if ret > 0 or ret == RpmResolver.ALREADY_ADDED:
                                found = 1
                                unresolved_deps = 0
                if found == 0:
                    tmplist = []
                    for repo in self.repos:
                        tmplist.extend(findPkgByName(pkg["name"], repo.getList()))
                    for upkg in tmplist:
                        if upkg in self.erase_list:
                            continue
                        res = self.opresolver.append(upkg)
                        if res > 0:
                            found = 1
                            unresolved_deps = 0
                    if found == 0:
                        if self.autoerase:
                            printWarning(1, "Autoerasing package %s due to missing update package." % pkg.getNEVRA())
                            self.__doAutoerase(pkg)
                        else:
                            printWarning(0, "Couldn't find update for package %s" \
                                % pkg.getNEVRA())
                            sys.exit(1)
            if unresolved_deps:
                for (pkg, deplist) in unresolved:
                    if self.autoerase:
                        printWarning(1, "Autoerasing package %s due to unresolved symbols." % pkg.getNEVRA())
                        self.__doAutoerase(pkg)
                    else:
                        printInfo(1, "Unresolved dependencies for "+pkg.getNEVRA()+"\n")
                        for dep in deplist:
                            printInfo(1, "\t" + depString(dep)+"\n")
                if not self.autoerase:
                    sys.exit(1)
            unresolved = self.opresolver.getUnresolvedDependencies()
            if not self.autoerase:
                continue
            conflicts = self.opresolver.getConflicts()
            self.__doConflictAutoerase(conflicts)
            unresolved = self.opresolver.getUnresolvedDependencies()
        if not self.autoerase:
            return 1
        conflicts = self.opresolver.getConflicts()
        while len(conflicts) > 0:
            self.__doConflictAutoerase(conflicts)
            conflicts = self.opresolver.getConflicts()

    def __doAutoerase(self, pkg):
        opkg = self.__genObsoletePkg(pkg)
        ret = self.opresolver.append(opkg)
        if ret > 0:
            self.erase_list.append(pkg)
            if opkg in self.opresolver.updates.keys():
                for upkg in self.opresolver.updates[opkg]:
                    if upkg in self.erase_list:
                        continue
                    self.opresolver.append(upkg)
                    self.opresolver.updates[opkg].remove(upkg)
                if len(self.opresolver.updates[opkg]) == 0:
                    del self.opresolver.updates[opkg]
        else:
            return 0
        return 1

    def __doConflictAutoerase(self, conflicts):
        for pkg1 in conflicts.keys():
            for (c, pkg2) in conflicts[pkg1]:
                printInfo(1, "Resolving conflicts for %s:%s\n" % (pkg1.getNEVRA(), pkg2.getNEVRA()))
                if pkg1 in self.installed:
                    pkg = pkg1
                elif pkg2 in self.installed:
                    pkg = pkg2
                else:
                    pkg = pkg2
                self.__doAutoerase(pkg)

    def runCommand(self):
        appended = self.opresolver.appended
        del self.opresolver
        self.opresolver = None
        for repo in self.repos:
            del repo
        self.repos = []
        if len(self.erase_list) > 0:
            printInfo(0, "Warning: Following packages will be automatically removed:\n")
            for pkg in self.erase_list:
                printInfo(0, "\t%s\n" % pkg.getNEVRA())
        if self.confirm:
            choice = raw_input("Is this ok [y/N]: ")
            if len(choice) == 0:
                sys.exit(0)
            else:
                if choice[0] != "y" and choice[0] != "Y":
                    sys.exit(0)
        control = RpmController()
        control.handlePkgs(appended, OP_UPDATE, rpmconfig.dbpath, rpmconfig.buildroot)
        ops = control.getOperations()
        i = 0
        while i < len(ops):
            (op, pkg) = ops[i]
            if pkg.has_key("thisisaobsoletespackage"):
                ops.pop(i)
                continue
            i += 1
        control.runOperations(ops)

    def __readRpmPackage(self, filename):
        pkg = RpmPackage(filename)
        pkg.open()
        pkg.read(tags=rpmconfig.resolvertags)
        pkg.close()
        return pkg

    def addRepo(self, dirname, excludes):
        pkg_list = []
        for f in os.listdir(dirname):
            fn = "%s/%s" % (dirname, f)
            if not f.endswith(".rpm") or not os.path.isfile(fn):
                continue
            pkg = self.__readRpmPackage(fn)
            if rpmconfig.ignorearch or \
               archCompat(pkg["arch"], rpmconfig.machine):
                pkg_list.append(pkg)
        ex_list = excludes.split()
        for ex in ex_list:
            excludes = findPkgByName(ex, pkg_list)
            for pkg in excludes:
                pkg_list.remove(pkg)
        resolver = RpmResolver(pkg_list, OP_INSTALL)
        self.repos.append(resolver)

    def __test(self):
        pass

    def __genObsoletePkg(self, pkg):
        dummy = RpmPackage("dummy")
        dummy["name"] = "obsoletes-%s" % pkg.getNEVRA()
        dummy["thisisaobsoletespackage"] = 1
        dummy["version"] = "0"
        dummy["release"] = "0"
        dummy["arch"] = "noarch"
        dummy["filenames"] = [ ] 
        dummy["obsoletename"] = [pkg["name"]]
        dummy["obsoleteflags"] = [RPMSENSE_EQUAL]
        dummy["obsoleteversion"] = [pkg.getEVR()]
        dummy["provides"] = dummy.getProvides()
        dummy["requires"] = dummy.getRequires()
        dummy["obsoletes"] = dummy.getObsoletes()
        dummy["conflicts"] = dummy.getConflicts()
        dummy["triggers"] = dummy.getTriggers()
        return dummy

# vim:ts=4:sw=4:showmatch:expandtab
