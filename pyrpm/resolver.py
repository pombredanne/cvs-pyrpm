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
# Copyright 2004 Red Hat, Inc.
#
# Author: Thomas Woerner
#

from hashlist import *
from rpmlist import *

def _gen_operator(flag):
    op = ""
    if flag & RPMSENSE_LESS:
        op = "<"
    if flag & RPMSENSE_GREATER:
        op += ">"
    if flag & RPMSENSE_EQUAL:
        op += "="
    return op

# ----

def _gen_depstr((name, flag, version)):
    if version == "":
        return name
    return "%s %s %s" % (name, _gen_operator(flag), version)

# ----

# normalize list
def _normalize(list):
    i = 0
    while i < len(list):
        j = i + 1
        while j < len(list):
            if str(list[i]) == str(list[j]):
                list.pop(j)
            else:
                j += 1
        i += 1

# ----------------------------------------------------------------------------

# pre and post relations for a package
class _Relation:
    def __init__(self):
        self.pre = HashList()
        self._post = HashList()
    def __str__(self):
        return "%d %d" % (len(self.pre), len(self._post))       

# ----

# relations
class _Relations:
    def __init__(self):
        self.list = HashList()
    def __len__(self):
        return len(self.list)
    def __getitem__(self, key):
        return self.list[key]
    def append(self, pkg, pre, flag):
        if pre == pkg:
            return
        if not pkg in self.list:
            self.list[pkg] = _Relation()
        if pre not in self.list[pkg].pre:
            self.list[pkg].pre[pre] = flag
        else:
            # prefer hard requirements
            if self.list[pkg].pre[pre] == 1 and flag == 2:
                self.list[pkg].pre[pre] = flag
        for (p,f) in self.list[pkg].pre:
            if p in self.list:
                if pkg not in self.list[p]._post:
                    self.list[p]._post[pkg] = 1
            else:
                self.list[p] = _Relation()
                self.list[p]._post[pkg] = 1
    def remove(self, pkg):
        rel = self.list[pkg]
        for (r,f) in rel._post:
            if len(self.list[r].pre) > 0:
                del self.list[r].pre[pkg]
        del self.list[pkg]
    def has_key(self, key):
        return self.list.has_key(key)

# ----------------------------------------------------------------------------

