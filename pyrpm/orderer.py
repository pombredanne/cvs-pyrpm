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
only at the changes for an installation. The packages, which will be the same
before and after the installation, update or erase, have no effect on the
ordering of the changes. The ordering is first done for the installs and
then for the erases in reverse order. Two packages A and B where both get
erased and package A has a erase dependency on package B, package B has to
get removed before package A.

At first, the orderer is creating a relation structure, where a relation
describes the dependence of a package from another. This relation structure
is a dependency tree. There are two kinds of relations: soft and hard. A soft
relation is a normal dependency, which has to be solved after package
installation at runtime. The hard relation is a pre requirement, which has to
be solved before the dependent package gets installed.


The second stage is detecting strongly connected components. These are maximal
groups of packages that are reachable from each other. These components are
merged into on single node in the relation graph and all relations from
outside are changed to this new node. After this the relation graph is cycle
free!

After this we can collect the leaf packages until all packages are processed.
When collecting a connected component it is broken up and the containing
packages are collected.

The final stage is to generate an operation list with the ordered packages and
which takes the updates and obsoletes list into consideration. The operation
list is a list of tuples, where each tuple is of the form (operation, package).
The operation is either "install", "update" or "erase".
For a package, which gets updated, and which is in the update or obsolete list
(which is an update for one or more installed packages or which obsoletes one
or more installed packages) an orderer is generated to order all the packages,
which get removed according to the updates and obsoletes list. The package
itself is put into the operation list and then the corresponding erases.


Weight based collection strategies
==================================

One way to collect packages is to assign weights to them and collect them in
the reversed order of the weights. To make this work every package must have
a higher weight than all packages depending on it.

Possible weights are:

 * Number of packages depending on the package
 * maximal path from a leaf node

