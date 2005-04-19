#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak,
#          Miloslav Trmac
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


import os.path, sys, struct, pwd, grp, md5, sha, weakref
from stat import S_ISREG

from functions import *
import openpgp

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
class FastRpmData(dict):
    __getitem__ = dict.get
    def __init__(self):
        dict.__init__(self)
        self.hash = int(str(weakref.ref(self)).split()[6][3:-1], 16)

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
                if rpmconfig.buildroot == None and \
                   os.path.isfile("/sbin/ldconfig"):
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
                if rpmconfig.buildroot == None and \
                   os.path.isfile("/sbin/ldconfig"):
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
    def __init__(self, source, verify=None, strict=None, hdronly=None,
                 db=None):
        RpmData.__init__(self)
        self.clear()
        self.source = source
        self.verify = verify
        self.strict = strict
        self.hdronly = hdronly
        self.range_signature = (None, None)
        self.range_header = (None, None)
        self.range_payload = (None, None)
        self.db = db

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
        if self.verify and self.verifyOneSignature() == -1:
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

    def verifySignatureTag(self, tag):
        """Verify digest or signature self["signature"][tag].

        Return 1 if verified, -1 if failed, 0 if unkown."""
        if tag == "dsaheader":
            if self.db is None:
                return 0
            sig = openpgp.parsePGPSignature(self["signature"][tag])
            digest = sig.prepareDigest()
            digest.update(RPM_HEADER_INDEX_MAGIC)
            r = self.__digestImmutableRegion(digest)
            if r != 1:
                return r
            if (sig.verifyDigest(self.db.keyring, sig.finishDigest(digest)) 
                is not None):
                return 1
            # FIXME: "missing key" and "invalid signature" treated equally
            return 0
        elif tag == "sha1header":
            digest = sha.new(RPM_HEADER_INDEX_MAGIC)
            r = self.__digestImmutableRegion(digest)
            if r != 1:
                return r
            if self["signature"][tag] == digest.hexdigest():
                return 1
            else:
                return -1
        elif tag == "size_in_sig":
            if self.range_header[0] is None:
                return 0
            fd = self.io.getFdForRange(self.range_header[0]
                                       + self.range_header[1], None)
            if fd is None:
                return 0
            total = os.fstat(fd.fileno()).st_size
            if self["signature"][tag][0] == total - self.range_header[0]:
                return 1
            else:
                return -1
        elif tag == "pgp" or tag == "gpg":
            if self.db is None or self.range_header[0] is None:
                return 0
            sig = openpgp.parsePGPSignature(self["signature"][tag])
            fd = self.io.getFdForRange(self.range_header[0], None)
            digest = sig.prepareDigest()
            updateDigestFromFile(digest, fd, None)
            if (sig.verifyDigest(self.db.keyring, sig.finishDigest(digest))
                is not None):
                return 1
            # FIXME: "missing key" and "invalid signature" treated equally
            return 0
        elif tag == "md5":
            if self.range_header[0] is None:
                return 0
            fd = self.io.getFdForRange(self.range_header[0], None)
            digest = md5.new()
            updateDigestFromFile(digest, fd, None)
            if self["signature"][tag] == digest.digest():
                return 1
            else:
                return -1
        # "payloadsize" requires uncompressing payload and adds no value,
        # unimplemented
        # "badsha1_1", "badsha1_2" are legacy, unimplemented.    
        return 0

    # [(tag name, needs payload)]
    __signatureUseOrder = [
        ("dsaheader", False), ("gpg", True), ("pgp", True),
        ("sha1header", False), ("md5", False)
    ]

    def verifyOneSignature(self):
        """Verify the "best" digest or signature available.

        Return 1 if verified, -1 if failed, 0 if unkown."""
        
        tags = [t for (t, payload) in self.__signatureUseOrder
                if not payload or not self.hdronly]
        for t in tags:
            r = self.verifySignatureTag(t)
            if r != 0:
                return r
        return 0

    def __digestImmutableRegion(self, digest):
        """Update digest with data from immutable header region."""

        immutable = self["immutable"]
        if immutable is None:
            # What was the digest computed from?
            return -1
        (tag, type_, offset, count) = struct.unpack("!4i", immutable)
        if (tag != 63 or type_ != RPM_BIN or -offset <= 0 or -offset % 16 != 0
            or count != 16):
            return -1
        regionIndexEntries = -offset / 16
        if self.range_header[0] is None:
            return 0
        fd = self.io.getFdForRange(*self.range_header)
        if fd is None:
            return 0
        data = fd.read(16)
        (totalIndexEntries, totalDataSize) = struct.unpack("!8x2i", data)
        data = fd.read(16 * totalIndexEntries)
        unsignedTags = []
        for i in xrange(totalIndexEntries):
            (tag, type_, offset, count) = \
                  struct.unpack("!4i", data[i * 16 : (i + 1) * 16])
            if tag == 63:
                break
            unsignedTags.append(tag)
        else:
            raiseFatal("%s: immutable tag disappeared" % self.source)
        if (type_ != RPM_BIN or count != 16 or
            i + regionIndexEntries > totalIndexEntries):
            return -1
        digest.update(struct.pack("!2i", regionIndexEntries, offset + 16))
        digest.update(data[i * 16 : (i + regionIndexEntries) * 16])
        for i in xrange(i + regionIndexEntries, totalIndexEntries):
            (tag,) = struct.unpack("!i", data[i * 16 : i * 16 + 4])
            unsignedTags.append(tag)
        if unsignedTags:
            # FIXME: only once per package
            printWarning(0, "%s: Unsigned tags %s"
                         % (self.source,
                            [rpmtagname[i] for i in unsignedTags]))
        # In practice region data starts at offset 0, but the original design
        # was proposing concatenated regions etc; where would the data region
        # start in that case? Lowest offset in region perhaps?
        updateDigestFromFile(digest, fd, offset + 16)
        return 1

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
                printError("\n%s: Error running pre install script." \
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
                printError("\n%s: Error running post install script." \
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
                printError("\n%s: Error running pre uninstall script." \
                    % self.getNEVRA())
        # Remove files starting from the end (reverse process to install)
        nfiles = len(files)
        n = 0
        pos = 0
        if rpmconfig.printhash:
            printInfo(0, "\r\t\t\t\t\t\t ")
        for i in xrange(len(files)-1, -1, -1):
            n += 1
            npos = int(n*30/nfiles)
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
                        # Maybe it's symlink....
                        try:
                            os.unlink(f)
                        except:
                            printWarning(1, "Couldn't remove dir %s from pkg %s" % (f, self.source))
            else:
                try:
                    os.unlink(f)
                except:
                    if not (self["fileflags"][i] & RPMFILE_GHOST):
                        printWarning(1, "Couldn't remove file %s from pkg %s" \
                            % (f, self.source))
        if rpmconfig.printhash:
            printInfo(0, "\n")
        else:
            printInfo(1, "\n")
        # Don't fail if the post script fails, just print out an error
        if self["postunprog"] != None and not rpmconfig.noscripts:
            if not runScript(self["postunprog"], self["postun"], numPkgs):
                printError("\n%s: Error running post uninstall script." \
                    % self.getNEVRA())
        return 1

    def isSourceRPM(self):
        # XXX: is it right method how detect by header?
        if self["sourcerpm"] == None:
            return 1
        return 0

    def isEqual(self, pkg):
        return self.getNEVRA() == pkg.getNEVRA()

    def isIdentical(self, pkg):
        if not self.isEqual(pkg):
            return 0
        if not self.has_key("signature") or not pkg.has_key("signature"):
            return 0
        # MD5 sum should always be there, so check that first
        if self["signature"].has_key("md5") and \
           pkg["signature"].has_key("md5"):
            return self["signature"]["md5"] == pkg["signature"]["md5"]
        if self["signature"].has_key("sha1header") and \
           pkg["signature"].has_key("sha1header"):
            return self["signature"]["sha1header"] == pkg["signature"]["sha1header"]
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
            printInfo(0, "\r\t\t\t\t\t\t ")
        while filename != None and filename != "EOF" :
            n += 1
            npos = int(n*30/nfiles)
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
            printInfo(0, "#"*(30-int(30*n/nfiles)))
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
            if self["arch"] == "noarch":
                return 1
            for pkg in plist:
                if not archDuplicate(self["arch"], pkg["arch"]) and \
                   self["arch"] in arch_compats[pkg["arch"]]:
                    return 0
            return 1
        # File should exsist in filesystem but doesn't...
        if not os.path.exists(rfi.filename):
            printWarning(1, "%s: File doesn't exist" % rfi.filename)
            return 1
        (mode, inode, dev, nlink, uid, gid, filesize, atime, mtime, ctime) \
            = os.stat(rfi.filename)
        # File on disc is not a regular file -> don't try to calc an md5sum
        if S_ISREG(mode):
            f = open(rfi.filename)
            m = md5.new()
            updateDigestFromFile(m, f)
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
                printWarning(2, "\n%s: Same config file between new and installed package, skipping." % self.getNEVRA())
                continue
            # OK, file in new package is different to some old package and it
            # is editied on disc. Now verify if it is a noreplace or not
            if rfi.flags & RPMFILE_NOREPLACE:
                printWarning(0, "\n%s: config(noreplace) file found that changed between old and new rpms and has changed on disc, creating new file as %s.rpmnew" %(self.getNEVRA(), rfi.filename))
                rfi.filename += ".rpmnew"
            else:
                printWarning(0, "\n%s: config file found that changed between old and new rpms and has changed on disc, moving edited file to %s.rpmsave" %(self.getNEVRA(), rfi.filename))
                if os.rename(rfi.filename, rfi.filename+".rpmsave") != None:
                    raiseFatal("\n%s: Edited config file %s couldn't be renamed, aborting." % (self.getNEVRA(), rfi.filename))
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
        deps = self.__getDeps(("triggername", "triggerflags",
            "triggerversion"))
        numdeps = len(deps)
        if len(self["triggerscriptprog"]) != len(self["triggerscripts"]):
            raiseFatal("%s: wrong length of triggerscripts/prog" % self.source)
        if numdeps != len(self["triggerindex"]):
            raiseFatal("%s: wrong length of triggerindex" % self.source)
        for i in xrange(numdeps):
            # Convert tuple into list, small hack
            di = deps[i]
            deps[i] = []
            deps[i].extend(di)
            ti = self["triggerindex"][i]
            if ti > len(self["triggerscriptprog"]):
                raiseFatal("%s: wrong index in triggerindex" % self.source)
            deps[i].append(self["triggerscriptprog"][ti])
            deps[i].append(self["triggerscripts"][ti])
        return deps

    def __getDeps(self, depnames):
        if self[depnames[0]] == None:
            return []
        deplength = len(self[depnames[0]])
        deps2 = []
        for d in depnames:
            x = self[d]
            if x != None:
                if len(x) != deplength:
                    raiseFatal("%s: wrong length of deps" % self.source)
                deps2.append(x)
            else:
                deps2.append(None*deplength)
        return zip(*deps2)


def readRpmPackage(source, verify=None, strict=None, hdronly=None, db=None,
                   tags=None):
    """Read RPM package from source and close it.

    tags, if defined, specifies tags to load."""

    pkg = RpmPackage(source, verify, strict, hdronly, db)
    pkg.read(tags = tags)
    pkg.close()
    return pkg


# vim:ts=4:sw=4:showmatch:expandtab
