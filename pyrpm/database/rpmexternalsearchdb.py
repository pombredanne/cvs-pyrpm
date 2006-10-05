from memorydb import RpmMemoryDB

class RpmExternalSearchDB(RpmMemoryDB):
    """MemoryDb that uses an external db for (filename) queries. The external
    DB must not chage and must contain all pkgs that are added to the
    RpmExternalSearchDB. Use
     * with yum.repos as part of the RpmShadowDB
     * with yum.repos for ordering pkgs to be installed
     * with Rpm(Disk)DB for ordering pkgs to be removed
    as external DB."""

    def __init__(self, externaldb, config, source, buildroot=''):
        self.externaldb = externaldb
        RpmMemoryDB.__init__(self, config, source, buildroot)
        self.filecache = {} # filename -> [pkgs], contains all available pkgs

    def _filter(self, result):
        """reduce list of pkgs to the ones contained in this DB"""
        return [pkg for pkg in result if pkg in self]

    def _filterdict(self, d):
        """reduce result dict to pkgs contained n this DB"""
        result = {}
        for pkg, entry in d.iteritems():
            if pkg in self:
                result[pkg] = entry
        return result

     # Commented out for performance issues
#    def searchProvides(self, name, flag, version):
#        return self._filterdict(self.externaldb.searchProvides(
#            name, flag, version))

    def reloadDependencies(self):
        self.filecache.clear()
        RpmMemoryDB.reloadDependencies(self)

    def searchFilenames(self, filename):
        if not self.filecache.has_key(filename):
            self.filecache[filename] = self.externaldb.searchFilenames(
                filename)

        r =  self._filter(self.filecache[filename])
        return r

     # Commented out for performance issues
#    def searchRequires(self, name, flag, version):
#        return self._filterdict(self.externaldb.searchRequires(
#            name, flag, version))

#    def searchConflicts(self, name, flag, version):
#        return self._filterdict(self.externaldb.searchConflicts(
#            name, flag, version))

#    def searchObsoletes(self, name, flag, version):
#        return self._filterdict(self.externaldb.searchObsoletes(
#            name, flag, version))

#    def searchTriggers(self, name, flag, version):
#        return self._filterdict(self.externaldb.searchTriggers(
#            name, flag, version))

#    def searchPkgs(self, names):
#        return self._filterdict(self.externaldb.searchPkgs(
#            name, flag, version))

