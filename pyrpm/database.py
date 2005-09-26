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


import fcntl, bsddb, libxml2, os, os.path, sys, struct, time
import zlib, gzip, sha, md5, string, stat, openpgp, re, sqlite
(pack, unpack) = (struct.pack, struct.unpack)
from binascii import b2a_hex, a2b_hex
from types import TupleType
from base import *
from io import *
import functions
import package


class RpmDatabase(RpmIO):
    """A persistent RPM database storage."""
    # FIXME: doesn't support adding/removing gpg keys

    def __init__(self, config, source, buildroot=None):
        """Create a new RpmDatabase for "URI" source.

        If buildroot is not None, use the database under buildroot."""
        # FIXME: buildroot is a misnomer

        self.config = config
        self.source = source
        self.buildroot = buildroot
        self.filenames = FilenamesList(self.config)
        self.pkglist = {}            # nevra => RpmPackage for non-key packages
        self.keyring = openpgp.PGPKeyRing()
        self.is_read = 0                # 1 if the database was already read

    # FIXME: not used
    def setSource(self, source):
        """Set database source to source.

        Does not write/reread the database."""

        self.source = source

    def setBuildroot(self, buildroot):
        """Set database chroot to buildroot."""

        self.buildroot = buildroot

    def open(self):
        """If the database keeps a connection, prepare it."""

        raise NotImplementedError

    def close(self):
        """If the database keeps a connection, close it."""
        
        raise NotImplementedError

    def read(self):
        """Read the database in memory.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    # FIXME: not used, addPkg/erasePkg write data immediately
    # For now, yes. Maybe someday there will be transcation based databases.
    def write(self):
        """Write the database out.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    def addPkg(self, pkg, nowrite=None):
        """Add RpmPackage pkg to database in memory and persistently if not
        nowrite.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    def _addPkg(self, pkg):
        """Add RpmPackage pkg to self.filenames and self.pkglist"""

        self.filenames.addPkg(pkg)
        self.pkglist[pkg.getNEVRA()] = pkg

    def erasePkg(self, pkg, nowrite=None):
        """Remove RpmPackage pkg from database in memory and persistently if
        not nowrite.

        Return 1 on success, 0 on failure."""
        
        raise NotImplementedError

    def _erasePkg(self, pkg):
        """Remove RpmPackage pkg from self.filenames and self.pkglist"""

        self.filenames.removePkg(pkg)
        del self.pkglist[pkg.getNEVRA()]

    # FIXME: not used
    def getPackage(self, nevra):
        """Return a RpmPackage with NEVRA nevra, or None if not found."""
        
        return self.pkglist.get(nevra)

    def getPkgList(self):
        """Return a list of RpmPackages in the database."""
        
        return self.pkglist.values()

    def isInstalled(self, pkg):
        """Return True if RpmPackage pkg is in the database.

        pkg must be exactly the same object, not only have the same NEVRA."""

        return pkg in self.pkglist.values()

    def isDuplicate(self, dirname, filename=None):
        """Return True if a file is contained in more than one package in the
        database.

        The file can be specified either as a single absolute path ("dirname")
        or as a (dirname, filename) pair."""

        if filename == None:
            (dirname, basename) = os.path.split(dirname)
            if len(dirname) > 0 and dirname[-1] != "/":
                dirname += "/"
        if dirname == "/etc/init.d/" or dirname == "/etc/rc.d/init.d/":
            num = 0
            d = self.filenames.path.get("/etc/rc.d/init.d/")
            if d:
                num = len(d.get(basename, []))
            d = self.filenames.path.get("/etc/init.d/")
            if d:
                num += len(d.get(basename, []))
            return num > 1
        d = self.filenames.path.get(dirname)
        if not d:
            return 0
        return len(d.get(basename, [])) > 1

    def getNumPkgs(self, name):
        """Return number of packages in database with %name name."""

        count = 0
        for pkg in self.pkglist.values():
            if pkg["name"] == name:
                count += 1
        return count

    def _getDBPath(self):
        """Return a physical path to the database."""

        if   self.source[:6] == 'pydb:/':
            tsource = self.source[6:]
        elif self.source[:7] == 'rpmdb:/':
            tsource = self.source[7:]
        else:
            tsource = self.source
        if self.buildroot != None:
            return self.buildroot + tsource
        else:
            return tsource


class RpmDB(RpmDatabase):
    """Standard RPM database storage in BSD db."""

    def __init__(self, config, source, buildroot=None):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.zero = pack("I", 0)
        self.dbopen = False
        self.maxid = 0
        self.indexdatahash = {}

    def open(self):
        pass

    def getNextFile(self):
        """Implementation for RpmIO:getNextFile()"""

        return ("EOF", 0, 0)

    def getTag(self, pkg, item):
        """Implementation for RpmIO:getTag()"""

        # FIXME: Maybe raise a ValueError here instead?
        if not pkg in self.indexdatahash.keys():
            return None

        if not self.__openDB4():
            return None

        (indexdata, offset) = self.indexdatahash[pkg]
        if not indexdata.has_key(item):
            return None
        index = indexdata.getIndex(item)
        offset += index[2]
        id = pkg["install_id"]
        storedata = self.packages_db[pack("I", id)][offset:offset+index[4]]
        return indexdata.parseTag(index, storedata)

    def has_key(self, pkg, item):
        """Implementation for RpmIO:has_key()"""

        # FIXME: Maybe raise a ValueError here instead?
        if not pkg in self.pkglist:
            return None

        if not self.__openDB4():
            return None

        indexdata = self.indexdatahash[pkg][0]
        return indexdata.has_key(item)

    def keys(self, pkg):
        """Implementation for RpmIO:keys()"""

        # FIXME: Maybe raise a ValueError here instead?
        if not pkg in self.pkglist:
            return None

        if not self.__openDB4():
            return None

        indexdata = self.indexdatahash[pkg][0]
        return indexdata.keys()

    def isSrc(self, pkg):
        return False

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
            rpmio = RpmFileIO(self.config, "dummy")
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
            indexdata = RpmIndexData(self.config, data[8:indexNo*16+8],
                                     storeSize)
            print indexdata.hdrhash
            pkg["install_id"] = val
            pkg.source = "rpmdb:/"+str(val)
            pkg.io = self
            pkg.header_read = 1
            self.indexdatahash[pkg] = (indexdata, indexNo*16 + 8)
            self._addPkg(pkg)
            print pkg.getNEVRA()
            rpmio.hdr = {}
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        self._addPkg(pkg)
        functions.blockSignals()

        if nowrite:
            return 1

        try:
            self.__openDB4()

            try:
                self.maxid = unpack("I", self.packages_db[self.zero])[0]
            except:
                pass

            self.maxid += 1
            pkgid = self.maxid

            rpmio = RpmFileIO(self.config, "dummy")
            if pkg.has_key("Ssize_in_sig"):
                pkg["install_size_in_sig"] = pkg["Ssize_in_sig"]
            if pkg.has_key("Sgpg"):
                pkg["install_gpg"] = pkg["Sgpg"]
            if pkg.has_key("Smd5"):
                pkg["install_md5"] = pkg["Smd5"]
            if pkg.has_key("Ssha1header"):
                pkg["install_sha1header"] = pkg["Ssha1header"]
            if pkg.has_key("Sdsaheader"):
                pkg["install_dsaheader"] = pkg["Sdsaheader"]
            if pkg.has_key("Spayloadsize"):
                pkg["archivesize"] = pkg["Spayloadsize"]
            pkg["installtime"] = int(time.time())
            if pkg.has_key("basenames"):
                pkg["filestates"]= ['\x00',] * len(pkg["basenames"])
            pkg["installcolor"] = [0,]
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
                            pkg)
            self.__writeDB4(self.sigmd5_db, "install_md5", pkgid, pkg)
            self.__writeDB4(self.triggername_db, "triggername", pkgid, pkg)
            self.packages_db[self.zero] = pack("I", self.maxid)
        except bsddb.error:
            functions.unblockSignals()
            self._erasePkg(pkg)
            return 0 # Due to the blocking, this is now virtually atomic
        functions.unblockSignals()
        return 1

    def erasePkg(self, pkg, nowrite=None):
        self._erasePkg(pkg)

        if nowrite:
            return 1

        functions.blockSignals()

        if not pkg.has_key("install_id"):
            functions.unblockSignals()
            self._addPkg(pkg)
            return 0

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
                            pkg)
            self.__removeId(self.sigmd5_db, "install_md5", pkgid, pkg)
            self.__removeId(self.triggername_db, "triggername", pkgid, pkg)
            del self.packages_db[pack("I", pkgid)]
        except bsddb.error:
            functions.unblockSignals()
            self._addPkg(pkg)
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
            return 1

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
        return 1

    def __removeId(self, db, tag, pkgid, pkg, useidx=True, func=str):
        """Remove index entries for tag of RpmPackage pkg (with id pkgid) from
        a BSD database db.

        The tag has a single value if not useidx.  Convert the value using
        func."""
        
        if not pkg.has_key(tag):
            return
        for idx in xrange(len(pkg[tag])):
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if not db.has_key(key):
                continue
            data = db[key]
            ndata = ""
            for i in xrange(0, len(data), 8):
                if not data[i:i+8] == pack("2I", pkgid, idx):
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


class RpmPyDB(RpmDatabase):
    """RPM database storage in separate files, as originally used in pyrpm."""

    def __init__(self, config, source, buildroot):
        RpmDatabase.__init__(self, config, source, buildroot)

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        # Reads only a selected tag subset
        if self.is_read:
            return 1
        self.is_read = 1
        dbpath = self._getDBPath()
        if not os.path.isdir(os.path.join(dbpath, "headers")):
            return 1
        namelist = os.listdir(os.path.join(dbpath, "headers"))
        tags = list(self.config.resolvertags)
        tags.extend(("filerdevs", "filemtimes", "filelinktos", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "preunprog", "preun", "postunprog", "postun", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
        for nevra in namelist:
            src = "pydb:/"+os.path.join(dbpath, "headers", nevra)
            pkg = package.RpmPackage(self.config, src)
            try:
                pkg.read(tags=tags)
                pkg.close()
            except (IOError, ValueError), e:
                self.config.printWarning(0, "Invalid header %s in database: %s"
                                         % (nevra, e))
                continue
            self._addPkg(pkg)
        if os.path.isdir(os.path.join(dbpath, "pubkeys")):
            namelist = os.listdir(os.path.join(dbpath, "pubkeys"))
            for name in namelist:
                try:
                    data = file(os.path.join(dbpath, "pubkeys", name)).read()
                except IOError, e:
                    self.config.printWarning(0, "Error reading %s: %s"
                                             % (name, e))
                    continue
                try:
                    keys = openpgp.parsePGPKeys(data)
                except ValueError, e:
                    self.config.printWarning(0, "Invalid keyring %s: %s"
                                             % (name, e))
                    continue
                for k in keys:
                    self.keyring.addKey(k)
        return 1

    def write(self):
        if not self.__mkDBDirs():
            return 0
        return 1

    def addPkg(self, pkg, nowrite=None):
        self._addPkg(pkg)
        functions.blockSignals()

        if nowrite:
            return 1

        if not self.__mkDBDirs():
            functions.unblockSignals()
            self._erasePkg(pkg)
            return 0

        dbpath = self._getDBPath()
        nevra = pkg.getNEVRA()
        src = "pydb:/"+os.path.join(dbpath, "headers", nevra)
        apkg = getRpmIOFactory(self.config, src)
        try:
            apkg.write(pkg)
            apkg.close()
        except IOError:
            functions.unblockSignals()
            self._erasePkg(pkg)
            return 0 # FIXME: clean up partial data?
        if not self.write():
            functions.unblockSignals()
            self._erasePkg(pkg)
            return 0
        functions.unblockSignals()
        return 1

    def erasePkg(self, pkg, nowrite=None):
        self._erasePkg(pkg)
        functions.blockSignals()

        if nowrite:
            return 1

        if not self.__mkDBDirs():
            functions.unblockSignals()
            self._addPkg(pkg)
            return 0
        dbpath = self._getDBPath()
        nevra = pkg.getNEVRA()
        headerfile = os.path.join(dbpath, "headers", nevra)
        try:
            os.unlink(headerfile)
        except OSError:
            self.config.printWarning(1, "%s: Package not found in PyDB" % nevra)
            functions.unblockSignals()
            self._addPkg(pkg)
            return 0
        if not self.write():
            functions.unblockSignals()
            self._addPkg(pkg)
            return 0
        functions.unblockSignals()
        return 1

    def __mkDBDirs(self):
        """Make sure dbpath/headers exists, try to create dbpath/pubkeys.

        Return 1 on success, 0 on failure."""
        
        dbpath = self._getDBPath()
        if not os.path.isdir(os.path.join(dbpath, "headers")):
            try:
                os.makedirs(os.path.join(dbpath, "headers"))
            except:
                self.config.printError("%s: Couldn't open PyRPM database" % dbpath)
                return 0
        if not os.path.isdir(os.path.join(dbpath, "pubkeys")):
            try:
                os.makedirs(os.path.join(dbpath, "pubkeys"))
            except OSError:
                pass
        return 1


class RpmSQLiteDB(RpmDatabase):
    """RPM database storage in an SQLite database."""
    
    # Tags stored in the Packages table
    pkgnames = ["name", "epoch", "version", "release", "arch", "prein", "preinprog", "postin", "postinprog", "preun", "preunprog", "postun", "postunprog", "verifyscript", "verifyscriptprog", "url", "license", "rpmversion", "sourcerpm", "optflags", "sourcepkgid", "buildtime", "buildhost", "cookie", "size", "distribution", "vendor", "packager", "os", "payloadformat", "payloadcompressor", "payloadflags", "rhnplatform", "platform", "capability", "xpm", "gif", "verifyscript2", "disturl"]
    # Tags stored in separate tables
    tagnames = ["providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex", "i18ntable", "summary", "description", "changelogtime", "changelogname", "changelogtext", "prefixes", "pubkeys", "group", "dirindexes", "dirnames", "basenames", "fileusername", "filegroupname", "filemodes", "filemtimes", "filedevices", "fileinodes", "filesizes", "filemd5s", "filerdevs", "filelinktos", "fileflags", "fileverifyflags", "fileclass", "filelangs", "filecolors", "filedependsx", "filedependsn", "classdict", "dependsdict", "policies", "filecontexts", "oldfilenames"]
    def __init__(self, config, source, buildroot=None):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.cx = None

    def open(self):
        if self.cx:
            return
        dbpath = self._getDBPath()
        self.cx = sqlite.connect(os.path.join(dbpath, "rpmdb.sqlite"),
                                 autocommit=1)

    def close(self):
        if self.cx:
            self.cx.close()
        self.cx = None

    def read(self):
        if self.is_read:
            return 1
        if not self.cx:
            return 0
        self.is_read = 1
        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        cu.execute("select rowid, "+string.join(self.pkgnames, ",")+" from Packages")
        for row in cu.fetchall():
            pkg = package.RpmPackage(self.config, "dummy")
            pkg["install_id"] = row[0]
            for i in xrange(len(self.pkgnames)):
                if row[i+1] != None:
                    if self.pkgnames[i] == "epoch" or \
                       self.pkgnames[i] == "size":
                        pkg[self.pkgnames[i]] = [row[i+1],]
                    else:
                        pkg[self.pkgnames[i]] = row[i+1]
            for tag in self.tagnames:
                self.__readTags(cu, row[0], pkg, tag)
            pkg.generateFileNames()
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
            self._addPkg(pkg)
            pkg.io = None
            pkg.header_read = 1
        try:
            cu.execute("commit")
        except:
            return 0
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        self._addPkg(pkg)

        if nowrite:
            return 1

        if not self.cx:
            self._erasePkg(pkg)
            return 0

        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        namelist = []
        vallist = []
        valstring = ""
        for tag in self.pkgnames:
            if not pkg.has_key(tag):
                continue
            namelist.append(tag)
            if valstring == "":
                valstring = "%s"
            else:
                valstring += ", %s"
            if rpmtag[tag][1] == RPM_BIN:
                vallist.append(b2a_hex(pkg[tag]))
            else:
                if isinstance(pkg[tag], TupleType):
                    vallist.append(str(pkg[tag][0]))
                else:
                    vallist.append(str(pkg[tag]))
        cu.execute("insert into Packages ("+string.join(namelist, ",")+") values ("+valstring+")", vallist)
        rowid = cu.lastrowid
        for tag in self.tagnames:
            if not pkg.has_key(tag):
                continue
            self.__writeTags(cu, rowid, pkg, tag)
        try:
            cu.execute("commit")
        except:
            self._erasePkg(pkg)
            return 0
        return 1

    def erasePkg(self, pkg, nowrite=None):
        self._erasePkg(pkg)

        if nowrite:
            return 1

        if not self.cx:
            self._addPkg(pkg)
            return 0

        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        cu.execute("delete from Packages where rowid=%d", (pkg["install_id"],))
        for tag in self.tagnames:
            cu.execute("delete from %s where id=%d", (tag, pkg["install_id"]))
        try:
            cu.execute("commit")
        except:
            self._addPkg(pkg)
            return 0
        return 1

    def __initDB(self):
        """Make sure the necessary tables are defined."""

        cu = self.cx.cursor()
        cu.execute("select tbl_name from sqlite_master where type='table' order by tbl_name")
        tables = [row.tbl_name for row in cu.fetchall()]
        if tables == []:
            cu.execute("""
