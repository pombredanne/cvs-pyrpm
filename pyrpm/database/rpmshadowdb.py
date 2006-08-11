import rpmdb, memorydb, jointdb

NOT_DELETED = -5

class RpmDiskDB(rpmdb.RpmDB):

    def addPkg(self, pkg):
        if self._pkgs.has_key(pkg["install_id"]):
            if self._pkgs[pkg["install_id"]] is not None:
                return self.ALREADY_INSTALLED
            else:
                # XXX really from this db?
                self._pkgs[pkg["install_id"]] = pkg
                return self.OK
        else:
            return NOT_DELETED

    def removePkg(self, pkg):
        if self._pkgs.has_key(pkg["install_id"]):
            if self._pkgs[pkg["install_id"]] is pkg:
                self._pkgs[pkg.key] = None
                return self.OK
            else:
                return self.NOT_INSTALLED
        else:
            # reject without testing???
            # check for equal pkgs
            #for p in self.getPkgsByName(pkg["name"]):
            #    if p.isEqual(pkg):
            #        self._pkgs[p.key] = None
            #        return self.OK
            return self.NOT_INSTALLED


class RpmShadowDB(jointdb.JointDB):

    def __init__(self, config, source, buildroot=None):
        jointdb.JointDB.__init__(self, config, source, buildroot)
        self.memorydb = memorydb.RpmMemoryDB(config, source, buildroot)
        self.diskdb = RpmDiskDB(config, source, buildroot)
        self.diskdb.open()
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
        self.diskdb.close()
