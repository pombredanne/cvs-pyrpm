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


import os.path, sys, pwd, grp, md5, sha
from stat import S_ISREG
from io import getRpmIOFactory
from base import RpmFileInfo, RPM_HEADER_INDEX_MAGIC, RPM_HEADER_LEAD_MAGIC, RPMFILE_GHOST, RPMFILE_CONFIG, RPMFILE_NOREPLACE, RPM_STRING, RPM_BIN, RPM_STRING_ARRAY, RPM_I18NSTRING, RPM_INT8, RPM_INT16, RPM_INT32, RPM_INT64, RPMSENSE_EQUAL, arch_compats
import functions
import openpgp


class _RpmFilenamesIterator:
    """An iterator over package files stored as basenames + dirindexes"""

    def __init__(self, pkg):
        self.pkg = pkg
        self.idx = -1
        self.has_oldfilenames = self.pkg.has_key("oldfilenames")

    def __iter__(self):
        return self

    def __len__(self):
        if self.has_oldfilenames:
            return len(self.pkg["oldfilenames"])
        if self.pkg["basenames"] != None and self.pkg["dirnames"] != None:
            return len(self.pkg["basenames"])
        return 0

    def __getitem__(self, i):
        if self.has_oldfilenames:
            return self.pkg["oldfilenames"][i]
        return self.pkg["dirnames"][self.pkg["dirindexes"][i]] \
               + self.pkg["basenames"][i]

    def index(self, name):
        if self.has_oldfilenames:
            return self.pkg["oldfilenames"].index(name)
        basename = os.path.basename(name)
        i = 0
        while i < len(self.pkg["basenames"]):
            i = self.pkg["basenames"].index(basename, i)
            if i < 0:
                break
            dirname = os.path.dirname(name)
            if len(dirname) > 0 and dirname[-1] != "/":
                dirname += "/"
            if self.pkg["dirnames"][self.pkg["dirindexes"][i]] == dirname:
                return i
            i += 1
        raise ValueError

    def next(self):
        self.idx += 1
        if self.has_oldfilenames:
            if self.idx == len(self.pkg["oldfilenames"]):
                raise StopIteration
        if not self.pkg.has_key("basenames") or \
               self.idx == len(self.pkg["basenames"]):
            raise StopIteration
        return self[self.idx]


class RpmData(dict):
    __hashcount__ = 0
    def __init__(self, config):
        dict.__init__(self)
        self.config = config
        self.hash = RpmData.__hashcount__
        RpmData.__hashcount__ += 1

    def __getitem__(self, item):
        if item == "filenames":
            return _RpmFilenamesIterator(self)
        return dict.get(self, item)

    def __repr__(self):
        return "FastRpmData: <0x" + str(self.hash) + ">"

    def __hash__(self):
        return self.hash

    def __eq__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 0
        return self.hash == pkg.hash

    def __ne__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 1
        return self.hash != pkg.hash