"""

from hashlist import HashList
from base import *
from resolver import RpmResolver
import database
from database.rpmexternalsearchdb import RpmExternalSearchDB
from logger import log

def operationFlag(flag, operation):
    """Return dependency flag for RPMSENSE_* flag during operation."""
    if isLegacyPreReq(flag) or \
           (operation == OP_ERASE and isErasePreReq(flag)) or \
           (operation != OP_ERASE and isInstallPreReq(flag)):
        return 1    # hard requirement
    return 0        # soft requirement

class RpmRelation:
    """Pre and post relations for a package (a node in the dependency
    graph)."""

    def __init__(self):
        self.pre = { }         # RpmPackage => flag
        self.post = { }        # RpmPackage => 1 (value is not used)
        self.weight = 0        # # of pkgs depending on this package
        self.weight_edges = 0

    def __str__(self):
        return "%d %d" % (len(self.pre), len(self.post))


class RpmRelations:
    """List of relations for each package (a dependency graph)."""

    def __init__(self, config, rpms, operation, externaldb=None):
        self.config = config
        self.list = HashList()          # RpmPackage => RpmRelation
        self.__len__ = self.list.__len__
        self.__getitem__ = self.list.__getitem__
        self.has_key = self.list.has_key
        self.genRelations(rpms, operation, externaldb)

    def genRelations(self, rpms, operation, externaldb=None):
        # clear list to get to a sane state
        self.list.clear()

        # add relations for all packages
        for pkg in rpms:
            self.list[pkg] = RpmRelation()

        # Build a new resolver to list all dependencies between packages.
        if externaldb:
            db = RpmExternalSearchDB(externaldb, self.config, None)
        else:
            db = database.memorydb.RpmMemoryDB(self.config, None)
        db.addPkgs(rpms)
        resolver = RpmResolver(self.config, db, nocheck=1)

        # Add dependencies:
        for pkg in db.getPkgs():
            log.info3Ln("Generating relations for %s", pkg.getNEVRA())
            resolved = resolver.getResolvedPkgDependencies(pkg)
            # ignore unresolved, we are only looking at the changes,
            # therefore not all symbols are resolvable in these changes
            for ((name, flag, version), s) in resolved:
                if name[:7] == "config(":
                    continue
                f = operationFlag(flag, operation)
                for pkg2 in s:
                    if pkg2 != pkg:
                        self.addRelation(pkg, pkg2, f)

        self.printRel()

    # ----

    def printRel(self):
        """Print relations."""
        if not log.isLoggingHere(log.DEBUG4):
            return
        log.debug4Ln("\t==== relations (%d) "
                     "==== #pre-relations #post-relations "
                     "package pre-relation-packages, '*' marks prereq's",
                     len(self))
        for pkg in self:
            rel = self[pkg]
            pre = ""
            if len(rel.pre) > 0:
                pre = ": "
                for p in rel.pre:
                    if len(pre) > 2:
                        pre += ", "
                    if rel.pre[p]:
                        pre += "*" # prereq
                    pre += p.getNEVRA()
            log.debug4Ln("\t%d %d %s%s",
                         len(rel.pre), len(rel.post), pkg.getNEVRA(), pre)
        log.debug4Ln("\t==== relations ====")

    # ----

    def addRelation(self, pkg, pre, flag):
        """Add an arc from RpmPackage pre to RpmPackage pkg with flag.
        pre can be None to add pkg to the graph with no arcs."""
        i = self.list[pkg]
        if flag or pre not in i.pre:
            # prefer hard requirements, do not overwrite with soft req
            i.pre[pre] = flag
            self.list[pre].post[pkg] = 1

    # ----

    def remove(self, pkg):
        """Remove RpmPackage pkg from the dependency graph."""
        rel = self.list[pkg]
        # remove all post relations for the matching pre relation packages
        for r in rel.pre:
            del self.list[r].post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel.post:
            del self.list[r].pre[pkg]
        del self.list[pkg]

    # ----

    def removeRelation(self, node, next, quiet=False):
        """Drop the "RpmPackage node requires RpmPackage next" arc."""
        if not quiet:
            txt = "Removing"
            if self[node].pre[next]:
                txt = "Zapping"
            log.debug4Ln("%s requires for %s from %s",
                       txt, next.getNEVRA(), node.getNEVRA())
        del self[node].pre[next]
        del self[next].post[node]

    # ----

    def collect(self, pkg, order):
        """Move package from the relations graph to the order list
        Handle ConnectedComponent."""
        if isinstance(pkg, ConnectedComponent):
            pkg.breakUp(order)
        else:
            order.append(pkg)
        self.remove(pkg)

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
        At last use the length of the dict as weight."""
        # Uncomment weight line in ConnectedComponent.__init__() to use this
        if self[pkg].weight == 0:
            weight = { pkg : pkg }
        else:
            weight = self[pkg].weight

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

    # ----

    def _calculateWeights(self, pkg, leafs):
        """Weight of a package is sum of the (weight+1) of all packages
        depending on it."""
        weight = self[pkg].weight + 1
        for p in self[pkg].pre:
            rel = self[p]
            rel.weight += weight
            rel.weight_edges += 1
            if rel.weight_edges == len(rel.post):
                leafs.append(p)

    # ----

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

    def processLeafNodes(self, order, leaflist=None):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list."""
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
            self.collect(leaf, order)
            log.debug4Ln("%s", leaf.getNEVRA())
            # check post nodes if they got a leaf now
            new_max = max_post
            for pkg in rels.post:
                if not self[pkg].pre:
                    post = len(self[pkg].post)
                    leafs.setdefault(post, []).append(pkg)
                    if post > new_max:
                        new_max = post
            # select new (highest) bucket
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

        log.info2Ln("Start ordering")

        order = [ ]

        connected_components = ConnectedComponentsDetector(self).detect(self)

        if connected_components:
            if log.isLoggingHere(log.DEBUG1):
                # debug output the components
                log.debug1Ln("-- STRONGLY CONNECTED COMPONENTS --")
                for i in xrange(len(connected_components)):
                    s = ", ".join([pkg.getNEVRA() for pkg in
                                   connected_components[i].pkgs])
                    log.debug1Ln("  %d: %s", i, s)

#         weights = self.calculateWeights()
#         weight_keys = weights.keys()
#         weight_keys.sort()
#         weight_keys.reverse()

#         for key in weight_keys:
#             if key == -1: continue
#             for pkg in weights[key]:
#                 log.debug2Ln("%s %s", key, pkg.getNEVRA())
#                 self.collect(pkg, order)

        self.processLeafNodes(order)

        if len(order) != length:
            log.errorLn("%d Packages of %d in order list! Number of connected components: %d ",
                len(order), length,
                len(connected_components))

        return order

# ----------------------------------------------------------------------------

class ConnectedComponent:
    """Contains a Strongly Connected Component (SCC).
    This is a (maximal) set of nodes that are all reachable from
    each other. In other words the component consists of loops touching
    each other.

    Automatically changes all relations of its pkgs from/to outside the
    component to itself. After all components have been created the relations
    graph is cycle free.

    Mimics RpmPackage.
    """

    def __init__(self, relations, pkgs):
        """relations: the RpmRelations object containing the loops."""

        self.relations = relations

        relations.list[self] = RpmRelation()

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
                relations.addRelation(self, p, flag)

            to_remove = [ ]
            for post in relations[pkg].post:
                if not post in self.pkgs:
                    to_remove.append(post)

            for p in to_remove:
                flag = relations[pkg].post[p]
                relations.removeRelation(p, pkg, quiet=True)
                relations.addRelation(p, self, flag)

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

    def processLeafNodes(self, order):
        """Remove all leaf nodes with the component and append them to order.
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
                self.relations.collect(next, order)
                del self.pkgs[next]
            else:
                return

    # ----

    def removeSubComponent(self, component):
        """Remove all packages of a sub component from own package list."""
        for pkg in component.pkgs:
            del self.pkgs[pkg]

    # ----

    def breakUp(self, order):
        hard_requirements = []
        for pkg in self.pkgs:
            for p, req in self.relations[pkg].pre.iteritems():
                if req:
                    hard_requirements.append((pkg, p))

        # pick requirement to delete
        weights = { }
        # calculate minimal distance to a pre req
        for pkg, nextpkg in hard_requirements:
            # dijkstra
            edge = [nextpkg]
            weights[nextpkg] = 0
            while edge:
                node = edge.pop()
                weight = weights[node] + 1
                for next_node, ishard in \
                    self.relations[node].pre.iteritems():
                    if ishard: continue
                    w = weights.get(next_node, None)
                    if w is not None and w < weight: continue
                    weights[next_node] = weight
                    edge.append(next_node)
                edge.sort()
                edge.reverse()

        if weights:
            # get pkg with largest minimal distance
            weight = -1
            for p, w in weights.iteritems():
                if w > weight:
                    weight, pkg2 = w, p

            # get the predesessor with largest minimal distance
            weight = -1
            for p in self.relations[pkg2].post:
                w = weights[p]
                if w > weight:
                    weight, pkg1 = w, p
        else:
            # search the relation that will most likely set a pkg free:
            # relations that are the last post (pre) of the start (end) pkg
            # are good, if there are lots of pre/post at the side
            # where the relation is the last it is even better
            # to make less relations better we use the negative values
            weight = None
            for p1 in self.pkgs:
                pre = len(self.relations[p1].pre)
                post = len(self.relations[p1].post)
                for p2 in self.relations[p1].pre.iterkeys():
                    pre2 = len(self.relations[p2].pre)
                    post2 = len(self.relations[p2].post)
                    if pre < post2: # start is more interesting
                        w = (-pre, post, -post2, pre)
                    elif pre > post2: #  end is more interesting
                        w = (-post2, pre2, -pre, post2)
                    else: # == both same, add the numbers of per and post
                        w = (-pre, post+pre2)
                    if w > weight:
                        # python handles comparison of tuples from left to
                        #  right (like strings)
                        weight = w
                        pkg1, pkg2 = p1, p2
        if self.relations[pkg1].pre[pkg2]:
            log.errorLn("Breaking pre requirement for %s: %s",
                        pkg1.getNEVRA(), pkg2.getNEVRA())

        # remove this requirement
        self.relations.removeRelation(pkg1, pkg2)

        # rebuild components
        components = ConnectedComponentsDetector(self.relations).detect(self.pkgs)
        for component in components:
            self.removeSubComponent(component)
            self.pkgs[component] = component

        # collect nodes
        self.processLeafNodes(order)

# ----------------------------------------------------------------------------

class ConnectedComponentsDetector:
    """Use Gabow algorithm to detect strongly connected components:
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
        If we go back in the recursion the following can happen:
        1. Our node has been removed from the root stack. It is part of a
           SCC -> do nothing
        2. Our node is top on the root stack: the pkg stack contains a SCC
           from the position of our node up -> remove it including our node
           also remove the node from the root stack
        """

    def __init__(self, relations):
        self.relations = relations

    # ----

    def detect(self, pkgs):
        """Returns a list of all strongly ConnectedComponents."""
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

    def __init__(self, config, installs, updates, obsoletes, erases,
                 installdb=None, erasedb=None):
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
        self.installdb = installdb
        self.erasedb = erasedb

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
                                         OP_INSTALL, self.installdb)

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
                relations = RpmRelations(self.config, self.erases, OP_ERASE,
                                         self.erasedb)

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
