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
be solved before the dependant package gets installed.


The second stage is detecting strongly connected components. These are maximal
groups of packages that are reachable from each other. These components are
merged into on single node in the relation graph and all relations from
outside are changed to this new node. After this the relation graph is cycle
free!

As a third stage every package get a weight assigned. The weights are designed
that the order of weights is compatible to the order given by the graph. Then
the nodes are collected in order of their weight (highest weight first).
Connected components are broken up when collected.





The final stage is to generate an opertion list with the ordered packages and
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
import time

class RpmRelation:
    """Pre and post relations for a package (a node in the dependency
    graph)."""

    SOFT    = 0 # normal requirement
    HARD    = 1 # prereq

    def __init__(self):
        self.pre = { }         # RpmPackage => flag
        self.post = { }        # RpmPackage => 1 (value is not used)
        self.weight = 0        # # of pkgs depending on this package
        self.weight_edges = 0

    def __str__(self):
        return "%d %d" % (len(self.pre), len(self.post))

    def isHard(flag):
        return (flag & RpmRelation.HARD == RpmRelation.HARD)
    isHard = staticmethod(isHard)

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
            # XXX may be raise an exception here?
            del self.list[r].post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel.post:
            del self.list[r].pre[pkg]
        del self.list[pkg]
    # ----

    def removeRelation(self, node, next, quiet=False):
        """Drop the "RpmPackage node requires RpmPackage next" arc"""

        hard = RpmRelation.isHard(self[node].pre[next])

        if not quiet:
            txt = "Removing"
            if hard:
                txt = "Zapping"

            self.config.printDebug(1, "%s requires for %s from %s" % \
                                   (txt, next.getNEVRA(), node.getNEVRA()))
        del self[node].pre[next]
        del self[next].post[node]
        if not node in self.dropped_relations:
            self.dropped_relations[node] = [ ]
        self.dropped_relations[node].append(next)

    # ----

    def separatePostLeafNodes(self, list):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list.

        Stop when each remaining package has successor (implies a dependency
        loop)."""

        i = 0
        found = 0
        while len(self) > 0:
            pkg = self[i]
            if len(self[pkg].post) == 0:
                list.append(pkg)
                self.remove(pkg)
                found = 1
            else:
                i += 1
            if i == len(self):
                if found == 0:
                    break
                i = 0
                found = 0

    # ----

    def _calculateWeights2(self, pkg, leafs):
        """For each package generate a dict of all packages that depend on it.
        At last use the length of the dict as weight.
        """
        # Uncomment weight line in ConnectedComponent.__init__() to use this
        if self[pkg].weight == 0:
            weight = { pkg : pkg }
        else:
            weight =  self[pkg].weight

        for p in self[pkg].pre:
            rel = self[p]
            if rel.weight == 0:
                rel.weight = weight.copy()
                rel.weight[p] = p
            else:
                rel.weight.update(weight)
            rel.weight_edges += 1
            if rel.weight_edges == len(rel.post):
                leafs.append(p)

        if self[pkg].weight == 0:
            self[pkg].weight = 1
        else:
            self[pkg].weight = len(weight)

    def _calculateWeights(self, pkg, leafs):
        """Weight of a package is sum of the (weight+1) of all packages
        depending on it
        """
        weight =  self[pkg].weight + 1
        for p in self[pkg].pre:
            rel = self[p]
            rel.weight += weight
            rel.weight_edges += 1
            if rel.weight_edges == len(rel.post):
                leafs.append(p)

    def calculateWeights(self):
        leafs = []
        for pkg in self:
            if not self[pkg].post: # post leaf node
                self._calculateWeights(pkg, leafs)

        while leafs:
            self._calculateWeights(leafs.pop(), leafs)

        weights = { }
        for pkg in self:
            weights.setdefault(self[pkg].weight, [ ]).append(pkg)
        return weights

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

    # ----

    def processLeafNodes(self, order, leaflist=None):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list.

        """
        if leaflist is None:
            leaflist = self # loop over all pkgs

        # do a bucket sort
        leafs = {} # len(post) -> [leaf pkgs]
        for pkg in leaflist:
            if not self[pkg].pre:
                post = len(self[pkg].post)
                leafs.setdefault(post, []).append(pkg)

        if leafs:
            max_post = max(leafs)

        while leafs:
            # remove leaf node
            leaf = leafs[max_post].pop()
            rels = self[leaf]
            self.remove(leaf)
            order.append(leaf)
            self.config.printDebug(2, "%s" % (leaf.getNEVRA()))
            # check post nodes if they got a leaf now
            new_max = max_post
            for pkg in rels.post:
                if not self[pkg].pre:
                    post = len(self[pkg].post)
                    leafs.setdefault(post, []).append(pkg)
                    if post > new_max: new_max = post
            if not leafs[max_post]:
                del leafs[max_post]
                if leafs:
                    max_post = max(leafs)
            else:
                max_post = new_max

    # ----

    def genOrder(self):
        """Order rpms in orderer.RpmRelations relations.

        Return an ordered list of RpmPackage's on success, None on error."""

        length = len(self)

        #t1 = time.time()
        self.config.printDebug(1, "Start ordering")

        order = [ ]

        last = [ ]

        if len(self)>0: # There are some loops
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

            connected_components = ConnectedComponentsDetector(self).detect(self)
            weights = self.calculateWeights()

            if len(connected_components) < 1:
                # raise AssertionError ?
                self.config.printError("Unable to detect loops.")
                return None
            if self.config.debug > 1:
                self.config.printDebug(2, "Strongly connected components:")
                for i in xrange(len(connected_components)):
                    s = ", ".join([pkg.getNEVRA() for pkg in
                                   connected_components[i].pkgs])
                    self.config.printDebug(2, "  %d: %s" % (i, s))


        weight_keys = weights.keys()
        weight_keys.sort()
        weight_keys.reverse()

        for key in weight_keys:
            if key == -1: continue
            for pkg in weights[key]:

                if isinstance(pkg, ConnectedComponent):
                    self.config.printDebug(2, "%s %s" % (key, pkg))
                    for p in pkg.pkgs:
                        self.config.printDebug(2, "\t%s" % p.getNEVRA())
                    pkg.breakUp(order)
                    self.remove(pkg)
                else:
                    self.config.printDebug(2, "%s %s" % (key, pkg.getNEVRA()))
                    self.remove(pkg)
                    order.append(pkg)

        #self.config.printDebug(0, "Ordering finished (%s s)" %
        #                       (time.time()-t1))

        print len(order), "/", length, "(", len(connected_components), ")"

        return order

    # ----

    def _operationFlag(self, flag, operation):
        """Return dependency flag for RPMSENSE_* flag during operation."""

        if isLegacyPreReq(flag) or \
               (operation == OP_ERASE and isErasePreReq(flag)) or \
               (operation != OP_ERASE and isInstallPreReq(flag)):
            return RpmRelation.HARD # hard requirement
        return RpmRelation.SOFT # soft requirement

