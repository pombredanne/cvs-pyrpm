#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
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


import os.path, sys, pwd, grp, md5, string, weakref
from stat import S_ISREG
from types import DictType
from struct import unpack
from functions import *

class RpmData:
    def __init__(self):
        self.data = {}

    def __repr__(self):
        return self.data.__repr__()

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value
        return value

    def __delitem__(self, key):
        del self.data[key]

    def has_key(self, key):
        return self.data.has_key(key)

    def keys(self):
        return self.data.keys()

## Faster version (overall performance gain 25%!!!)
class FastRpmData(DictType):
    __getitem__ = DictType.get
    def __init__(self):
        DictType.__init__(self)
        self.hash \
            = int(string.atoi(str(weakref.ref(self)).split()[6][3:-1], 16))

    def __repr__(self):
        return "FastRpmData: <0x" + str(self.hash) + ">"

    def __hash__(self):
        return self.hash

## Comment out, if you experience strange results
RpmData = FastRpmData

class RpmUserCache:
    """If glibc is not yet installed (/sbin/ldconfig is missing), we parse
    /etc/passwd and /etc/group with our own routines."""
    def __init__(self):
        self.uid = {"root": 0}
        self.gid = {"root": 0}

    def __parseFile(self, ugfile):
        rethash = {}
        try:
            fp = open(ugfile, "r")
        except:
            return rethash
        lines = fp.readlines()
        fp.close()
        for l in lines:
            tmp = l.split(":")
            rethash[tmp[0]] = int(tmp[2])
        return rethash

    def getUID(self, username):
        if not self.uid.has_key(username):
            if os.path.isfile("/etc/passwd"):
                if os.path.isfile("/sbin/ldconfig"):
                    try:
                        pw = pwd.getpwnam(username)
                        self.uid[username] = pw[2]
                    except:
                        # XXX: print warning
                        self.uid[username] = 0
                else:
                    r = self.__parseFile("/etc/passwd")
                    if r.has_key(username):
                        self.uid[username] = r[username]
                    else:
                        # XXX: print warning
                        self.uid[username] = 0
            else:
                return 0
        return self.uid[username]

    def getGID(self, groupname):
        if not self.gid.has_key(groupname):
            if os.path.isfile("/etc/group"):
                if os.path.isfile("/sbin/ldconfig"):
                    try:
                        gr = grp.getgrnam(groupname)
                        self.gid[groupname] = gr[2]
                    except:
                        # XXX: print warning
                        self.gid[groupname] = 0
                else:
                    r = self.__parseFile("/etc/group")
                    if r.has_key(groupname):
                        self.gid[groupname] = r[groupname]
                    else:
                        # XXX: print warning
                        self.gid[groupname] = 0
            else:
                return 0
        return self.gid[groupname]


