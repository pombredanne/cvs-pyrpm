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


class RpmUserCache:
    def __init__(self):
        self.uid = {}
        self.gid = {}

    def getUID(self, username):
        if username == "root":
            return 0
        if not self.uid.has_key(username):
            if os.path.isfile("/etc/passwd"):
                try:
                    pw = pwd.getpwnam(username)
                    self.uid[username] = pw[2]
                except:
                    pass
        if not self.uid.has_key(username):
            self.uid[username] = 0
        return self.uid[username]

    def getGID(self, groupname):
        if groupname == "root":
            return 0
        if not self.gid.has_key(groupname):
            if os.path.isfile("/etc/group"):
                try:
                    gr = grp.getgrnam(groupname)
                    self.gid[groupname] = gr[2]
                except:
                    pass
        if not self.gid.has_key(groupname):
            self.gid[groupname] = 0
        return self.gid[groupname]


class RpmPackage(RpmData):
    def __init__(self, source, verify=None, legacy=None, hdronly=None):
        RpmData.__init__(self)
        self.clear()
        self.source = source
        self.verify = verify
        self.legacy = legacy
        self.hdronly = hdronly

    def clear(self):
        self.io = None
        self.header_read = 0
        self.rpmusercache = RpmUserCache()

    def open(self, mode="r"):
        if self.io != None:
            return 1
        self.io = getRpmIOFactory(self.source, self.verify, self.legacy, self.hdronly)
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
            origsource = self.source
            self.source = source
            self.close()
        if not self.open("w"):
            return 0
        ret = self.io.write(self)
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
        if self["preinprog"] != None or self["postinprog"] != None:
            numPkgs = str(db.getNumPkgs(self["name"])+1)
        if self["preinprog"] != None:
            if not runScript(self["preinprog"], self["prein"], numPkgs):
                printError("%s: Error running pre install script." % self.getNEVRA())
                return 0
        if not self.__extract(db):
            return 0
        # Don't fail if the post script fails, just print out an error
        if self["postinprog"] != None:
            if not runScript(self["postinprog"], self["postin"], numPkgs):
                printError("%s: Error running post install script." % self.getNEVRA())
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
        if self["preunprog"] != None:
            if not runScript(self["preunprog"], self["preun"], numPkgs):
                printError("%s: Error running pre uninstall script." % self.getNEVRA())
                return 0
        # Remove files starting from the end (reverse process to install)
        for i in xrange(len(files)-1, -1, -1):
            f = files[i]
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
        # Don't fail if the post script fails, just print out an error
        if self["postunprog"] != None:
            if not runScript(self["postunprog"], self["postun"], numPkgs):
                printError("%s: Error running post uninstall script." % self.getNEVRA())
        return 1

    def isSourceRPM(self):
        # XXX: is it right method how detect by header?
        if self["sourcerpm"]==None:
            return 1
        return 0

    def __readHeader(self, tags=None, ntags=None):
        if self.header_read:
#            self.io.read(skip=1)      # Skip over complete header
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
        self.generateFileNames()
        self.header_read = 1
        return 1

    def __extract(self, db=None):
        files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.__generateFileInfoList()
        self.__generateHardLinkList()
        (filename, filerawdata) = self.io.read()
        nfiles = len(files)
        n = 0
        pos = 0
        printInfo(0, "\r\t\t\t\t ")
        while filename != None and filename != "EOF" :
            n += 1
            npos = int(n*45/nfiles)
            if pos < npos:
                printInfo(0, "#"*(npos-pos))
            pos = npos
            sys.stdout.flush()
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
        if nfiles == 0:
            nfiles = 1
        printInfo(0, "#"*(45-int(45*n/nfiles)))
        return self.__handleRemainingHardlinks()

    def __verifyFileInstall(self, rfi, db):
        # No db -> overwrite file ;)
        if not db:
            return 1
        # File is not a regular file -> just do it
        if (rfi.mode & CP_IFMT) != CP_IFREG:
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
        for pkg in plist:
            orfi = pkg.getRpmFileInfo(rfi.filename)
            # Is the current file in the filesystem identical to the one in the
            # old rpm? If yes, then it's a simple update.
            if orfi.mode == mode and orfi.uid == uid and orfi.gid == gid and orfi.filesize == filesize and orfi.md5sum == md5sum:
                return 1
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

    def generateFileNames(self):
        self["filenames"] = []
        if self["oldfilenames"] != None:
            self["filenames"] = self["oldfilenames"]
            return
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            filename = self["dirnames"][self["dirindexes"][i]] + self["basenames"][i]
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
        rpmuid = self.rpmusercache.getUID(self["fileusername"][i])
        rpmgid = self.rpmusercache.getGID(self["filegroupname"][i])
        rpmmtime = self["filemtimes"][i]
        rpmfilesize = self["filesizes"][i]
        rpmdev = self["filedevices"][i]
        rpmrdev = self["filerdevs"][i]
        rpmmd5sum = self["filemd5s"][i]
        rpmflags = self["fileflags"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid, rpmgid, rpmmtime, rpmfilesize, rpmdev, rpmrdev, rpmmd5sum, rpmflags)
        return rfi

    def getEVR(self):
        if self["epoch"] != None:
            e = str(self["epoch"][0])+":"
        else:
            e = ""
        return "%s%s-%s" % (e, self["version"], self["release"])

    def getNEVR(self):
        return "%s-%s" % (self["name"], self.getEVR())

    def getNEVRA(self):
        return "%s.%s" % (self.getNEVR(), self["arch"])

    def getProvides(self):
        return self.__getDeps(("providename", "provideflags", "provideversion"))

    def getRequires(self):
        return self.__getDeps(("requirename", "requireflags", "requireversion"))

    def getObsoletes(self):
        return self.__getDeps(("obsoletename", "obsoleteflags", "obsoleteversion"))

    def getConflicts(self):
        return self.__getDeps(("conflictname", "conflictflags", "conflictversion"))

    def getTriggers(self):
        if self["triggerindex"] == None:
            return self.__getDeps(("triggername", "triggerflags", "triggerversion", "triggerscriptprog", "triggerscripts"))
        deps =  self.__getDeps(("triggername", "triggerflags", "triggerversion"))
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
                print self["triggerindex"]
                print dep, depnames[0]
                print self[dep], self[depnames[0]]
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
