#!/usr/bin/python
#
# rpmgraph
#
# (c) 2005 Thomas Woerner <twoerner@redhat.com>
#
# version 2005-06-07-01

import sys, os

PYRPMDIR = ".."
if not PYRPMDIR in sys.path:
    sys.path.append(PYRPMDIR)
import pyrpm
from pyrpm.logger import log

def usage():
    print """Usage: %s [-h] <rpm name/package>...

  -h  | --help           print help
  -v  | --verbose        be verbose, and more, ..
  -f                     use full package names (NEVR)
  -o                     write simple graph output to file
                         (default: rpmgraph.dot)
  -i                     iterate and write iteration and loop graphs
                         (iteration_XXX.dot and loop_XXX.dot)
  -nC                    no conflict checks
  -nF                    no file conflict checks

This program prints a tree for package dependencies if '-i' is not given else
it iterates though the normal ordering process and writes the iteration and
loop graphs.
""" % sys.argv[0]

# ----------------------------------------------------------------------------

sout =  os.readlink("/proc/self/fd/1")
devpts = 0
if sout[0:9] == "/dev/pts/":
    devpts = 1

def progress_write(msg):
    if devpts == 1:
        sys.stdout.write("\r")
    sys.stdout.write(msg)
    if devpts == 0:
        sys.stdout.write("\n")
    sys.stdout.flush()

# ----------------------------------------------------------------------------

rpms = [ ]

verbose = 0
full_names = 0
iteration = 0
output = "rpmgraph.dot"

tags = [ "name", "epoch", "version", "release", "arch",
         "providename", "provideflags", "provideversion", "requirename",
         "requireflags", "requireversion", "obsoletename", "obsoleteflags",
         "obsoleteversion", "conflictname", "conflictflags",
         "conflictversion", "filesizes", "filemodes", "filemd5s", "fileflags",
         "dirindexes", "basenames", "dirnames" ]

if __name__ == '__main__':
    if len(sys.argv) == 1:
        usage()
        sys.exit(0)

    pargs = [ ]
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "-h" or sys.argv[i] == "--help":
            usage()
            sys.exit(0)
        elif sys.argv[i][:2] == "-v":
            j = 1
            while j < len(sys.argv[i]) and sys.argv[i][j] == "v":
                verbose += 1
                j += 1
        elif sys.argv[i][:2] == "-v":
            verbose += 1
        elif sys.argv[i][:2] == "-f":
            full_names = 1
        elif sys.argv[i][:2] == "-i":
            iteration = 1
        elif sys.argv[i] == "-o":
            i += 1
            output = sys.argv[i]
        elif sys.argv[i] == "-nC":
            pyrpm.rpmconfig.noconflictcheck = 1
        elif sys.argv[i] == "-nF":
            pyrpm.rpmconfig.nofileconflictcheck = 1
        else:
            pargs.append(sys.argv[i])
        i += 1

    pyrpm.rpmconfig.verbose = verbose
    if pyrpm.rpmconfig.verbose > 3:
        pyrpm.rpmconfig.debug = pyrpm.rpmconfig.verbose - 3
    if pyrpm.rpmconfig.verbose > 2:
        pyrpm.rpmconfig.warning = pyrpm.rpmconfig.verbose - 2
    elif pyrpm.rpmconfig.verbose > 1:
        pyrpm.rpmconfig.warning = pyrpm.rpmconfig.verbose - 1

    if len(pargs) == 0:
        usage()
        sys.exit(0)        

    # -- load packages

    i = 1
    for f in pargs:
        if verbose > 0:
            progress_write("Reading %d/%d " % (i, len(pargs)))
        r = pyrpm.RpmPackage(pyrpm.rpmconfig, f)
        try:
            r.read(tags=tags)
        except IOError:
            print "Loading of %s failed, exiting." % f
            sys.exit(-1)
        r.close()
        rpms.append(r)
        i += 1
    if verbose > 0 and len(pargs) > 0:
        print

    del pargs
    
    # -----------------------------------------------------------------------

    def printRelations(relations, output):
        if output == "-":
            fp = sys.stdout
        else:
            fp = open(output, "w+")

        fp.write('digraph rpmgraph {\n')
        fp.write('graph [\n');
        fp.write('	overlap="false",\n');
        fp.write('	nodesep="1.0",\n');
        fp.write('	K=2,\n');
        fp.write('	splines="true",\n');
        fp.write('	mindist=2,\n');
        fp.write('	pack="true",\n');
        fp.write('	ratio="compress",\n');
        fp.write('	size="50,50"\n');
        fp.write('];\n')
        fp.write('node [\n');
