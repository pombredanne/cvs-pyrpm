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

import sys, os, tempfile, string
import pyrpm

def usage():
    print """Usage: %s [-v[v]] <log file>

  -h  | --help                print help
  -v  | --verbose             be verbose, and more, ..

This program ...

""" % sys.argv[0]

# ----------------------------------------------------------------------------

verbose = 0

if len(sys.argv) < 2:
    usage()
    sys.exit(0)

i = 1
input = None

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

        if not input:
            input = sys.argv[i]
    i += 1

if not input:
    usage()
    sys.exit(0)        


source = None
target = None
line_no = 0

seconds = 0.0
orig_size = 0
delta_size = 0

file = open(input, "r")
while 1:
    line = file.readline()
    if not line: break

    if line[-1:] == "\n":
        line = line[:-1]
    if len(line) < 1: continue
    if line[0] == '#': continue

    if line[0] == " ":
        s = line[2:].split()
        if line_no == 0:
            secs = float(s[1][:-1]) # remove 's'
            o_size = 0
            d_size = 0
        elif line_no == 1:
            o_size= int(s[0])
            d_size = int(s[1])
        line_no += 1
    else:
        if line_no > 0:
            if verbose:
                print "%s -> %s orig: %dk, delta: %dk (%.02f%%)" % \
                      (source, target, o_size, d_size,
                       (100.0 * d_size / o_size))
            seconds += secs
            orig_size += o_size
            delta_size += d_size
            line_no = 0
        if not source:
            source = line.split(":")[0]
        else:
            target = line.split(":")[0]

file.close()

sys.stdout.flush()

print "complete: %dk" % (orig_size/1024)
print "delta: %dk (%.2f%%) %0.2fs" % (delta_size/1024,
                                      (100.0 * delta_size / orig_size),
                                      seconds)

sys.exit(0)
