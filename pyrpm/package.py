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
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
#

import os.path, tempfile, sys, gzip, pwd, grp, md5
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

    def __delitem__(self, key):
        self.modified = 1
        del self.data[key]

    def has_key(self, key):
        return self.data.has_key(key)

    def keys(self):
        return self.data.keys()

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
        if not self.__readHeader(tags, ntags):
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

    def install(self, db=None, tags=None, ntags=None):
        if not self.open():
            return 0
        if not self.__readHeader(tags, ntags):
            return 0
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preinprog"] != None:
            if not runScript(self["preinprog"], self["prein"], "1"):
                return 0
        if not self.__extract(db):
            return 0
        if self["postinprog"] != None:
            if not runScript(self["postinprog"], self["postin"], "1"):
                return 0
        self.rfilist = None
        return 1

    def erase(self, db=None):
        if not self.open():
            return 0
        if not self.__readHeader():
            return 0
        files = self["filenames"]
        self.__generateFileInfoList()
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preunprog"] != None:
            if not runScript(self["preunprog"], self["preun"], "1"):
                printError("%s: Error running pre uninstall script." % self.getNEVRA())
        # Remove files starting from the end (reverse process to install)
        for i in xrange(len(files)-1, -1, -1):
            f = files[i]
            rfi = self.getRpmFileInfo(f)
            if db.isDuplicate(f):
                printDebug(2, "File/Dir %s still in db, not removing..." % f)
                continue
            if os.path.isdir(f) and os.listdir(f) != []:
                try:
                    os.rmdir(f)
                except:
                    printWarning(1, "Couldn't remove dir %s from pkg %s" % (f, self.source))
            else:
                try:
                    os.unlink(f)
                except:
                    printWarning(1, "Couldn't remove file %s from pkg %s" % (f, self.source))
        if self["postunprog"] != None:
            if not runScript(self["postunprog"], self["postun"], "1"):
                printError("%s: Error running post uninstall script." % self.getNEVRA())
        return 1

    def isSourceRPM(self):
        # XXX: is it right method how detect by header?
        if self["sourcerpm"]==None:
            return 1
        return 0

    def __readHeader(self, tags=None, ntags=None):
        if self.header_read:
            return 1
        (key, value) = self.io.read()
        # Read over lead
        while key != None and key != "-":
            (key, value) = self.io.read()
        # Read sig
        (key, value) = self.io.read()
        while key != None and key != "-":
            if not self.has_key("signature"):
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
        self.__generateFileNames()
        self.header_read = 1
        return 1

    def __extract(self, db=None):
        files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.__generateFileInfoList()
        self.__generateHardLinkList()
        (filename, filerawdata) = self.io.read()
        while filename != None and filename != "EOF" :
            if not self.rfilist.has_key(filename):
                # src.rpm has empty tag "dirnames", but we use absolut paths in io.read(),
                # so at least the directory '/' is there ...
                if os.path.dirname(filename)=='/' and self.isSourceRPM():
                    filename = filename[1:]
            if filename in files:
                rfi = self.rfilist[filename]
                if self.__verifyFileInstall(rfi, db):
                    if not str(rfi.inode)+":"+str(rfi.dev) in self.hardlinks.keys():
                        if not installFile(rfi, filerawdata):
                            return 0
                    else:
                        if len(filerawdata) > 0:
                            if not installFile(rfi, filerawdata):
                                return 0
                            if not self.__handleHardlinks(rfi):
                                return 0
            (filename, filerawdata) = self.io.read()
        return self.__handleRemainingHardlinks()

    def __verifyFileInstall(self, rfi, db):
        # No db -> overwrite file ;)
        if not db:
            return 1
        # File not already in db -> write it
        if not db.filenames.has_key(rfi.filename):
            return 1
        # Don't install ghost files ;)
        if rfi.flags & RPMFILE_GHOST:
            return 0
        # Not a config file -> always overwrite it, resolver didn't say we
        # had any conflicts ;)
        if rfi.flags & RPMFILE_CONFIG == 0:
            return 1
        plist = db.filenames[rfi.filename]
        (mode, inode, dev, nlink, uid, gid, filesize, atime, mtime, ctime) = os.stat(rfi.filename)
        md5sum = md5.new(open(rfi.filename).read()).hexdigest()
        # Same file in new rpm as on disk -> just write it.
        if rfi.mode == mode and rfi.uid == uid and rfi.gid == gid and rfi.filesize == filesize and rfi.md5sum == md5sum:
            return 1
        # File has changed on disc, now check if it has changed between the
        # different packages that share it and the new package
        for nevra in plist:
            pkg = db.getPackage(nevra)
            orfi = pkg.getRpmFileInfo(rfi.filename)
            # If installed and new stats of the file are the same don't do
            # anything with it. If the file hasn't changed in the packages we
            # keep the editited file on disc.
            if rfi.mode == orfi.mode and rfi.uid == orfi.uid and rfi.gid == orfi.gid and rfi.filesize == orfi.filesize and rfi.md5sum == orfi.md5sum:
                printDebug(1, "%s: Same file between new and installed package, skipping." % self.getNEVRA())
                continue
            # OK, file in new package is different to some old package and it
            # is editied on disc. Now verify if it is a noreplace or not
            if rfi.flags & RPMFILE_NOREPLACE:
                printDebug(1, "%s: config(noreplace) file found that changed between old and new rpms and has changed on disc, creating new file as %s.rpmnew" %(self.getNEVRA(), rfi.filename))
                rfi.filename += ".rpmnew"
            else:
                printDebug(1, "%s: config file found that changed between old and new rpms and has changed on disc, moving edited file to %s.rpmsave" %(self.getNEVRA(), rfi.filename))
                if os.rename(rfi.filename, rfi.filename+".rpmsave") != None:
                    raiseFatal("%s: Edited config file %s couldn't be renamed, aborting." % (self.getNEVRA(), rfi.filename))
            break
        return 1

    def __generateFileNames(self):
        self["filenames"] = []
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            filename = self["dirnames"][self["dirindexes"][i]] + self["basenames"][i]
            self["filenames"].append(filename)

    def __generateFileInfoList(self):
        self.rfilist = {}
        for filename in self["filenames"]:
            self.rfilist[filename] = self.getRpmFileInfo(filename)

    def __generateHardLinkList(self):
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

    def __handleHardlinks(self, rfi):
        key = str(rfi.inode)+":"+str(rfi.dev)
        self.hardlinks[key].remove(rfi)
        for hrfi in self.hardlinks[key]:
            makeDirs(hrfi.filename)
            if not createLink(rfi.filename, hrfi.filename):
                return 0
        del self.hardlinks[key]
        return 1

    def __handleRemainingHardlinks(self):
        keys = self.hardlinks.keys()
        for key in keys:
            rfi = self.hardlinks[key][0]
            if not installFile(rfi, ""):
                return 0
            if not self.__handleHardlinks(rfi):
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
        rpmflags = self["fileflags"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid, rpmgid, rpmmtime, rpmfilesize, rpmdev, rpmrdev, rpmmd5sum, rpmflags)
        return rfi

    def getNEVR(self):
        if self["epoch"] != None:
            e = str(self["epoch"][0])+":"
        else:
            e = ""
        return "%s-%s%s-%s" % (self["name"], e, self["version"], self["release"])

    def getNEVRA(self):
        return "%s.%s" % (self.getNEVR(), self["arch"])

    def getProvides(self):
        return self.__getDeps("providename", "provideflags", "provideversion")

    def getRequires(self):
        return self.__getDeps("requirename", "requireflags", "requireversion")

    def getObsoletes(self):
        return self.__getDeps("obsoletename", "obsoleteflags", "obsoleteversion")

    def getConflicts(self):
        return self.__getDeps("conflictname", "conflictflags", "conflictversion")

    def getTriggers(self):
        return self.__getDeps("triggername", "triggerflags", "triggerversion")

    def __getDeps(self, name, flags, version):
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

# vim:ts=4:sw=4:showmatch:expandtab
