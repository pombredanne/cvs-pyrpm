#!/usr/bin/python
#
# Copyright (C) 2005 Red Hat, Inc.
# Author: Thomas Woerner
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

""" The Orderer
...
"""

from hashlist import HashList
from config import rpmconfig
from functions import *
from resolver import RpmResolver

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
        self.__len__ = self.list.__len__
        self.__getitem__ = self.list.__getitem__
        self.has_key = self.list.has_key

    def append(self, pkg, pre, flag):
        if pre == pkg:
            return
        i = self.list[pkg]
        if i == None:
            i = _Relation()
            self.list[pkg] = i
        if pre == None:
            return # we have to do nothing more for empty relations
        if pre not in i.pre:
            i.pre[pre] = flag
        else:
            # prefer hard requirements, do not overwrite with soft req
            if flag == 2 and i.pre[pre] == 1:
                i.pre[pre] = flag
        for p in i.pre:
            if p in self.list:
                if pkg not in self.list[p]._post:
                    self.list[p]._post[pkg] = 1
            else:
                self.list[p] = _Relation()
                self.list[p]._post[pkg] = 1

    def remove(self, pkg):
        rel = self.list[pkg]
        # remove all post relations for the matching pre relation packages
        for r in rel.pre:
            del self.list[r]._post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel._post:
            del self.list[r].pre[pkg]
        del self.list[pkg]

# ----------------------------------------------------------------------------