class RpmUserCache:
    """If glibc is not yet installed (/sbin/ldconfig is missing), we parse
    /etc/passwd and /etc/group with our own routines."""
    def __init__(self, config):
        self.config = config
        self.uid = {"root": 0}
        self.gid = {"root": 0}

    def __parseFile(self, ugfile):
        """Parse ugfile.

        Return { name: id }."""

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
        """Return UID for username, or 0 if unknown."""

        if not self.uid.has_key(username):
            if os.path.isfile("/etc/passwd"):
                if self.config.buildroot == None and \
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
        """Return GID for groupname, or 0 if unknown."""

        if not self.gid.has_key(groupname):
            if os.path.isfile("/etc/group"):
                if self.config.buildroot == None and \
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
    def __init__(self, config, source, verify=None, hdronly=None, db=None):
        RpmData.__init__(self, config)
        self.config = config
        self.clear()
        self.source = source
        self.yumrepo = None     # Yum repository if package is from that repo
        self.yumhref = None     # Original relative href in yum repo
        self.compstype = None   # If available refers to the type in comps.xml
        self.verify = verify    # Verify file format constraints and signatures
        self.hdronly = hdronly  # Don't open the payload
        self.db = db            # RpmDatabase
        self.io = None          # Our rpm IO class
        self.issrc = None       # Stored from rpm IO class after read
        # Ranges are (starting position or None, length)
        self.range_signature = (None, None) # Signature header
        self.range_header = (None, None) # Main header
        self.range_payload = (None, None) # Payload; length is always None

    def clear(self, tags=None, ntags=None):
        """Drop read data and prepare for rereading it, unless install_id is
        known."""

        if self.has_key("install_id"):
            return

        for key in self.keys():
            if tags and key in tags:
                del self[key]
            elif ntags and not key in ntags:
                del self[key]
            elif not tags and not ntags:
                del self[key]

        self.header_read = 0
        self.rpmusercache = RpmUserCache(self.config)

    def open(self, mode="r"):
        """Open the package if it is not already open and install_id is not
        known.

        Raise IOError."""

        if self.has_key("install_id"):
            return

        if self.io != None:
            return
        self.io = getRpmIOFactory(self.config, self.source, self.hdronly)
        self.io.open(mode)

    def close(self):
        """Close the package IO if install_id is not known.

        Raise IOError."""

        if self.has_key("install_id"):
            return

        if self.io != None:
            try:
                self.io.close()
            finally:
                self.io = None

    def read(self, tags=None, ntags=None):
        """Open and read the package.

        Read only specified tags if tags != None, or skip tags in ntags.  In
        addition, generate self["provides"], self["requires"],
        self["obsoletes"], self["conflicts"] and self["triggers"].  Raise
        ValueError on invalid data, IOError."""

        self.open()
        self.__readHeader(tags, ntags)
        if self.verify and self.verifyOneSignature() == -1:
            raise ValueError, "Signature verification failed."""
        if self.io:
            self.issrc = self.io.issrc
        self["provides"] = self.getProvides()
        self["requires"] = self.getRequires()
        self["obsoletes"] = self.getObsoletes()
        self["conflicts"] = self.getConflicts()
        self["triggers"] = self.getTriggers()

    def reread(self, tags=None, ntags=None):
        """Reread the package. Basically reopens, clears and trys to read
        the headers again."""
        self.close()
        self.clear()
        self.read(tags, ntags)

    def write(self, source=None):
        """Open and write package to the specified source.

        Use the the original source if source is not specified.  Raise IOError,
        NotImplementedError."""

        if source != None:
            #origsource = self.source
            self.source = source
            self.close()
        self.open("w")
        self.io.write(self)

    def verifySignatureTag(self, tag):
        """Verify digest or signature self["signature"][tag].

        Return 1 if verified, -1 if failed, 0 if unkown. Raise IOError."""

        if tag == "dsaheader":
            if self.db is None:
                return 0
            try:
                sig = openpgp.parsePGPSignature(self["signature"][tag])
                digest = sig.prepareDigest()
                digest.update(RPM_HEADER_INDEX_MAGIC)
                self.io.updateDigestFromRegion(digest, self["immutable"],
                                               self.range_header)
            except NotImplementedError:
                return 0
            except ValueError:
                return -1
            return (sig.verifyDigest(self.db.keyring, sig.finishDigest(digest))
                    [0])
        elif tag == "sha1header":
            digest = sha.new(RPM_HEADER_INDEX_MAGIC)
            try:
                self.io.updateDigestFromRegion(digest, self["immutable"],
                                               self.range_header)
            except NotImplementedError:
                return 0
            except ValueError:
                return -1
            if self["signature"][tag] == digest.hexdigest():
                return 1
            else:
                return -1
        elif tag == "size_in_sig":
            if self.range_header[0] is None:
                return 0
            total = self.io.getRpmFileSize()
            if total is None:
                return 0
            elif self["signature"][tag][0] == total - self.range_header[0]:
                return 1
            else:
                return -1
        elif tag == "pgp" or tag == "gpg":
            if self.db is None or self.range_header[0] is None:
                return 0
            try:
                sig = openpgp.parsePGPSignature(self["signature"][tag])
            except ValueError:
                return -1
            try:
                digest = sig.prepareDigest()
                self.io.updateDigestFromRange(digest, self.range_header[0],
                                              None)
            except NotImplementedError:
                return 0
            return (sig.verifyDigest(self.db.keyring, sig.finishDigest(digest))
                    [0])
        elif tag == "md5":
            if self.range_header[0] is None:
                return 0
            digest = md5.new()
            try:
                self.io.updateDigestFromRange(digest, self.range_header[0],
                                              None)
            except NotImplementedError:
                return 0
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

        Return 1 if verified, -1 if failed, 0 if unkown. Raise IOError."""

        tags = [tag for (tag, payload) in self.__signatureUseOrder
                if (tag in self["signature"]
                    and not (payload and self.hdronly))]
        for t in tags:
            r = self.verifySignatureTag(t)
            if r != 0:
                return r
        return 0

    def install(self, db=None, tags=None, ntags=None):
        """Open package, read its header and install it.

        Use RpmDatabase db for getting information, don't modify it.  Run
        specified scripts, but no triggers.  Raise ValueError on invalid
        package data, IOError, OSError."""

        self.open()
        self.__readHeader(tags, ntags)
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preinprog"] != None or self["postinprog"] != None:
            numPkgs = str(len(db.getPkgsByName(self["name"]))+1)
        if self["preinprog"] != None and not self.config.noscripts:
            try:
                (status, rusage, log) = functions.runScript(self["preinprog"], self["prein"], [numPkgs], rusage = self.config.rusage)
            except (IOError, OSError), e:
                self.config.printError("\n%s: Error running pre install script: %s" \
                    % (self.getNEVRA(), e))
                # return 0
            if rusage != None and len(rusage):
                sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (self.getNEVRA(), "prein", str(rusage[0]), str(rusage[1])))
            if status != 0:
                self.config.printError("Error running pre install script for package %s" % self.getNEVRA())
        self.__extract(db)
        if self.config.printhash:
            self.config.printInfo(0, "\n")
        else:
            self.config.printInfo(1, "\n")
        # Don't fail if the post script fails, just print out an error
        if self["postinprog"] != None and not self.config.noscripts:
            try:
                (status, rusage, log) = functions.runScript(self["postinprog"], self["postin"], [numPkgs], rusage = self.config.rusage)
            except (IOError, OSError), e:
                self.config.printError("\n%s: Error running post install script: %s" \
                    % (self.getNEVRA(), e))
            if rusage != None and len(rusage):
                sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (self.getNEVRA(), "postin", str(rusage[0]), str(rusage[1])))
            if status != 0:
                self.config.printError("Error running post install script for package %s" % self.getNEVRA())
        self.rfilist = None

    def erase(self, db=None):
        """Open package, read its header and remove it.

        Use RpmDatabase db for getting information, don't modify it.  Run
        specified scripts, but no triggers.  Raise ValueError on invalid
        package data, IOError."""

        self.open()
        self.__readHeader()
        files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preunprog"] != None or self["postunprog"] != None:
            numPkgs = str(len(db.getPkgsByName(self["name"]))-1)
        if self["preunprog"] != None and not self.config.noscripts:
            try:
                (status, rusage, log) = functions.runScript(self["preunprog"], self["preun"], [numPkgs], rusage = self.config.rusage)
            except (IOError, OSError), e:
                self.config.printError("\n%s: Error running pre uninstall script: %s" \
                    % (self.getNEVRA(), e))
                # return 0
            if rusage != None and len(rusage):
                sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (self.getNEVRA(), "preun", str(rusage[0]), str(rusage[1])))
            if status != 0:
                self.config.printError("Error running pre uninstall script for package %s" % self.getNEVRA())
        # Generate the rpmfileinfo list, needed for erase verification
        self.__generateFileInfoList()
        # Remove files starting from the end (reverse process to install)
        nfiles = len(files)
        n = 0
        pos = 0
        if self.config.printhash:
            self.config.printInfo(0, "\r\t\t\t\t\t\t ")
        for i in xrange(len(files)-1, -1, -1):
            n += 1
            npos = int(n*30/nfiles)
            if pos < npos and self.config.printhash:
                self.config.printInfo(0, "#"*(npos-pos))
            pos = npos
            f = files[i]
            if db.numFileDuplicates(f) > 1:
                self.config.printDebug(1, "File/Dir %s still in db, not removing..." % f)
                continue
            if os.path.isdir(f):
                if os.listdir(f) == []:
                    try:
                        os.rmdir(f)
                    except OSError:
                        # Maybe it's symlink....
                        try:
                            os.unlink(f)
                        except OSError:
                            self.config.printWarning(2, "Couldn't remove dir %s from pkg %s" % (f, self.source))
            else:
                if self.rfilist.has_key(f):
                    rfi = self.rfilist[f]
                    # Check if we need to erase the file
                    if not self.__verifyFileErase(rfi):
                        continue
                    try:
                        os.unlink(f)
                    except OSError:
                        if not (rfi.flags & RPMFILE_GHOST):
                            self.config.printWarning(2, "Couldn't remove file %s from pkg %s" \
                                % (f, self.source))
        if nfiles == 0:
            nfiles = 1
        if self.config.printhash:
            self.config.printInfo(0, "#"*(30-int(30*n/nfiles)) + "\n")
        else:
            self.config.printInfo(1, "\n")
        # Hack to prevent errors for glibc and bash postunscripts
        #if self["name"] == "glibc" or self["name"] == "bash":
        #    return
        # Don't fail if the post script fails, just print out an error
        if self["postunprog"] != None and not self.config.noscripts:
            try:
                (status, rusage, log) = functions.runScript(self["postunprog"], self["postun"], [numPkgs], rusage = self.config.rusage)
            except (IOError, OSError), e:
                self.config.printError("\n%s: Error running post uninstall script: %s" \
                    % (self.getNEVRA(), e))
            if rusage != None and len(rusage):
                sys.stderr.write("\nRUSAGE, %s_%s, %s, %s\n" % (self.getNEVRA(), "preun", str(rusage[0]), str(rusage[1])))
            if status != 0:
                self.config.printError("Error running post uninstall script for package %s" % self.getNEVRA())

    def isSourceRPM(self):
        """Return 1 if the package is a SRPM."""

        # XXX: is it a right method how to detect it by header?
        if self.issrc != None:
            return self.issrc
        if self["sourcerpm"] == None:
            return 1
        return 0

    def isEqual(self, pkg):
        """Return true if self and pkg have the same NEVRA. Missing Epoch
        is identical to Epoch=0."""

        if self["name"]    != pkg["name"] or \
           self["version"] != pkg["version"] or \
           self["release"] != pkg["release"] or \
           self["arch"]    != pkg["arch"]:
            return 0

        if not self["epoch"] or len(self["epoch"]) == 0:
            e1 = 0
        else:
            e1 = self["epoch"][0]
        if not pkg["epoch"] or len(pkg["epoch"]) == 0:
            e2 = 0
        else:
            e2 = pkg["epoch"][0]

        return e1 == e2

    def isIdentical(self, pkg):
        """Return true if self and pkg have the same checksum.

        Use md5, or sha1header if md5 is missing."""

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
        """Read signature header to self["signature"], tag header to self.

        Use only specified tags if tags != None, or skip tags in ntags.  Raise
        ValueError on invalid data, IOError."""

        if self.header_read:
            return
        (key, value) = self.io.read()
        # Read over lead
        while key != "-":
            (key, value) = self.io.read()
        self.range_signature = value
        # Read sig
        (key, value) = self.io.read()
        while key != "-":
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
        while key != "-":
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

    def __extract(self, db=None):
        """Extract files from self.io (positioned at start of payload).

        Raise ValueError on invalid package data, IOError, OSError."""

        files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.__generateFileInfoList()
        self.hardlinks = {}
        (filename, cpio, filesize) = self.io.read()
        nfiles = len(files)
        n = 0
        pos = 0
        issrc = self.isSourceRPM()
        if self.config.printhash:
            self.config.printInfo(0, "\r\t\t\t\t\t\t ")
        while filename != "EOF":
            n += 1
            npos = int(n*30/nfiles)
            if pos < npos and self.config.printhash:
                self.config.printInfo(0, "#"*(npos-pos))
            pos = npos
            if issrc and filename[:1] == "/":
                # src.rpm has empty tag "dirnames", but we use absolut paths in
                # io.read(), so at least the directory '/' is there ...
                filename = filename[1:]
            if self.rfilist.has_key(filename):
                rfi = self.rfilist[filename]
                if self.__verifyFileInstall(rfi, db):
                    if filesize == 0 and S_ISREG(rfi.mode): # Only hardlink reg
                        self.__possibleHardLink(rfi)
                    else:
                        functions.installFile(rfi, cpio, filesize, not issrc)
                        # Many scripts have problems like e.g. openssh is
                        # stopping all sshd (also outside of a chroot if
                        # it is de-installed. Real hacky workaround:
                        if self.config.service and filename == "/sbin/service":
                            open("/sbin/service", "wb").write("exit 0\n")
                        self.__handleHardlinks(rfi)
                else:
                    cpio.skipToNextFile()
                    if filesize > 0:
                        # FIXME: If other hard links are installed, the data
                        # is lost.
                        self.__removeHardlinks(rfi)
            # FIXME: else report error?
            (filename, cpio, filesize) = self.io.read()
        if nfiles == 0:
            nfiles = 1
        if self.config.printhash:
            self.config.printInfo(0, "#"*(30-int(30*n/nfiles)))
        self.__handleRemainingHardlinks()

    def __verifyFileInstall(self, rfi, db):
        """Return 1 if file with RpmFileInfo rfi should be installed.

        Modify rfi.filename if necessary.  Raise OSError."""

        # No db -> overwrite file ;)
        if not db:
            return 1
        # File is not a regular file -> just do it
        if not S_ISREG(rfi.mode):
            return 1
        plist = db.searchFilenames(rfi.filename)
        # File not already in db -> write it
        if len(plist) == 0:
            return 1
        # Don't install ghost files ;)
        # FIXME: check at the very start?
        if rfi.flags & RPMFILE_GHOST:
            return 0
        # Not a config file -> always overwrite it, resolver didn't say we
        # had any conflicts ;)
        if rfi.flags & RPMFILE_CONFIG == 0:
            # Check if we need to overwrite a file on a multilib system. If any
            # package which already owns the file has a higher "arch" don't
            # overwrite it.
            if self["arch"] == "noarch":
                return 1
            for pkg in plist:
                if not functions.archDuplicate(self["arch"], pkg["arch"]) and \
                   self["arch"] in arch_compats[pkg["arch"]]:
                    return 0
            return 1
        # File should exist in filesystem but doesn't...
        if not os.path.exists(rfi.filename):
            self.config.printWarning(1, "%s: File doesn't exist" % rfi.filename)
            return 1
        (mode, inode, dev, nlink, uid, gid, filesize, atime, mtime, ctime) \
            = os.stat(rfi.filename)
        # File on disc is not a regular file -> don't try to calc an md5sum
        if S_ISREG(mode):
            try:
                f = open(rfi.filename)
                m = md5.new()
                functions.updateDigestFromFile(m, f)
                f.close()
                md5sum = m.hexdigest()
            except IOError, e:
                self.config.printWarning(0, "%s: %s" % (rfi.filename, e))
                md5sum = ''
        # Same file in new rpm as on disk -> just write it.
        if rfi.mode == mode and rfi.uid == uid and rfi.gid == gid \
            and rfi.filesize == filesize and rfi.md5sum == md5sum:
            return 1
        # File has changed on disc, now check if it has changed between the
        # different packages that share it and the new package
        # Remember if we have to actually write the file or not.
        do_write = 0
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
                self.config.printWarning(2, "\n%s: Same config file between new and installed package, skipping." % self.getNEVRA())
                continue
            # OK, file in new package is different to some old package and it
            # is editied on disc. Now verify if it is a noreplace or not
            if rfi.flags & RPMFILE_NOREPLACE:
                self.config.printWarning(0, "\n%s: config(noreplace) file found that changed between old and new rpms and has changed on disc, creating new file as %s.rpmnew" %(self.getNEVRA(), rfi.filename))
                rfi.filename += ".rpmnew"
            else:
                self.config.printWarning(0, "\n%s: config file found that changed between old and new rpms and has changed on disc, moving edited file to %s.rpmsave" %(self.getNEVRA(), rfi.filename))
                try:
                    os.rename(rfi.filename, rfi.filename+".rpmsave")
                except OSError, e:
                    self.config.printError("%s: Can't rename edited config "
                                           "file %s"
                                           % (self.getNEVRA(), rfi.filename))
                    raise
            # Now we know we have to write either a .rpmnew file or we have
            # already backed up the old one to .rpmsave and need to write the
            # new file
            do_write = 1
            break
        return do_write

    def __verifyFileErase(self, rfi):
        """Return 1 if file with RpmFileInfo rfi should be erased.

        Modify rfi.filename if necessary.  Raise OSError."""
        # Special case config files
        if rfi.flags & RPMFILE_CONFIG:
            # Is this a %ghost config file?
            if rfi.flags & RPMFILE_GHOST:
                return 0        # Don't remove if %ghost file
            # File should exist in filesystem but doesn't...
            if not os.path.exists(rfi.filename):
                self.config.printWarning(2, "%s: File doesn't exist" % rfi.filename)
                return 0
            (mode, inode, dev, nlink, uid, gid, filesize, atime, mtime, ctime) \
                = os.stat(rfi.filename)
            # File on disc is not a regular file -> don't try to calc an md5sum
            md5sum = ''
            if S_ISREG(mode):
                try:
                    f = open(rfi.filename)
                    m = md5.new()
                    functions.updateDigestFromFile(m, f)
                    f.close()
                    md5sum = m.hexdigest()
                except IOError, e:
                    self.config.printWarning(0, "%s: %s" % (rfi.filename, e))
            # Same file in new rpm as on disk -> just erase it.
            if rfi.mode == mode and rfi.uid == uid and rfi.gid == gid \
                and rfi.filesize == filesize and rfi.md5sum == md5sum:
                return 1
            try:
                os.rename(rfi.filename, rfi.filename+".rpmsave")
            except OSError, e:
                self.config.printError("%s: Can't rename edited config "
                                       "file %s"
                                       % (self.getNEVRA(), rfi.filename))
            # We only get here if it was a config file, no ghost and has been
            # edited and renamed to .rpmsave on disc, so no need to remove
            # anymore.
            return 0
        return 1

    def generateFileNames(self):
        """Generate basenames, dirnames and dirindexes for old packages from
        oldfilenames"""

        # Don't recreate basnames/dirnames/dirindexes if we already have them.
        if self.has_key("dirnames") or self.has_key("basenames") or \
           self.has_key("dirindexes"):
            return

        if self["oldfilenames"] != None and len(self["oldfilenames"]) > 0:
            self["basenames"] = [ ]
            self["dirnames"] = [ ]
            self["dirindexes"] = [ ]
            for filename in self["oldfilenames"]:
                basename = os.path.basename(filename)
                dirname = os.path.dirname(filename)
                if dirname[-1] != "/":
                    dirname += "/"
                dirindex = functions.bsearch(dirname, self["dirnames"],
                                             len(self["dirnames"]))
                if dirindex < 0:
                    self["dirnames"].append(dirname)
                    dirindex = len(self["dirnames"]) - 1
                self["basenames"].append(basename)
                self["dirindexes"].append(dirindex)

    def __generateFileInfoList(self):
        """Build self.rfilist: {path name: RpmFileInfo}"""

        self.rpmusercache = RpmUserCache(self.config)
        self.rfilist = {}
        issrc = self.isSourceRPM()
        for filename in self["filenames"]:
            rfi = self.getRpmFileInfo(filename)
            if issrc:
                rfi.filename = self.config.srpmdir + "/" + rfi.filename
            self.rfilist[filename] = rfi

    def __possibleHardLink(self, rfi):
        """Add the given RpmFileInfo rfi as a possible hardlink"""

        key = rfi.getHardLinkID()
        self.hardlinks.setdefault(key, []).append(rfi)

    def __handleHardlinks(self, rfi):
        """Create hard links to RpmFileInfo rfi if specified so in
        self.hardlinks.

        Raise IOError, OSError."""

        key = rfi.getHardLinkID()
        links = self.hardlinks.get(key)
        if not links:
            return
        for hrfi in links:
            functions.makeDirs(hrfi.filename)
            functions.createLink(rfi.filename, hrfi.filename)
        del self.hardlinks[key]

    def __removeHardlinks(self, rfi):
        """Drop information about hard links to RpmFileInfo rfi, if any."""

        key = rfi.getHardLinkID()
        if self.hardlinks.has_key(key):
            del self.hardlinks[key]

    def __handleRemainingHardlinks(self):
        """Create empty hard-linked files according to self.hardlinks.

        Raise ValueError on invalid package data, IOError, OSError."""

        issrc = self.isSourceRPM()
        for key in self.hardlinks.keys():
            rfi = self.hardlinks[key].pop(0)
            functions.installFile(rfi, None, 0, not issrc)
            self.__handleHardlinks(rfi)

    def getRpmFileInfo(self, filename):
        """Return RpmFileInfo describing filename, or None if this package does
        not contain filename."""

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
        rpmlinktos = None
        rpmflags = None
        rpmverifyflags = None
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
        if self.has_key("filelinktos"):
            rpmlinktos = self["filelinktos"][i]
        if self.has_key("fileflags"):
            rpmflags = self["fileflags"][i]
        if self.has_key("fileverifyflags"):
            rpmverifyflags = self["fileverifyflags"][i]
        if self.has_key("filecolors"):
            rpmfilecolor = self["filecolors"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid,
                          rpmgid, rpmmtime, rpmfilesize, rpmdev, rpmrdev,
                          rpmmd5sum, rpmlinktos, rpmflags, rpmverifyflags,
                          rpmfilecolor)
        return rfi

    def getEpoch(self):
        """Return %epoch as a string, or "0" for unspecified epoch."""

        e = self["epoch"]
        if e == None:
            return "0"
        return str(e[0])

    def getVR(self):
        """Return %version-%release."""

        return "%s-%s" % (self["version"], self["release"])

    def getEVR(self):
        """Return [%epoch:]%version-%release."""

#        e = self["epoch"]
#        if e != None:
#            return "%s:%s-%s" % (str(e[0]), self["version"], self["release"])
#        return "%s-%s" % (self["version"], self["release"])
        # Need to always use epochs because of repos. Maybe fixable in the
        # future.
        return "%s:%s-%s" % (self.getEpoch(), self["version"], self["release"])

    def getNEVR(self):
        """Return %name-[%epoch:]%version-%release."""

        return "%s-%s" % (self["name"], self.getEVR())

    def getNEVRA(self):
        """Return %name-[%epoch:]%version-%release.%arch."""

        if self.isSourceRPM():
            return "%s.src" % self.getNEVR()
        return "%s.%s" % (self.getNEVR(), self["arch"])

    def getProvides(self):
        """Return built value for self["provides"].
        Don't add the self provide anymore, it's added now properly in the
        ProvidesList if it's not there.
        Raise ValueError on invalid data."""

        return self.__getDeps(("providename", "provideflags", "provideversion"))
        #r = self.__getDeps(("providename", "provideflags", "provideversion"))
        #r.append( (self["name"], RPMSENSE_EQUAL, self.getEVR()) )
        #return r

    def getRequires(self):
        """Return built value for self["requires"].

        Raise ValueError on invalid data."""

        return self.__getDeps(("requirename", "requireflags", "requireversion"))

    def getObsoletes(self):
        """Return built value for self["obsoletes"].

        Raise ValueError on invalid data."""

        return self.__getDeps(("obsoletename", "obsoleteflags",
            "obsoleteversion"))

    def getConflicts(self):
        """Return built value for self["conflicts"].

        Raise ValueError on invalid data."""

        return self.__getDeps(("conflictname", "conflictflags",
            "conflictversion"))

    def getTriggers(self):
        """Return built value for self["triggers"].

        Raise ValueError on invalid data."""

        if self["triggerindex"] == None:
            return self.__getDeps(("triggername", "triggerflags",
                "triggerversion", "triggerscriptprog", "triggerscripts"))
        deps = self.__getDeps(("triggername", "triggerflags",
            "triggerversion"))
        numdeps = len(deps)
        if len(self["triggerscriptprog"]) != len(self["triggerscripts"]):
            raise ValueError, "wrong length of triggerscripts/prog"
        if numdeps != len(self["triggerindex"]):
            raise ValueError, "wrong length of triggerindex"
        deps2 = []
        for i in xrange(numdeps):
            ti = self["triggerindex"][i]
            deps2.append( (deps[i][0], deps[i][1], deps[i][2],
                 self["triggerscriptprog"][ti], self["triggerscripts"][ti]) )
        return deps2

    def __getDeps(self, depnames):
        """Zip values from tags in list depnames.

        Replace missing values (except for the first tag) with '' or 0.
        Raise ValueError on invalid data."""

        if self[depnames[0]] == None:
            return []
        deplength = len(self[depnames[0]])
        deps2 = []
        for d in depnames:
            x = self[d]
            if x != None:
                if len(x) != deplength:
                    raise ValueError, \
                          "Tag lengths of %s and %s differ" % (depnames[0], d)
                deps2.append(x)
            else:
                if   rpmtag[d][1] == RPM_STRING or \
                     rpmtag[d][1] == RPM_BIN or \
                     rpmtag[d][1] == RPM_STRING_ARRAY or \
                     rpmtag[d][1] == RPM_I18NSTRING:
                    deps2.append(deplength*[''])
                elif rpmtag[d][1] == RPM_INT8 or \
                     rpmtag[d][1] == RPM_INT16 or \
                     rpmtag[d][1] == RPM_INT32 or \
                     rpmtag[d][1] == RPM_INT64:
                    deps2.append(deplength*[0])
        return zip(*deps2)

    def __lt__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 0
        return functions.pkgCompare(self, pkg) < 0

    def __le__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 0
        return functions.pkgCompare(self, pkg) <= 0

    def __ge__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 1
        return functions.pkgCompare(self, pkg) >= 0

    def __gt__(self, pkg):
        if not isinstance(pkg, RpmData):
            return 1
        return functions.pkgCompare(self, pkg) > 0

# vim:ts=4:sw=4:showmatch:expandtab
