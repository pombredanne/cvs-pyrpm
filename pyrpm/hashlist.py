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
# Author: Thomas Woerner <twoerner@redhat.com>
#

import types

class HashList:
    """ hash list """

    def __init__(self):
        self.list = []
        self.hash = {}

    def __len__(self):
        return len(self.list)

    def __repr__(self):
        return self.list.__repr__()

    def __getitem__(self, key):
        if isinstance(key, types.IntType):
            return (self.list[key], self.hash[self.list[key]])
        return self.hash.get(key) # return value only

    def __setitem__(self, key, value):
        if not self.hash.has_key(key):
            self.hash[key] = value
            self.list.append(key)
        else:
            self.hash[key] = value
        return self.hash[key]

    def __delitem__(self, key):
        if self.hash.has_key(key):
            del self.hash[key]
            self.list.remove(key)
            return key
        return None

    def __contains__(self, key):
        return self[key]

    def has_key(self, key):
        return (self[key] != None)

    def pop(self, idx):
        key = self.list[idx]
        self.list.pop(idx)
        del self[key]

# vim:ts=4:sw=4:showmatch:expandtab
