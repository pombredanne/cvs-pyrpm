#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch <pknirsch@redhat.com>
#          Thomas Woerner <twoerner@redhat.com>
#          Florian Festi <ffesti@redhat.com>
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

import sys, time, struct, os, bsddb, re, fnmatch
(pack, unpack) = (struct.pack, struct.unpack)
from binascii import b2a_hex, a2b_hex
from pyrpm.base import *
import pyrpm.io as io
import pyrpm.functions as functions
import pyrpm.package as package
import db
import pyrpm.openpgp as openpgp
import lists

class RpmDBPackage(package.RpmPackage):

    filetags = {'basenames' : None,
                'dirnames' : None,
                'dirindexes' : None,
                'oldfilenames' : None}

    def __init__(self, config, source, verify=None, hdronly=None, db=None):
        self.indexdata = {}

        package.RpmPackage.__init__(self, config, source, verify, hdronly, db)

    def has_key(self, key):
        if self.indexdata.has_key(key): return True
        if dict.has_key(self, key): return True
        return key in ('requires','provides','conflicts',
                       'obsoletes', 'triggers')

    def __getitem__(self, name):
        if dict.has_key(self, name):
            return dict.get(self, name)
        if name in ('requires','provides','conflicts','obsoletes', 'triggers'):
            tags = [name[:-1] + suffix for suffix in
                    ("name", "flags", "version")]
            self.db.readTags(self, tags)
        elif not self.indexdata.has_key(name):
            return None
        elif name in self.filetags:
            self.db.readTags(self, self.filetags)
        else:
            self.db.readTags(self, {name : None})
        return self.get(name)

    def get(self, key, value=None):
        if self.has_key(key):
            return self[key]
        else:
            return value

    def setdefault(self, key, value):
        if self.has_key(key):
            return self[key]
        else:
            self[key] = value
            return value

