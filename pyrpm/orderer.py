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
# Copyright 2005 Red Hat, Inc.
#
# Author: Thomas Woerner
#

""" The Orderer
...
"""

from hashlist import HashList
from rpmlist import RpmList
from resolver import *

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

class RpmOrderer:
    def __init__(self, rpms, obsoletes, operation):
        """ rpms is a list of the packages which has to be installed, updated
        or removed. The operation is either OP_INSTALL, OP_UPDATE or
        OP_ERASE. """
        self.rpms = rpms
        self.obsoletes = obsoletes
        self.operation = operation
        
    # ----

    def _operationFlag(self, flag):
        """ Return operation flag or requirement """
        if self.operation == "erase":
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

    def genRelations(self):
        """ Generate relations from RpmList """
        relations = _Relations()

        # generate todo list
        rpmlist = RpmResolver(self.rpms, self.operation)

        for rlist in rpmlist:
            for r in rlist:
                printDebug(1, "Generating Relations for %s" % r.getNEVRA())
                (unresolved, resolved) = rpmlist.getPkgDependencies(r)
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
                    f = self._operationFlag(flag)
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
                    printDebug(1, "Generating empty Relations for %s" % \
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

    def genOperations(self, order):
        """ Generate operations list """
        operations = [ ]
        if self.operation == RpmList.OP_ERASE:
            # reverse order
            # obsoletes: there are none
            for i in xrange(len(order)-1, -1, -1):
                operations.append((self.operation, order[i]))
        else:
            for r in order:
                operations.append((self.operation, r))
                if r in self.obsoletes:
                    if len(self.obsoletes[r]) == 1:
                        operations.append((RpmList.OP_ERASE,
                                           self.obsoletes[r][0]))
                    else:
                        # more than one obsolete: generate order
                        resolver = RpmResolver(self.obsoletes[r],
                                               RpmList.OP_ERASE)
                        ops = resolver.resolve()
                        operations.extend(ops)
                        del resolver
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

    def order(self):
        """ Start the order process
        Returns ordered list of operations on success, with tupels of the
        form (operation, package). The operation is one of OP_INSTALL,
        OP_UPDATE or OP_ERASE per package.
        If an error occurs, None is returned. """

        # generate relations
        relations = self.genRelations()

        # order package list
        order = self.orderRpms(relations)
        if order == None:
            return None

        # cleanup relations
        del relations

        # generate operations
        return self.genOperations(order)
