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

import pyrpm.base as base
import pyrpm.openpgp as openpgp

#
# Database base class only __init__ and clear are implemented
# Merge of old database class and parts of the resolver
#

class RpmDatabase:
    OK = 1
    ALREADY_INSTALLED = -1
    NOT_INSTALLED = -3

    def __init__(self, config, source, buildroot=None):
        self.config = config
        self.source = source
        self.buildroot = buildroot
        RpmDatabase.clear(self)
        self.keyring = openpgp.PGPKeyRing()
        self.is_read = 0                # 1 if the database was already read

    def __contains__(self, pkg):
        return None

    # clear all structures
    def clear(self):
        pass

    def setBuildroot(self, buildroot):
        """Set database chroot to buildroot."""
        self.buildroot = buildroot

    ### not implemented functions ###

    def open(self):
        """If the database keeps a connection, prepare it."""
        raise NotImplementedError

    def close(self):
        """If the database keeps a connection, close it."""
        raise NotImplementedError

    def read(self):
        """Read the database in memory."""
        raise NotImplementedError

    # add package
    def addPkg(self, pkg):
        raise NotImplementedError

    # add package list
    def addPkgs(self, pkgs):
        raise NotImplementedError

    # remove package
    def removePkg(self, pkg):
        raise NotImplementedError

    def searchName(self, name):
        raise NotImplementedError

    def getPkgs(self, dep):
        raise NotImplementedError

    def getNames(self):
        raise NotImplementedError

    def hasName(self, name):
        raise NotImplementedError

    def getPkgsByName(self, name):
        raise NotImplementedError

    def getProvides(self):
        raise NotImplementedError

    def getFilenames(self):
        raise NotImplementedError

    def numFileDuplicates(self, filename):
        raise NotImplementedError

    def getFileDuplicates(self):
        raise NotImplementedError

    def getRequires(self):
        raise NotImplementedError

    def getFileRequires(self):
        return [file for file in self.getRequires().keys() if file[0]=="/"]

    def getConflicts(self):
        raise NotImplementedError

    def getObsoletes(self):
        raise NotImplementedError

    def getTriggers(self):
        raise NotImplementedError

    def reloadDependencies(self):
        raise NotImplementedError

    def searchProvides(self, dep):
        raise NotImplementedError

    def searchFilenames(self, dep):
        raise NotImplementedError

    def searchRequires(self, dep):
        raise NotImplementedError

    def searchConflicts(self, dep):
        raise NotImplementedError

    def searchObsoletes(self, dep):
        raise NotImplementedError

    def searchTriggers(self, dep):
        raise NotImplementedError

    def searchDependency(self, name, flag, version):
        raise NotImplementedError

    def _getDBPath(self):
        raise NotImplementedError

# vim:ts=4:sw=4:showmatch:expandtab