# ----------------------------------------------------------------------------

class Loop(HashList):

    def __init__(self, relations, pkgs):
        HashList.__init__(self)
        self.relations = relations

        # start with pkg with smallest hash number
        # to be able to detect identical loops
        min_hash = None
        min_idx = 0
        for i in xrange(len(pkgs)):
            if min_hash is None or hash(pkgs[i])<min_hash:
                min_hash = hash(pkgs[i])
                min_idx = i

        for i in xrange(min_idx, len(pkgs)):
            self[pkgs[i]] = pkgs[i]
        for i in xrange(min_idx):
            self[pkgs[i]] = pkgs[i]

    # ----

    def __cmp__(self, other):
        """compare loops:

        Sort by size first, use hash values of the pkgs from te beginning then
        """
        result = cmp(len(self), len(other))
        if result == 0:
            for i in xrange(len(self)): # both have same lenght
                result = cmp(hash(self[i]), hash(other[i]))
                if result != 0:
                    return result
        return result

    # ----

    def __iter__(self):
        """Return Iterator. Iterator returns (Node, Next) Tuples.
        """
        idx = 1
        while idx < len(self):
            yield (self.list[idx-1], self.list[idx])
            idx += 1
        yield (self.list[-1], self.list[0])

    # ----

    def containsRequirement(self, pkg, pre):
        if pkg in self and pre in self:
            idx = self.index(pre)
            return self[idx-1] is pkg
        return False

    # ----

    def containsHardRequirement(self):
        """Does the loop contain any hard relations"""
        for pkg, pre in self:
            if RpmRelation.isHard(self.relations[pkg].pre[pre]):
                return True
        return False

    # ----

    def breakUp(self):
        """Searches for the relation that has the maximum distance
        from hard requirements and removes it.
        Returns (Node, Next) of the removed requirement.

        Assumes self.containsHardRequirement() == True"""

        # find the requirement that has the largest distance
        # to a hard requirement

        distances = [0]
        for pkg, pre in self:
            if RpmRelation.isHard(self.relations[pkg].pre[pre]):
                distances.append(0)
            else:
                distances.append(distances[-1]+1)

        for idx in xrange(len(distances)):
            if distances[idx] == 0 and idx > 0:
                break
            else:
                distances[idx] += distances[-1]

        max = -1
        max_idx = 0
        for idx in xrange(len(distances)):
            if distances[idx]>max:
                max = distances[idx]
                max_idx = idx

        self.relations.removeRelation(self[max_idx-1], self[max_idx])

        return (self[max_idx-1], self[max_idx])