class RpmDB(db.RpmDatabase):

    zero = pack("I", 0)

    def __init__(self, config, source, buildroot=''):
        db.RpmDatabase.__init__(self, config, source, buildroot)
        # Correctly initialize the tscolor based on the current arch
        self.config.tscolor = self.__getInstallColor()
        self.netsharedpath = self.__getNetSharedPath()

        self._pkgs = { }
        self.basenames_cache = {}
        self.clear()
        self.dbopen = 0
        self.obsoletes_list = None

        self.path = self._getDBPath()

        self.tags = {
            "name" : None,
            "epoch" : None,
            "version" : None,
            "release" : None,
            "arch" : None,
            "obsoletename" : None,
            "obsoleteflags" : None,
            "obsoleteversion" : None,
            }

    def __contains__(self, pkg):
        return hasattr(pkg, "db") and pkg.db is self and \
               self.getPkgById(pkg.key) is pkg

    def isIdentitySave(self):
        """return if package objects that are added are in the db afterwards
        (.__contains__() returns True and the object are return from searches)
        """
        return False

    # clear all structures
    def clear(self):
        self.obsoletes_list = None
        self.basenames_cache.clear()
        self._pkgs.clear()

    def setBuildroot(self, buildroot):
        """Set database chroot to buildroot."""
        self.buildroot = buildroot

    def iterId(self, data):
        for i in xrange(0, len(data), 8):
            yield data[i:i+4]

    def iterIdIdx(self, data):
        for i in xrange(0, len(data), 8):
            yield data[i:i+4], struct.unpack("I", data[i+4:i+8])[0]

    def getPkgsFromData(self, data):
        result = [self.getPkgById(data[i:i+4])
                  for i in xrange(0, len(data), 8)]
        return filter(None, result)

    def open(self):
        return self.__openDB4()

    def close(self):
        if not self.dbopen:
            return
        self.basenames_db.close()
        self.conflictname_db.close()
        self.dirnames_db.close()
        self.filemd5s_db.close()
        self.group_db.close()
        self.installtid_db.close()
        self.name_db.close()
        self.packages_db.close()
        self.providename_db.close()
        self.provideversion_db.close()
        self.requirename_db.close()
        self.requireversion_db.close()
        self.sha1header_db.close()
        self.sigmd5_db.close()
        self.triggername_db.close()

        self.basenames_db      = None
        self.conflictname_db   = None
        self.dirnames_db       = None
        self.filemd5s_db       = None
        self.group_db          = None
        self.installtid_db     = None
        self.name_db           = None
        self.packages_db       = None
        self.providename_db    = None
        self.provideversion_db = None
        self.requirename_db    = None
        self.requireversion_db = None
        self.sha1header_db     = None
        self.sigmd5_db         = None
        self.triggername_db    = None
        self.dbopen = False

    def read(self):
        """Read the database in memory."""
        return self.open()

    def getMemoryCopy(self, reposdb=None):
        from pyrpm.database.rpmshadowdb import RpmShadowDB
        db = RpmShadowDB(self, reposdb)
        return db

    def _readObsoletes(self):
        self.obsoletes_list = lists.ObsoletesList()

        for pkg in self.getPkgs():
            self.obsoletes_list.addPkg(pkg)

        self.is_read = 1
        return self.OK

    def readRpm(self, key, db, tags):
        pkg = RpmDBPackage(self.config, "dummy")
        pkg.key = key
        pkg.db = self
        data = db[key]
        try:
            val = unpack("I", key)[0]
        except struct.error:
            self.config.printError("Invalid key %s in rpmdb" % repr(key))
            return None

        if val == 0:
            return None

        try:
            (indexNo, storeSize) = unpack("!2I", data[0:8])
        except struct.error:
            self.config.printError("Value for key %s in rpmdb is too short"
                                   % repr(key))
            return None

        if len(data) < indexNo*16 + 8:
            self.config.printError("Value for key %s in rpmdb is too short"
                                   % repr(key))
            return None
        indexdata = unpack("!%sI" % (indexNo*4), data[8:indexNo*16+8])
        indexes = zip(indexdata[0::4], indexdata[1::4],
                      indexdata[2::4], indexdata[3::4])
        indexdata = {}
        for idx in indexes:
            if rpmtagname.has_key(idx[0]):
                indexdata[rpmtagname[idx[0]]] = idx
        pkg.indexdata = indexdata

        storedata = data[indexNo*16+8:]
        pkg["signature"] = {}

        # read the tags
        ok = self.readTags(pkg, tags, storedata)
        if not ok:
            return None
        if not pkg.has_key("epoch"):
            pkg["epoch"] = [ 0 ]


        if pkg["name"] == "gpg-pubkey":
            return None  # FIXME
            try:
                keys = openpgp.parsePGPKeys(pkg["description"])
            except ValueError, e:
                self.config.printError("Invalid key package %s: %s"
                                       % (pkg["name"], e))
                return None
            for k in keys:
                self.keyring.addKey(k)
            return None

        if not pkg.has_key("arch"): # FIXME: when does this happen?
            return None

        pkg.source = "rpmdb:/"+os.path.join(self.path, pkg.getNEVRA())
        pkg.io = None
        pkg.header_read = 1
        return pkg


    def readTags(self, pkg, tags, storedata=None):
        rpmio = io.RpmFileIO(self.config, "dummy")

        if storedata is None:
            data = self.packages_db[pkg.key]
            storedata = data[len(pkg.indexdata)*16+8:]


        for tag in tags:
            if pkg.indexdata.has_key(tag):
                index = pkg.indexdata[tag]
            else:
                continue
            try:
                tagval = rpmio.getHeaderByIndexData(index, storedata)
            except ValueError, e:
                self.config.printError("Invalid header entry %s in %s: %s"
                                       % (idx, key, e))
                return 0

            if tag == "archivesize":
                pkg["signature"]["payloadsize"] = tagval
            else:
                pkg[tag] = tagval
            if tag.startswith("install_"):
                pkg["signature"][tag[8:]] = tagval


        try:
            if "basenames" in tags and pkg.has_key("oldfilenames"):
                pkg.generateFileNames()
            if "providename" in tags:
                pkg["provides"] = pkg.getProvides()
            if "requirename" in tags:
                pkg["requires"] = pkg.getRequires()
            if "obsoletename" in tags:
                pkg["obsoletes"] = pkg.getObsoletes()
            if "conflictname" in tags:
                pkg["conflicts"] = pkg.getConflicts()
            if "triggername" in tags:
                pkg["triggers"] = pkg.getTriggers()
        except ValueError, e:
            self.config.printError("Error in package %s: %s"
                                   % pkg.getNEVRA(), e)
            return 0
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg):
        self.basenames_cache.clear()
        result = self._addPkg(pkg)
        if result and pkg["obsoletes"] and self.obsoletes_list is not None:
            p = self.getPkgById(result)
            self.obsoletes_list.addPkg(p)
        return bool(result)

    def _addPkg(self, pkg):
        signals = functions.blockSignals()
        try:
            if self.__openDB4() != self.OK:
                functions.unblockSignals(signals)
                return 0

            try:
                maxid = unpack("I", self.packages_db[self.zero])[0]
            except (struct.error, KeyError):
                maxid = 0

            pkgid = pack("I", maxid + 1)

            rpmio = io.RpmFileIO(self.config, "dummy")
            if pkg["signature"].has_key("size_in_sig"):
                pkg["install_size_in_sig"] = pkg["signature"]["size_in_sig"]
            if pkg["signature"].has_key("gpg"):
                pkg["install_gpg"] = pkg["signature"]["gpg"]
            if pkg["signature"].has_key("md5"):
                pkg["install_md5"] = pkg["signature"]["md5"]
            if pkg["signature"].has_key("sha1header"):
                pkg["install_sha1header"] = pkg["signature"]["sha1header"]
            if pkg["signature"].has_key("badsha1_1"):
                pkg["install_badsha1_1"] = pkg["signature"]["badsha1_1"]
            if pkg["signature"].has_key("badsha1_2"):
                pkg["install_badsha1_2"] = pkg["signature"]["badsha1_2"]
            if pkg["signature"].has_key("dsaheader"):
                pkg["install_dsaheader"] = pkg["signature"]["dsaheader"]
            if pkg["signature"].has_key("payloadsize"):
                pkg["archivesize"] = pkg["signature"]["payloadsize"]
            pkg["installtime"] = int(time.time())
            if pkg.has_key("basenames"):
                pkg["filestates"] = self.__getFileStates(pkg)
            pkg["installcolor"] = [self.config.tscolor,]
            pkg["installtid"] = [self.config.tid,]

            self.packages_db[self.zero] = pkgid

            (headerindex, headerdata) = rpmio._generateHeader(pkg, 4)
            self.packages_db[pkgid] = headerindex[8:]+headerdata

            self.__writeDB4(self.basenames_db, "basenames", pkgid, pkg)
            self.__writeDB4(self.conflictname_db, "conflictname", pkgid, pkg)
            self.__writeDB4(self.dirnames_db, "dirnames", pkgid, pkg)
            self.__writeDB4(self.filemd5s_db, "filemd5s", pkgid, pkg, True,
                            a2b_hex)
            self.__writeDB4(self.group_db, "group", pkgid, pkg)
            self.__writeDB4(self.installtid_db, "installtid", pkgid, pkg, True,
                            lambda x:pack("i", x))
            self.__writeDB4(self.name_db, "name", pkgid, pkg, False)
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
        except bsddb.error:
            functions.unblockSignals(signals)
            return 0 # Due to the blocking, this is now virtually atomic
        functions.unblockSignals(signals)
        return pkgid

    def removePkg(self, pkg):
        self.basenames_cache.clear()
        if (not hasattr(pkg, 'key') or
            not hasattr(pkg, 'db') or
            pkg.db is not self):
            return 0

        result = self._removePkg(pkg)
        self._pkgs.pop(pkg.key, None)
        if self.obsoletes_list and result:
            self.obsoletes_list.removePkg(pkg)
        return result

    def _removePkg(self, pkg):
        pkgid = pkg.key

        signals = functions.blockSignals()
        try:
            if self.__openDB4() != self.OK:
                functions.unblockSignals(signals)
                return 0

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
            del self.packages_db[pkgid]
        except bsddb.error:
            functions.unblockSignals(signals)
            return 0 # FIXME: keep trying?
        functions.unblockSignals(signals)
        return 1

    def __openDB4(self):
        """Make sure the database is read, and open all subdatabases.

        Raise bsddb.error."""

        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            os.makedirs(dbpath)

        if self.dbopen:
            return self.OK

        # We first need to remove the __db files, otherwise rpm will later
        # be really upset. :)
        for i in xrange(9):
            try:
                os.unlink(os.path.join(dbpath, "__db.00%d" % i))
            except OSError:
                pass
        try:
            self.basenames_db      = bsddb.hashopen(
                os.path.join(dbpath, "Basenames"), "c")
            self.conflictname_db   = bsddb.hashopen(
                os.path.join(dbpath, "Conflictname"), "c")
            self.dirnames_db       = bsddb.btopen(
                os.path.join(dbpath, "Dirnames"), "c")
            self.filemd5s_db       = bsddb.hashopen(
                os.path.join(dbpath, "Filemd5s"), "c")
            self.group_db          = bsddb.hashopen(
                os.path.join(dbpath, "Group"), "c")
            self.installtid_db     = bsddb.btopen(
                os.path.join(dbpath, "Installtid"), "c")
            self.name_db           = bsddb.hashopen(
                os.path.join(dbpath, "Name"), "c")
            self.packages_db       = bsddb.hashopen(
                os.path.join(dbpath, "Packages"), "c")
            self.providename_db    = bsddb.hashopen(
                os.path.join(dbpath, "Providename"), "c")
            self.provideversion_db = bsddb.btopen(
                os.path.join(dbpath, "Provideversion"), "c")
            self.requirename_db    = bsddb.hashopen(
                os.path.join(dbpath, "Requirename"), "c")
            self.requireversion_db = bsddb.btopen(
                os.path.join(dbpath, "Requireversion"), "c")
            self.sha1header_db     = bsddb.hashopen(
                os.path.join(dbpath, "Sha1header"), "c")
            self.sigmd5_db         = bsddb.hashopen(
                os.path.join(dbpath, "Sigmd5"), "c")
            self.triggername_db    = bsddb.hashopen(
                os.path.join(dbpath, "Triggername"), "c")
            self.dbopen = True
        except bsddb.error:
            return
        return self.OK

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
            rdata = pkgid + pack("I", idx)
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
            db[key] = db.get(key, "") + (pkgid + pack("I", idx))
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
                fname = self.buildroot + "/etc/rpm/macros"
            else:
                fname = "/etc/rpm/macros"
            lines = open(fname).readlines()
            inpath = 0
            liststr = ""
            for l in lines:
                if not inpath and not l.startswith("%_netsharedpath"):
                    continue
                l = l[:-1]
                if not l:
                    continue
                if l.startswith("%_netsharedpath"):
                    inpath = 1
                    l = l.split(None, 1)[1]
                if not l[-1] == "\\":
                    liststr += l
                    break
                liststr += l[:-1]
            return liststr.split(",")
        except IOError:
            return []

    def getPkgById(self, id):
        if self._pkgs.has_key(id):
            return self._pkgs[id]
        else:
            pkg = self.readRpm(id, self.packages_db, self.tags)
            if pkg is not None:
                self._pkgs[id] = pkg
            return pkg

    def searchName(self, name):
        data = self.name_db.get(name, '')
        result = [self.getPkgById(id) for id in self.iterId(data)]
        return filter(None, result)

    def getPkgs(self):
        result = [self.getPkgById(key) for key in self.packages_db.keys()]
        return filter(None, result)

    def getNames(self):
        return self.name_db.keys()

    def hasName(self, name):
        return self.name_db.has_key(name)

    def getPkgsByName(self, name):
        return self.searchName(name)

    def _iter(self, tag, db=None):
        for pkg in self.getPkgs():
            l = pkg[tag]
            for name, flag, version in l:
                yield name, flag, version, pkg

    def _iter2(self, tag, db):
        for name, data in db:
            for id, idx in self.iterIdIdx(data):
                pkg = self.getPkg(id)
                if pkg:
                    yield pkg["tag"][idx] + (pkg,)

    def iterProvides(self):
        return self._iter("provides")

    def getFilenames(self):
        raise NotImplementedError

    def numFileDuplicates(self, filename):
        (dirname, basename) = functions.pathsplit2(filename)
        if not self.basenames_cache.has_key(basename):
            data = self.basenames_db.get(basename, '')
            filedict = {}
            self.basenames_cache[basename] = filedict

            for id, idx in self.iterIdIdx(data):
                pkg = self.getPkgById(id)
                if not pkg:
                    continue
                f = pkg.iterFilenames()[idx]
                filedict.setdefault(f, []).append(pkg)
        return len(self.basenames_cache[basename].get(filename, []))

    def getFileRequires(self):
        return [name for name in self.requirename_db if name[0]=='/']

    def getFileDuplicates(self):
        duplicates = {}
        for basename, data in self.basenames_db.iteritems():
            if len(data) <= 8: continue
            for id, idx in self.iterIdIdx(data):
                pkg = self.getPkgById(id)
                if not pkg: continue
                file = pkg.iterFilenames()[idx]
                duplicates.setdefault(file, [ ]).append(pkg)
        for filename, pkglist in duplicates.iteritems():
            if len(pkglist)<2:
                del duplicates[filename]
        return duplicates

    def iterRequires(self):
        return self._iter("requires")

    def iterConflicts(self):
        return self._iter("conflicts", self.conflictname_db)

    def iterObsoletes(self):
        if self.obsoletes_list is None:
            self._readObsoletes()
        for name, l in self.obsoletes_list.hash.iteritems():
            for f, v, p in l:
                p = self.getPkgById(p.key)
                if p:
                    yield  name, f, v, p

    def iterTriggers(self):
        return self._iter2("triggers", self.triggername_db)

    def reloadDependencies(self):
        self.obsoletes_list = None

    def _search(self, db, attr, name, flag, version):
        data = db.get(name, '')
        result = {}
        evr = functions.evrSplit(version)
        for id, idx in self.iterIdIdx(data):
            pkg = self.getPkgById(id)
            if not pkg: continue
            dep = pkg[attr][idx]
            name_, flag_, version_ = dep[:3]
            if version == "":
                result.setdefault(pkg, [ ]).append(dep)
            elif functions.rangeCompare(flag, evr,
                                        flag_, functions.evrSplit(version_)):
                result.setdefault(pkg, [ ]).append(dep)
            elif version_ == "": # compare with package version for unversioned provides
                evr2 = (pkg.getEpoch(), pkg["version"], pkg["release"])
                if functions.evrCompare(evr2, flag, evr):
                    result.setdefault(pkg, [ ]).append(dep)
        return result

    def searchProvides(self, name, flag, version):
        return self._search(self.providename_db, "provides",
                            name, flag, version)

    def searchFilenames(self, filename):
        (dirname, basename) = functions.pathsplit2(filename)
        data1 = self.basenames_db.get(basename, "")
        data2 = self.dirnames_db.get(dirname, '')
        dirname_ids = {}
        for id in self.iterId(data2):
            dirname_ids[id] = None

        #print `data1` , `data2`, set2
        result = []
        for id, idx in self.iterIdIdx(data1):
            if id not in dirname_ids:
                continue
            pkg = self.getPkgById(id)
            if pkg and pkg.iterFilenames()[idx] == filename:
                result.append(pkg)
            #elif pkg:
            #    print "dropping", pkg.getNEVRA(), pkg.iterFilenames()[idx]
        return result

    def searchRequires(self, name, flag, version):
        return self._search(self.requirename_db, "requires",
                            name, flag, version)

    def searchConflicts(self, name, flag, version):
        return self._search(self.conflictname_db, "conflicts",
                            name, flag, version)

    def searchObsoletes(self, name, flag, version):
        if self.obsoletes_list is None:
            self._readObsoletes()

        r = self.obsoletes_list.search(name, flag, version)
        result = {}
        for pkg, obsoletes in r.iteritems():
            pkg = self.getPkgById(pkg.key)
            if pkg is not None:
                result[pkg] = obsoletes
        return result

    def searchTriggers(self, name, flag, version):
        return self._search(self.triggername_db, "triggers",
                            name, flag, version)



    # Use precompiled regex for faster checks
    __fnmatchre__ = re.compile(".*[\*\[\]\?].*")
    __splitre__ = re.compile(r"([:*?\-.]|\[[^]]+\])")

    def searchPkgs(self, names):
        """Return a list of RpmPackage's from pkgs matching pkgnames.
        pkgnames is a list of names, each name can contain epoch, version,
        release and arch. If the name doesn't match literally, it is
        interpreted as a glob pattern. The resulting list contains all matches
        in arbitrary order, and it may contain a single package more than
        once."""
        result = []
        pkgnames = None
        for name in names:
            parts = self.__splitre__.split(name)
            if self.__fnmatchre__.match(name):
                regex = re.compile(fnmatch.translate(name))
                if pkgnames is None:
                    pkgnames = self.getNames()
                for pkgname in pkgnames:
                    if pkgname.startswith(parts[0]):
                        pkgs = self.getPkgsByName(pkgname)
                        for pkg in pkgs:
                            for n in pkg.getAllNames():
                                if regex.match(n):
                                    result.append(pkg)
                                    break
            else:
                print parts
                for idx in xrange(1, len(parts)+1, 2):
                    pkgs = self.getPkgsByName(''.join(parts[:idx]))
                    for pkg in pkgs:
                        for n in pkg.getAllNames():
                            if n == name:
                                result.append(pkg)
                                break
        #normalizeList(result)
        return result

    def _getDBPath(self):
        """Return a physical path to the database."""

        if   self.source[:6] == 'pydb:/':
            tsource = self.source[6:]
        elif self.source[:7] == 'rpmdb:/':
            tsource = self.source[7:]
        else:
            tsource = self.source

        return self.buildroot + tsource

# vim:ts=4:sw=4:showmatch:expandtab
