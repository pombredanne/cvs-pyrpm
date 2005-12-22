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

"""
The RpmOrderer
--------------

The orderer gets lists of packages, which have to get installed, the list of
updates, the obsoletes and the erases from a previous running RpmResolver.
With these lists, the orderer is feeding a resolver. The orderer is looking
only at the changes for a installation. The packages, which will be the same
before and after the installation, update or erase, have no effect on the
ordering of the changes. The ordering is first done for the installes and
then for the erases in reverse order. Two packages A and B where both get
erased and package A has a erase dependency on package B, package B has to
get removed before package A.

At first, the orderer is creating a relation structure, where a relation
describes the dependance of a package from another. This relation structure
is a dependency tree. There are two kinds of relations: soft and hard. A soft
relation is a normal dependency, which has to be solved after package
installation at runtime. The hard relation is a pre requirement, which has to
be solved before the dependant package gets installed. For the ordering
process, there is an additional sub-kind: virtual. When there is a loop of
relations, it has to get broken up. If a loop gets broken up, the orderer has
to take care, that removed relations do not drop away. If package A has a
relation to package B and this relation has to get removed to breakup a loop,
this relation is transferred to all packages which have a relation to A as a
virtual relation. A virtual relation can be either soft or hard, like a
normal relation, depending on the removed relation from A to B and the
relation from C to A. If both relations are hard, the virtual relation also
becomes hard.

The second stage is the ordering. At first all post leaf nodes in the relation
tree are moved to a new list. A post leaf node is a package, which has no
dependant packages. This is done, till there are no more post leaf nodes. The
order of the moved packages is important. Here is an exmaple: A -> B -> C -> D
Package A depends on package B, which depends on C and so on. At first package
A gets moved to the list, then B, then C and at least D. If there are no more
leaf nodes and the tree is not empty, there have to be loops in the tree. This
does not mean that there are only loops, there can be lots of packages in
there, which require a package, which is part of a loop. If the tree is empty,
the ordering is done, but if there are any, then these loops has to get broken
up. The simplest loop is that package A depends on package B and package B
depends on package A. If both relations are soft (a soft loop), the one which
is part of the most loops gets removed, if both have the same count, the fist
is used. If one is hard and the other one soft, the soft relation is the one,
but if both are hard (a hard loop), one of them has to get dropped. This loop
will be broken up like a soft loop. A hard loop is a bad thing and should
never happen, but it could. A hard loop is a result of packaging problems. The
breakup of a virtual relation has priority to breaking up any other relation
and is done according to the same rules of hard and soft relations.
When all loops are detected, these loops get sorted according to the number of
relations from other packages in the relation tree to all nodes in the loop.
The loop with the most dependant packages gets on top of that list. This loop
is the one, which gets broken up, because it might free most other dependant
packages.

The third stage is to generate an opertion list with the ordered packages and
which takes the updates and obsoletes list into consideration. The operation
list is a list of tupels, where each tupel is of the form (operation, package).
The operation is either "install", "update" or "erase".
For a package, which gets updated, and which is in the update or obsolete list
(which is an update for one or more installed packages or which obsoletes one
or more installed packages) an orderer is generated to order all the packages,
which get removed according to the updates and obsoletes list. The package
itself is put into the operation list and then the corresponding erases.
"""

from hashlist import HashList
from base import *
from resolver import RpmResolver
import database

class RpmRelation:
    """Pre and post relations for a package (a node in the dependency
    graph)."""

    SOFT    = 0 # normal requirement
    HARD    = 1 # prereq
    VIRTUAL = 2 # added by _dropRelation

    def __init__(self):
        self.pre = { }                  # RpmPackage => flag
        self.post = { }        # RpmPackage => 1 or VIRTUAL (value is not used)

    def __str__(self):
        return "%d %d" % (len(self.pre), len(self.post))

    def isHard(flag):
        return (flag & RpmRelation.HARD == RpmRelation.HARD)
    isHard = staticmethod(isHard)

    def isVirtual(flag):
        return (flag & RpmRelation.VIRTUAL == RpmRelation.VIRTUAL)
    isVirtual = staticmethod(isVirtual)

