# Copyright 2005 Duke University
# Copyright (C) 2006 Red Hat, Inc.
# Authors: Florian Festi <ffesti@redhat.com>
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

import os, re, bz2, shutil
try:
    # python-2.5 layout:
    from xml.etree.cElementTree import iterparse
except ImportError:
    try:
        # often older python versions add this to site-packages:
        from cElementTree import iterparse
    except ImportError:
        try:
            # maybe the python-only version is available?
            from ElementTree import iterparse
        except:
            raise "No ElementTree parser found. Aborting."

from pyrpm import *
import pyrpm.base
import repodb
from pyrpm.logger import log

# This version refers to the internal structure of the sqlite cache files
# increasing this number forces all caches of a lower version number
# to be re-generated
dbversion = '9'
supported_dbversions = ('9', '8')

USEYUM = False
try:
    import yum.storagefactory
    import yum.mdparser
    try:
        # new dbversion
        import yum.constants
        USEYUM = yum.constants.DBVERSION == dbversion
    except:
        try:
            # old dbversion
            import yum.sqlitecache
            USEYUM = yum.sqlitecache.dbversion == dbversion
        except:
            pass
except:
    pass
USEYUM = False # disable yum metadata parser for now
               # as it messes up pre requirements

import sqlitecompat as sqlite3
from lrucache import SmallLRUCache

class SqliteRpmPackage(package.RpmPackage):

    CACHE = {
        'requires' : SmallLRUCache(maxsize=100),
        'provides' : SmallLRUCache(maxsize=100),
        'conflicts' : SmallLRUCache(maxsize=100),
        }

    def __init__(self, config, source, verify=None, hdronly=None, db=None):
        self.filesloaded = False
        package.RpmPackage.__init__(self, config, source, verify, hdronly, db)

    def has_key(self, name):
        if dict.has_key(self, name):
            return True
        elif not self.filesloaded and \
             name in ('basenames', 'dirnames', 'dirindexes', 'oldfilenames'):
            self.filesloaded = True
            self.yumrepo.getFiles(self)
            return dict.has_key(self, name)
        elif name in ('requires','provides','conflicts','obsoletes'):
            return True
        return False

    def __getitem__(self, name):
        if dict.has_key(self, name):
            return dict.get(self, name)
        if name in self.CACHE:
            if self.CACHE[name].has_key(self):
                return self.CACHE[name][self]
            deps = self.yumrepo.getDependencies(name, self.pkgKey)
            self.CACHE[name][self] = deps
            return deps
        if name in ('obsoletes', 'requires','provides','conflicts'):
            deps = self.yumrepo.getDependencies(name, self.pkgKey)
            self[name] = deps
            return deps
        if (name in ('basenames', 'dirnames', 'dirindexes', 'oldfilenames') and
            not self.filesloaded):
            self.filesloaded = True
            self.yumrepo.getFiles(self)
            return self.get(name, None)
        # don't cache other tags
        return self.yumrepo.getPkgTag(self, name)

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

    def reread(self, tags=None, ntags=None):
        package.RpmPackage.reread(self, tags, ntags)
        self.filesloaded = True

    def clearFilelist(self):
        self.filesloaded = False
        for tag in ('basenames', 'dirnames', 'dirindexes', 'oldfilenames'):
            if dict.has_key(self, tag):
                del self[tag]