create table Packages (
               name text,
               epoch int,
               version text,
               release text,
               arch text,
               prein text,
               preinprog text,
               postin text,
               postinprog text,
               preun text,
               preunprog text,
               postun text,
               postunprog text,
               verifyscript text,
               verifyscriptprog text,
               url text,
               license text,
               rpmversion text,
               sourcerpm text,
               optflags text,
               sourcepkgid text,
               buildtime text,
               buildhost text,
               cookie text,
               size int,
               distribution text,
               vendor text,
               packager text,
               os text,
               payloadformat text,
               payloadcompressor text,
               payloadflags text,
               rhnplatform text,
               platform text,
               capability int,
               xpm text,
               gif text,
               verifyscript2 text,
               disturl text)
""")
            for tag in self.tagnames:
                cu.execute("""
create table %s (
               id int,
               idx int,
               val text,
               primary key(id, idx))
""", tag)

    def __readTags(self, cu, rowid, pkg, tag):
        """Read values of tag with name tag to RpmPackage pkg with ID rowid
        using cu."""
        
        cu.execute("select val from %s where id=%d order by idx", (tag, rowid))
        for row in cu.fetchall():
            if not pkg.has_key(tag):
                pkg[tag] = []
            if   rpmtag[tag][1] == RPM_BIN:
                pkg[tag].append(a2b_hex(row[0]))
            elif rpmtag[tag][1] == RPM_INT8 or \
                 rpmtag[tag][1] == RPM_INT16 or \
                 rpmtag[tag][1] == RPM_INT32 or \
                 rpmtag[tag][1] == RPM_INT64:
                pkg[tag].append(int(row[0]))
            else:
                pkg[tag].append(row[0])

    def __writeTags(self, cu, rowid, pkg, tag):
        """Write values of tag with name tag from RpmPackage pkg with ID rowid
        using cu."""

        for idx in xrange(len(pkg[tag])):
            if rpmtag[tag][1] == RPM_BIN:
                val = b2a_hex(pkg[tag][idx])
            else:
                val = str(pkg[tag][idx])
            cu.execute("insert into %s (id, idx, val) values (%d, %d, %s)", (tag, rowid, idx, val))


class RpmRepo(RpmDatabase):
    """A (mostly) read-only RPM database storage in repodata XML.

    This is not a full implementation of RpmDatabase: notably the file database
    is not populated at all."""

    # A mapping between strings and RPMSENSE_* comparison flags
    flagmap = { None: None,
                "EQ": RPMSENSE_EQUAL,
                "LT": RPMSENSE_LESS,
                "GT": RPMSENSE_GREATER,
                "LE": RPMSENSE_EQUAL | RPMSENSE_LESS,
                "GE": RPMSENSE_EQUAL | RPMSENSE_GREATER,
                RPMSENSE_EQUAL: "EQ",
                RPMSENSE_LESS: "LT",
                RPMSENSE_GREATER: "GT",
                RPMSENSE_EQUAL | RPMSENSE_LESS: "LE",
                RPMSENSE_EQUAL | RPMSENSE_GREATER: "GE"}

    def __init__(self, config, source, buildroot=None, excludes="", reponame="default"):
        """Exclude packages matching whitespace-separated excludes.  Use
        reponame for cache subdirectory name and pkg["yumreponame"]."""
        
        RpmDatabase.__init__(self, config, source, buildroot)
        self.excludes = excludes.split()
        self.reponame = reponame
        self.filelist_imported  = 0
        # Files included in primary.xml
        self._filerc = re.compile('^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$')
        self._dirrc = re.compile('^(.*bin/.*|/etc/.*)$')

    def read(self):
        self.is_read = 1 # FIXME: write-only
        filename = functions._uriToFilename(self.source)
        filename = functions.cacheLocal(os.path.join(filename, "repodata/primary.xml.gz"),
                                        self.reponame, 1)
        if not filename:
            return 0
        try:
            reader = libxml2.newTextReaderFilename(filename)
        except libxml2.libxmlError:
            return 0
        self.__parseNode(reader)
        return 1

    def addPkg(self, pkg, unused_nowrite=None):
        # Doesn't know how to write things out, so nowrite is ignored
        if self.__isExcluded(pkg):
            return 0
        self.pkglist[pkg.getNEVRA()] = pkg
        return 1

    def importFilelist(self):
        """Parse filelists.xml.gz if it was not parsed before.

        Return 1 on success, 0 on failure."""

        if self.filelist_imported:
            return 1
        filename = _URItOfILename(self.source)
        filename = functions.cacheLocal(os.path.join(filename, "repodata/filelists.xml.gz"),
                              self.reponame, 1)
        if not filename:
            return 0
        try:
            reader = libxml2.newTextReaderFilename(filename)
        except libxml2.libxmlError:
            return 0
        self.__parseNode(reader)
        self.filelist_imported = 1
        return 1

    def createRepo(self):
        """Create repodata metadata for self.source.

        Return 1 on success, 0 on failure.  Assumes self.source is a local file
        system path without schema prefix."""

        self.filerequires = []
        self.config.printInfo(1, "Pass 1: Parsing package headers for file requires.\n")
        self.__readDir(self.source, "")
        filename = functions._uriToFilename(self.source)
        datapath = os.path.join(filename, "repodata")
        if not os.path.isdir(datapath):
            try:
                os.makedirs(datapath)
            except OSError, e:
                self.config.printError("%s: Couldn't create repodata: %s"
                                       % (filename, e))
                return 0
        try:
            pfd = gzip.GzipFile(os.path.join(datapath, "primary.xml.gz"), "wb")
        except IOError:
            return 0
        try:
            ffd = gzip.GzipFile(os.path.join(datapath, "filelists.xml.gz"),
                                "wb")
        except IOError:
            return 0
        #try:
        #    ofd = gzip.GzipFile(os.path.join(datapath, "other.xml.gz"), "wb")
        #except IOError:
        #    return 0
        pdoc = libxml2.newDoc("1.0")
        proot = pdoc.newChild(None, "metadata", None)
        fdoc = libxml2.newDoc("1.0")
        froot = fdoc.newChild(None, "filelists", None)
        #odoc = libxml2.newDoc("1.0")
        #oroot = odoc.newChild(None, "filelists", None)
        self.config.printInfo(1, "Pass 2: Writing repodata information.\n")
        pfd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        pfd.write('<metadata xmlns="http://linux.duke.edu/metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="%d">\n' % len(self.getPkgList()))
        ffd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        ffd.write('<filelists xmlns:rpm="http://linux.duke.edu/filelists" packages="%d">\n' % len(self.getPkgList()))
        for pkg in self.getPkgList():
            self.config.printInfo(2, "Processing complete data of package %s.\n" % pkg.getNEVRA())
            pkg.header_read = 0
            try:
                pkg.open()
                pkg.read()
            except (IOError, ValueError), e:
                self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                continue
            # If it is a source rpm change the arch to "src". Only valid
            # for createRepo, never do this anywhere else. ;)
            if pkg.isSourceRPM():
                pkg["arch"] = "src"
            try:
                checksum = self.__getChecksum(pkg)
            except (IOError, NotImplementedError), e:
                self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                continue
            pkg["yumchecksum"] = checksum
            self.__writePrimary(pfd, proot, pkg)
            self.__writeFilelists(ffd, froot, pkg)
#            self.__writeOther(ofd, oroot, pkg)
            try:
                pkg.close()
            except IOError:
                pass # Should not happen when opening for reading anyway
            pkg.clear()
        pfd.write('</metadata>\n')
        ffd.write('</filelists>\n')
        pfd.close()
        ffd.close()
        del self.filerequires
        return 1

    def __parseNode(self, reader):
        """Parse <package> tags from libxml2.xmlTextReader reader."""
        
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT or \
               reader.Name() != "package":
                continue
            props = self.__getProps(reader)
            if props.get("type") == "rpm":
                try:
                    pkg = self.__parsePackage(reader)
                except ValueError, e:
                    self.config.printWarning(0, "Error parsing package: %s" % e)
                    continue
                if pkg["arch"] == "src" or self.__isExcluded(pkg):
                    continue
                pkg["yumreponame"] = self.reponame
                self.pkglist[pkg.getNEVRA()] = pkg
            if props.has_key("name"):
                try:
                    arch = props["arch"]
                except KeyError:
                    self.config.printWarning(0,
                                             "%s: missing arch= in <package>"
                                             % pkg.getNEVRA())
                    continue
                try:
                    self.__parseFilelist(reader, props["name"], arch)
                except ValueError, e:
                    self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                    continue

    def __isExcluded(self, pkg):
        """Return True if RpmPackage pkg is excluded by configuration.""" 
        
        found = 0
        for ex in self.excludes:
            excludes = functions.findPkgByName(ex, [pkg])
            if len(excludes) > 0:
                found = 1
                break
        return found

    def __escape(self, s):
        """Return escaped string converted to UTF-8"""

        if s == None:
            return ''
        s = string.replace(s, "&", "&amp;")
        if isinstance(s, unicode):
            return s
        try:
            x = unicode(s, 'ascii')
            return s
        except UnicodeError:
            encodings = ['utf-8', 'iso-8859-1', 'iso-8859-15', 'iso-8859-2']
            for enc in encodings:
                try:
                    x = unicode(s, enc)
                except UnicodeError:
                    pass
                else:
                    if x.encode(enc) == s:
                        return x.encode('utf-8')
        newstring = ''
        for char in s:
            if ord(char) > 127:
                newstring = newstring + '?'
            else:
                newstring = newstring + char
        return re.sub("\n$", '', newstring) # FIXME: not done in other returns

    def __readDir(self, dir, location):
        """Look for non-excluded *.rpm files under dir and add them to
        self.pkglist.

        dir must be a local file system path.  The remote location prefix
        corresponding to dir is location.  Collect file requires of added
        packages in self.filerequires.  Set pkg["yumlocation"] to the remote
        relative path to the package."""

        for f in os.listdir(dir):
            path = os.path.join(dir, f)
            if os.path.isdir(path):
                self.__readDir(path, "%s%s/" % (location, f))
            elif f.endswith(".rpm"):
                pkg = package.RpmPackage(self.config, path)
                try:
                    pkg.read(tags=("name", "epoch", "version", "release", "arch", "sourcerpm", "requirename", "requireflags", "requireversion"))
                    pkg.close()
                except (IOError, ValueError), e:
                    self.config.printWarning(0, "%s: %s" % (path, e))
                    continue
                if self.__isExcluded(pkg):
                    continue
                for reqname in pkg["requirename"]:
                    if reqname[0] == "/":
                        self.filerequires.append(reqname)
                # FIXME: this is done in createRepo too
                # If it is a source rpm change the arch to "src". Only valid
                # for createRepo, never do this anywhere else. ;)
                if pkg.isSourceRPM():
                    pkg["arch"] = "src"
                nevra = pkg.getNEVRA()
                self.config.printInfo(2, "Adding %s to repo and checking file requires.\n" % nevra)
                pkg["yumlocation"] = location+f
                self.pkglist[nevra] = pkg

    def __writePrimary(self, fd, parent, pkg):
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('type', 'rpm')
        pkg_node.newChild(None, 'name', pkg['name'])
        pkg_node.newChild(None, 'arch', pkg['arch'])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        tnode = pkg_node.newChild(None, 'checksum', pkg["yumchecksum"])
        tnode.newProp('type', self.config.checksum)
        tnode.newProp('pkgid', 'YES')
        pkg_node.newChild(None, 'summary', self.__escape(pkg['summary'][0]))
        pkg_node.newChild(None, 'description', self.__escape(pkg['description'][0]))
        pkg_node.newChild(None, 'packager', self.__escape(pkg['packager']))
        pkg_node.newChild(None, 'url', self.__escape(pkg['url']))
        tnode = pkg_node.newChild(None, 'time', None)
        tnode.newProp('file', str(pkg['buildtime'][0]))
        tnode.newProp('build', str(pkg['buildtime'][0]))
        tnode = pkg_node.newChild(None, 'size', None)
        tnode.newProp('package', str(pkg['signature']['size_in_sig'][0]+pkg.range_signature[0]+pkg.range_signature[1]))
        tnode.newProp('installed', str(pkg['size'][0]))
        tnode.newProp('archive', str(pkg['signature']['payloadsize'][0]))
        tnode = pkg_node.newChild(None, 'location', None)
        tnode.newProp('href', pkg["yumlocation"])
        fnode = pkg_node.newChild(None, 'format', None)
        self.__generateFormat(fnode, pkg)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __writeFilelists(self, fd, parent, pkg):
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('pkgid', pkg["yumchecksum"])
        pkg_node.newProp('name', pkg["name"])
        pkg_node.newProp('arch', pkg["arch"])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        self.__generateFilelist(pkg_node, pkg, 0)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __getChecksum(self, pkg):
        """Return checksum of package source of RpmPackage pkg.

        Raise IOError, NotImplementedError."""

        io = getRpmIOFactory(self.config, pkg.source)
        if self.config.checksum == "md5":
            s = md5.new()
        else:
            s = sha.new()
        io.updateDigestFromRange(s, 0, None)
        return s.hexdigest()

    def __getProps(self, reader):
        """Return a dictionary (name => value) of attributes of current tag
        from libxml2.xmlTextReader reader."""

        props = {}
        while reader.MoveToNextAttribute():
            props[reader.Name()] = reader.Value()
        return props

    def __parsePackage(self, reader):
        """Parse a package from current <package> tag at libxml2.xmlTextReader
        reader.

        Raise ValueError on invalid data."""
        
        pkg = package.RpmPackage(self.config, "dummy")
        pkg["signature"] = {}
        pkg["signature"]["size_in_sig"] = [0,]
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "package":
                    break
                continue
            props = self.__getProps(reader)
            if    name == "name":
                if reader.Read() != 1:
                    break
                pkg["name"] = reader.Value()
            elif name == "arch":
                if reader.Read() != 1:
                    break
                pkg["arch"] = reader.Value()
                if pkg["arch"] != "src":
                    pkg["sourcerpm"] = ""
            elif name == "version":
                try:
                    pkg["version"] = props["ver"]
                    pkg["release"] = props["rel"]
                    pkg["epoch"] = [int(props["epoch"]),]
                except KeyError:
                    raise ValueError, "Missing attributes of <version>"
            elif name == "checksum":
                try:
                    type_ = props["type"]
                except KeyError:
                    raise ValueError, "Missing type= in <checksum>"
                if   type_ == "md5":
                    if reader.Read() != 1:
                        break
                    pkg["signature"]["md5"] = reader.Value()
                elif type_ == "sha":
                    if reader.Read() != 1:
                        break
                    pkg["signature"]["sha1header"] = reader.Value()
            elif name == "location":
                try:
                    pkg.source = self.source + "/" + props["href"]
                except KeyError:
                    raise ValueError, "Missing href= in <location>"
            elif name == "size":
                try:
                    pkg["signature"]["size_in_sig"][0] += int(props["package"])
                except KeyError:
                    raise ValueError, "Missing package= in <size>"
            elif name == "format":
                self.__parseFormat(reader, pkg)
        pkg.header_read = 1
        pkg.generateFileNames()
        pkg["provides"] = pkg.getProvides()
        pkg["requires"] = pkg.getRequires()
        pkg["obsoletes"] = pkg.getObsoletes()
        pkg["conflicts"] = pkg.getConflicts()
        pkg["triggers"] = pkg.getTriggers()
        if pkg.has_key("providename"):
            del pkg["providename"]
        if pkg.has_key("provideflags"):
            del pkg["provideflags"]
        if pkg.has_key("provideversion"):
            del pkg["provideversion"]
        if pkg.has_key("requirename"):
            del pkg["requirename"]
        if pkg.has_key("requireflags"):
            del pkg["requireflags"]
        if pkg.has_key("requireversion"):
            del pkg["requireversion"]
        if pkg.has_key("obsoletename"):
            del pkg["obsoletename"]
        if pkg.has_key("obsoleteflags"):
            del pkg["obsoleteflags"]
        if pkg.has_key("obsoleteversion"):
            del pkg["obsoleteversion"]
        if pkg.has_key("conflictname"):
            del pkg["conflictname"]
        if pkg.has_key("conflictflags"):
            del pkg["conflictflags"]
        if pkg.has_key("conflictversion"):
            del pkg["conflictversion"]
        return pkg

    def __parseFilelist(self, reader, pname, arch):
        """Parse a file list from current <package name=pname> tag at
        libxml2.xmlTextReader reader for package with arch arch.

        Raise ValueError on invalid data."""
        
        filelist = []
        version, release, epoch = None, None, None
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "package":
                    break
                continue
            props = self.__getProps(reader)
            if   name == "version":
                version = props.get("ver")
                release = props.get("rel")
                epoch   = props.get("epoch")
            elif name == "file":
                if reader.Read() != 1:
                    break
                filelist.append(reader.Value())
        if version is None or release is None or epoch is None:
            raise ValueError, "Missing version information"
        nevra = "%s-%s:%s-%s.%s" % (pname, epoch, version, release, arch)
        pkg = self.pkglist.get(nevra)
        if pkg:
            pkg["oldfilenames"] = filelist
            pkg.generateFileNames()
            del pkg["oldfilenames"]

    def __generateFormat(self, node, pkg):
        """Add RPM-specific tags under libxml2.xmlNode node for RpmPackage
        pkg."""

        node.newChild(None, 'rpm:license', self.__escape(pkg['license']))
        node.newChild(None, 'rpm:vendor', self.__escape(pkg['vendor']))
        node.newChild(None, 'rpm:group', self.__escape(pkg['group'][0]))
        node.newChild(None, 'rpm:buildhost', self.__escape(pkg['buildhost']))
        node.newChild(None, 'rpm:sourcerpm', self.__escape(pkg['sourcerpm']))
        tnode = node.newChild(None, 'rpm:header-range', None)
        tnode.newProp('start', str(pkg.range_signature[0] + pkg.range_signature[1]))
        tnode.newProp('end', str(pkg.range_payload[0]))
        if len(pkg["provides"]) > 0:
            self.__generateDeps(node, pkg, "provides")
        if len(pkg["requires"]) > 0:
            self.__generateDeps(node, pkg, "requires")
        if len(pkg["conflicts"]) > 0:
            self.__generateDeps(node, pkg, "conflicts")
        if len(pkg["obsoletes"]) > 0:
            self.__generateDeps(node, pkg, "obsoletes")
        self.__generateFilelist(node, pkg)

    def __generateDeps(self, node, pkg, name):
        """Add RPM-specific dependency info under libxml2.xmlNode node for
        RpmPackage pkg dependencies "name"."""

        dnode = node.newChild(None, 'rpm:%s' % name, None)
        deps = self.__filterDuplicateDeps(pkg[name])
        for dep in deps:
            enode = dnode.newChild(None, 'rpm:entry', None)
            enode.newProp('name', dep[0])
            if dep[1] != "":
                if (dep[1] & RPMSENSE_SENSEMASK) != 0:
                    enode.newProp('flags', self.flagmap[dep[1] & RPMSENSE_SENSEMASK])
                if isLegacyPreReq(dep[1]) or isInstallPreReq(dep[1]):
                    enode.newProp('pre', '1')
            if dep[2] != "":
                e,v,r = functions.evrSplit(dep[2])
                enode.newProp('epoch', e)
                enode.newProp('ver', v)
                if r != "":
                    enode.newProp('rel', r)

    def __generateFilelist(self, node, pkg, filter=1):
        """Add RPM-specific file list under libxml2.xmlNode node for RpmPackage
        pkg.

        Restrict the output to _dirrc/_filerc or known file requires if
        filter."""

        files = pkg['filenames']
        fileflags = pkg['fileflags']
        filemodes = pkg['filemodes']
        if files == None or fileflags == None or filemodes == None:
            return
        for (fname, mode, flag) in zip(files, filemodes, fileflags):
            if stat.S_ISDIR(mode):
                if not filter or \
                   self._dirrc.match(fname) or \
                   fname in self.filerequires:
                    tnode = node.newChild(None, 'file', self.__escape(fname))
                    tnode.newProp('type', 'dir')
            elif not filter or \
                 self._filerc.match(fname) or \
                 fname in self.filerequires:
                tnode = node.newChild(None, 'file', self.__escape(fname))
                if flag & RPMFILE_GHOST:
                    tnode.newProp('type', 'ghost')

    def __parseFormat(self, reader, pkg):
        """Parse data from current <format> tag at libxml2.xmlTextReader reader
        to RpmPackage pkg.

        Raise ValueError on invalid input."""

        pkg["oldfilenames"] = []
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "format":
                    break
                continue
            elif name == "rpm:sourcerpm":
                if reader.Read() != 1:
                    break
                pkg["sourcerpm"] = reader.Value()
            elif name == "rpm:header-range":
                props = self.__getProps(reader)
                try:
                    header_start = int(props["start"])
                    header_end = int(props["end"])
                except KeyError:
                    raise ValueError, "Missing start= in <rpm:header_range>"
                pkg["signature"]["size_in_sig"][0] -= header_start
                pkg.range_signature = [96, header_start-96]
                pkg.range_header = [header_start, header_end-header_start]
                pkg.range_payload = [header_end, None]
            elif name == "rpm:provides":
                plist = self.__parseDeps(reader, name)
                pkg["providename"], pkg["provideflags"], pkg["provideversion"] = plist
            elif name == "rpm:requires":
                plist = self.__parseDeps(reader, name)
                pkg["requirename"], pkg["requireflags"], pkg["requireversion"] = plist
            elif name == "rpm:obsoletes":
                plist = self.__parseDeps(reader, name)
                pkg["obsoletename"], pkg["obsoleteflags"], pkg["obsoleteversion"] = plist
            elif name == "rpm:conflicts":
                plist = self.__parseDeps(reader, name)
                pkg["conflictname"], pkg["conflictflags"], pkg["conflictversion"] = plist
            elif name == "file":
                if reader.Read() != 1:
                    break
                pkg["oldfilenames"].append(reader.Value())

    def __filterDuplicateDeps(self, deps):
        """Return the list of (name, flags, release) dependencies deps with
        duplicates (when output by __generateDeps ()) removed."""

        fdeps = []
        for name, flags, version in deps:
            duplicate = 0
            for fname, fflags, fversion in fdeps:
                if name != fname or \
                   version != fversion or \
                   (isErasePreReq(flags) or \
                    isInstallPreReq(flags) or \
                    isLegacyPreReq(flags)) != \
                   (isErasePreReq(fflags) or \
                    isInstallPreReq(fflags) or \
                    isLegacyPreReq(fflags)) or \
                   (flags & RPMSENSE_SENSEMASK) != (fflags & RPMSENSE_SENSEMASK):
                    continue
                duplicate = 1
                break
            if not duplicate:
                fdeps.append([name, flags, version])
        return fdeps

    def __parseDeps(self, reader, ename):
        """Parse a dependency list from currrent tag ename at
        libxml2.xmlTextReader reader.

        Return [namelist, flaglist, versionlist].  Raise ValueError on invalid
        input."""
        
        plist = [[], [], []]
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == ename:
                    break
                continue
            props = self.__getProps(reader)
            if name == "rpm:entry":
                try:
                    name = props["name"]
                except KeyError:
                    raise ValueError, "Missing name= in <rpm.entry>"
                ver = props.get("ver")
                flags = props.get("flags")
                if props.has_key("pre"):
                    prereq = RPMSENSE_PREREQ
                else:
                    prereq = 0
                if ver == None:
                    plist[0].append(name)
                    plist[1].append(prereq)
                    plist[2].append("")
                    continue
                epoch = props.get("epoch")
                rel = props.get("rel")
                if epoch != None:
                    ver = "%s:%s" % (epoch, ver)
                if rel != None:
                    ver = "%s-%s" % (ver, rel)
                plist[0].append(name)
                try:
                    flags = self.flagmap[flags]
                except KeyError:
                    raise ValueError, "Unknown flags %s" % flags
                plist[1].append(flags + prereq)
                plist[2].append(ver)
        return plist

class RpmCompsXML:
    def __init__(self, config, source):
        """Initialize the parser.

        source is an URL to comps.xml."""

        self.config = config
        self.source = source
        self.grouphash = {}             # group id => { key => value }
        self.grouphierarchyhash = {}    # FIXME: write-only

    def __str__(self):
        return str(self.grouphash)

    def read(self):
        """Open and parse the comps file.

        Return 1 on success, 0 on failure."""

        filename = functions.cacheLocal(functions._uriToFilename(self.source), "", 1)
        if filename is None:
            return 0
        try:
            doc = libxml2.parseFile (filename)
            root = doc.getRootElement()
        except libxml2.libxmlError:
            return 0
        return self.__parseNode(root.children)

    def getPackageNames(self, group):
        """Return a list of mandatory an default packages from group and its
        dependencies and the dependencies of the packages.

        The list may contain a single package name more than once.  Only the
        first-level package dependencies are returned, not their transitive
        closure."""

        ret = self.__getPackageNames(group, ("mandatory", "default"))
        ret2 = []
        for val in ret:
            ret2.append(val[0])
            ret2.extend(val[1])
        return ret2

    def getOptionalPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        optional packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["optional"])

    def getDefaultPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        default packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["default"])

    def getMandatoryPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        mandatory packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["mandatory"])

    def __getPackageNames(self, group, typelist):
        """Return a sorted list of (package name, [package requirement]) of
        packages from group and its dependencies with selection type in
        typelist."""
        
        ret = []
        if not self.grouphash.has_key(group):
            return ret
        if self.grouphash[group].has_key("packagelist"):
            pkglist = self.grouphash[group]["packagelist"]
            for (pkgname, value) in pkglist.iteritems():
                if value[0] in typelist:
                    ret.append((pkgname, value[1]))
        if self.grouphash[group].has_key("grouplist"):
            grplist = self.grouphash[group]["grouplist"]
            # FIXME: Stack overflow with loops in group requirements
            for grpname in grplist["groupreqs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
            for grpname in grplist["metapkgs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
        # Sort and duplicate removal
        ret.sort()
        for i in xrange(len(ret)-2, -1, -1):
            if ret[i+1] == ret[i]:
                ret.pop(i+1)
        return ret

    def __parseNode(self, node):
        """Parse libxml2.xmlNode node and its siblings under the root
        element.

        Return 1 on success, 0 on failure.  Handle <group>, <grouphierarchy>,
        warn about other tags."""

        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "group":
                self.__parseGroup(node.children)
            elif node.name == "grouphierarchy":
                ret = self.__parseGroupHierarchy(node.children)
                if not ret:
                    return 0
            else:
                self.config.printWarning(1, "Unknown entry in comps.xml: %s" % node.name)
                return 0
            node = node.next
        return 1

    def __parseGroup(self, node):
        """Parse libxml2.xmlNode node and its siblings under <group>."""

        group = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if  node.name == "name":
                lang = node.prop("lang")
                if lang:
                    group["name:"+lang] = node.content
                else:
                    group["name"] = node.content
            elif node.name == "id":
                group["id"] = node.content
            elif node.name == "description":
                lang = node.prop("lang")
                if lang:
                    group["description:"+lang] = node.content
                else:
                    group["description"] = node.content
            elif node.name == "default":
                group["default"] = functions.parseBoolean(node.content)
            elif node.name == "langonly":
                group["langonly"] = node.content
            elif node.name == "packagelist":
                group["packagelist"] = self.__parsePackageList(node.children)
            elif node.name == "grouplist":
                group["grouplist"] = self.__parseGroupList(node.children)
            node = node.next
        self.grouphash[group["id"]] = group

    def __parsePackageList(self, node):
        """Parse libxml2.xmlNode node and its siblings under <packagelist>.

        Return { package => (selection, [requirement]) }."""

        plist = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "packagereq":
                ptype = node.prop("type")
                if ptype == None:
                    ptype = "default"
                requires = node.prop("requires")
                if requires != None:
                    requires = requires.split()
                else:
                    requires = []
                plist[node.content] = (ptype, requires)
            node = node.next
        return plist

    def __parseGroupList(self, node):
        """Parse libxml2.xmlNode node and its siblings under <grouplist>.

        Return { "groupgreqs" => [requirement],
        "metapkgs" => { requirement => requirement type } }."""

        glist = {}
        glist["groupreqs"] = []
        glist["metapkgs"] = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if   node.name == "groupreq":
                glist["groupreqs"].append(node.content)
            elif node.name == "metapkg":
                gtype = node.prop("type")
                if gtype == None:
                    gtype = "default"
                glist["metapkgs"][node.content] = gtype
            node = node.next
        return glist

    def __parseGroupHierarchy(self, node):
        """"Parse" libxml2.xmlNode node and its siblings under
        <grouphierarchy>.

        Return 1."""

        # We don't need grouphierarchies, so don't parse them ;)
        return 1


def getRpmDBFactory(config, source, root=None):
    """Get a RpmDatabase implementation for database "URI" source under
    root.

    Default to rpmdb:/ if no scheme is provided."""

    if   source[:6] == 'pydb:/':
        return RpmPyDB(config, source[6:], root)
    elif source[:7] == 'rpmdb:/':
        return RpmDB(config, source[7:], root)
    elif source[:10] == 'sqlitedb:/':
        return RpmSQLiteDB(config, source[10:], root)
    return RpmDB(config, source, root)


# vim:ts=4:sw=4:showmatch:expandtab
