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

import os, time, struct
(pack, unpack) = (struct.pack, struct.unpack)
from libxml2 import XML_READER_TYPE_ELEMENT, XML_READER_TYPE_END_ELEMENT
import bsddb
from binascii import b2a_hex, a2b_hex
from pyrpm.base import *
import memorydb
import pyrpm.functions as functions
import pyrpm.io as io
import pyrpm.package as package
import pyrpm.openpgp as openpgp


class RpmDB(memorydb.RpmMemoryDB):
    """Standard RPM database storage in BSD db."""

    def __init__(self, config, source, buildroot=None):
        memorydb.RpmMemoryDB.__init__(self, config, source, buildroot)
        self.zero = pack("I", 0)
        self.dbopen = False
        self.maxid = 0
        # Correctly initialize the tscolor based on the current arch
        self.config.tscolor = self.__getInstallColor()
        self.netsharedpath = self.__getNetSharedPath()

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        # Never fails, attempts to recover as much as possible
        if self.is_read:
            return 1
        self.is_read = 1
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            return 1
        try:
            db = bsddb.hashopen(os.path.join(dbpath, "Packages"), "r")
        except bsddb.error:
            return 1
        for key in db.keys():
            rpmio = io.RpmFileIO(self.config, "dummy")
            pkg = package.RpmPackage(self.config, "dummy")
            data = db[key]
            try:
                val = unpack("I", key)[0]
            except struct.error:
                self.config.printError("Invalid key %s in rpmdb" % repr(key))
                continue

            if val == 0:
                self.maxid = unpack("I", data)[0]
                continue

            try:
                (indexNo, storeSize) = unpack("!2I", data[0:8])
            except struct.error:
                self.config.printError("Value for key %s in rpmdb is too short"
                                       % repr(key))
                continue
            if len(data) < indexNo*16 + 8:
                self.config.printError("Value for key %s in rpmdb is too short"
                                       % repr(key))
                continue
            indexdata = data[8:indexNo*16+8]
            storedata = data[indexNo*16+8:]
            pkg["signature"] = {}
            for idx in xrange(0, indexNo):
                try:
                    (tag, tagval) = rpmio.getHeaderByIndex(idx, indexdata,
                                                           storedata)
                except ValueError, e:
                    self.config.printError("Invalid header entry %s in %s: %s"
                                           % (idx, key, e))
                    continue
                if rpmtag.has_key(tag):
                    if rpmtagname[tag] == "archivesize":
                        pkg["signature"]["payloadsize"] = tagval
                    else:
                        pkg[rpmtagname[tag]] = tagval
                if   tag == 257:
                    pkg["signature"]["size_in_sig"] = tagval
                elif tag == 261:
                    pkg["signature"]["md5"] = tagval
                elif tag == 262:
                    pkg["signature"]["gpg"] = tagval
                elif tag == 264:
                    pkg["signature"]["badsha1_1"] = tagval
                elif tag == 265:
                    pkg["signature"]["badsha1_2"] = tagval
                elif tag == 267:
                    pkg["signature"]["dsaheader"] = tagval
                elif tag == 269:
                    pkg["signature"]["sha1header"] = tagval
            if pkg["name"] == "gpg-pubkey":
                continue # FIXME
                try:
                    keys = openpgp.parsePGPKeys(pkg["description"])
                except ValueError, e:
                    self.config.printError("Invalid key package %s: %s"
                                           % (pkg["name"], e))
                    continue
                for k in keys:
                    self.keyring.addKey(k)
                continue
            if not pkg.has_key("arch"): # FIXME: when does this happen?
                continue
            pkg.generateFileNames()
            pkg.source = "rpmdb:/"+os.path.join(dbpath, pkg.getNEVRA())
            try:
                pkg["provides"] = pkg.getProvides()
                pkg["requires"] = pkg.getRequires()
                pkg["obsoletes"] = pkg.getObsoletes()
                pkg["conflicts"] = pkg.getConflicts()
                pkg["triggers"] = pkg.getTriggers()
            except ValueError, e:
                self.config.printError("Error in package %s: %s"
                                       % pkg.getNEVRA(), e)
                continue
            pkg["install_id"] = val
            memorydb.RpmMemoryDB.addPkg(self, pkg)
            pkg.io = None
            pkg.header_read = 1
            rpmio.hdr = {}
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        memorydb.RpmMemoryDB.addPkg(self, pkg)

        if nowrite:
            return 1

        functions.blockSignals()
        try:
            self.__openDB4()

            try:
                self.maxid = unpack("I", self.packages_db[self.zero])[0]
            except:
                pass

            self.maxid += 1
            pkgid = self.maxid

            rpmio = io.RpmFileIO(self.config, "dummy")
            if pkg["signature"].has_key("size_in_sig"):
                pkg["install_size_in_sig"] = pkg["signature"]["size_in_sig"]
            if pkg["signature"].has_key("gpg"):
                pkg["install_gpg"] = pkg["signature"]["gpg"]
            if pkg["signature"].has_key("md5"):
                pkg["install_md5"] = pkg["signature"]["md5"]
            if pkg["signature"].has_key("sha1header"):
                pkg["install_sha1header"] = pkg["signature"]["sha1header"]
            if pkg["signature"].has_key("dsaheader"):
                pkg["install_dsaheader"] = pkg["signature"]["dsaheader"]
            if pkg["signature"].has_key("payloadsize"):
                pkg["archivesize"] = pkg["signature"]["payloadsize"]
            pkg["installtime"] = int(time.time())
            if pkg.has_key("basenames"):
                pkg["filestates"] = self.__getFileStates(pkg)
            pkg["installcolor"] = [self.config.tscolor,]
            pkg["installtid"] = [self.config.tid,]

            self.__writeDB4(self.basenames_db, "basenames", pkgid, pkg)
            self.__writeDB4(self.conflictname_db, "conflictname", pkgid, pkg)
            self.__writeDB4(self.dirnames_db, "dirnames", pkgid, pkg)
            self.__writeDB4(self.filemd5s_db, "filemd5s", pkgid, pkg, True,
                            a2b_hex)
            self.__writeDB4(self.group_db, "group", pkgid, pkg)
            self.__writeDB4(self.installtid_db, "installtid", pkgid, pkg, True,
                            lambda x:pack("i", x))
            self.__writeDB4(self.name_db, "name", pkgid, pkg, False)
            (headerindex, headerdata) = rpmio._generateHeader(pkg, 4)
            self.packages_db[pack("I", pkgid)] = headerindex[8:]+headerdata
            self.__writeDB4(self.providename_db, "providename", pkgid, pkg)
            self.__writeDB4(self.provideversion_db, "provideversion", pkgid,
                            pkg)
            self.__writeDB4(self.requirename_db, "requirename", pkgid, pkg)
            self.__writeDB4(self.requireversion_db, "requireversion", pkgid,
                            pkg)
            self.__writeDB4(self.sha1header_db, "install_sha1header", pkgid,
                            pkg, False)
            self.__writeDB4(self.sigmd5_db, "install_md5", pkgid, pkg, False)
            self.__writeDB4(self.triggername_db, "triggername", pkgid, pkg)
            self.packages_db[self.zero] = pack("I", self.maxid)
        except bsddb.error:
            functions.unblockSignals()
            memorydb.RpmMemoryDB.removePkg(self, pkg)
            return 0 # Due to the blocking, this is now virtually atomic
        functions.unblockSignals()
        return 1

    def erasePkg(self, pkg, nowrite=None):
        if not pkg.has_key("install_id"):
            return 0

        memorydb.RpmMemoryDB.removePkg(self, pkg)

        if nowrite:
            return 1

        functions.blockSignals()
        try:
            self.__openDB4()

            pkgid = pkg["install_id"]

            self.__removeId(self.basenames_db, "basenames", pkgid, pkg)
            self.__removeId(self.conflictname_db, "conflictname", pkgid, pkg)
            self.__removeId(self.dirnames_db, "dirnames", pkgid, pkg)
            self.__removeId(self.filemd5s_db, "filemd5s", pkgid, pkg, True,
                            a2b_hex)
            self.__removeId(self.group_db, "group", pkgid, pkg)
            self.__removeId(self.installtid_db, "installtid", pkgid, pkg, True,
                            lambda x:pack("i", x))
            self.__removeId(self.name_db, "name", pkgid, pkg, False)
            self.__removeId(self.providename_db, "providename", pkgid, pkg)
            self.__removeId(self.provideversion_db, "provideversion", pkgid,
                            pkg)
            self.__removeId(self.requirename_db, "requirename", pkgid, pkg)
            self.__removeId(self.requireversion_db, "requireversion", pkgid,
                            pkg)
            self.__removeId(self.sha1header_db, "install_sha1header", pkgid,
                            pkg, False)
            self.__removeId(self.sigmd5_db, "install_md5", pkgid, pkg, False)
            self.__removeId(self.triggername_db, "triggername", pkgid, pkg)
            del self.packages_db[pack("I", pkgid)]
        except bsddb.error:
            functions.unblockSignals()
            memorydb.RpmMemoryDB.addPkg(self, pkg)
            return 0 # FIXME: keep trying?
        functions.unblockSignals()
        return 1

    def __openDB4(self):
        """Make sure the database is read, and open all subdatabases.

        Raise bsddb.error."""

        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            os.makedirs(dbpath)

        if not self.is_read:
            self.read() # Never fails

        if self.dbopen:
            return

        # We first need to remove the __db files, otherwise rpm will later
        # be really upset. :)
        for i in xrange(9):
            try:
                os.unlink(os.path.join(dbpath, "__db.00%d" % i))
            except OSError:
                pass
        self.basenames_db      = bsddb.hashopen(os.path.join(dbpath,
                                                             "Basenames"), "c")
        self.conflictname_db   = bsddb.hashopen(os.path.join(dbpath,
                                                             "Conflictname"),
                                                "c")
        self.dirnames_db       = bsddb.btopen(os.path.join(dbpath, "Dirnames"),
                                              "c")
        self.filemd5s_db       = bsddb.hashopen(os.path.join(dbpath,
                                                             "Filemd5s"), "c")
        self.group_db          = bsddb.hashopen(os.path.join(dbpath, "Group"),
                                                "c")
        self.installtid_db     = bsddb.btopen(os.path.join(dbpath,
                                                           "Installtid"), "c")
        self.name_db           = bsddb.hashopen(os.path.join(dbpath, "Name"),
                                                "c")
        self.packages_db       = bsddb.hashopen(os.path.join(dbpath,
                                                             "Packages"), "c")
        self.providename_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Providename"),
                                                "c")
        self.provideversion_db = bsddb.btopen(os.path.join(dbpath,
                                                           "Provideversion"),
                                              "c")
        self.requirename_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Requirename"),
                                                "c")
        self.requireversion_db = bsddb.btopen(os.path.join(dbpath,
                                                           "Requireversion"),
                                              "c")
        self.sha1header_db     = bsddb.hashopen(os.path.join(dbpath,
                                                             "Sha1header"),
                                                "c")
        self.sigmd5_db         = bsddb.hashopen(os.path.join(dbpath, "Sigmd5"),
                                                "c")
        self.triggername_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Triggername"),
                                                "c")
        self.dbopen = True

    def __removeId(self, db, tag, pkgid, pkg, useidx=True, func=str):
        """Remove index entries for tag of RpmPackage pkg (with id pkgid) from
        a BSD database db.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        if not pkg.has_key(tag):
            return
        if useidx:
            maxidx = len(pkg[tag])
        else:
            maxidx = 1
        for idx in xrange(maxidx):
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if not db.has_key(key):
                continue
            data = db[key]
            ndata = ""
            rdata = pack("2I", pkgid, idx)
            for i in xrange(0, len(data), 8):
                if not data[i:i+8] == rdata:
                    ndata += data[i:i+8]
            if len(ndata) == 0:
                del db[key]
            else:
                db[key] = ndata

    def __writeDB4(self, db, tag, pkgid, pkg, useidx=True, func=str):
        """Add index entries for tag of RpmPackage pkg (with id pkgid) to a
        BSD database db.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        tnamehash = {}
        if not pkg.has_key(tag):
            return
        for idx in xrange(len(pkg[tag])):
            if tag == "requirename":
                # Skip rpmlib() requirenames...
                #if key.startswith("rpmlib("):
                #    continue
                # Skip install prereqs, just like rpm does...
                if isInstallPreReq(pkg["requireflags"][idx]):
                    continue
            # Skip all files with empty md5 sums
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if tag == "filemd5s" and (key == "" or key == "\x00"):
                continue
            # Equal Triggernames aren't added multiple times for the same pkg
            if tag == "triggername":
                if tnamehash.has_key(key):
                    continue
                else:
                    tnamehash[key] = 1
            if not db.has_key(key):
                db[key] = ""
            db[key] += pack("2I", pkgid, idx)
            if not useidx:
                break

    def __getKey(self, tag, idx, pkg, useidx, func):
        """Convert idx'th (0-based) value of RpmPackage pkg tag to a string
        usable as a database key.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        if useidx:
            key = pkg[tag][idx]
        else:
            key = pkg[tag]
        # Convert empty keys, handle filemd5s a little different
        if key != "":
            key = func(key)
        elif tag != "filemd5s":
            key = "\x00"
        return key

    def __getInstallColor(self):
        """Return the install color for self.config.machine."""

        if self.config.machine == "ia64": # also "0" and "3" have been here
            return 2
        elif self.config.machine in ("ia32e", "amd64", "x86_64", "sparc64",
            "s390x", "powerpc64") or self.config.machine.startswith("ppc"):
            return 3
        return 0

    def __getFileStates(self, pkg):
        """Returns a list of file states for rpmdb. """
        states = []
        for i in xrange(len(pkg["basenames"])):
            if pkg.has_key("filecolors"):
                fcolor = pkg["filecolors"][i]
            else:
                fcolor = 0
            if self.config.tscolor and fcolor and \
               not (self.config.tscolor & fcolor):
                states.append(RPMFILE_STATE_WRONGCOLOR)
                continue
            if pkg["dirnames"][pkg["dirindexes"][i]] in self.netsharedpath:
                states.append(RPMFILE_STATE_NETSHARED)
                continue
            fflags = pkg["fileflags"][i]
            if self.config.excludedocs and (RPMFILE_DOC & fflags):
                states.append(RPMFILE_STATE_NOTINSTALLED)
                continue
            if self.config.excludeconfigs and (RPMFILE_CONFIG & fflags):
                states.append(RPMFILE_STATE_NOTINSTALLED)
                continue
            states.append(RPMFILE_STATE_NORMAL)
            # FIXME: Still missing:
            #  - install_langs (found in /var/lib/rpm/macros) (unimportant)
            #  - Now empty dirs which contained files which weren't installed
        return states

    def __getNetSharedPath(self):
        netpaths = []
        try:
            if self.buildroot:
                fname = br + "/etc/rpm/macros"
            else:
                fname = "/etc/rpm/macros"
            lines = open(fname).readlines()
            inpath = 0
            liststr = ""
            for l in lines:
                if not inpath and not l.startswith("%_netsharedpath"):
                    continue
                l = l[:-1]
                if l.startswith("%_netsharedpath"):
                    inpath = 1
                    l = l.split(None, 1)[1]
                if not l[-1] == "\\":
                    liststr += l
                    break
                liststr += l[:-1]
            return liststr.split(",")
        except:
            return []
