#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
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


import os


class RpmConfig:
    def __init__(self):
        (self.sysname, self.nodename, self.release, self.version,
            self.machine) = os.uname()
        self.debug_level = 0
        self.warning_level = 0
        self.verbose_level = 0
        self.printhash = 0
        self.buildroot = None
        self.dbpath = "/var/lib/pyrpm/"
        self.force = 0
        self.oldpackage = 0
        self.justdb = 0
        self.test = 0
        self.ignoresize = 0
        self.ignorearch = 0
        self.nodeps = 0
        self.nodigest = 0
        self.nosignature = 0
        self.noorder = 0
        self.noscripts = 0
        self.notriggers = 0
        self.noconflictcheck = 0
        self.nofileconflictcheck = 0
        self.exactarch = 0
        self.compsfile = None
        self.resolvertags = ("name", "epoch", "version", "release", "arch",
            "providename", "provideflags", "provideversion", "requirename",
            "requireflags", "requireversion", "obsoletename", "obsoleteflags",
            "obsoleteversion", "conflictname", "conflictflags",
            "conflictversion", "filesizes", "filemodes", "filemd5s",
            "dirindexes", "basenames", "dirnames")
        self.ignore_epoch = 0
        self.fileconflicts = 1
        self.timer = 0

# Automatically create a global rpmconfig variable.
rpmconfig = RpmConfig()

# vim:ts=4:sw=4:showmatch:expandtab
