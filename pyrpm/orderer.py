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
from base import *
from resolver import RpmResolver


class Relation:
    SOFT    = 0 # normal requirement
    HARD    = 1 # prereq
    VIRTUAL = 2

    """ Pre and post relations for a package """
    def __init__(self):
        self.pre = { }
        self.post = { }
    def __str__(self):
        return "%d %d" % (len(self.pre), len(self.post))

def isHardRelation(flag):
    return (flag & Relation.HARD == Relation.HARD)
def isVirtualRelation(flag):
    return (flag & Relation.VIRTUAL == Relation.VIRTUAL)

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
            i = Relation()
            self.list[pkg] = i
        if pre == None:
            return # no additional things to do for empty relations
        if pre not in i.pre or isHardRelation(flag):
            # prefer hard requirements, do not overwrite with soft req
            i.pre[pre] = flag
            if not pre in self.list:
                self.list[pre] = Relation()
            self.list[pre].post[pkg] = 1

    def remove(self, pkg):
        rel = self.list[pkg]
        # remove all post relations for the matching pre relation packages
        for r in rel.pre:
            del self.list[r].post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel.post:
            del self.list[r].pre[pkg]
        del self.list[pkg]

# ----------------------------------------------------------------------------

class RpmOrderer:
    def __init__(self, config, installs, updates, obsoletes, erases):
        """ rpms is a list of the packages which has to be installed, updated
        or removed. The operation is either OP_INSTALL, OP_UPDATE or
        OP_ERASE. """
        self.config = config
        self.installs = installs
        self.updates = updates
        self.erases = erases
        if self.updates:
            for pkg in self.updates:
                for p in self.updates[pkg]:
                    if p in self.erases:
                        self.erases.remove(p)
        self.obsoletes = obsoletes
        if self.obsoletes:
            for pkg in self.obsoletes:
                for p in self.obsoletes[pkg]:
                    if p in self.erases:
                        self.erases.remove(p)
        self.dropped_relations = { }

    # ----

    def _operationFlag(self, flag, operation):
        """ Return operation flag or requirement """
        if isLegacyPreReq(flag) or \
               (operation == OP_ERASE and isErasePreReq(flag)) or \
               (operation != OP_ERASE and isInstallPreReq(flag)):
            return Relation.HARD # hard requirement
        return Relation.SOFT # soft requirement

    # ----

    def genRelations(self, rpms, operation):
        """ Generate relations from RpmList """
        relations = _Relations()

        # generate todo list for installs
        resolver = RpmResolver(self.config, rpms)

        for name in resolver:
            for r in resolver[name]:
                self.config.printDebug(1, "Generating relations for %s" % r.getNEVRA())
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
                    f = self._operationFlag(flag, operation)
                    for r2 in s:
                        relations.append(r, r2, f)
                    empty = 0
                if empty:
                    self.config.printDebug(1, "No relations found for %s, generating empty relations" % \
                               r.getNEVRA())
                    relations.append(r, None, 0)

        if self.config.debug > 1:
            # print relations
            self.config.printDebug(2, "\t==== relations (%d) ==== #pre-relations #post-relations package pre-relation-packages, '*' marks prereq's" % len(relations))
            for pkg in relations:
                rel = relations[pkg]
                pre = ""
                if self.config.debug > 2 and len(rel.pre) > 0:
                    pre = ": "
                    for p in rel.pre:
                        if len(pre) > 2:
                            pre += ", "
                        if isHardRelation(rel.pre[p]):
                            pre += "*" # prereq
                        pre += p.getNEVRA()
                self.config.printDebug(2, "\t%d %d %s%s" % (len(rel.pre),
                                                            len(rel.post),
                                                            pkg.getNEVRA(),
                                                            pre))
            self.config.printDebug(2, "\t==== relations ====")

        return relations

    # ----

    def _genEraseOps(self, list):
        if len(list) == 1:
            return [(OP_ERASE, list[0])]

        # more than one in list: generate order
        return RpmOrderer(self.config, None, None, None, list).order()

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
        if pkg in used:
            return
        used[pkg] = 1
        for p in relations[pkg].pre:
            if len(path) > 0 and p in path:
                w = path[path.index(p):] # make shallow copy of loop
                w.append(pkg)
                w.append(p)
                loops.append(tuple(w))
            else:
                w = path[:] # make shallow copy of path
                w.append(pkg)
                self._detectLoops(relations, w, p, loops, used)

    # ----

    def detectLoops(self, relations):
        loops = [ ]
        used =  { }
        for pkg in relations:
            if not used.has_key(pkg):
                self._detectLoops(relations, [ ], pkg, loops, used)
        return loops

    # ----

    def genCounter(self, loops):
        counter = HashList()
        for loop in loops:
            for j in xrange(len(loop) - 1):
                # first and last pkg are the same, use once
                node = loop[j]
                next = loop[j+1]
                if node not in counter:
                    counter[node] = HashList()
                if next not in counter[node]:
                    counter[node][next] = 1
                else:
                    counter[node][next] += 1
        return counter

    # ----

    def _breakupLoop(self, relations, counter, loop, hard=0):
        # breakup loop
        virt_max_count_node = None
        virt_max_count_next = None
        virt_max_count = 0
        max_count_node = None
        max_count_next = None
        max_count = 0
        for j in xrange(len(loop) - 1):
            # first and last node (package) are the same
            node = loop[j]
            next = loop[j+1]
            if isHardRelation(relations[node].pre[next]) and not hard:
                continue
            if isVirtualRelation(relations[node].pre[next]):
                if virt_max_count < counter[node][next]:
                    virt_max_count_node = node
                    virt_max_count_next = next
                    virt_max_count = counter[node][next]
            else:
                if max_count < counter[node][next]:
                    max_count_node = node
                    max_count_next = next
                    max_count = counter[node][next]

        # prefer to drop virtual relation
        if virt_max_count_node:
            self._dropRelation(relations, virt_max_count_node,
                               virt_max_count_next, virt_max_count)
            return 1
        elif max_count_node:
            self._dropRelation(relations, max_count_node, max_count_next,
                               max_count)
            return 1

        return 0
    
    # ----

    def _dropRelation(self, relations, node, next, count):
        hard = isHardRelation(relations[node].pre[next])

        txt = "Removing"
        if hard:
            txt = "Zapping"
        if isVirtualRelation(relations[node].pre[next]):
            txt += " virtual"
        self.config.printDebug(1, "%s requires for %s from %s (%d)" % \
                   (txt, next.getNEVRA(),
                    node.getNEVRA(), count))
        del relations[node].pre[next]
        del relations[next].post[node]
        if not node in self.dropped_relations:
            self.dropped_relations[node] = [ ]
        self.dropped_relations[node].append(next)

        # add virtual relation to make sure, that next is
        # installed before p if the relation was not kicked before
        for p in relations[node].post:
            if p == next or p == node:
                continue
            if p in self.dropped_relations and \
               next in self.dropped_relations[p]:
                continue
            self.config.printDebug(1, "%s: Adding virtual requires for %s" % \
                                   (p.getNEVRA(), next.getNEVRA()))

            if not next in relations[p].pre:
                req = Relation.SOFT
                if hard and isHardRelation(relations[p].pre[node]):
                    req = Relation.HARD
                relations[p].pre[next] = Relation.VIRTUAL | req
            if not p in relations[next].post:
                relations[next].post[p] = Relation.VIRTUAL

    # ----

    def breakupLoop(self, relations, loops, loop):
        counter = self.genCounter(loops)

        # breakup soft loop
        if self._breakupLoop(relations, counter, loop, hard=0):
            return 1

        # breakup hard loop
        return self._breakupLoop(relations, counter, loop, hard=1)

    # ----

    def sortLoops(self, relations, loops):
        loop_nodes = [ ]
        for loop in loops:
            for j in xrange(len(loop) - 1):
                # first and last pkg are the same, use once
                pkg = loop[j]
                if not pkg in loop_nodes:
                    loop_nodes.append(pkg)

        loop_relations = { }
        loop_requires = { }
        for loop in loops:
            loop_relations[loop] = 0
            loop_requires[loop] = 0
            for j in xrange(len(loop) - 1):
                # first and last pkg are the same, use once
                pkg = loop[j]
                for p in relations[pkg].pre:
                    if p in loop_nodes and p not in loop:
                        # p is not in own loop, but in an other loop
                        loop_relations[loop] += 1
                for p in relations[pkg].post:
                    if p not in loop:
                        # p is not in own loop, but in an other loop
                        loop_requires[loop] += 1

        sorted = [ ]
        for loop in loop_relations:
            i = 0
            added = 0
            for i in xrange(len(sorted)):
                if (loop_relations[loop] < loop_relations[sorted[i]]) or \
                       (loop_relations[loop] == loop_relations[sorted[i]] and \
                        loop_requires[loop] > loop_requires[sorted[i]]):
                    sorted.insert(i, loop)
                    added = 1
                    break
            if added == 0:
                sorted.append(loop)            

        return sorted

    # ----

    def _separatePostLeafNodes(self, relations, list):
        while len(relations) > 0:
            i = 0
            found = 0
            while i < len(relations):
                pkg = relations[i]
                if len(relations[pkg].post) == 0:
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
            if len(rel.pre) == 0 and len(rel.post) > next_post_len:
                next = pkg
                next_post_len = len(rel.post)
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
                self.config.printDebug(2, "%d: %s" % (idx, next.getNEVRA()))
                idx += 1
            else:
                if self.config.debug > 0:
                    self.config.printDebug(1, "-- LOOP --")
                    self.config.printDebug(2, "\n===== remaining packages =====")
                    for pkg2 in relations:
                        rel2 = relations[pkg2]
                        self.config.printDebug(2, "%s" % pkg2.getNEVRA())
                        for r in rel2.pre:
                            # print nevra and flag
                            self.config.printDebug(2, "\t%s (%d)" %
                                       (r.getNEVRA(), rel2.pre[r]))
                    self.config.printDebug(2, "===== remaining packages =====\n")

                loops = self.detectLoops(relations)
                if len(loops) < 1:
                    self.config.printError("Unable to detect loops.")
                    return None
                if self.config.debug > 1:
                    self.config.printDebug(2, "Loops:")
                    for i in xrange(len(loops)):
                        str = ""
                        for pkg in loops[i]:
                            if len(str) > 0:
                                str += ", "
                            str += pkg.getNEVRA()
                        self.config.printDebug(2, "  %d: %s" % (i, str))
                sorted_loops = self.sortLoops(relations, loops)
                if self.breakupLoop(relations, loops, sorted_loops[0]) != 1:
                    self.config.printError("Unable to breakup loop.")
                    return None

        if self.config.debug > 1:
            for r in last:
                self.config.printDebug(2, "%d: %s" % (idx, r.getNEVRA()))
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
