import rpmdb, memorydb, jointdb

NOT_DELETED = -5

class RpmDiskShadowDB(rpmdb.RpmDB):

    def __init__(self, rpmdb):
        #db.RpmDatabase.__init__(self, config, source, buildroot)
        # Correctly initialize the tscolor based on the current arch
        self.rpmdb = rpmdb

        rpmdb.open()
        
        self.netsharedpath = rpmdb.netsharedpath

        # Shared instances !!!
        self._pkgs = rpmdb._pkgs
        self.basenames_cache = rpmdb.basenames_cache

        self.basenames_db      = rpmdb.basenames_db
        self.conflictname_db   = rpmdb.conflictname_db
        self.dirnames_db       = rpmdb.dirnames_db
        self.filemd5s_db       = rpmdb.filemd5s_db
        self.group_db          = rpmdb.group_db
        self.installtid_db     = rpmdb.installtid_db
        self.name_db           = rpmdb.name_db
        self.packages_db       = rpmdb.packages_db
        self.providename_db    = rpmdb.providename_db
        self.provideversion_db = rpmdb.provideversion_db
        self.requirename_db    = rpmdb.requirename_db
        self.requireversion_db = rpmdb.requireversion_db
        self.sha1header_db     = rpmdb.sha1header_db
        self.sigmd5_db         = rpmdb.sigmd5_db
        self.triggername_db    = rpmdb.triggername_db

        self.obsoletes_list = rpmdb.obsoletes_list

        self.deleted = {}

        self.path = rpmdb.path
        self.tags = rpmdb.tags

    def __contains__(self, pkg):
        return hasattr(pkg, "db") and pkg.db is self.rpmdb and \
               self.getPkgById(pkg.key) is pkg

    def getPkgById(self, id):
        pkg = self.rpmdb.getPkgById(id)
        if pkg in self.deleted:
            return None
        else:
            return pkg
    
    def addPkg(self, pkg):
        if (hasattr(pkg, 'key') and
            self._pkgs.has_key(pkg.key) and
            self._pkgs[pkg.key] is pkg):
            if pkg not in self.deleted:
                return self.ALREADY_INSTALLED
            else:
                self.deleted[pkg] = None
                return self.OK
        else:
            return NOT_DELETED

    def removePkg(self, pkg):
        if (hasattr(pkg, 'key') and
            self._pkgs.has_key(pkg.key) and
            self._pkgs[pkg.key] is pkg):
            if pkg not in self.deleted:
                self.deleted[pkg] = None
                return self.OK
            else:
                return self.NOT_INSTALLED
        else:
            return self.NOT_INSTALLED

    def _readObsoletes(self):
        self.rpmdb._readObsoletes()
        self.obsoletes_list = self.rpmdb.obsoletes_list # shared instance

class RpmShadowDB(jointdb.JointDB):

    def __init__(self, rpmdb):
        jointdb.JointDB.__init__(self, rpmdb.config, rpmdb.source,
                                 rpmdb.buildroot)
        self.memorydb = memorydb.RpmMemoryDB(rpmdb.config, rpmdb.source,
                                             rpmdb.buildroot)
        self.diskdb = RpmDiskShadowDB(rpmdb)
        self.dbs.append(self.memorydb)
        self.dbs.append(self.diskdb)

    def addPkg(self, pkg):
        result = self.OK
        index = range(len(self.dbs))
        index.reverse()
        for idx in index:
            result = self.dbs[idx].addPkg(pkg)
            if result == self.OK:
                return result
        return result

    def removePkg(self, pkg):
        for db in self.dbs:
            result = db.removePkg(pkg)
            if result == self.OK:
                return result
        return result

    def load_into_ram(self):
        if len(self.dbs) == 1: return
        self.memorydb.addPkgs(self.diskdb.getPkgs())
        del self.dbs[1]