# ----------------------------------------------------------------------------

class ConnectedComponent:
    """Contains a Strongly Connected Component (SCC).
    This is a number (maximal) number of nodes that are all reachable from
    each other. In other words the components consists of loops touching
    each other.

    Automatically changes all relations of its pkgs from/to outside the
    component to itself. After all components have been created the graph
    is cycle free.

    Mimics RpmPackage.
    """

    def __init__(self, relations, pkgs):
        """relations: the RpmRelations object containing the loops
        """

        self.relations = relations

        relations.append(self, None, 0)

        self.pkgs = { }
        for pkg in pkgs:
            self.pkgs[pkg] = pkg
            relations[pkg].weight = -1

        for pkg in pkgs:
            to_remove = [ ]
            for pre in relations[pkg].pre:
                if not pre in self.pkgs:
                    to_remove.append(pre)

            for p in to_remove:
                flag = relations[pkg].pre[p]
                relations.removeRelation(pkg, p, quiet=True)
                relations.append(self, p, flag)


            to_remove = [ ]
            for post in relations[pkg].post:
                if not post in self.pkgs:
                    to_remove.append(post)

            for p in to_remove:
                flag = relations[pkg].post[p]
                relations.removeRelation(p, pkg, quiet=True)
                relations.append(p, self, flag)

        relations[self].weight = len(self.pkgs)
        # uncomment for use of the dict based weight algorithm
        # relations[self].weight = self.pkgs.copy()


    # ----

    def __len__(self):
        return len(self.pkgs)

    # ----

    def __str__(self):
        return repr(self)

    # ----

    def getNEVRA(self):
        return "Component: " + ",".join([pkg.getNEVRA() for pkg in self.pkgs])

    # ----

    def detectLoops(self):
        """Sets self.loops.
        self.loops is sorted with Loop.__cmp__() and the loops are unique.
        """

        loops = [ ]
        self._detectLoops([ ], self.pkgs.iterkeys().next(), loops)
        # remove duplicates
        loops.sort()
        previous = Loop(self.relations, [])
        self.loops = []
        for loop in loops:
            if loop != previous:
                self.loops.append(loop)
            previous = loop

    # ----

    def _detectLoops(self, path, pkg, loops):
        """Do a DFS walk in orderer.RpmRelations relations from RpmPackage pkg,
        add discovered loops to loops.

        The list of RpmPackages path contains the path from the search root to
        the current package.  loops is a list of Loop objects.
        """

        for p in self.relations[pkg].pre:
            # "p in path" is O(N), can be O(1) with another hash.
            if len(path) > 0 and p in path:
                w = path[path.index(p):] # make shallow copy of loop
                w.append(pkg)
                w.append(p)
                loops.append(Loop(self.relations, w))
            else:
                path.append(pkg)
                self._detectLoops(path, p, loops)
                path.pop()

    # ----

    def isLeaf(self):
        """Return if any package within the component depends on packages
        that are not part of the component itself.
        """

        return not self.relations[self].pre

    # ----

    def processLeafNodes(self, order):
        """Remove all leaf nodes with the component and append them to order
        """
        while True:
            # Without the requirement of max(rel.pre) this could be O(1)
            next = None
            next_post_len = -1
            for pkg in self.pkgs:
                if (len(self.relations[pkg].pre) == 0 and
                    len(self.relations[pkg].post) > next_post_len):
                    next = pkg
                    next_post_len = len(self.relations[pkg].post)
            if next:
                self.relations.remove(next)
                order.append(next)
                del self.pkgs[next]
            else:
                return

    # ----

    def removeSubComponent(self, component):
        """Remove all packages of a sub component from own package list"""
        for pkg in component.pkgs:
            del self.pkgs[pkg]

    # ----

    def genCounter(self):
        """Count number of times each arcs is represented in the list of loop
        tuples loops.

        Return a HashList: RpmPackage A =>
        HashList :RpmPackage B => number of loops in which A requires B."""

        counter = HashList()
        for loop in self.loops:
            for node, next in loop:
                # first and last pkg are the same, use once
                if node not in counter:
                    counter[node] = HashList()
                if next not in counter[node]:
                    counter[node][next] = 1
                else:
                    counter[node][next] += 1
        return counter

    # ----

    def breakUp(self, order):
        """Remove this component from the graph by breaking it apart.

        Assumes that the LoopGroup is a leaf
        """

        self.detectLoops()

        hardloops = [l for l in self.loops
                     if l.containsHardRequirement()]

        if hardloops:
            # loops with hard requirements found!
            # break up  one of these loops and recursivly try again

            # break up smallest loop
            pkg, pre = hardloops[0].breakUp()

            self.processLeafNodes(order)

            components = ConnectedComponentsDetector(self.relations).detect(self.pkgs)
            while components:
                found = False
                for component in components:
                    if component.isLeaf():
                        self.removeSubComponent(component)
                        component.breakUp(order)
                        components.remove(component)
                        self.relations.remove(component)
                        found = True
                        break
                if not found:
                    self.config.printError("Can't find leaf component!")
                    raise AssertionError  # XXX
                self.processLeafNodes(order)
        else:
            # No loops with hard requirements found, breaking up everything
            while self.loops:
                # find most used relation
                counter = self.genCounter()

                max_count_node = None
                max_count_next = None
                max_count = 0

                for node in counter:
                    for next in counter[node]:
                        if counter[node][next] > max_count:
                             max_count_node = node
                             max_count_next = next
                             max_count = counter[node][next]

                self.relations.removeRelation(max_count_node, max_count_next)
                # remove loops that got broken up
                self.loops = [l for l in self.loops
                         if not l.containsRequirement(max_count_node,
                                                      max_count_next)]
            # collect the nodes after all loops got broken up
            self.processLeafNodes(order)

