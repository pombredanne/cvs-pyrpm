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
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
#

import os.path, tempfile, sys, gzip, pwd, grp
from struct import unpack
from base import *
from functions import *
from io import *


class RpmData:
    def __init__(self):
        self.data = {}
        self.modified = None

    def __repr__(self):
        return self.data.__repr__()

    def __getitem__(self, key):
        try:
            return self.data[key]
        except:
            # XXX: try to catch wrong/misspelled keys here?
            return None

    def __setitem__(self, key, value):
        self.modified = 1
        self.data[key] = value
        return self.data[key]

    def verify(self):
        ret = 0
        return ret


class RpmPackage(RpmData):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmData.__init__(self)
        self.clear()
        self.source = source
        self.verify = verify
        self.legacy = legacy
        self.parsesig = parsesig
        self.hdronly = hdronly

    def clear(self):
        self.io = None
        self.header_read = 0

    def open(self, mode="r"):
        self.header_read = 0
        if self.io != None:
            return 1
        self.io = getRpmIOFactory(self.source, self.verify, self.legacy, self.parsesig, self.hdronly)
        if not self.io:
            return 0
        if not self.io.open(mode):
            return 0
        return 1

    def close(self):
        if self.io != None:
            self.io.close()
        self.io = None
        return 1

    def read(self, tags=None, ntags=None):
        if not self.open():
            return 0
        if not self.readHeader(tags, ntags):
            return 0
        self["provides"] = self.getProvides()
        self["requires"] = self.getRequires()
        self["obsoletes"] = self.getObsoletes()
        self["conflicts"] = self.getConflicts()
        self.close()
        return 1

    def write(self):
        if not self.open("w"):
            return 0
        ret = self.io.write(self)
        self.close()
        return ret

    def verify(self):
        ret = RpmData.verify(self)
        return ret

    def install(self, files=None, tags=None, ntags=None):
        if not self.open():
            return 0
        if not self.readHeader(tags, ntags):
            return 0
        if not files:
            files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preinprog"] != None:
            if not runScript(self["preinprog"], self["prein"], "1"):
                return 0
        if not self.extract(files):
            return 0
        if self["postinprog"] != None:
            if not runScript(self["postinprog"], self["postin"], "1"):
                return 0
        return 1

    def remove(self, files=None):
        if not self.open():
            return 0
        if not self.readHeader():
            return 0
        if not files:
            files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preunprog"] != None:
            if not runScript(self["preunprog"], self["preun"], "1"):
                return 0
        # Remove files starting from the end (reverse process to install)
        files.reverse()
        for f in files:
            if os.path.isdir(f):
                try:
                    os.rmdir(f)
                except:
                    print "Error removing dir %s from pkg %s" % (f, self.source)
            else:
                try:
                    os.unlink(f)
                except:
                    print "Error removing file %s from pkg %s" % (f, self.source)
        if self["postunprog"] != None:
            if not runScript(self["postunprog"], self["postun"], "1"):
                return 0

    def readHeader(self, tags=None, ntags=None):
        if self.header_read:
            return 1
        (key, value) = self.io.read()
        # Read over lead
        while key != None and key != "-":
            (key, value) = self.io.read()
        # Read sig
        (key, value) = self.io.read()
        while key != None and key != "-":
            if not self.data.has_key("signature"):
                self["signature"] = {}
            if tags and key in tags:
                self["signature"][key] = value
            elif ntags and not key in ntags:
                self["signature"][key] = value
            elif not tags and not ntags:
                self["signature"][key] = value
            (key, value) = self.io.read()
        # Read header
        (key, value) = self.io.read()
        while key != None and key != "-":
            if tags and key in tags:
                self[key] = value
            elif ntags and not key in ntags:
                self[key] = value
            elif not tags and not ntags:
                self[key] = value
            (key, value) = self.io.read()
        self.generateFileNames()
        self.header_read = 1
        return 1

    def extract(self, files=None):
        if files == None:
            files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.generateFileInfoList()
        self.generateHardLinkList()
        (filename, filerawdata) = self.io.read()
        while filename != None and filename != "EOF" :
            rfi = self.rfilist[filename]
            if rfi != None:
                if not str(rfi.inode)+":"+str(rfi.dev) in self.hardlinks.keys():
                    if not installFile(rfi, filerawdata):
                        return 0
                else:
                    if len(filerawdata) > 0:
                        if not installFile(rfi, filerawdata):
                            return 0
                        if not self.handleHardlinks(rfi):
                            return 0
            (filename, filerawdata) = self.io.read()
        return self.handleRemainingHardlinks()

    def generateFileNames(self):
        self["filenames"] = []
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            filename = self["dirnames"][self["dirindexes"][i]] + self["basenames"][i]
            self["filenames"].append(filename)

    def generateFileInfoList(self):
        self.rfilist = {}
        for filename in self["filenames"]:
            self.rfilist[filename] = self.getRpmFileInfo(filename)

    def generateHardLinkList(self):
        self.hardlinks = {}
        for filename in self.rfilist.keys():
            rfi = self.rfilist[filename]
            key = str(rfi.inode)+":"+str(rfi.dev)
            if key not in self.hardlinks.keys():
                self.hardlinks[key] = []
            self.hardlinks[key].append(rfi)
        for key in self.hardlinks.keys():
            if len(self.hardlinks[key]) == 1:
                del self.hardlinks[key]

    def handleHardlinks(self, rfi):
        key = str(rfi.inode)+":"+str(rfi.dev)
        self.hardlinks[key].remove(rfi)
        for hrfi in self.hardlinks[key]:
            makeDirs(hrfi.filename)
            if not createLink(rfi.filename, hrfi.filename):
                return 0
        del self.hardlinks[key]
        return 1

    def handleRemainingHardlinks(self):
        keys = self.hardlinks.keys()
        for key in keys:
            rfi = self.hardlinks[key][0]
            if not installFile(rfi, ""):
                return 0
            if not self.handleHardlinks(rfi):
                return 0
        return 1

    def getRpmFileInfo(self, filename):
        try:
            i = self["filenames"].index(filename)
        except:
            return None
        rpminode = self["fileinodes"][i]
        rpmmode = self["filemodes"][i]
        if os.path.isfile("/etc/passwd"):
            try:
                pw = pwd.getpwnam(self["fileusername"][i])
            except:
                pw = None
        else:
            pw = None
        if pw != None:
            rpmuid = pw[2]
        else:
            rpmuid = 0      # default to root as uid if not found
        if os.path.isfile("/etc/group"):
            try:
                gr = grp.getgrnam(self["filegroupname"][i])
            except:
                gr = None
        else:
            gr = None
        if gr != None:
            rpmgid = gr[2]
        else:
            rpmgid = 0      # default to root as gid if not found
        rpmmtime = self["filemtimes"][i]
        rpmfilesize = self["filesizes"][i]
        rpmdev = self["filedevices"][i]
        rpmrdev = self["filerdevs"][i]
        rpmmd5sum = self["filemd5s"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid, rpmgid, rpmmtime, rpmfilesize, rpmdev, rpmrdev, rpmmd5sum)
        return rfi

    def getNEVR(self):
        if self["epoch"] != None:
            e = str(self["epoch"][0])+":"
        else:
            e = ""
        return "%s-%s%s-%s" % (self["name"], e, self["version"], self["release"])

    def getNEVRA(self):
        return "%s.%s" % (self.NEVR(), self["arch"])

    def getDeps(self, name, flags, version):
        n = self[name]
        if not n:
            return []
        f = self[flags]
        v = self[version]
        if f == None or v == None or len(n) != len(f) or len(f) != len(v):
            if f != None or v != None:
                raiseFatal("%s: wrong length of deps" % self.source)
        deps = []
        for i in xrange(0, len(n)):
            if f != None:
                deps.append( (n[i], f[i], v[i]) )
            else:
                deps.append( (n[i], None, None) )
        return deps

    def getProvides(self):
        return self.getDeps("providename", "provideflags", "provideversion")

    def getRequires(self):
        return self.getDeps("requirename", "requireflags", "requireversion")

    def getObsoletes(self):
        return self.getDeps("obsoletename", "obsoleteflags", "obsoleteversion")

    def getConflicts(self):
        return self.getDeps("conflictname", "conflictflags", "conflictversion")

    def getTriggers(self):
        return self.getDeps("triggername", "triggerflags", "triggerversion")

# vim:ts=4:sw=4:showmatch:expandtab