class RpmOrderer:
    def __init__(self, installs, updates, obsoletes, erases):
        """ rpms is a list of the packages which has to be installed, updated
        or removed. The operation is either OP_INSTALL, OP_UPDATE or
        OP_ERASE. """
        self.installs = installs
        self.erases = erases
        self.updates = updates
        if self.updates:
            for pkg in self.updates:
                for p in self.updates[pkg]:
                    self.erases.remove(p)
        self.obsoletes = obsoletes
        if self.obsoletes:
            for pkg in self.obsoletes:
                for p in self.obsoletes[pkg]:
                    self.erases.remove(p)

    # ----

    def _operationFlag(self, flag, operation):
        """ Return operation flag or requirement """
        if operation == OP_ERASE:
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

    def genRelations(self, rpms, operation):
        """ Generate relations from RpmList """
        relations = _Relations()

        # generate todo list for installs
        resolver = RpmResolver(rpms, operation)

        for name in resolver:
            for r in resolver[name]:
                printDebug(1, "Generating relations for %s" % r.getNEVRA())
                (unresolved, resolved) = resolver.getPkgDependencies(r)
                # ignore unresolved, we are only looking at the changes,
                # therefore not all symbols are resolvable in these changes
                empty = 1
                for ((name, flag, version), s) in resolved:
                    if name.startswith("config("): # drop config requirements
                        continue
                    # drop requirements which are resolved by the package
                    # itself
                    if r in s:
                        continue
                    f = self._operationFlag(flag, OP_INSTALL)
                    if f == 0: # no hard or soft requirement
                        continue
                    for r2 in s:
                        relations.append(r, r2, f)
                    if empty:
                        empty = 0
                if empty:
                    printDebug(1, "No relations found for %s, generating empty relations" % \
                               r.getNEVRA())
                    relations.append(r, None, 0)
        del resolver

        if rpmconfig.debug_level > 1:
            # print relations
            printDebug(2, "\t==== relations (%d) ====" % len(relations))
            for pkg in relations:
                rel = relations[pkg]
                pre = ""
                if rpmconfig.debug_level > 2 and len(rel.pre) > 0:
                    pre = " pre: "
                    for i in xrange(len(rel.pre)):
                        p = rel.pre[i]
                        f = rel.pre[p]
                        if i > 0: pre += ", "
                        if f == 2: pre += "*"
                        pre += p.getNEVRA()
                printDebug(2, "\t%d %d %s%s" % (len(rel.pre), len(rel._post),
                                                pkg.getNEVRA(), pre))
            printDebug(2, "\t==== relations ====")

        return relations

    # ----

    def _genEraseOps(self, list):
        if len(list) == 1:
            ops = [(OP_ERASE, list[0])]
        else:
            # more than one in list: generate order
            orderer = RpmOrderer(None, None, None, list)
            ops = orderer.order()
            del orderer
        return ops

    # ----

    def genOperations(self, order):
        """ Generate operations list """
        operations = [ ]
        for r in order:
            if r in self.erases:
                operations.append((OP_ERASE, r))
            else:
                if self.updates and r in self.updates:
                    op = OP_UPDATE
                else:
                    op = OP_INSTALL
                operations.append((op, r))
                if self.obsoletes and r in self.obsoletes:
                    operations.extend(self._genEraseOps(self.obsoletes[r]))
                if self.updates and r in self.updates:
                    operations.extend(self._genEraseOps(self.updates[r]))
        return operations

    # ----

    def _detectLoops(self, relations, path, pkg, loops, used):
        if pkg in used: return
        used[pkg] = 1
        for p in relations[pkg].pre:
            if len(path) > 0 and p in path:
                w = path[path.index(p):] # make shallow copy of loop
                w.append(pkg)
                w.append(p)
                loops.append(w)
            else:
                w = path[:] # make shallow copy of path
                w.append(pkg)
                self._detectLoops(relations, w, p, loops, used)

    # ----

    def getLoops(self, relations):
        loops = [ ]
        used =  { }
        for pkg in relations:
            if not used.has_key(pkg):
                self._detectLoops(relations, [ ], pkg, loops, used)
        return loops

    # ----

    def genCounter(self, loops):
        counter = HashList()
        for w in loops:
            for j in xrange(len(w) - 1):
                node = w[j]
                next = w[j+1]
                if node not in counter:
                    counter[node] = HashList()
                if next not in counter[node]:
                    counter[node][next] = 1
                else:
                    counter[node][next] += 1
        return counter

    # ----

    def breakupLoops(self, relations, loops):
        counter = self.genCounter(loops)

        # breakup soft loop
        max_count_node = None
        max_count_next = None
        max_count = 0
        for node in counter:
            for next in counter[node]:
                count = counter[node][next]
                if max_count < count and relations[node].pre[next] == 1:
                    max_count_node = node
                    max_count_next = next
                    max_count = count

        if max_count_node:
            printDebug(1, "Removing requires for %s from %s (%d)" % \
                       (max_count_next.getNEVRA(), max_count_node.getNEVRA(),
                        max_count))
            del relations[max_count_node].pre[max_count_next]
            del relations[max_count_next]._post[max_count_node]
            return 1

        # breakup hard loop
        max_count_node = None
        max_count_next = None
        max_count = 0
        for node in counter:
            for next in counter[node]:
                count = counter[node][next]
                if max_count < count:
                    max_count_node = node
                    max_count_next = next
                    max_count = count

        if max_count_node:
            printDebug(1, "Zapping requires for %s from %s (%d)" % \
                       (max_count_next.getNEVRA(), max_count_node.getNEVRA(),
                        max_count))
            del relations[max_count_node].pre[max_count_next]
            del relations[max_count_next]._post[max_count_node]
            return 1
        
        return 0

    # ----

    def _separatePostLeafNodes(self, relations, list):
        while len(relations) > 0:
            i = 0
            found = 0
            while i < len(relations):
                pkg = relations[i]
                if len(relations[pkg]._post) == 0:
                    list.insert(0, pkg)
                    relations.remove(pkg)
                    found = 1
                else:
                    i += 1
            if found == 0:
                break

    # ----

    def _getNextLeafNode(self, relations):
        next = None
        next_post_len = -1
        for pkg in relations:
            rel = relations[pkg]
            if len(rel.pre) == 0 and len(rel._post) > next_post_len:
                next = pkg
                next_post_len = len(rel._post)
        return next
        
    # ----

    def _genOrder(self, relations):
        """ Order rpms.
        Returns ordered list of packages. """
        order = [ ]
        idx = 1
        last = [ ]
        while len(relations) > 0:
            # remove and save all packages without a post relation in reverse
            # order 
            # these packages will be appended later to the list
            self._separatePostLeafNodes(relations, last)

            if len(relations) == 0:
                break

            next = self._getNextLeafNode(relations)
            if next != None:
                order.append(next)
                relations.remove(next)
                printDebug(2, "%d: %s" % (idx, next.getNEVRA()))
                idx += 1
            else:
                if rpmconfig.debug_level > 0:
                    printDebug(1, "-- LOOP --")
                    printDebug(2, "\n===== remaining packages =====")
                    for pkg2 in relations:
                        rel2 = relations[pkg2]
                        printDebug(2, "%s" % pkg2.getNEVRA())
                        for r in rel2.pre:
                            # print nevra and flag
                            printDebug(2, "\t%s (%d)" %
                                       (r.getNEVRA(), rel2.pre[r]))
                    printDebug(2, "===== remaining packages =====\n")

                loops = self.getLoops(relations)
                if self.breakupLoops(relations, loops) != 1:
                    printError("Unable to breakup loop.")
                    return None

        if rpmconfig.debug_level > 1:
            for r in last:
                printDebug(2, "%d: %s" % (idx, r.getNEVRA()))
                idx += 1

        return (order + last)

    # ----

    def genOrder(self):
        order = [ ]

        # order installs
        if self.installs and len(self.installs) > 0:
            # generate relations
            relations = self.genRelations(self.installs, OP_INSTALL)

            # order package list
            order2 = self._genOrder(relations)
            if order2 == None:
                return None
            order.extend(order2)
            
        # order erases
        if self.erases and len(self.erases) > 0:
            # generate relations
            relations = self.genRelations(self.erases, OP_ERASE)

            # order package list
            order2 = self._genOrder(relations)
            if order2 == None:
                return None
            order2.reverse()
            order.extend(order2)

        return order

    # ----

    def order(self):
        """ Start the order process
        Returns ordered list of operations on success, with tupels of the
        form (operation, package). The operation is one of OP_INSTALL,
        OP_UPDATE or OP_ERASE per package.
        If an error occurs, None is returned. """

        order = self.genOrder()
        if order == None:
            return None

        # generate operations
        return self.genOperations(order)

# vim:ts=4:sw=4:showmatch:expandtab
