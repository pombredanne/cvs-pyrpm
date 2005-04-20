#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Thomas Woerner <twoerner@redhat.com>
#          Harald Hoyer <harald@redhat.com>
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

from types import IntType

class HashList:
    """ hash list """

    def __init__(self, config):
        self.config = config
        self.list = [ ]
        self.hash = { }

        self.__len__ = self.list.__len__
        self.__repr__ = self.list.__repr__
        self.has_key = self.hash.has_key
        self.keys = self.hash.keys

    def __getitem__(self, key):
        if isinstance(key, IntType):
            return self.list[key]
        return self.hash.get(key)

    def __contains__(self, key):
        if isinstance(key, IntType):
            return self.list.__contains__(key)
        return self.hash.__contains__(key)

    def __setitem__(self, key, value):
        if not self.hash.has_key(key):
            self.hash[key] = value
            self.list.append(key)
        else:
            self.hash[key] = value
        return value

    def __delitem__(self, key):
        if self.hash.has_key(key):
            del self.hash[key]
            self.list.remove(key)
            return key
        return None

    def pop(self, idx):
        key = self.list.pop(idx)
        del self.hash[key]
        return key

# vim:ts=4:sw=4:showmatch:expandtab
