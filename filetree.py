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
# Author: Florian La Roche, <laroche@redhat.com>, <florian.laroche@gmx.net>
#

#import ugid


class Perms:
    def __init__(self, perms):
        self.name = perms[0]
        self.mode = perms[1]
        self.user = perms[2]
        self.group = perms[3]
        self.time = perms[4]
        self.dev = perms[5]
        self.inode = perms[6]
        self.nlink = perms[7]

    def __repr__(self):
        return \
"name: %s, mode=%s, user=%s, group=%s, time=%d, dev=%d, inode=%d, nlink=%d" % \
            (self.name, oct(self.mode), self.user, self.group, self.time,
            self.dev, self.inode, self.nlink)


class RFile(Perms):
    def __init__(self, perms, flag, size=None, md5sum=None,
        rdev=None, symlink=None):
        Perms.__init__(self, perms)
        self.flag = flag
        self.size = size
        self.md5sum = md5sum
        self.rdev = rdev
        self.symlink = symlink

    def __repr__(self):
        ret = "%s, flag=%d" % (Perms.__repr__(self), self.flag)
        if self.size != None:
            return "%s, size=%d, md5sum=%s" % (ret, self.size, self.md5sum)
        if self.rdev != None:
            return "%s, rdev=%d" % (ret, self.rdev)
        if self.symlink != None:
            return "%s, symlink=%s" % (ret, self.symlink)
        return "error"


class RDir(Perms):
    def __init__(self, perms, flag, helperdir=None):
        Perms.__init__(self, perms)
        self.flag = flag
        self.helperdir = helperdir
        self.files = {}

    def addFile(self, file):
        name = file.name
        if self.files.has_key(name):
            raise ValueError, "dir %s already contains file %s" % (self.name,
                name)
        self.files[name] = file


class RTree:
    def __init__(self):
        self.dirs = {}

    def addDir(self, dir):
        name = dir.name
        if self.dirs.has_key(name):
            raise ValueError, "tree already contains dir %s" % name
        self.dirs[name] = dir


if __name__ == "__main__":
    perm = ["fname", 0644, "root", "root", 10000, 0, 1, 1]
    print RFile(perm, 0, 120, "md5sum")
    print RFile(perm, 0, rdev=0)
    print RFile(perm, 0, symlink="f2")

# vim:ts=4:sw=4:showmatch:expandtab
