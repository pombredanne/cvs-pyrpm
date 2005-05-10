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


import os, copy, sys


class RpmMessageHandler:
    def __init__(self, config, prefix="", suffix="\n"):
        self.config = config
        self.prefix = prefix
        self.suffix = suffix

    def handle(self, msg):
        sys.stdout.write("%s%s%s" % (self.prefix, msg, self.suffix))
        sys.stdout.flush()


class RpmConfig:
    def __init__(self):
        (self.sysname, self.nodename, self.release, self.version,
            self.machine) = os.uname()
        self.debug = 0
        self.warning = 0
        self.verbose = 0
        self.debug_handler = RpmMessageHandler(self, "Debug: ")
        self.warning_handler = RpmMessageHandler(self, "Warning: ")
        self.verbose_handler = RpmMessageHandler(self, "", "")
        self.error_handler = RpmMessageHandler(self, "Error: ")
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
        self.noconflicts = 0
        self.nofileconflicts = 0
        self.checkinstalled = 0
        self.exactarch = 0
        self.compsfile = None
        self.resolvertags = ("name", "epoch", "version", "release", "arch",
            "providename", "provideflags", "provideversion", "requirename",
            "requireflags", "requireversion", "obsoletename", "obsoleteflags",
            "obsoleteversion", "conflictname", "conflictflags", 
            "conflictversion", "filesizes", "filemodes", "filemd5s",
            "dirindexes", "basenames", "dirnames", "oldfilenames", "sourcerpm")
        self.timer = 0
        self.ldconfig = 0
        self.delayldconfig = 0
        self.service = 0

    def printDebug(self, level, msg):
        if self.debug_handler and level <= self.debug:
            self.debug_handler.handle(msg)

    def printWarning(self, level, msg):
        if self.warning_handler and level <= self.warning:
            self.warning_handler.handle(msg)

    def printInfo(self, level, msg):
        if self.verbose_handler and level <= self.verbose:
            self.verbose_handler.handle(msg)

    def printError(self, msg):
        if self.error_handler:
            self.error_handler.handle(msg)

    def copy(self):
        return copy.deepcopy(self)


# Automatically create a global rpmconfig variable.
rpmconfig = RpmConfig()

# vim:ts=4:sw=4:showmatch:expandtab
