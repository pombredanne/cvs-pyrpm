#!/usr/bin/python
#
# (c) 2005 Red Hat, Inc.
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
# AUTHOR: Thomas Woerner <twoerner@redhat.com>
#

import sys, os, tempfile
from time import clock
import pyrpm

def usage():
    print """Usage: %s [-v[v]] <rpm package> <rpm package>

  -h  | --help                print help
  -v  | --verbose             be verbose, and more, ..

This program ...

""" % sys.argv[0]

# ----------------------------------------------------------------------------

verbose = 0
tags = [ "name", "epoch", "version", "release", "arch", "sourcerpm" ]


dir1 = None
dir2 = None

if len(sys.argv) < 3:
    usage()
    sys.exit(0)

ops = [ ]
i = 1
op = pyrpm.OP_INSTALL
while i < len(sys.argv):
    if sys.argv[i] == "-h" or sys.argv[i] == "--help":
        usage()
        sys.exit(0)
    elif sys.argv[i][:2] == "-v":
        j = 1
        while j < len(sys.argv[i]) and sys.argv[i][j] == "v":
            verbose += 1
            j += 1
    elif sys.argv[i] == "--verbose":
        verbose += 1
    else:
        pyrpm.rpmconfig.debug = verbose
        pyrpm.rpmconfig.warning = verbose
        pyrpm.rpmconfig.verbose = verbose

        if not dir1:
            dir1 = sys.argv[i]
        else:
            dir2 = sys.argv[i]
    i += 1

if not dir1 or not dir2:
    usage()
    sys.exit(0)        


packages = pyrpm.HashList()
updates = pyrpm.HashList()


# load dir1
list = os.listdir(dir1)
list.sort()
for i in xrange(len(list)):
    f = list[i]
    if not os.path.isfile("%s/%s" % (dir1, f)):
        continue
    r = pyrpm.RpmPackage(pyrpm.rpmconfig, "%s/%s" % (dir1, f))
    try:
        r.read(tags=tags)
    except Exception, msg:
        print msg
        print "Loading of %s/%s failed, ignoring." % (dir1, f)
        continue
    r.close()
    if not r["name"] in packages:
        packages[r["name"]] = [ ]
    packages[r["name"]].append(r)

# load dir2
list = os.listdir(dir2)
list.sort()
for i in xrange(len(list)):
    f = list[i]
    if not os.path.isfile("%s/%s" % (dir2, f)):
        continue
    r = pyrpm.RpmPackage(pyrpm.rpmconfig, "%s/%s" % (dir2, f))
    try:
        r.read(tags=tags)
    except Exception, msg:
        print msg
        print "Loading of %s/%s failed, ignoring." % (dir2, f)
        continue
    r.close()
    if r["name"] in packages:
        for pkg in packages[r["name"]]:
            if pkg.getNEVRA() == r.getNEVRA():
                continue
            if r["arch"] == pkg["arch"] or \
                   r["arch"] == "noarch" or \
                   pkg["arch"] == "noarch" or \
                   (pyrpm.archDuplicate(r["arch"], pkg["arch"]) and \
                    len(packages[r["name"]]) == 1):
                if not pkg in updates:
                    res = pyrpm.pkgCompare(pkg, r)
                    if res < 0:
                        updates[pkg] = r
                    elif res == 0:
                        pass
                    else:
                        print "Source package %s" % pkg.getNEVRA(), \
                              "is newer than target %s," % r.getNEVRA(), \
                              "ignoring"
                else:
                    res = pyrpm.pkgCompare(updates[pkg], r)
                    if res < 0:
                        updates[pkg] = r
                    elif res == 0:
                        # pkg == r
                        del updates[pkg]
                    # else res > 0, keep updates[pkg] as is

for pkg in updates:
    r = updates[pkg]
    pkg_size = os.stat(pkg.source).st_size
    r_size = os.stat(r.source).st_size
    print "%s: %d" % (pkg.source, pkg_size)
    print "%s: %d" % (r.source, r_size)
    r_size = os.stat(r.source).st_size
    sys.stdout.write("  ")
    sys.stdout.flush()
    os.system("delta.py -V create %s %s" % (pkg.source, r.source))
    sys.stdout.flush()
    delta_name = "%s.drpm" % r.getNEVRA()
    delta_size = os.stat(delta_name).st_size
    os.unlink(delta_name)
    print "  %d %d\n" % (r_size, delta_size)

sys.exit(0)
