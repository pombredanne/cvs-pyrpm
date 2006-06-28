#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch <pknirsch@redhat.com>
#          Thomas Woerner <twoerner@redhat.com>
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

import memorydb
import rpmdb
import rpmmemorydb
import repodb
import sqlitedb
#import rpmshadowdb
#import directorydb

def getRpmDBFactory(config, source, root=None):
    """Get a RpmDatabase implementation for database "URI" source under
    root.

    Default to rpmdb:/ if no scheme is provided."""

    if   source[:5] == 'mem:/':
        return memorydb.RpmMemoryDB(config, source[5:], root)
    elif source[:6] == 'repo:/':
        return repodb.RpmRepoDB(config, source[6:], root)
    elif source[:7] == 'rpmdb:/':
        #return rpmshadowdb.RpmDB(config, source[7:], root)
        return rpmmemorydb.RpmMemoryDB(config, source[7:], root)
    elif source[:10] == 'sqlitedb:/':
        return sqlitedb.RpmSQLiteDB(config, source[10:], root)
    elif source[:5] == 'dir:/':
        return directorydb.RpmDirectoryDB(config, source[4:], root)
    return rpmmemorydb.RpmMemoryDB(config, source, root)
    #return rpmshadowdb.RpmDB(config, source, root)

# vim:ts=4:sw=4:showmatch:expandtab