class SqliteRepoDB(repodb.RpmRepoDB):
    COLUMNS = (
            'pkgId',
            'name',
            'arch',
            'version',
            'epoch',
            'release',
            'summary',
            'description',
            'url',
            'time_file', # ???
            'time_build',
            'rpm_license',
            'rpm_vendor',
            'rpm_group',
            'rpm_buildhost',
            'rpm_sourcerpm',
            'rpm_header_start', # position in bytes
            'rpm_header_end',   # position in bytes
            'rpm_packager',
            'size_package',
            'size_installed',
            'size_archive',
            'location_href', # locale position with in repo
            'location_base', # repo url (empty)
            'checksum_type', # 'sha' or 'md5'
            'checksum_value',#
            )

    COLUMNS_LOOKUP = set(COLUMNS)

    DB2PKG = {
        # 'time_file' : '' # -> pkg.time_file
        'time_build' : 'buildtime',
        'rpm_buildhost' : 'buildhost',

        'rpm_license': 'license',
        'rpm_vendor': 'vendor',
        'rpm_group': 'group',
        'rpm_buildhost': 'buildhost',
        'rpm_sourcerpm': 'sourcerpm',
        # 'rpm_header_start' : '',
        # 'rpm_header_end' : '',
        'rpm_packager': 'packager',

        'size_package' : 'archivesize',
        'size_installed' : 'size',
        # 'size_archive' : '',

        # 'location_href' : '', pkg.source
        # 'location_base' : '', ''

        }

    PKG2DB = { }
    for k, v in DB2PKG.iteritems():
        PKG2DB[v] = k


    tags = 'pkgKey, name, arch, version, epoch, release, location_href'

    def __init__(self, config, source, buildroot='', reponame="default", nc=None):
        repodb.RpmRepoDB.__init__(self, config, source, buildroot, reponame, nc)
        self._primarydb = None
        self._filelistsdb = None
        self._othersdb = None
        self._pkgs = { }
        self.search_cache = {
            "provides" : SmallLRUCache(maxsize=1000),
            "requires" : SmallLRUCache(maxsize=1000),
            "obsoletes" : SmallLRUCache(maxsize=1000),
            "conflicts" : SmallLRUCache(maxsize=1000),
            }

    def isIdentitySave(self):
        """return if package objects that are added are in the db afterwards
        (.__contains__() returns True and the object are return from searches)
        """
        return False

    def clear(self):
        self.close()
        self._pkgs.clear()

    def clearPkgs(self, tags=None, ntags=None):
        for pkg in self._pkgs.itervalues():
            if pkg:
                pkg.clear(tags, ntags)

    def create(self, filename):
        """Create an initial database"""

        # If it exists, remove it as we were asked to create a new one
        if os.path.exists(filename):
            try:
                os.unlink(filename)
            except OSError:
                pass

        # Try to create the databse in filename, or use in memory when
        # this fails
        try:
            f = open(filename, 'w')
            db = sqlite3.connect(filename)
        except IOError:
            log.warning("Could not create sqlite cache file, using in memory "
                        "cache instead")
            db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.text_factory = str
        return db

    def createDbInfo(self, cur):
        # Create the db_info table, this contains sqlite cache metadata
        cur.execute("""CREATE TABLE db_info (
            dbversion TEXT,
            checksum TEXT)
        """)

    def setInfo(self, db, dbversion, checksum):
        cur = db.cursor()
        data = {'dbversion' : dbversion,
                'checksum' : checksum
                }
        self.insertHash("db_info", data, cur)
        db.commit()

    def insertHash(self, table, hash, cursor):
        """Insert the key value pairs in hash into a database table"""
        keys = hash.keys()
        values = hash.values()
        query = "INSERT INTO %s (" % (table)
        query += ",".join(keys)
        query += ") VALUES ("
        query += ', '.join(["?"] * len(hash))
        query += ")"
        values = hash.values()
        if 'pre' in hash and sqlite3.sqlite:
            idx = hash.keys().index('pre')
            values[idx] = ("False", "True")[values[idx]]

        cursor.execute(query, values)# XXX ??? .encode('utf8'))
        return cursor.lastrowid

    def loadCache(self, filename):
        """Load cache from filename, check if it is valid and that dbversion
        matches the required dbversion"""
        db = sqlite3.connect(filename)
        db.row_factory = sqlite3.Row
        db.text_factory = str
        cur = db.cursor()
        cur.execute("SELECT * FROM db_info")
        info = cur.fetchone()
        # If info is not in there this is an incompelete cache file
        # (this could happen when the user hits ctrl-c or kills yum
        # when the cache is being generated or updated)
        if not info:
            raise sqlite3.DatabaseError, "Incomplete database cache file"

        # Now check the database version
        if info['dbversion'] not in supported_dbversions:
            log.info2("Cache file is version %s, we need %s, will "
                      "regenerate.\n", info['dbversion'], dbversion)
            raise sqlite3.DatabaseError, "Older version of yum sqlite: %s" % info['dbversion']

        # This appears to be a valid database, return checksum value and
        # database object
        return (info['checksum'], db)

    def createFilelistsTables(self):
        """Create the required tables for filelists metadata in the sqlite
           database"""
        cur = self._filelistsdb.cursor()
        self.createDbInfo(cur)
        # This table is needed to match pkgKeys to pkgIds
        cur.execute("""CREATE TABLE packages(
            pkgKey INTEGER PRIMARY KEY,
            pkgId TEXT)
        """)
        cur.execute("""CREATE TABLE filelist(
            pkgKey INTEGER,
            dirname TEXT,
            filenames TEXT,
            filetypes TEXT)
        """)
        cur.execute("CREATE INDEX keyfile ON filelist (pkgKey)")
        cur.execute("CREATE INDEX pkgId ON packages (pkgId)")
        cur.execute("CREATE INDEX dirnames ON filelist (dirname)")
        self._filelistsdb.commit()

    def createOthersTables(self):
        """Create the required tables for other.xml.gz metadata in the sqlite
           database"""
        cur = self._othersdb.cursor()
        self.createDbInfo(cur)
        # This table is needed to match pkgKeys to pkgIds
        cur.execute("""CREATE TABLE packages(
            pkgKey INTEGER PRIMARY KEY,
            pkgId TEXT)
        """)
        cur.execute("""CREATE TABLE changelog(
            pkgKey INTEGER,
            author TEXT,
            date TEXT,
            changelog TEXT)
        """)
        cur.execute("CREATE INDEX keychange ON changelog (pkgKey)")
        cur.execute("CREATE INDEX pkgId ON packages (pkgId)")
        self._othersdb.commit()

    def createPrimaryTables(self):
        """Create the required tables for primary metadata in the sqlite
           database"""
        cur = self._primarydb_cursor
        self.createDbInfo(cur)
        # The packages table contains most of the information in primary.xml.gz

        q = 'CREATE TABLE packages(\n' \
            'pkgKey INTEGER PRIMARY KEY,\n'
        cols = []
        for col in self.COLUMNS:
            cols.append('%s TEXT' % col)
        q += ',\n'.join(cols) + ')'
        cur.execute(q)

        # Create requires, provides, conflicts and obsoletes tables
        # to store prco data
        for t in ('requires','provides','conflicts','obsoletes'):
            extraCol = ""
            if t == 'requires':
                extraCol= ", pre BOOL DEFAULT FALSE"
            cur.execute("""CREATE TABLE %s (
              name TEXT,
              flags TEXT,
              epoch TEXT,
              version TEXT,
              release TEXT,
              pkgKey TEXT %s)
            """ % (t, extraCol))
        # Create the files table to hold all the file information
        cur.execute("""CREATE TABLE files (
            name TEXT,
            type TEXT,
            pkgKey TEXT)
        """)
        # Create indexes for faster searching
        cur.execute("CREATE INDEX packagename ON packages (name)")
        cur.execute("CREATE INDEX providesname ON provides (name)")
        cur.execute("CREATE INDEX pkgprovides ON provides (pkgKey)")
        cur.execute("CREATE INDEX requiresname ON requires (name)")
        cur.execute("CREATE INDEX pkgrequires ON requires (pkgKey)")
        cur.execute("CREATE INDEX pkgconflicts ON conflicts (pkgKey)")
        cur.execute("CREATE INDEX pkgobsoletes ON obsoletes (pkgKey)")
        cur.execute("CREATE INDEX packageId ON packages (pkgId)")
        cur.execute("CREATE INDEX filenames ON files (name)")
        self._primarydb.commit()

    def open(self):
        """If the database keeps a connection, prepare it."""
        return 1

    def close(self):
        """If the database keeps a connection, close it."""
        for db in (self._primarydb, self._filelistsdb, self._othersdb):
            if db is not None:
                db.close()
        self._primarydb = None
        self._filelistsdb = None
        self._othersdb = None
        return 1

    def getDbFile(self, dbtype):
        if dbtype != "primary":
            log.info2("Loading %s for %s...", dbtype, self.reponame)

        cachebase = os.path.join(self.config.cachedir, self.reponame)
        cachepath = os.path.join(self.config.cachedir, self.reponame, "sqlite")

        if not os.path.isdir(cachebase):
            os.makedirs(cachebase)
        if not os.path.isdir(cachepath):
            os.makedirs(cachepath)

        # check existing sqlite db
        dbfilename = os.path.join(cachepath, "%s.xml.gz.sqlite" % dbtype)
        if os.path.exists(dbfilename):
            try:
                csum, db = self.loadCache(dbfilename)
            except sqlite3.Error, e:
                log.error(e)
                csum = None
            if self.repomd.has_key(dbtype) and \
                   self.repomd[dbtype].has_key("checksum") and \
                   csum == self.repomd[dbtype]["checksum"]:
                setattr(self, "_%sdb" % dbtype, db)
                setattr(self, "_%sdb_cursor" % dbtype, db.cursor())
                return 1

        # try to get %dbtype.xml.gz.sqlite.bz2 from repository
        for force in [0, 1]:
            filenamebz2 = self.nc.cache(
                "repodata/%s.xml.gz.sqlite.bz2" % dbtype, force)
            if not filenamebz2:
                break

            try:
                f = bz2.BZ2File(filenamebz2)
                o = open(dbfilename, "w")

                o.write(f.read())
                o.close()
                f.close()
            except (IOError, EOFError):
                continue


            try:
                csum, db = self.loadCache(dbfilename)
            except sqlite3.Error, e:
                csum = None

            if self.repomd.has_key(dbtype) and \
                   self.repomd[dbtype].has_key("checksum") and \
                   csum == self.repomd[dbtype]["checksum"]:
                setattr(self, "_%sdb" % dbtype, db)
                setattr(self, "_%sdb_cursor" % dbtype, db.cursor())
                return 1

        # get %dbtype.xml.gz and create sqlite db
        (csum, destfile) = self.nc.checksum("repodata/%s.xml.gz" % dbtype,
                                            "sha")
        if self.repomd.has_key(dbtype) and \
           self.repomd[dbtype].has_key("checksum") and \
           csum == self.repomd[dbtype]["checksum"] and \
           self.nc.isCached("repodata/%s.xml.gz" % dbtype):
            filename = self.nc.getCachedFilename("repodata/%s.xml.gz" % dbtype)
        else:
            filename = self.nc.cache("repodata/%s.xml.gz" % dbtype, 1,
                                     copy_local=True)
            (csum, destfile) = self.nc.checksum("repodata/%s.xml.gz" % dbtype,
                                                "sha")
            if not (self.repomd.has_key(dbtype) and \
                    self.repomd[dbtype].has_key("checksum") and \
                    csum == self.repomd[dbtype]["checksum"]):
                return 0

        if filename:
            log.info2("Creating %s", dbfilename)
            if USEYUM:
                parser = yum.mdparser.MDParser(filename)
                storage = yum.storagefactory.GetStorage()
                cache = storage.GetCacheHandler(dbfilename, 'tmp', None)
                if dbtype == 'primary':
                    db = cache.getPrimary(filename, csum)
                elif dbtype == 'filelists':
                    db = cache.getFilelists(filename, csum)
                elif dbtype == 'other':
                    db = cache.getOtherdata(filename, csum)
                # XXX error handling
                shutil.move(filename + '.sqlite', dbfilename)
                setattr(self, "_%sdb" % dbtype, db)
                setattr(self, "_%sdb_cursor" % dbtype, db.cursor())
                # TODO: add all other indices
                if dbtype == 'primary':
                    cur = db.cursor()
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS "
                        "requiresname ON requires (name)")
                return 1
            db = self.create(dbfilename)
            setattr(self, "_%sdb" % dbtype, db)
            setattr(self, "_%sdb_cursor" % dbtype, db.cursor())
            if dbtype == 'primary':
                self.createPrimaryTables()
            elif dbtype == 'filelists':
                self.createFilelistsTables()
            elif dbtype == 'other':
                self.createOthersTables()

            try:
                fd = PyGZIP(filename)
                ip = iterparse(fd, events=("start","end"))
                ip = iter(ip)
            except IOError:
                return 0
            self._parse(ip)
            self.setInfo(db, dbversion, self.repomd[dbtype]["checksum"])
            db.commit()
            return 1
        return 0

    def readPrimary(self):
        result = self.getDbFile("primary")
        #self.readRpms()
        return result

    def _addFilesToPkg(self, name, epoch, version, release, arch, filelist,
                      filetypelist):
        """Add a package to the filelists cache"""
        cur = self._primarydb_cursor
        fcur = self._filelistsdb_cursor
        cur.execute('SELECT pkgId, pkgKey FROM packages WHERE name=? '
                    'and epoch=? and version=? and release=? '
                    'and arch=?',
                    (name, epoch, version, release, arch))
        op = cur.fetchone()
        if op is None:
            # package not found
            return
        pkgId, pkgKey = op[0], op[1]

        try:
            self.insertHash('packages', {'pkgId' : pkgId, 'pkgKey' : pkgKey},
                fcur)
        except sqlite3.DatabaseError:
            # Files of package already in database: skipping
            return

        if self._pkgs.has_key(pkgKey) and self._pkgs[pkgKey] is not None:
            self._pkgs[pkgKey]['oldfilenames'] = filelist

        dirs = {}
        for (filename, ftype) in zip(filelist, filetypelist):
            (dirname, filename) = functions.pathsplit(filename)
            if not dirs.has_key(dirname):
                dirs[dirname] = {'files' : [], 'types' : []}
            dirs[dirname]['files'].append(filename)
            dirs[dirname]['types'].append(ftype[0])

        for (dirname, dir) in dirs.items():
            data = {
                'pkgKey': pkgKey,
                'dirname': dirname,
                'filenames': '/'.join(dir['files']),
                'filetypes': ''.join(dir['types'])
            }
            self.insertHash('filelist', data, fcur)

    def importFilelist(self):
        # try mirror that just worked
        if self.getDbFile("filelists"):
            for pkg in self._pkgs.itervalues():
                if pkg is not None:
                    pkg.clearFilelist()
            self.filelist_imported = True
            return 1
        return 0

    def readRpm(self, pkgKey):
        cur = self._primarydb_cursor
        cur.execute('SELECT %s FROM packages WHERE pkgKey=?' %
                    self.tags, (pkgKey,))
        ob = cur.fetchone()
        pkg = self._buildRpm(ob)
        return pkg

    def readRpms(self):
        self._primarydb_cursor.execute("SELECT %s FROM packages" % self.tags)
        for ob in self._primarydb_cursor.fetchall():
            pkgKey = int(ob['pkgKey'])
            if self._pkgs.has_key(pkgKey):
                continue
            pkg = self._buildRpm(ob)
            if pkg:
                self._pkgs[pkgKey] = pkg
                if self._isExcluded(pkg):
                    self._pkgs[pkgKey] = None
                                                

    def _buildRpm(self, data):
        pkg = SqliteRpmPackage(self.config, source='', db=self)
        pkg.yumrepo = self
        pkg.reponame = self.reponame
        for key in ['pkgKey', 'name', 'arch', 'version',
                    'epoch', 'release', 'location_href']:
            name = self.DB2PKG.get(key, key)
            val = data[key]
            if val is not None and name in base.rpmtag:
                pkg[name] = val
        pkg.pkgKey = data['pkgKey']
        pkg['epoch'] = [int(pkg['epoch'])]
        pkg.source = data['location_href']
        pkg.issrc = 0
        pkg.size = int(pkg["archivesize"][0])
        if self.comps != None:
            if   self.comps.hasType(pkg["name"], "mandatory"):
                pkg.compstype = "mandatory"
            elif self.comps.hasType(pkg["name"], "default"):
                pkg.compstype = "default"
            elif self.comps.hasType(pkg["name"], "optional"):
                pkg.compstype = "optional"
        pkg["triggers"] = []
        return pkg

    def getPkgTag(self, pkg, tag):
        ttype = base.rpmtag[tag][1]
        tag = self.PKG2DB.get(tag, tag)
        if tag not in self.COLUMNS_LOOKUP:
            return None
        cur = self._primarydb_cursor
        cur.execute('SELECT %s FROM packages WHERE pkgKey=?' %
                    tag, (pkg.pkgKey,))
        if ttype == RPM_STRING:
            return cur.fetchone()[0]
        elif ttype in (RPM_STRING_ARRAY, RPM_I18NSTRING):
            return [ cur.fetchone()[0] ]
        elif ttype in (RPM_CHAR, RPM_INT8, RPM_INT16, RPM_INT32, RPM_INT64):
            return ( int(cur.fetchone()[0]), )

    def getFiles(self, pkg):
        pkgKey = pkg.pkgKey
        if self._filelistsdb:
            cur = self._filelistsdb.cursor()
            cur.execute('SELECT * FROM filelist WHERE pkgKey=?', (pkgKey,))
            basenames = []
            dirnames = []
            dirindexes = []
            for ob in cur.fetchall():
                idx = len(dirnames)
                base = ob["filenames"].split('/')
                dirnames.append(ob["dirname"] + '/')
                basenames.extend(base)
                dirindexes.extend([idx] * len(base))
            if pkg.has_key('oldfilenames'):
                del pkg['oldfilenames']
            if basenames:
                pkg['basenames'] = basenames
                pkg['dirnames'] = dirnames
                pkg['dirindexes'] = dirindexes
        else:
            cur = self._primarydb_cursor
            cur.execute(
                'SELECT * FROM files WHERE pkgKey=?', (pkgKey,))
            files = [ob['name'] for ob in cur.fetchall()]
            if files:
                pkg['oldfilenames'] = files
                pkg.generateFileNames()

    def _getDBFlags(self, ob):
        try:
            pre = ob['pre']
        except (KeyError, IndexError):
            pre = 0
        if isinstance(pre, str):
            pre = pre.lower() == 'true'

        if pre:
            return self.flagmap[ob['flags']] | pyrpm.base.RPMSENSE_PREREQ
        return self.flagmap[ob['flags']]

    def getDependencies(self, tag, pkgKey):
        cur = self._primarydb_cursor
        cur.execute(
            'SELECT * FROM %s WHERE pkgKey=?' % tag, (pkgKey,))
        return [(ob['name'], self._getDBFlags(ob), functions.evrMerge(
            ob['epoch'], ob['version'], ob['release']))
                for ob in cur.fetchall()]

    # add package
    def addPkg(self, pkg):
        cur = self._primarydb_cursor
        data = {}
        for tag in self.COLUMNS:
            data[tag] = pkg[self.DB2PKG.get(tag, tag)]
        if pkg['signature'].has_key('sha1header'):
            data['checksum_type'] = 'sha'
            data['checksum_value'] = pkg['signature']['sha1header']
        elif pkg['signature'].has_key('md5'):
            data['checksum_type'] = 'md5'
            data['checksum_value'] = pkg['signature']['md5']
        data['pkgId'] = data['checksum_value']
        data['epoch'] = pkg['epoch'][0]
        data['location_href'] = pkg.source
        data['time_file'] = pkg.time_file
        data['rpm_header_start'] = pkg.range_header[0]
        data['rpm_header_end'] = pkg.range_header[0] + pkg.range_header[1]
        for k, v in pkg.sizes.iteritems():
            data['size_' + k] = v

        # check if package already in db
        cur.execute('SELECT pkgKey FROM packages WHERE pkgId=?',
                    (data['pkgId'],))
        if cur.fetchone():
            return

        pkgKey = self.insertHash('packages', data, cur)
        pkg.pkgKey = pkgKey

        for tag in ('requires', 'provides', 'conflicts', 'obsoletes'):
            for (n, f, v) in pkg[tag]:
                epoch, version, release = functions.evrSplit(v, "")
                data = {
                    'name' : n,
                    'flags' : self.flagmap[f & base.RPMSENSE_SENSEMASK],
                    'epoch' : epoch,
                    'version' : version,
                    'release' : release,
                    'pkgKey' : pkgKey,
                    }
                if (f & base.RPMSENSE_PREREQ) and tag == 'requires':
                    data['pre'] = True
                self.insertHash(tag, data, cur)

        for f, t in  zip(pkg.iterFilenames(), pkg.filetypelist):
            self.insertHash(
                'files', {'name' : f, 'type' : t[0], 'pkgKey' : pkgKey}, cur)

    # remove package
    def removePkg(self, pkg):
        raise NotImplementedError

    def getPkgByKey(self, pkgKey):
        pkgKey = int(pkgKey)
        if self._pkgs.has_key(pkgKey):
            return self._pkgs[pkgKey]
        pkg = self.readRpm(pkgKey)
        if pkg:
            self._pkgs[pkgKey] = pkg
            if self._isExcluded(pkg):
                self._pkgs[pkgKey] = None
                return None
        return pkg

    def getPkgById(self, pkgId):
        cur = self._primarydb_cursor
        cur.execute('SELECT pkgKey FROM packages WHERE pkgId=?', (pkgId,))
        ob = cur.fetchone()
        if ob:
            return self.getPkgByKey(ob["pkgKey"])
        else:
            return None

    def getPkgs(self):
        cur = self._primarydb_cursor
        cur.execute('SELECT pkgKey FROM packages')
        result = [self.getPkgByKey(ob["pkgKey"]) for ob in cur.fetchall()]
        return filter(None, result)

    def getNames(self):
        cur = self._primarydb_cursor
        cur.execute("SELECT name FROM packages")
        return [ob["name"] for ob in cur.fetchall()]

    def hasName(self, name):
        cur = self._primarydb_cursor
        cur.execute('SELECT name FROM packages WHERE name=?', (name,))
        return bool(cur.fetchone())

    def getPkgsByName(self, name):
        cur = self._primarydb_cursor
        cur.execute('SELECT pkgKey FROM packages WHERE name=?', (name,))
        result = [self.getPkgByKey(ob['pkgKey']) for ob in cur.fetchall()]
        return filter(None, result)

    def getPkgsFileRequires(self):
        cur = self._primarydb_cursor
        cur.execute('SELECT pkgKey, name FROM requires WHERE name LIKE "/%"')
        result = {}
        for ob in cur.fetchall():
            pkg = self.getPkgByKey(ob[0])
            if pkg is None:
                continue
            result.setdefault(pkg, [ ]).append(ob[1])
        return result

    def getFilenames(self):
        raise NotImplementedError

    def numFileDuplicates(self, filename):
        raise NotImplementedError

    def getFileDuplicates(self):
        raise NotImplementedError

    def _iter(self, tag):
        cur = self._primarydb_cursor
        cur.execute("SELECT * FROM %s" % tag)
        for res in cur.fetchall():
            pkg = self.getPkgByKey(res['pkgKey'])
            if pkg is None:
                continue
            version = functions.evrMerge(res['epoch'], res['version'],
                                         res['release'])
            yield res['name'], self.flagmap[res['flags']], version, pkg

    def _iter2(self, tag):
        for pkg in self.getPkgs():
            for entry in pkg[tag]:
                yield entry + (pkg,)

    def iterProvides(self):
        return self._iter2("provides")

    def iterRequires(self):
        return self._iter2("requires")

    def iterConflicts(self):
        return self._iter("conflicts")

    def iterObsoletes(self):
        return self._iter("obsoletes")

    def iterTriggers(self):
        raise NotImplementedError # XXX StopIteration?

    def reloadDependencies(self):
        pass

    # Use precompiled regex for faster checks
    __fnmatchre__ = re.compile(".*[\*\[\]\?].*")
    __splitre__ = re.compile(r"([:*?\-.]|\[[^]]+\])")

    def searchPkgs(self, names):
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
                for idx in xrange(1, len(parts)+1, 2):
                    pkgs = self.getPkgsByName(''.join(parts[:idx]))
                    for pkg in pkgs:
                        for n in pkg.getAllNames():
                            if n == name:
                                result.append(pkg)
                                break
        #normalizeList(result)
        return result

    def search(self, words):
        result = []
        cur = self._primarydb_cursor
        for word in words:
            word = '%' + word + '%'
            cur.execute('SELECT pkgKey FROM packages WHERE '
                        '(name LIKE ?) OR (description LIKE ?) OR '
                        '(summary LIKE ?) OR (rpm_packager LIKE ?) OR '
                        '(rpm_group LIKE ?) OR (url LIKE ?)',
                        (word, ) * 6)
            result.extend((self.getPkgByKey(res['pkgKey']) for res in cur))
        result = filter(None, result)
        normalizeList(result)
        return result

    def _search(self, attr_table, name, flag, version):
        """return hash {pkg -> [ (name, flag, evr), ... ]"""
        result = { }
        evr = functions.evrSplit(version)
        cache = None
        if self.search_cache.has_key(attr_table):
            cache = self.search_cache[attr_table]
            query = (name, flag, version)
            if query in cache:
                return cache[query]
        cur = self._primarydb_cursor
        cur.execute('SELECT * FROM %s WHERE name = ?' %
                    attr_table, (name,))
        for res in cur.fetchall():
            pkg = self.getPkgByKey(res['pkgKey'])
            if pkg is None:
                continue
            name_ = res['name']
            flag_ = self._getDBFlags(res)
            version_ = functions.evrMerge(res['epoch'], res['version'],
                                          res['release'])
            if version == "":
                result.setdefault(pkg, [ ]).append(
                    (name_, flag_, version_))
            elif functions.rangeCompare(flag, evr,
                                        flag_, functions.evrSplit(version_)):
                result.setdefault(pkg, [ ]).append((name_, flag_, version_))
            elif version_ == "":
                result.setdefault(pkg, [ ]).append((name_, flag_, version_))
        if cache is not None:
            cache[query] = result
        return result

    def searchProvides(self, name, flag, version):
        return self._search("provides", name, flag, version)

    def searchRequires(self, name, flag, version):
        return self._search("requires", name, flag, version)

    def searchConflicts(self, name, flag, version):
        return self._search("conflicts", name, flag, version)

    def searchObsoletes(self, name, flag, version):
        return self._search("obsoletes", name, flag, version)

    def searchTriggers(self, name, flag, version):
        raise NotImplementedError

    def searchFilenames(self, name):
        # If it is a filename, search the primary.xml file info
        matched = 0
        globs = ['.*bin\/.*', '^\/etc\/.*', '^\/usr\/lib\/sendmail$']
        for glob in globs:
            globc = re.compile(glob)
            if globc.match(name):
                matched = 1
                break

        result = [ ]

        if matched:
            cur = self._primarydb_cursor
            cur.execute('SELECT * FROM files WHERE name = ?', (name,))
            files = cur.fetchall()
            for res in files:
                pkg = self.getPkgByKey(res['pkgKey'])
                if pkg is None:
                    continue
                result.append(pkg)
            return result

        # If it is a filename, search the files.xml file info
        if not self._filelistsdb:
            return result

        cur = self._filelistsdb.cursor()
        (dirname, filename) = functions.pathsplit(name)
        if name.find('%') == -1: # no %'s in the thing safe to LIKE
            cur.execute("SELECT * FROM filelist WHERE "
                        'dirname=? AND filenames LIKE ?',
                        (dirname, "%%%s%%" % filename))
        else:
            cur.execute('SELECT * FROM filelist WHERE dirname=?', (dirname,))

        files = cur.fetchall()

        for res in files:
            if filename and not filename in res['filenames'].split('/'):
                continue
            pkg = self.getPkgByKey(res['pkgKey'])
            if pkg:
                result.append(pkg)
        return result

# fall back to RpmRepoDB if sqlite is not installed
if not sqlite3.ok:
    SqliteRepoDB = repodb.RpmRepoDB

# vim:ts=4:sw=4:showmatch:expandtab
