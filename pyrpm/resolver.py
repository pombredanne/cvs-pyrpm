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

""" The Resolver
...
"""

import string
from hashlist import *
from rpmlist import *

# ----------------------------------------------------------------------------

def _genOperator(flag):
    """ generate readable operator """
    op = ""
    if flag & RPMSENSE_LESS:
        op = "<"
    if flag & RPMSENSE_GREATER:
        op += ">"
    if flag & RPMSENSE_EQUAL:
        op += "="
    return op

# ----

def _genDepString((name, flag, version)):
    if version == "":
        return name
    return "%s %s %s" % (name, _genOperator(flag), version)

# ----

def _normalize(list):
    """ normalize list """
    if len(list) < 2:
        return
    hash = { }
    i = 0
    while i < len(list):
        item = list[i]
        if hash.has_key(item):
            list.pop(i)
        else:
            hash[item] = 1
        i += 1
    return

# ----------------------------------------------------------------------------

class _Relation:
    """ Pre and post relations for a package """
    def __init__(self):
        self.pre = HashList()
        self._post = HashList()
    def __str__(self):
        return "%d %d" % (len(self.pre), len(self._post))       

# ----

class _Relations:
    """ relations list for packages """
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
        if pre == None:
            return # we have to do nothing more for empty relations
        if pre not in self.list[pkg].pre:
            self.list[pkg].pre[pre] = flag
        else:
            # prefer hard requirements, do not overwrite with soft req
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
    """ The RpmResolver is able ro resolve a list of rpms for installation, 
    update or removal.
    The main function of this class is resolve, which does the complete job.
    This is done in 9 stages:
      1) Generate the list of packages which will be installed after the
         operations are done
      2) Check dependencies in this list. Are there unresolved requires?
      3) Check for conflicts between packages in this list.
         Obsoletes are treatened as conflicts in here.
      4) Check for file conflicts: Are there files in multiple packages,
         which have the same name and path, but are different in size and
         md5sum?
      5) Generate the todo list. This is the list of the changes, which should
         be made. The already installed packages are not relevant for the
         ordering process of the changes.
      6) Generate the relations for the packages in the todo list. There are
         pre and post relation lists for every package. In the pre relation
         list are the packages, which have to be installed before this package
         can be installed. Every pre relation has a weight: hard or soft. A
         hard weight means, that the relation is needed in pre and post
         scripts, the soft weight is needed later at execution time. The post
         relation list holds all packages which are dependant on this package.
         This list is only needed for optimization purposes.
      7) Save all packages which do not have any relation to another package
         from the todo list.
      8) Order the packages in the relations:
         a) Search for a leaf node, which has the most post relations. Leaf
            node means, that this rpm package has no dependency to an other
            package in the list.
         b) If the list is not empty and there is no leaf node, then there is
            one or more loops in the relations. Continue with d)
         c) Put the found node (the rpm package) in the order list and remove
            it and all it's relations from the relations list. Goto a)
         d) Detect a loop
            A) Take the first package with the smallest list of pre relations
            B) goto 

      9) 

    """

    OP_INSTALL = "install"
    OP_UPDATE = "update"
    OP_ERASE = "erase"

    def __init__(self, rpms, installed, operation):
        """ rpms is a list of the packages which has to be installed, updated
        or removed. Installed is a list of the packages which are installed
        at this time. The operation is either OP_INSTALL, OP_UPDATE or
        OP_ERASE. """
        self.rpms = rpms
        self.operation = operation
        self.installed = installed

    # ----

    def checkPkgDependencies(self, rpm, rpmlist):
        """ Check dependencies for a rpm package """
        unresolved = [ ]
        resolved = [ ]
        j = 0
        for u in rpm["requires"]:
            if u[0][0:7] == "rpmlib(": # drop rpmlib requirements
                continue
            s = rpmlist.searchDependency(u)
            if len(s) > 0:
                _normalize(s)
                if len(s) > 1 and rpm in s:
                    # prefer self dependencies if there are others, too
                    s = [rpm]
                elif u[0][0] != "/": # check arch if no file requires
                    i = 0
                    while i < len(s):
                        r = s[i]
                        # equal are ok, noarch is ok
                        if not (r["arch"] == rpm["arch"] or \
                                rpm["arch"] == "noarch" or \
                                r["arch"] == "noarch"):
                            print "%s -> %s" % (rpm.getNEVRA(), r.getNEVRA())
                            # is rpm in arch compat list of r?
                            # if buildarchtranslate[r["arch"]] != buildarchtranslate[rpm["arch"]]:
                            if rpm["arch"] not in arch_compats[r["arch"]]:
                                if buildarchtranslate[r["arch"]] != \
                                       buildarchtranslate[rpm["arch"]]:
                                    print "\t removing"
                                    s.pop(i)
                                    continue
                        i += 1
            if len(s) == 0: # found nothing
                unresolved.append(u)
            else: # resolved
                resolved.append((u, s))
        return (unresolved, resolved)

    # ----

    def checkDependencies(self, rpmlist):
        """ Check dependencies for a list of rpm packages """
        no_unresolved = 1
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.checkPkgDependencies(r, rpmlist)
                if len(resolved) > 0 and rpmconfig.debug_level > 1:
                    # do this only in debug level > 1
                    printDebug(2, "%s: resolved dependencies:" % r.getNEVRA())
                    for (u, s) in resolved:
                        str = ""
                        for r2 in s:
                            str += "%s " % r2.getNEVRA()
                        printDebug(2, "\t%s: %s" % (_genDepString(u), str))
                if len(unresolved) > 0:
                    no_unresolved = 0
                    printError("%s: unresolved dependencies:" % r.getNEVRA())
                    for u in unresolved:                        
                        printError("\t%s" % _genDepString(u))
        return no_unresolved

    # ----

    def checkConflicts(self, rpmlist):
        """ Check for conflicts in RpmList (conflicts and obsoletes) """
        no_conflicts = 1
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    s = rpmlist.searchDependency(c)
                    if len(s) > 0:
                        _normalize(s)
                        # the package does not conflict with itself
                        if r in s: s.remove(r)
                    if len(s) > 0:
                        for r2 in s:
                            printError("%s conflicts for '%s' with %s" % \
                                       (r.getNEVRA(), _genDepString(c), \
                                        r2.getNEVRA()))
                            no_conflicts = 0

        return no_conflicts

    # ----

    def checkFileConflicts(self, rpmlist):
        """ Check for file conflicts """
        no_conflicts = 1
        for f in rpmlist.filenames.multi:
            printDebug(1, "Checking for file conflicts for '%s'" % f)
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
                    if fi1.mode != fi2.mode or \
                           fi1.filesize != fi2.filesize or \
                           fi1.md5 != fi2.md5:
                        no_conflicts = 0
                        printError("%s: File conflict for '%s' with %s" % \
                                   (s[j].getNEVRA(), f, s[k].getNEVRA()))
        return no_conflicts

    # ----

    def _operationFlag(self, flag, operation):
        """ Return operation flag or requirement """
        if operation == "erase":
            if not (isInstallPreReq(flag) or \
                    not (isErasePreReq(flag) or isLegacyPreReq(flag))):
                return 2  # hard requirement
            if not (isInstallPreReq(flag) or \
                    (isErasePreReq(flag) or isLegacyPreReq(flag))):
                return 1  # soft requirement
        else: # operation: install or update
            if not (isErasePreReq(flag) or \
                    not (isInstallPreReq(flag) or isLegacyPreReq(flag))):
                return 2  # hard requirement
            if not (isErasePreReq(flag) or \
                    (isInstallPreReq(flag) or isLegacyPreReq(flag))):
                return 1  # soft requirement
        return 0
    
    # ----

    def genRelations(self, rpmlist, operation):
        """ Generate relations from RpmList """
        relations = _Relations()

        for rlist in rpmlist:
            for r in rlist:
                printDebug(1, "Generating Relations for %s" % r.getNEVRA())
                (unresolved, resolved) = self.checkPkgDependencies(r, rpmlist)
                # ignore unresolved, we are only looking at the changes,
                # therefore not all symbols are resolvable in these changes
                for (u,s) in resolved:
                    (name, flag, version) = u
                    if name[0:7] == "config(": # drop config requirements
                        continue
                    if r in s:
                        continue
                        # drop requirements which are resolved by the package
                        # itself
                    f = self._operationFlag(flag, operation)
                    if f == 0:
                        # no hard or soft requirement
                        continue
                    for s2 in s:
                        relations.append(r, s2, f)

        # packages which have no relations
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                if not relations.has_key(r):
                    printDebug(1, "Generating an empty Relation for %s" % \
                               r.getNEVRA())
                    relations.append(r, None, 0)

        if rpmconfig.debug_level > 1:
            # print relations
            printDebug(2, "\t==== relations (%d) ====" % len(relations))
            for (pkg, rel) in relations:
                pre = ""
                if rpmconfig.debug_level > 2 and len(rel.pre) > 0:
                    pre = " pre: "
                    for i in xrange(len(rel.pre)):
                        (p,f) = rel.pre[i]
                        if i > 0: pre += ", "
                        if f == 2: pre += "*"
                        pre += p.getNEVRA()
                printDebug(2, "\t%d %d %s%s" % (len(rel.pre), len(rel._post),
                                                pkg.getNEVRA(), pre))
            printDebug(2, "\t==== relations ====")

        return relations
    
    # ----

    def _genInstList(self):
        """ Generate instlist """
        instlist = RpmList()

        for r in self.installed:
            instlist.install(r)

        for r in self.rpms:
            if self.operation == self.OP_ERASE:
                instlist.erase(r)
            elif self.operation == self.OP_UPDATE:
                instlist.update(r)
            else:
                instlist.install(r)

        return instlist

    # ----

    def _genOperations(self, order, obsoletes):
        """ Generate operations list """
        operations = [ ]
        if self.operation == self.OP_ERASE:
            # reverse order
            # obsoletes: there are none
            for i in xrange(len(order)-1, -1, -1):
                operations.append((self.operation, order[i]))
        else:
            for r in order:
                operations.append((self.operation, r))
                if r in obsoletes:
                    if len(obsoletes[r]) == 1:
                        operations.append((self.OP_ERASE, obsoletes[r][0]))
                    else:
                        # more than one obsolete: generate order
                        todo = RpmList()
                        for r2 in obsoletes[r]:
                            todo.install(r2)
                        relations = self.genRelations(todo, self.OP_ERASE)
                        if relations == None:                        
                            return None
                        order2 = self.orderRpms(relations)
                        del relations
                        del todo
                        if order2 == None:
                            return None
                        for i in xrange(len(order2)-1, -1, -1):
                            operations.append((self.OP_ERASE, order2[i]))
                        del order2
        return operations

    # ----

    def _detectLoop(self, relations):
        """ Detect loop in relations """

        # search for the best node: the smallest list of pre relations
        node = relations[0]
        node_pre_len = len(node[1].pre)
        for (pkg, rel) in relations:
            if len(rel.pre) == 0 and len(rel.pre) < node_pre_len:
                node = (pkg, rel)
                node_pre_len = len(rel.pre)

        # found starting node
        (package, rel) = node
        loop = HashList()
        loop[package] = 0
        i = 0
        pkg = package
        p = None
        while i < len(relations):
            if p == package:
                break
            # try to find a minimal loop
            p = None
            for (p2,i2) in loop:
                if p2 in relations[pkg].pre:
                    p = p2
            if p == None:
                (p,f) = relations[pkg].pre[loop[pkg]]
            if loop.has_key(p):
                # got node which is already in list: found loop
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
            printError("A loop without a loop?")
            return None

        if rpmconfig.debug_level > 0:
            printDebug(1, "===== loop (%d) =====" % len(loop))
            for (p,i) in loop:
                printDebug(1, "%s" % p.getNEVRA())
            printDebug(1, "===== loop =====")

        return loop

    # ----

    def _breakupLoop(self, loop, relations):
        """ Breakup loop in relations """
        ### first try to breakup a soft relation

        # search for the best node: soft relation and the smallest list of pre
        # relations
        node = None
        node_pre_len = 1000000000
        for (p,i) in loop:
            (p2,f) = relations[p].pre[i]
            if f == 1 and len(relations[p].pre) < node_pre_len:
                node = p
                node_pre_len = len(relations[p].pre)
                
        if node != None:
            (p2,f) = relations[node].pre[loop[node]]
            printDebug(1, "Removing requires for %s from %s" % \
                       (p2.getNEVRA(), node.getNEVRA()))
            del relations[node].pre[p2]
            del relations[p2]._post[node]
            return 1

        ### breakup hard loop (zapping)

        # search for the best node: the smallest list of pre relations
        for (p,i) in loop:
            (p2,f) = relations[p].pre[i]
            if len(relations[p].pre) < node_pre_len:
                node = p
                node_pre_len = len(relations[p].pre)
                
        if node != None:
            (p2,f) = relations[node].pre[loop[node]]
            printDebug(1, "Zapping requires for %s from %s to break up hard loop" % \
                       (p2.getNEVRA(), node.getNEVRA()))
            del relations[node].pre[p2]
            del relations[p2]._post[node]
            return 1

        return 0

    # ----

    def orderRpms(self, relations):
        """ Order rpmlist.
        Returns ordered list of packages. """
        order = [ ]
        idx = 1
        while len(relations) > 0:
            next = None
            # we have to have at least one entry, so start with -1 for len
            next_post_len = -1
            for (pkg, rel) in relations:
                if len(rel.pre) == 0 and len(rel._post) > next_post_len:
                    next = (pkg, rel)
                    next_post_len = len(rel._post)
            if next != None:
                pkg = next[0]
                order.append(pkg)
                relations.remove(pkg)
                printDebug(2, "%d: %s" % (idx, pkg.getNEVRA()))
                idx += 1
            else:
                if rpmconfig.debug_level > 0:
                    printDebug(1, "-- LOOP --")
                    printDebug(2, "\n===== remaining packages =====")
                    for (pkg2, rel2) in relations:
                        printDebug(2, "%s" % pkg2.getNEVRA())
                        for i in xrange(len(rel2.pre)):
                            printDebug(2, "\t%s (%d)" %
                                       (rel2.pre[i][0].getNEVRA(),
                                        rel2.pre[i][1]))
                    printDebug(2, "===== remaining packages =====\n")

                # detect loop
                loop = self._detectLoop(relations)
                if loop == None:
                    return None

                # breakup loop
                if self._breakupLoop(loop, relations) != 1:
                    printError("Could not breakup loop")
                    return None

        return order

    # ----

    def resolve(self):
        """ Start the resolving process
        Returns ordered list of operations on success, with tupels of the
        form (operation, package). The operation is one of OP_INSTALL,
        OP_UPDATE or OP_ERASE per package.
        If an error occurs, None is returned. """

        # generate instlist
        instlist = self._genInstList()

        # checking dependencies
        if self.checkDependencies(instlist) != 1:
            return None

        # check for conflicts
        if self.checkConflicts(instlist) != 1:
            return None

        # check for file conflicts
        if self.checkFileConflicts(instlist) != 1:
            return None

        # save obsolete list before freeing instlist
        obsoletes = instlist.obsoletes

        # generate 
        todo = RpmList()
        for r in self.rpms:
            printDebug(1, "Adding %s to todo list." % r.getNEVRA())
            if self.operation == self.OP_UPDATE:
                todo.update(r)
            else:
                todo.install(r)

        # resolving requires
        relations = self.genRelations(todo, self.operation)
        del todo

        # order package list
        order = self.orderRpms(relations)
        if order == None:
            return None
        del relations

        # generate operations
        operations = self._genOperations(order, obsoletes)
        # cleanup order list
        del order
        
        return operations