# ----

class RpmRelations:
    """List of relations for each package (a dependency graph)."""

    def __init__(self, config, rpms, operation):
        self.config = config
        self.list = HashList()          # RpmPackage => RpmRelation
        self.__len__ = self.list.__len__
        self.__getitem__ = self.list.__getitem__
        self.has_key = self.list.has_key

        # RpmPackage =>
        # [list of required RpmPackages that were dropped to break a loop]
        self.dropped_relations = { }

        db = database.memorydb.RpmMemoryDB(self.config, None)
        db.addPkgs(rpms)
        resolver = RpmResolver(self.config, db, nocheck=1)

        for pkg in db.getPkgs():
            self.config.printDebug(1, "Generating relations for %s" % \
                                   pkg.getNEVRA())
            resolved = resolver.getResolvedPkgDependencies(pkg)
            # ignore unresolved, we are only looking at the changes,
            # therefore not all symbols are resolvable in these changes
            l = len(self)
            for ((name, flag, version), s) in resolved:
                if name.startswith("config("): # drop config requirements
                    continue
                f = self._operationFlag(flag, operation)
                for pkg2 in s:
                    if pkg2 == pkg:
                        continue
                    self.append(pkg, pkg2, f)
            if len(self) == l:
                # if there are no new relations, then pkg has either no
                # relations or only self-relations
                self.config.printDebug(1, "No relations found for %s, " % \
                                       pkg.getNEVRA() + \
                                       "generating empty relations")
                self.append(pkg, None, 0)

        del db
        del resolver

        if self.config.debug > 1:
            # print relations
            self.config.printDebug(2, "\t==== relations (%d) " % len(self) +\
                                   "==== #pre-relations #post-relations " + \
                                   "package pre-relation-packages, " +\
                                   "'*' marks prereq's")
            for pkg in self:
                rel = self[pkg]
                pre = ""
                if self.config.debug > 2 and len(rel.pre) > 0:
                    pre = ": "
                    for p in rel.pre:
                        if len(pre) > 2:
                            pre += ", "
                        if RpmRelation.isHard(rel.pre[p]):
                            pre += "*" # prereq
                        pre += p.getNEVRA()
                self.config.printDebug(2, "\t%d %d %s%s" % \
                                       (len(rel.pre), len(rel.post),
                                        pkg.getNEVRA(), pre))
            self.config.printDebug(2, "\t==== relations ====")

    # ----

    def append(self, pkg, pre, flag):
        """Add an arc from RpmPackage pre to RpmPackage pkg with flag.

        pre can be None to add pkg to the graph with no arcs."""

        if pre == pkg:
            return
        i = self.list[pkg]
        if i == None:
            i = RpmRelation()
            self.list[pkg] = i
        if pre == None:
            return # no additional things to do for empty relations
        if pre not in i.pre or RpmRelation.isHard(flag):
            # prefer hard requirements, do not overwrite with soft req
            i.pre[pre] = flag
            if not pre in self.list:
                self.list[pre] = RpmRelation()
            self.list[pre].post[pkg] = 1

    # ----

    def remove(self, pkg):
        """Remove RpmPackage pkg from the dependency graph"""

        rel = self.list[pkg]
        # remove all post relations for the matching pre relation packages
        for r in rel.pre:
            del self.list[r].post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel.post:
            del self.list[r].pre[pkg]
        del self.list[pkg]

    # ----

    def detectLoops(self):
        """Return a list of loops in orderer.RpmRelations relations.

        Each loop is represented by a tuple in reverse dependency order,
        starting and ending with the same RpmPackage.  The loops each differ
        in at least one package, but one package can be in more than one loop
        (e.g. ABA, ACA)."""

        loops = [ ]
        used =  { }
        for pkg in self:
            if not used.has_key(pkg):
                self._detectLoops([ ], pkg, loops, used)
        return loops

    # ----

    def _detectLoops(self, path, pkg, loops, used):
        """Do a DFS walk in orderer.RpmRelations relations from RpmPackage pkg,
        add discovered loops to loops.

        The list of RpmPackages path contains the path from the search root to
        the current package.  loops is a list of RpmPackage tuples, each tuple
        contains a loop.  Use hash used (RpmPackage => 1) to mark visited
        nodes.

        The tuple in loops starts and ends with the same RpmPackage.  The
        nodes in the tuple are in reverse dependency order (B is in
        relations[A].pre)."""

        if pkg in used:
            return
        used[pkg] = 1
        for p in self[pkg].pre:
            # "p in path" is O(N), can be O(1) with another hash.
            if len(path) > 0 and p in path:
                w = path[path.index(p):] # make shallow copy of loop
                w.append(pkg)
                w.append(p)
                loops.append(tuple(w))
            else:
                w = path[:] # make shallow copy of path
                w.append(pkg)
                self._detectLoops(w, p, loops, used)
                # or just path.pop() instead of making a copy?

    # ----

    def breakupLoop(self, loops, loop):
        """Remove an arc from loop tuple loop in loops from
        orderer.RpmRelations relations.

        Return 1 on success, 0 on failure."""

        counter = self.genCounter(loops)

        # breakup soft loop
        if self._breakupLoop(counter, loop, hard=0):
            return 1

        # breakup hard loop; should never fail
        return self._breakupLoop(counter, loop, hard=1)

    # ----

    def _breakupLoop(self, counter, loop, hard=0):
        """Remove an arc in loop tuple loop from orderer.RpmRelations
        relations..

        Return 1 on success, 0 if no arc to break was found.  Use counter from
        genCounter.  Remove hard arcs only if hard."""

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
            if RpmRelation.isHard(self[node].pre[next]) and not hard:
                continue
            if RpmRelation.isVirtual(self[node].pre[next]):
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
            self._dropRelation(virt_max_count_node, virt_max_count_next,
                               virt_max_count)
            return 1
        elif max_count_node:
            self._dropRelation(max_count_node, max_count_next, max_count)
            return 1

        return 0

    # ----

    def genCounter(self, loops):
        """Count number of times each arcs is represented in the list of loop
        tuples loops.

        Return a HashList: RpmPackage A =>
        HashList :RpmPackage B => number of loops in which A requires B."""

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

    def _dropRelation(self, node, next, count):
        """Drop the "RpmPackage node requires RpmPackage next" arc, this
        requirement appears count times in current loops in
        orderer.RpmRelations relations.

        To preserve X->node->next, try to add virtual arcs X->next."""

        hard = RpmRelation.isHard(self[node].pre[next])

        txt = "Removing"
        if hard:
            txt = "Zapping"
        if RpmRelation.isVirtual(self[node].pre[next]):
            txt += " virtual"
        self.config.printDebug(1, "%s requires for %s from %s (%d)" % \
                   (txt, next.getNEVRA(), node.getNEVRA(), count))
        del self[node].pre[next]
        del self[next].post[node]
        if not node in self.dropped_relations:
            self.dropped_relations[node] = [ ]
        self.dropped_relations[node].append(next)

        # add virtual relation to make sure, that next is
        # installed before p if the relation was not kicked before
        for p in self[node].post:
            if p == next or p == node:
                continue
            if p in self.dropped_relations and \
               next in self.dropped_relations[p]:
                continue
            self.config.printDebug(1, "%s: Adding virtual requires for %s" % \
                                   (p.getNEVRA(), next.getNEVRA()))

            if not next in self[p].pre:
                req = RpmRelation.SOFT
                if hard and RpmRelation.isHard(self[p].pre[node]):
                    req = RpmRelation.HARD
                self[p].pre[next] = RpmRelation.VIRTUAL | req
            if not p in self[next].post:
                self[next].post[p] = RpmRelation.VIRTUAL

    # ----

    def sortLoops(self, loops):
        """Return a copy loop tuple list loops from order.RpmRelations
        relations, ordered by decreasing preference to break them."""

        loop_nodes = [ ] # All nodes in loops
        for loop in loops:
            for j in xrange(len(loop) - 1):
                # first and last pkg are the same, use once
                pkg = loop[j]
                if not pkg in loop_nodes:
                    loop_nodes.append(pkg)

        # loop => number of packages required from other loops
        loop_relations = { }
        loop_requires = { } # loop => number of packages requiring the loop
        for loop in loops:
            loop_relations[loop] = 0
            loop_requires[loop] = 0
            for j in xrange(len(loop) - 1):
                # first and last pkg are the same, use once
                pkg = loop[j]
                for p in self[pkg].pre:
                    if p in loop_nodes and p not in loop:
                        # p is not in own loop, but in an other loop
                        loop_relations[loop] += 1
                for p in self[pkg].post:
                    if p not in loop:
                        # p is not in own loop, but in an other loop
                        loop_requires[loop] += 1

        sorted = [ ]
        for loop in loop_relations:
            for i in xrange(len(sorted)):
                if (loop_relations[loop] < loop_relations[sorted[i]]) or \
                       (loop_relations[loop] == loop_relations[sorted[i]] and \
                        loop_requires[loop] > loop_requires[sorted[i]]):
                    sorted.insert(i, loop)
                    break
            else:
                sorted.append(loop)

        return sorted

    # ----

    def separatePostLeafNodes(self, list):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list.

        Stop when each remaining package has successor (implies a dependency
        loop)."""

        # This is O(N * M * hash lookup), can be O(M * hash lookup)
        while len(self) > 0:
            i = 0
            found = 0
            while i < len(self):
                pkg = self[i]
                if len(self[pkg].post) == 0:
                    list.insert(0, pkg)
                    self.remove(pkg)
                    found = 1
                else:
                    i += 1
            if found == 0:
                break

    # ----

    def getNextLeafNode(self):
        """Return a node from orderer.RpmRelations relations which has no
        predecessors.

        Return None if there is no such node, otherwise select a node on which
        depend the maximum possible number of other nodes."""

        # Without the requirement of max(rel.pre) this could be O(1)
        next = None
        next_post_len = -1
        for pkg in self:
            rel = self[pkg]
            if len(rel.pre) == 0 and len(rel.post) > next_post_len:
                next = pkg
                next_post_len = len(rel.post)
        return next

    # ----

    def orderIterationFunc(self):
        """ Overload this function to get a call into the order process
        each time the iteration starts."""
        # Remember: Do not change any contents!
        return

    # ---

    def orderLoopFunc(self, loops):
        """ Overload this function to get a call into the order process
        each time loops are detected."""
        # Remember: Do not change any contents!
        return

    # ---

    def genOrder(self):
        """Order rpms in orderer.RpmRelations relations.

        Return an ordered list of RpmPackage's on success, None on error."""

        order = [ ]
        idx = 1
        last = [ ]
        while len(self) > 0:
            # for each iteration, call orderIterationFunc
            # see function description
            self.orderIterationFunc()

            # remove and save all packages without a post relation in reverse
            # order
            # these packages will be appended later to the list
            self.separatePostLeafNodes(last)

            if len(self) == 0:
                break

            next = self.getNextLeafNode()
            if next != None:
                order.append(next)
                self.remove(next)
                self.config.printDebug(2, "%d: %s" % (idx, next.getNEVRA()))
                idx += 1
            else:
                if self.config.debug > 0:
                    self.config.printDebug(1, "-- LOOP --")
                    self.config.printDebug(2,
                                           "\n===== remaining packages =====")
                    for pkg2 in self:
                        rel2 = self[pkg2]
                        self.config.printDebug(2, "%s" % pkg2.getNEVRA())
                        for r in rel2.pre:
                            # print nevra and flag
                            self.config.printDebug(2, "\t%s (%d)" %
                                       (r.getNEVRA(), rel2.pre[r]))
                    self.config.printDebug(2,
                                           "===== remaining packages =====\n")

                loops = self.detectLoops()
                if len(loops) < 1:
                    # raise AssertionError ?
                    self.config.printError("Unable to detect loops.")
                    return None
                if self.config.debug > 1:
                    self.config.printDebug(2, "Loops:")
                    for i in xrange(len(loops)):
                        s = ", ".join([pkg.getNEVRA() for pkg in loops[i]])
                        self.config.printDebug(2, "  %d: %s" % (i, s))
                sorted_loops = self.sortLoops(loops)

                # for loop detection, call orderLoopFunc
                # see function description
                self.orderLoopFunc(sorted_loops)
                
                if self.breakupLoop(loops, sorted_loops[0]) != 1:
                    self.config.printError("Unable to breakup loop.")
                    return None

        if self.config.debug > 1:
            for r in last:
                self.config.printDebug(2, "%d: %s" % (idx, r.getNEVRA()))
                idx += 1

        return (order + last)

    # ----

    def _operationFlag(self, flag, operation):
        """Return dependency flag for RPMSENSE_* flag during operation."""

        if isLegacyPreReq(flag) or \
               (operation == OP_ERASE and isErasePreReq(flag)) or \
               (operation != OP_ERASE and isInstallPreReq(flag)):
            return RpmRelation.HARD # hard requirement
        return RpmRelation.SOFT # soft requirement

