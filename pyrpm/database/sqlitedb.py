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


import sqlite, os, os.path, string
from types import TupleType
from binascii import b2a_hex, a2b_hex

import memorydb, pyrpm.package
from pyrpm.base import rpmtag, RPM_BIN, RPM_INT8, RPM_INT16, RPM_INT32, RPM_INT64


class RpmSQLiteDB(memorydb.RpmMemoryDB):
    """RPM database storage in an SQLite database."""

    # Tags stored in the Packages table
    pkgnames = ["name", "epoch", "version", "release", "arch", "prein", "preinprog", "postin", "postinprog", "preun", "preunprog", "postun", "postunprog", "verifyscript", "verifyscriptprog", "url", "license", "rpmversion", "sourcerpm", "optflags", "sourcepkgid", "buildtime", "buildhost", "cookie", "size", "distribution", "vendor", "packager", "os", "payloadformat", "payloadcompressor", "payloadflags", "rhnplatform", "platform", "capability", "xpm", "gif", "verifyscript2", "disturl"]
    # Tags stored in separate tables
    tagnames = ["providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex", "i18ntable", "summary", "description", "changelogtime", "changelogname", "changelogtext", "prefixes", "pubkeys", "group", "dirindexes", "dirnames", "basenames", "fileusername", "filegroupname", "filemodes", "filemtimes", "filedevices", "fileinodes", "filesizes", "filemd5s", "filerdevs", "filelinktos", "fileflags", "fileverifyflags", "fileclass", "filelangs", "filecolors", "filedependsx", "filedependsn", "classdict", "dependsdict", "policies", "filecontexts", "oldfilenames"]
    def __init__(self, config, source, buildroot=None):
        memorydb.RpmMemoryDB.__init__(self, config, source, buildroot)
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
            pkg = pyrpm.package.RpmPackage(self.config, "dummy")
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
            memorydb.RpmMemoryDB.addPkg(self, pkg)
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
        if not self.cx:
            return 0

        memorydb.RpmMemoryDB.addPkg(self, pkg)

        if nowrite:
            return 1

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
            memorydb.RpmMemoryDB.removePkg(self, pkg)
            return 0
        return 1

    def erasePkg(self, pkg, nowrite=None):
        if not self.cx:
            return 0

	memorydb.RpmMemoryDB.removePkg(self, pkg)

        if nowrite:
            return 1

        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        cu.execute("delete from Packages where rowid=%d", (pkg["install_id"],))
        for tag in self.tagnames:
            cu.execute("delete from %s where id=%d", (tag, pkg["install_id"]))
        try:
            cu.execute("commit")
        except:
            memorydb.RpmMemoryDB.addPkg(self, pkg)
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

# vim:ts=4:sw=4:showmatch:expandtab