#        fp.write('	label="\N",\n');
        fp.write('	fontsize=150\n');
        fp.write('];\n')
        fp.write('edge [\n');
        fp.write('	minlen=1,\n');
        fp.write('	tailclip=true,\n');
        fp.write('	headclip=true\n');
        fp.write('];\n')

        for pkg in relations:
            rel = relations[pkg]
            if full_names:
                pkg_name = pkg.getNEVRA()
            else:
                pkg_name = pkg["name"]
            fp.write('"%s" [peripheries=%d];\n' % \
                     (pkg_name, len(rel.pre)+len(rel.post)))

        for pkg in relations:
            rel = relations[pkg]
            if full_names:
                pkg_name = pkg.getNEVRA()
            else:
                pkg_name = pkg["name"]
            if len(rel.pre) > 0:
                for p in rel.pre:
                    f = rel.pre[p]
                    if f == 1:
                        style='solid'
                    else:
                        style='bold'
                    if full_names:
                        name = p.getNEVRA()
                    else:
                        name = p["name"]
                    fp.write('"%s" -> "%s" [style="%s", arrowsize=10.0];\n' % \
                             (pkg_name, name, style))

        fp.write('}\n')

        if output != "-":
            fp.close()

    # -----------------------------------------------------------------------

    class Node:
        def __init__(self, name, index):
            self.name = name
            self.index = index
            self.x = 0
            self.y = 0
            self.width = 0.7
            self.height = 0.5
            if len(self.name) * 0.07 + 0.2 > self.width:
                self.width = len(self.name) * 0.07 + 0.2

    class Loop:
        def __init__(self, relations, loop, start_index):
            self.relations = relations
            self.loop = loop
            self.x = 0
            self.y = 0
            self.nodes = { }
            l = len(self.loop)-1
            for i in xrange(l):
                self.nodes[self.loop[i]] = Node(self.loop[i]["name"],
                                                start_index + i)
                if i < 2:
                    if l == 2:
                        self.nodes[self.loop[i]].x = 50
                    else:
                        self.nodes[self.loop[i]].x = 100
                    self.nodes[self.loop[i]].y = i * (l - 1) * 100 + 50
                else:
                    self.nodes[self.loop[i]].x = 0
                    self.nodes[self.loop[i]].y = (l - i) * 100 + 50

            self.width = 150
            if l > 2:
                self.width = 200
            self.height = l * 100
        def __len__(self):
            return len(self.loop)
        def __getitem__(self, i):
            return self.loop[i]
        def __str__(self):
            s = ""
            for node in self.nodes:
                s += '"node%08d" ' % self.nodes[node].index
                s += '[label="%s", pos="%d,%d", width="%.2f", height="%.2f"];\n' % \
                     (self.nodes[node].name,
                      self.nodes[node].x + self.x, self.nodes[node].y + self.y,
                      self.nodes[node].width, self.nodes[node].height)
            l = len(self.loop)-1
            for i in xrange(l):
                node = self.loop[i]
                next = self.loop[i+1]
                style='style="solid"'
                if self.relations[node].pre[next] == 2:
                    style='style="bold"'
                x2 = self.nodes[node].x + self.x
                y2 = self.nodes[node].y + self.y
                x1 = self.nodes[next].x + self.x
                y1 = self.nodes[next].y + self.y
                if y1 > y2:
                    y1 -= self.nodes[next].height * 30
                    y2 += self.nodes[node].height * 30
                if y1 < y2:
                    y1 += self.nodes[next].height * 30
                    y2 -= self.nodes[node].height * 30
                if x1 > x2:
                    x1 -= self.nodes[next].width * 20
                if x1 < x2:
                    x2 -= self.nodes[node].width * 20
                if l == 2: # two nodes
                    x1 += - 10 + i*20
                    x2 += - 10 + i*20
                pos = 'pos="e,%d,%d %d,%d %d,%d %d,%d %d,%d"' % \
                      (x1, y1, x2, y2, x2, y2, x2, y2,
                       (x1 + x2) / 2, (y1 + y2) / 2)
                s += '"node%08d" -> "node%08d" [%s, %s];\n' % \
                     (self.nodes[node].index, self.nodes[next].index, 
                      style, pos)
            return s

    def arrangeLoops(loop_list, _y_max):
        x = 50
        y = y_max = 0
        line_width = 0
        lines = [ ] # unfilled lines
        for loop in loop_list:
            # first check if it fits in an unfilled line
            if len(lines) > 0:
                found = 0
                for line in lines:
                    if line[1] + loop.height <= _y_max and \
                           loop.width <= line[2]:
                        loop.x = line[0]
                        loop.y = line[1]
                        line[1] += loop.height
                        if y_max < line[1]:
                            y_max = line[1]
                        found = 1
                        break
                if found == 1:
                    continue

            if y != 0 and y + loop.height > _y_max:
                if y < _y_max:
                    lines.append([x, y, line_width])
                y = 0
                x += line_width
                line_width = 0

            loop.x = x
            loop.y = y
            if line_width < loop.width:
                line_width = loop.width            
            y += loop.height
            if y_max < y:
                y_max = y

        return (x + line_width, y_max)

    def printLoops(relations, loops, output):
        if output == "-":
            fp = sys.stdout
        else:
            fp = open(output, "w+")

        loop_list = [ ]
        nodes_index = 0
        for loop in loops:
            loop_list.append(Loop(relations, loop, nodes_index))
            nodes_index += len(loop)-1

        (x_max, y_max) = arrangeLoops(loop_list, 100)
        old_y_max = [ ]
        # make it about (3*height x 4*width)
        while y_max < 1.25 * x_max or y_max > 1.5 * x_max:
