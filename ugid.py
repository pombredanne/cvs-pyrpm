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

import pwd
import grp
from types import StringType

# TODO: XXX: write a simple parser for passwd/group and add checks against
#            such default values

class ID:
    def __init__(self):
        self.data = {}

    def addId(self, key):
        pass

    def __getitem__(self, key):
        if not self.data.has_key(key):
            self.addId(key)
        try:
            return self.data[key]
        except:
            return None

    def __setitem__(self, key, item):
        if self.data.has_key(key) or self.data.has_key(item):
            raise ValueError, "id or name conflicts"
        data = (key, item)
        self.data[key] = data
        self.data[item] = data

class UID(ID):
    def addId(self, key):
        try:
            if isinstance(key, StringType):
                uid = pwd.getpwnam(key)[2]
                self[uid] = key
            else:
                name = pwd.getpwuid(key)[0]
                self[key] = name
        except:
            return False
        return True

class GID(ID):
    def addId(self, key):
        try:
            if isinstance(key, StringType):
                uid = grp.getgrnam(key)[2]
                self[uid] = key
            else:
                name = grp.getgrgid(key)[0]
                self[key] = name
        except:
            return False
        return True

if __name__ == "__main__":
    uid = UID()
    uid.addId(0)
    uid = UID()
    uid.addId("root")
    gid = GID()
    gid.addId(0)
    gid = GID()
    gid.addId("root")

# vim:ts=4:sw=4:showmatch:expandtab