class RpmPackage(RpmData):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmData.__init__(self)
        self.clear()
        self.source = source
        self.verify = verify
        self.strict = strict
        self.hdronly = hdronly
        self.range_signature = (None, None)
        self.range_header = (None, None)
        self.range_payload = (None, None)

    def clear(self):
        self.io = None
        self.header_read = 0
        self.rpmusercache = RpmUserCache()

    def open(self, mode="r"):
        from io import getRpmIOFactory

        if self.io != None:
            return 1
        self.io = getRpmIOFactory(self.source, self.verify, self.strict,
            self.hdronly)
        if not self.io:
            return 0
        if not self.io.open(mode):
            return 0
        return 1

    def close(self):
        if self.io != None:
            self.io.close()
        self.clear()
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
        self["triggers"] = self.getTriggers()
        return 1

    def write(self, source=None):
        if source != None:
            #origsource = self.source
            self.source = source
            self.close()
        if not self.open("w"):
            return 0
        return self.io.write(self)

    def install(self, db=None, tags=None, ntags=None):
        if not self.open():
            return 0
        if not self.__readHeader(tags, ntags):
            return 0
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preinprog"] != None or self["postinprog"] != None:
            numPkgs = str(db.getNumPkgs(self["name"])+1)
        if self["preinprog"] != None and not rpmconfig.noscripts:
            if not runScript(self["preinprog"], self["prein"], numPkgs):
                printError("%s: Error running pre install script." \
                    % self.getNEVRA())
        if not self.__extract(db):
            return 0
        if rpmconfig.printhash:
            printInfo(0, "\n")
        else:
            printInfo(1, "\n")
        # Don't fail if the post script fails, just print out an error
        if self["postinprog"] != None and not rpmconfig.noscripts:
            if not runScript(self["postinprog"], self["postin"], numPkgs):
                printError("%s: Error running post install script." \
                    % self.getNEVRA())
        self.rfilist = None
        return 1

    def erase(self, db=None):
        if not self.open():
            return 0
        if not self.__readHeader():
            return 0
        files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preunprog"] != None or self["postunprog"] != None:
            numPkgs = str(db.getNumPkgs(self["name"])-1)
        if self["preunprog"] != None and not rpmconfig.noscripts:
            if not runScript(self["preunprog"], self["preun"], numPkgs):
                printError("%s: Error running pre uninstall script." \
                    % self.getNEVRA())
        # Remove files starting from the end (reverse process to install)
        nfiles = len(files)
        n = 0
        pos = 0
        if rpmconfig.printhash:
            printInfo(0, "\r\t\t\t\t\t\t\t ")
        for i in xrange(len(files)-1, -1, -1):
            n += 1
            npos = int(n*22/nfiles)
            if pos < npos and rpmconfig.printhash:
                printInfo(0, "#"*(npos-pos))
            pos = npos
            f = files[i]
            if db.isDuplicate(f):
                printDebug(1, "File/Dir %s still in db, not removing..." % f)
                continue
            if os.path.isdir(f):
                if os.listdir(f) == []:
                    try:
                        os.rmdir(f)
                    except:
                        printWarning(1, "Couldn't remove dir %s from pkg %s" \
                            % (f, self.source))
            else:
                try:
                    os.unlink(f)
                except:
                    printWarning(1, "Couldn't remove file %s from pkg %s" \
                        % (f, self.source))
        if rpmconfig.printhash:
            printInfo(0, "\n")
        else:
            printInfo(1, "\n")
        # Don't fail if the post script fails, just print out an error
        if self["postunprog"] != None and not rpmconfig.noscripts:
            if not runScript(self["postunprog"], self["postun"], numPkgs):
                printError("%s: Error running post uninstall script." \
                    % self.getNEVRA())
        return 1

    def isSourceRPM(self):
        # XXX: is it right method how detect by header?
        if self["sourcerpm"] == None:
            return 1
        return 0

    def __readHeader(self, tags=None, ntags=None):
        if self.header_read:
            return 1
        (key, value) = self.io.read()
        # Read over lead
        while key != None and key != "-":
            (key, value) = self.io.read()
        self.range_signature = value
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
        self.range_header = value
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
        self.range_payload = value
        self.generateFileNames()
        self.header_read = 1
        return 1

    def __extract(self, db=None):
        files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.__generateFileInfoList()
        self.__generateHardLinkList()
        (filename, cpio, filesize) = self.io.read()
        nfiles = len(files)
        n = 0
        pos = 0
        if rpmconfig.printhash:
            printInfo(0, "\r\t\t\t\t\t\t\t ")
        while filename != None and filename != "EOF" :
            n += 1
            npos = int(n*22/nfiles)
            if pos < npos and rpmconfig.printhash:
                printInfo(0, "#"*(npos-pos))
            pos = npos
            if self.isSourceRPM() and os.path.dirname(filename)=='/':
                # src.rpm has empty tag "dirnames", but we use absolut paths in
                # io.read(), so at least the directory '/' is there ...
                filename = filename[1:]
            if self.rfilist.has_key(filename):
                rfi = self.rfilist[filename]
                if self.__verifyFileInstall(rfi, db):
                    if not rfi.getHardLinkID() in self.hardlinks.keys():
                        if not installFile(rfi, cpio, filesize):
                            return 0
                    else:
                        if filesize > 0:
                            if not installFile(rfi, cpio, filesize):
                                return 0
                            if not self.__handleHardlinks(rfi):
                                return 0
                else:
                    cpio.skipToNextFile()
                    self.__removeHardlinks(rfi)
            (filename, cpio, filesize) = self.io.read()
        if nfiles == 0:
            nfiles = 1
        if rpmconfig.printhash:
            printInfo(0, "#"*(22-int(22*n/nfiles)))
        return self.__handleRemainingHardlinks()

    def __verifyFileInstall(self, rfi, db):
        # No db -> overwrite file ;)
        if not db:
            return 1
        # File is not a regular file -> just do it
        if not S_ISREG(rfi.mode):
            return 1
        # File not already in db -> write it
        if not db.filenames.has_key(rfi.filename):
            return 1
        # Don't install ghost files ;)
        if rfi.flags & RPMFILE_GHOST:
            return 0
        plist = db.filenames[rfi.filename]
        # Not a config file -> always overwrite it, resolver didn't say we
        # had any conflicts ;)
        if rfi.flags & RPMFILE_CONFIG == 0:
            # Check if we need to overwrite a file on a multilib system. If any
            # package which already owns the file has a higher "arch" don't
            # overwrite it.
            for pkg in plist:
                if self["arch"] in arch_compats[pkg["arch"]]:
                    return 0
            return 1
        if not os.path.exists(rfi.filename):
            printWarning(1, "%s: File doesn't exist" % rfi.filename)
            return 1
        (mode, inode, dev, nlink, uid, gid, filesize, atime, mtime, ctime) \
            = os.stat(rfi.filename)
        # File on disc is not a regular file -> don't try to calc an md5sum
        if S_ISREG(mode):
            f = open(rfi.filename)
            m = md5.new()
            buf = "1"
            while buf:
                buf = f.read(65536)
                if buf:
                    m.update(buf)
            f.close()
            md5sum = m.hexdigest()
        # Same file in new rpm as on disk -> just write it.
        if rfi.mode == mode and rfi.uid == uid and rfi.gid == gid \
            and rfi.filesize == filesize and rfi.md5sum == md5sum:
            return 1
        # File has changed on disc, now check if it has changed between the
        # different packages that share it and the new package
        for pkg in plist:
            orfi = pkg.getRpmFileInfo(rfi.filename)
            # Is the current file in the filesystem identical to the one in the
            # old rpm? If yes, then it's a simple update.
            if orfi.mode == mode and orfi.uid == uid and orfi.gid == gid \
                and orfi.filesize == filesize and orfi.md5sum == md5sum:
                return 1
            # If installed and new stats of the file are the same don't do
            # anything with it. If the file hasn't changed in the packages we
            # keep the editited file on disc.
            if rfi.mode == orfi.mode and rfi.uid == orfi.uid and \
                rfi.gid == orfi.gid and rfi.filesize == orfi.filesize and \
                rfi.md5sum == orfi.md5sum:
                printWarning(1, "%s: Same file between new and installed package, skipping." % self.getNEVRA())
                continue
            # OK, file in new package is different to some old package and it
            # is editied on disc. Now verify if it is a noreplace or not
            if rfi.flags & RPMFILE_NOREPLACE:
                printWarning(0, "%s: config(noreplace) file found that changed between old and new rpms and has changed on disc, creating new file as %s.rpmnew" %(self.getNEVRA(), rfi.filename))
                rfi.filename += ".rpmnew"
            else:
                printWarning(0, "%s: config file found that changed between old and new rpms and has changed on disc, moving edited file to %s.rpmsave" %(self.getNEVRA(), rfi.filename))
                if os.rename(rfi.filename, rfi.filename+".rpmsave") != None:
                    raiseFatal("%s: Edited config file %s couldn't be renamed, aborting." % (self.getNEVRA(), rfi.filename))
            break
        return 1

    def generateFileNames(self):
        self["filenames"] = []
        if self["oldfilenames"] != None:
            self["filenames"] = self["oldfilenames"]
            return
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            filename = self["dirnames"][self["dirindexes"][i]] \
                + self["basenames"][i]
            self["filenames"].append(filename)

    def __generateFileInfoList(self):
        self.rpmusercache = RpmUserCache()
        self.rfilist = {}
        for filename in self["filenames"]:
            self.rfilist[filename] = self.getRpmFileInfo(filename)

    def __generateHardLinkList(self):
        self.hardlinks = {}
        for filename in self.rfilist.keys():
            rfi = self.rfilist[filename]
            if not S_ISREG(rfi.mode):
                continue
            key = rfi.getHardLinkID()
            if not self.hardlinks.has_key(key):
                self.hardlinks[key] = []
            self.hardlinks[key].append(rfi)
        for key in self.hardlinks.keys():
            if len(self.hardlinks[key]) == 1:
                del self.hardlinks[key]

    def __handleHardlinks(self, rfi):
        key = rfi.getHardLinkID()
        self.hardlinks[key].remove(rfi)
        for hrfi in self.hardlinks[key]:
            makeDirs(hrfi.filename)
            if not createLink(rfi.filename, hrfi.filename):
                return 0
        del self.hardlinks[key]
        return 1

    def __removeHardlinks(self, rfi):
        key = rfi.getHardLinkID()
        if self.hardlinks.has_key(key):
            del self.hardlinks[key]

    def __handleRemainingHardlinks(self):
        keys = self.hardlinks.keys()
        for key in keys:
            rfi = self.hardlinks[key][0]
            if not installFile(rfi, 0, 0):
                return 0
            if not self.__handleHardlinks(rfi):
                return 0
        return 1

    def getRpmFileInfo(self, filename):
        try:
            i = self["filenames"].index(filename)
        except:
            return None
        rpminode = None
        rpmmode = None
        rpmuid = None
        rpmgid = None
        rpmmtime = None
        rpmfilesize = None
        rpmdev = None
        rpmrdev = None
        rpmmd5sum = None
        rpmflags = None
        rpmfilecolor = None
        if self.has_key("fileinodes"):
            rpminode = self["fileinodes"][i]
        if self.has_key("filemodes"):
            rpmmode = self["filemodes"][i]
        if self.has_key("fileusername"):
            rpmuid = self.rpmusercache.getUID(self["fileusername"][i])
        if self.has_key("filegroupname"):
            rpmgid = self.rpmusercache.getGID(self["filegroupname"][i])
        if self.has_key("filemtimes"):
            rpmmtime = self["filemtimes"][i]
        if self.has_key("filesizes"):
            rpmfilesize = self["filesizes"][i]
        if self.has_key("filedevices"):
            rpmdev = self["filedevices"][i]
        if self.has_key("filerdevs"):
            rpmrdev = self["filerdevs"][i]
        if self.has_key("filemd5s"):
            rpmmd5sum = self["filemd5s"][i]
        if self.has_key("fileflags"):
            rpmflags = self["fileflags"][i]
        if self.has_key("filecolors"):
            rpmfilecolor = self["filecolors"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid, rpmgid,
            rpmmtime, rpmfilesize, rpmdev, rpmrdev, rpmmd5sum, rpmflags,
            rpmfilecolor)
        return rfi

    def getEpoch(self):
        e = self["epoch"]
        if e == None:
            return "0"
        return str(e[0])

    def getEVR(self):
        e = self["epoch"]
        if e != None:
            return "%s:%s-%s" % (str(e[0]), self["version"], self["release"])
        return "%s-%s" % (self["version"], self["release"])

    def getNEVR(self):
        return "%s-%s" % (self["name"], self.getEVR())

    def getNEVRA(self):
        return "%s.%s" % (self.getNEVR(), self["arch"])

    def getProvides(self):
        r = self.__getDeps(("providename", "provideflags", "provideversion"))
        r.append( (self["name"], RPMSENSE_EQUAL, self.getEVR()) )
        #if rpmconfig.ignore_epoch and self["epoch"] != None:
        #    r.append( (self["name"], RPMSENSE_EQUAL, "%s-%s" % (self["version"], self["release"])) )
        return r

    def getRequires(self):
        return self.__getDeps(("requirename", "requireflags", "requireversion"))

    def getObsoletes(self):
        return self.__getDeps(("obsoletename", "obsoleteflags",
            "obsoleteversion"))

    def getConflicts(self):
        return self.__getDeps(("conflictname", "conflictflags",
            "conflictversion"))

    def getTriggers(self):
        if self["triggerindex"] == None:
            return self.__getDeps(("triggername", "triggerflags",
                "triggerversion", "triggerscriptprog", "triggerscripts"))
        deps =  self.__getDeps(("triggername", "triggerflags",
            "triggerversion"))
        numdeps = len(deps)
        if len(self["triggerscriptprog"]) != len(self["triggerscripts"]):
            raiseFatal("%s: wrong length of triggerscripts/prog" % self.source)
        if numdeps != len(self["triggerindex"]):
            raiseFatal("%s: wrong length of triggerindex" % self.source)
        for i in xrange(numdeps):
            ti = self["triggerindex"][i]
            if ti > len(self["triggerscriptprog"]):
                raiseFatal("%s: wrong index in triggerindex" % self.source)
            deps[i].append(self["triggerscriptprog"][ti])
            deps[i].append(self["triggerscripts"][ti])
        return deps

    def __getDeps(self, depnames):
        if self[depnames[0]] == None:
            return []
        for dep in depnames:
            if dep == depnames[0] or self[dep] == None:
                continue
            if len(self[dep]) != len(self[depnames[0]]):
                raiseFatal("%s: wrong length of deps" % self.source)
        deps = []
        for i in xrange(0, len(self[depnames[0]])):
            l = []
            for j in xrange(0, len(depnames)):
                if self[depnames[j]] != None:
                    l.append(self[depnames[j]][i])
                else:
                    l.append(None)
            deps.append(l)
        return deps

# vim:ts=4:sw=4:showmatch:expandtab