# ----------------------------------------------------------------------------

class RpmOrderer:
    def __init__(self, config, installs, updates, obsoletes, erases):
        """Initialize.

        installs is a list of added RpmPackage's
        erases a list of removed RpmPackage's (including updated/obsoleted)
        updates is a hash: new RpmPackage => ["originally" installed RpmPackage
        	removed by update]
        obsoletes is a hash: new RpmPackage => ["originally" installed
        	RpmPackage removed by update]
        installs, updates and obsoletes can be None."""

        self.config = config
        self.installs = installs
        self.updates = updates
        # Only explicitly removed packages, not updated/obsoleted
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

    # ----

    def _genEraseOps(self, list):
        """Return a list of (operation, RpmPackage) for erasing RpmPackage's
        in list."""

        if len(list) == 1:
            return [(OP_ERASE, list[0])]

        # more than one in list: generate order
        return RpmOrderer(self.config, None, None, None, list).order()

    # ----

    def genOperations(self, order):
        """Return a list of (operation, RpmPackage) tuples from ordered list of
        RpmPackage's order."""

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

    def genOrder(self):
        """Return an ordered list of RpmPackage's, first installs, then
        erases.

        Return None on error."""

        order = [ ]

        # order installs
        if self.installs and len(self.installs) > 0:
            if len(self.installs) == 1:
                # special case: one package to install, no ordering required
                order.extend(self.installs)
            else:
                # generate relations
                relations = RpmRelations(self.config, self.installs,
                                         OP_INSTALL)

                # order package list
                order2 = relations.genOrder()
                if order2 == None:
                    return None
                order.extend(order2)
        # order erases
        if self.erases and len(self.erases) > 0:
            if len(self.erases) == 1:
                # special case: one package to erase, no ordering required
                order.extend(self.erases)
            else:
                # generate relations
                relations = RpmRelations(self.config, self.erases, OP_ERASE)

                # order package list
                order2 = relations.genOrder()
                if order2 == None:
                    return None
                order2.reverse()
                order.extend(order2)

        return order

    # ----

    def order(self):
        """Order operations.

        Return an ordered list of operations on success, with tuples of the
        form (operation, RpmPackage). The operation is one of OP_INSTALL,
        OP_UPDATE or OP_ERASE per package.
        If an error occurs, return None."""

        order = self.genOrder()
        if order == None:
            return None

        # generate operations
        return self.genOperations(order)

# vim:ts=4:sw=4:showmatch:expandtab