class RpmResolver:
    def __init__(self, rpms, installed, operation):
        self.rpms = rpms
        self.operation = operation
        self.installed = installed

    # check dependencies for a list of rpms
    def checkDependencies(self, rpmlist):
        no_unresolved = 1
        i = 0
        r_old = None
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                unresolved = [ ]
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                j = 0
                for u in r["requires"]:
                    if u[0][0:7] == "rpmlib(": # drop rpmlib requirements
                        continue
                    s = rpmlist.searchDependency(u)
                    if len(s) == 0: # found nothing
                        unresolved.append(_gen_depstr(u))
                        no_unresolved = 0
                if len(unresolved) > 0:
                    printError("%s: unresolved dependencies:\n" % \
                               r.getNEVRA(), string.join(unresolved, "\n\t"))
        return no_unresolved

    # generate relations from RpmList
    def genRelations(self, rpmlist, operation):
        relations = _Relations()

        i = 0
        for rlist in rpmlist:
            for r in rlist:
                printDebug(1, "Generate Relations for %s" % r.getNEVRA())
                j = 0
                for u in r["requires"]:
                    (name, flag, version) = u
                    if name[0:7] == "rpmlib(": # drop rpmlib requirements
                        continue
                    if name[0:7] == "config(": # drop config requirements
                        continue
                    drop = 0
                    for p in r["provides"]:
                        if p[0] == u[0] and \
                               (u[2] == "" or \
                                (evrCompare(u[2], p[1], p[2]) == 1 and \
                                 evrCompare(u[2], u[1], p[2]) == 1)):
                            printDebug(2, "Dropping self requirement for %s" %\
                                       _gen_depstr(u))
                            drop = 1
                            break
                    if drop == 1:
                        continue
                    s = rpmlist.searchDependency(u)
                    # found packages
                    if len(s) > 0:
                        _normalize(s)
                        f = 0
                        if operation == "erase":
                            if not (isInstallPreReq(flag) or \
                                    not (isErasePreReq(flag) or \
                                         isLegacyPreReq(flag))):
                                f += 2
                            if not (isInstallPreReq(flag) or \
                                    (isErasePreReq(flag) or \
                                     isLegacyPreReq(flag))):
                                f += 1
                        else: # install or update
                            if not (isErasePreReq(flag) or \
                                    not (isInstallPreReq(flag) or \
                                         isLegacyPreReq(flag))):
                                f += 2
                            if not (isErasePreReq(flag) or \
                                    (isInstallPreReq(flag) or \
                                     isLegacyPreReq(flag))):
                                f += 1
                        if f != 0:
                            for s2 in s:
                                if s2 not in self.installed:
                                    relations.append(r, s2, f)
            i += 1

        # -- print relations
        printDebug(2, "\t==== relations (%d) ====" % len(relations))
        for (pkg, rel) in relations:
            printDebug(2, "\t%d %d %s" % (len(rel.pre), len(rel._post),
                                          pkg.getNEVRA()))
        printDebug(2, "\t==== relations ====")

        return relations
    
    # -- check for conflicts in RpmList (conflicts and obsoletes)
    def checkConflicts(self, rpmlist):
        no_conflicts = 1
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    s = rpmlist.searchDependency(c)
                    if len(s) > 0:
                        _normalize(s)
                        if r in s: s.remove(r)
                    if len(s) > 0:
                        for r2 in s:
                            printError("%s conflicts for '%s' with %s" % \
                                       (r.getNEVRA(), _gen_depstr(c), \
                                        r2.getNEVRA()))
                            no_conflicts = 0

        # -- check for file conflicts

        i = 0
        for f in rpmlist.filenames.multi:
            printDebug(1, "Checking for file conflicts")
            s = rpmlist.filenames.search(f)
            for j in xrange(len(s)):
                fi1 = s[j].getRpmFileInfo(f)
                for k in xrange(j+1, len(s)):
                    fi2 = s[k].getRpmFileInfo(f)
                    # ignore directories and links
                    if fi1.mode & CP_IFDIR and fi2.mode & CP_IFDIR:
                        continue
                    if fi1.mode & CP_IFLNK and fi2.mode & CP_IFLNK:
                        continue
                    # TODO: use md5
                    if fi1.mode != fi2.mode or fi1.mtime != fi2.mtime or \
                           fi1.filesize != fi2.filesize:
                        no_conflicts = 0
                        printError("%s: File conflict for '%s' with %s" % \
                                   (s[j].getNEVRA(), f, s[k].getNEVRA()))
            i += 1
        return no_conflicts

    # order rpmlist
    def orderRpms(self, rpmlist, relations):
        # save packages which have no relations
        no_relations = [ ]
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                if not relations.has_key(r):
                    no_relations.append(r)

        # order
        order = [ ]
        idx = 1
        while len(relations) > 0:
            next = None
            for (pkg, rel) in relations:
                if len(rel.pre) == 0:
                    next = (pkg, rel)
                    break
            if next != None:
                pkg = next[0]
                order.append(pkg)
                relations.remove(pkg)
                printDebug(2, "%d: %s" % (idx, pkg.getNEVRA()))
            else:
                printDebug(1, "-- LOOP --")
                printDebug(2, "\n===== remaining packages =====")
                for (pkg2, rel2) in relations:
                    printDebug(2, "%s" % pkg2.getNEVRA())
                    for i in xrange(len(rel2.pre)):
                        printDebug(2, "\t%s (%d)" % (rel2.pre[i][0].getNEVRA(),
                                                 rel2.pre[i][1]))
                printDebug(2, "===== remaining packages =====\n")

                (package, rel) = relations[0]
                loop = HashList()
                loop[package] = 0
                i = 0
                pkg = package
                p = None
                while p != package and i >= 0 and i < len(relations):
                    (p,f) = relations[pkg].pre[loop[pkg]]
                    if p == package:
                        break
                    if loop.has_key(p):
                        package = p
                        # remove leading nodes
                        while len(loop) > 0 and loop[0][0] != package:
                            del loop[loop[0][0]]
                        break
                    else:
                        loop[p] = 0
                        pkg = p
                        i += 1

                if p != package:
                    print "\nERROR: A loop without a loop?"
                    return None

                printDebug(1, "===== loop (%d) =====" % len(loop))
                for (p,i) in loop:
                    printDebug(1, "%s" % p.getNEVRA())
                printDebug(1, "===== loop =====")

                found = 0
                for (p,i) in loop:
                    (p2,f) = relations[p].pre[i]
                    if f == 1:
                        printDebug(1, "Removing requires for %s from %s" % \
                                   (p2.getNEVRA(), p.getNEVRA()))
                        del relations[p].pre[p2]
                        del relations[p2]._post[p]
                        found = 1
                        break
                if found == 0:
                    (p, i) = loop[0]
                    (p2,f) = relations[p].pre[i]
                    printDebug(1, "Zapping requires for %s from %s to break up hard loop" % \
                               (p2.getNEVRA(), p.getNEVRA()))
                    del relations[p].pre[p2]
                    del relations[p2]._post[p]

        if len(no_relations) > 0:
            printDebug(2, "===== packages without relations ====")
        for r in no_relations:
            order.append(r)
            printDebug(2, "%d: %s" % (idx, r.getNEVRA()))
            idx += 1

        return order

    # resolves list of installed, new, update and to erase rpms
    # returns ordered list of operations
    # operation has to be "install", "update" or "erase"
    def resolve(self):
        OP_UPDATE = "update"
        OP_ERASE = "erase"
        
        instlist = RpmList()

        for r in self.installed:
            instlist.install(r)

        for r in self.rpms:
            if self.operation == OP_ERASE:
                instlist.erase(r)
            elif self.operation == OP_UPDATE:
                instlist.update(r)
            else:
                instlist.install(r)

        # checking dependencies
        if self.checkDependencies(instlist) != 1:
            return None

        # check for conflicts
        if self.checkConflicts(instlist) != 1:
            return None

        # save obsolete list before freeing instlist
        obsoletes = instlist.obsoletes
        del instlist

        # generate 
        todo = RpmList()
        for r in self.rpms:
            todo.update(r)

        # resolving requires
        relations = self.genRelations(todo, self.operation)

        # order package list
        order = self.orderRpms(todo, relations)
        if order == None:
            return None
        del relations
        del todo

        operations = [ ]
        if self.operation == OP_ERASE:
            # reverse order
            # obsoletes: there are none
            for i in xrange(len(order)-1, -1, -1):
                operations.append((self.operation, order[i]))
        else:
            for r in order:
                operations.append((self.operation, r))
                if r in obsoletes:
                    if len(obsoletes[r]) == 1:
                        operations.append((OP_ERASE, obsoletes[r][0]))
                    else:
                        # more than one obsolete: generate order
                        todo = RpmList()
                        for r2 in obsoletes[r]:
                            todo.install(r2)
                        relations = self.genRelations(todo, OP_ERASE)
                        if relations == None:                        
                            return None
                        order2 = self.orderRpms(todo, relations)
                        del relations
                        del todo
                        if order2 == None:
                            return None
                        for i in xrange(len(order2)-1, -1, -1):
                            operations.append((OP_ERASE, order2[i]))
                        del order2
        del order
        return operations
