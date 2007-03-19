from memorydb import RpmMemoryDB
from pyrpm.hashlist import HashList

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
        self._filerequires = None

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

    def reloadDependencies(self):
        self.filecache.clear()
        RpmMemoryDB.reloadDependencies(self)

    def searchFilenames(self, filename):
        if not self.filecache.has_key(filename):
            self.filecache[filename] = self.externaldb.searchFilenames(
                filename)
        r =  self._filter(self.filecache[filename])
        return r

    if True: # was commented out for performance issues

        def getFileRequires(self):
            if len(self) == 0:
                return []
            if self._filerequires is None:
                self._filerequires = self.externaldb.getPkgsFileRequires()
            result = set()
            for pkg, filenames in self._filerequires.iteritems():
                if pkg in self:
                    for filename in filenames:
                        result.add(filename)
            return list(result)
        
        def searchRequires(self, name, flag, version):
            result = self.externaldb.searchRequires(
                name, flag, version)
            return self._filterdict(result)

    if True:

        def searchProvides(self, name, flag, version):
            result = self.externaldb.searchProvides(
                name, flag, version)
            return self._filterdict(result)

        def searchConflicts(self, name, flag, version):
            result = self.externaldb.searchConflicts(
                name, flag, version)
            return self._filterdict(result)

        #def searchObsoletes(self, name, flag, version):
        #    return self._filterdict(self.externaldb.searchObsoletes(
        #        name, flag, version))

        def searchTriggers(self, name, flag, version):
            return self._filterdict(self.externaldb.searchTriggers(
                name, flag, version))

        def searchPkgs(self, names):
            return self._filter(self.externaldb.searchPkgs(names))

# vim:ts=4:sw=4:showmatch:expandtab