# ----------------------------------------------------------------------------

class ConnectedComponentsDetector:
    '''Use Gabow algorithm to detect strongly connected components:
        Do a depth first traversal and number the nodes.
        "root node": the node of a SCC that is visited first
        Keep two stacks:
          1. stack of all still possible root nodes
          2. stack of all visited but still unknown nodes (pkg stack)
        If we reach a unknown node just descent.
        If we reach an unprocessed node it has a smaller number than the
         node we came from and all nodes with higher numbers than this
         node can be reach from it. So we must remove those nodes
         from the root stack.
        If we reach a node already processed (part of a SCC (of possibly
         only one node size)) there is no way form this node to our current.
         Just ignore this way.
        If we go back in the recusion the following can happen:
        1. Our node has been removed from the root stack. It is part of a
           SCC -> do nothing
        2. Our node is top on the root stack: the pkg stack contains a SCC
           from the position of our node up -> remove it including our node
           also remove the node from the root stack
        '''

    def __init__(self, relations):
        self.relations = relations

    # ----

    def detect(self, pkgs):
        """Returns a list of all strongly ConnectedComponents"""
        self.states = {} # attach numbers to packages
        self.root_stack = [] # stack of possible root nodes
        self.pkg_stack = [] # stack of all nodes visited and not processed yet
        self.sccs = [] # already found strongly connected components
        self.pkg_cnt = 0 # number of current package

        # continue until all nodes have been visited
        for pkg in pkgs:
            if not self.states.has_key(pkg):
                self._process(pkg)
        return [ConnectedComponent(self.relations, pkgs) for pkgs in self.sccs]

    # ----

    def _process(self, pkg):
        """Descent recursivly"""
        states = self.states
        root_stack = self.root_stack
        pkg_stack = self.pkg_stack

        self.pkg_cnt += 1
        states[pkg] = self.pkg_cnt
        # push pkg to both stacks
        pkg_stack.append(pkg)
        root_stack.append(pkg)

        for next in self.relations[pkg].pre:
            if states.has_key(next):
                if states[next] > 0:
                    # if visited but not finished
                    # remove all pkgs with higher number from root stack
                    i = len(root_stack)-1
                    while i >= 0 and states[root_stack[i]] > states[next]:
                        i -= 1
                    del root_stack[i+1:]
            else:
                # visit
                self._process(next)

        # going up in the recursion
        # if pkg is a root node (top on root stack)
        if root_stack[-1] is pkg:
            if pkg_stack[-1] is pkg:
                # only one node SCC, drop it
                pkg_stack.pop()
                states[pkg] = 0 # set to "already processed"
            else:
                # get non trivial SCC from stack
                idx = pkg_stack.index(pkg)
                scc = pkg_stack[idx:]
                del pkg_stack[idx:]
                for p in scc:
                    states[p] = 0 # set to "already processed"
                self.sccs.append(scc)
            root_stack.pop()

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