#            y_max = (x_max + y_max) / 2
            y_max = (1.33 * x_max + 0.75 * y_max) / 2
            (x_max, y_max) = arrangeLoops(loop_list, y_max)
            if y_max in old_y_max:
                break
            old_y_max.append(y_max)

        fp.write('digraph rpmgraph {\n')
        fp.write('graph [\n');
        fp.write('	overlap="false",\n');
        fp.write('	nodesep="1.0",\n');
        fp.write('	K=2,\n');
        fp.write('	splines="true",\n');
        fp.write('	mindist=2,\n');
        fp.write('	pack="true",\n');
        fp.write('	ratio="compress",\n');
        fp.write('	bb="0,0,%d,%d"\n' % (x_max, y_max));
        fp.write('];\n')
        fp.write('node [\n');
        fp.write('	fontsize=10\n');
        fp.write('];\n')
        fp.write('edge [\n');
        fp.write('	minlen=1,\n');
        fp.write('	tailclip=true,\n');
        fp.write('	headclip=true\n');
        fp.write('	arrowsize=1.0\n');
        fp.write('];\n')
        
        for loop in loop_list:
            fp.write(str(loop))

        fp.write('}\n')

        if output != "-":
            fp.close()

    # -----------------------------------------------------------------------

    def orderRpms(orderer, relations):
        """ Order rpmlist.
        Returns ordered list of packages. """
        global iteration_count
        global loop_count
        order = [ ]
        last = [ ]
        idx = 1
        while len(relations) > 0:
            printRelations(relations, "iteration_%03d.dot" % iteration_count)
            iteration_count += 1

            # remove and save all packages without a post relation in reverse
            # order
            # these packages will be appended later to the list
            orderer._separatePostLeafNodes(relations, last)

            if len(relations) == 0:
                break

            next = orderer._getNextLeafNode(relations)
            if next != None:
                order.append(next)
                relations.remove(next)
                log.debug2Ln("%d: %s", idx, next.getNEVRA())
                idx += 1
            else:
                loops = orderer.getLoops(relations)
                printLoops(relations, loops, "loop_%03d.dot" % loop_count)
                loop_count += 1
                if orderer.breakupLoops(relations, loops) != 1:
                    log.errorLn("Unable to breakup loop.")
                    return None
        
        if pyrpm.rpmconfig.debug > 1:
            for r in last:
                log.debug2Ln("%d: %s", idx, r.getNEVRA())
                idx += 1

        return (order + last)

    # -----------------------------------------------------------------------

    operation = pyrpm.OP_UPDATE
    db = pyrpm.database.memorydb.RpmMemoryDB(pyrpm.rpmconfig, None)
    db.addPkgs([])
    resolver = pyrpm.RpmResolver(pyrpm.rpmconfig, db)

    i = 0
    l = len(rpms)
    while len(rpms) > 0:
        if verbose > 0:
            progress_write("Appending %d/%d " % (i, l))
        r = rpms.pop(0)
        # append
        resolver.install(r)
        i += 1
    del rpms

    if len(resolver.installs) == 0:
        print "Nothing to do."
        sys.exit(0)

    if resolver.resolve() != 1:
        sys.exit(-1)

    # -----------------------------------------------------------------------
        
    orderer = pyrpm.RpmOrderer(pyrpm.rpmconfig,
                               resolver.installs, resolver.updates,
                               resolver.obsoletes, resolver.erases)
    del resolver
    relations = orderer.genRelations(orderer.installs, pyrpm.OP_INSTALL)

    if relations == None or len(relations) < 1:
        sys.exit(-1)

    if iteration:
        iteration_count = 1
        loop_count = 1
        orderRpms(orderer, relations)
    else:
        printRelations(relations, output)

    del orderer
    sys.exit(0)
