#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche
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


import os, copy, sys, time, signal


class RpmMessageHandler:
    """A closure for message output."""

    def __init__(self, config, prefix="", suffix="\n"):
        self.config = config            # FIXME: write-only
        self.prefix = prefix
        self.suffix = suffix

    def handle(self, msg):
        """Write msg to stdout, using the defined prefix and suffix."""
        # FIXME: to stderr?

        sys.stdout.write("%s%s%s" % (self.prefix, msg, self.suffix))
        sys.stdout.flush()


class RpmConfig:
    def __init__(self):
        (self.sysname, self.nodename, self.release, self.version,
            self.machine) = os.uname()
        self.debug = 0              # Maximum level of debug messages to output
        self.warning = 0          # Maximum level of warning messages to output
        self.verbose = 0             # Maximum level of info messages to output
        self.debug_handler = RpmMessageHandler(self, "Debug: ")
        self.warning_handler = RpmMessageHandler(self, "Warning: ")
        self.verbose_handler = RpmMessageHandler(self, "", "")
        self.error_handler = RpmMessageHandler(self, "Error: ")
        self.printhash = 0
        self.buildroot = ''
        self.dbpath = "rpmdb://var/lib/rpm/"
        self.force = 0
        self.rusage = 0
        self.oldpackage = 0
        self.justdb = 0
        self.test = 0
        self.ignoresize = 0
        self.ignorearch = 0
        self.nodeps = 0
        self.nosignature = 1        # Default: No signature/gpg checks
        self.noorder = 0
        self.noscripts = 0
        self.notriggers = 0
        self.noconflicts = 0
        self.nofileconflicts = 0
        self.excludedocs = 0
        self.excludeconfigs = 0
        self.checkinstalled = 0
        self.exactarch = 0          # same base arch is not enough for updates
        self.tid = int(time.time()) # Install time id.
        self.tscolor = 0            # Transaction color, needed for rpmdb
        self.nevratags = ("name", "epoch", "version", "release",
                          "arch", "sourcerpm")
        self.resolvertags = self.nevratags + \
           ("providename", "provideflags", "provideversion", "requirename",
            "requireflags", "requireversion", "obsoletename", "obsoleteflags",
            "obsoleteversion", "conflictname", "conflictflags",
            "conflictversion", "filesizes", "filemodes", "filemd5s",
            "fileusername", "filegroupname", "filelinktos", "fileflags",
            "filecolors", "fileverifyflags", "dirindexes", "basenames",
            "dirnames", "oldfilenames", "md5", "sha1header")
            # Tags used by RpmResolver
        self.diskspacetags = self.nevratags + \
                             ("filesizes", "dirindexes", "basenames",
                              "dirnames", "oldfilenames", "filemodes")
        self.timer = 0                   # Output timing information
        self.ldconfig = 0             # Number of ldconfig calls optimized away
        self.delayldconfig = 0           # A delayed ldconfig call is pending
        self.service = 0                 # Install /sbin/service with "exit 0"
        self.yumconf = ['/etc/yum.conf'] # Yum config files
        self.relver  = '3'               # Release version, needed by YumConfig
        self.arch = None                 # If explicitly selected, for --test
        self.archlist = None             # Specific list of supported archs
        self.tmpdir = None
        self.supported_signals = [ signal.SIGINT, signal.SIGTERM,
                                   signal.SIGHUP ]
        self.srpmdir = "/usr/src/redhat/SOURCES" # Dir where srpms will be
                                                 # installed to
        self.enablerepo = [ ]           # Manually enabled repos
        self.disablerepo  = [ ]         # Manually disabled repos
        self.cachedir = "/var/cache/pyrpm"      # Directory for cached files
        self.nocache = 0                # Disable caching for packages
        self.excludes = [ ]
        # The first element should be a full path, interpreted outside
        # self.buildroot
        self.prelink_undo = ["/usr/sbin/prelink", "-y"]
        self.diff = False               # Try to show a diff in pyrpmverify
        # Verify contents of all nonempty config files, even if the package has
        # disabled it
        self.verifyallconfig = False
        self.keepcache = True           # Keep cached packages after install

    def readConfig(self, filename="/etc/pyrpm.conf"):
        return execfile(filename)

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

    def copy(self):                     # FIXME: not used
        return copy.deepcopy(self)


# Automatically create a global rpmconfig variable.
rpmconfig = RpmConfig()

# vim:ts=4:sw=4:showmatch:expandtab
