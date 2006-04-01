#!/usr/bin/python
#
# (c) 2005 Red Hat, Inc.
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
# Copyright 2004, 2005 Red Hat, Inc.
#
# AUTHOR: Thomas Woerner <twoerner@redhat.com>
#

import os, sys, md5, stat, tempfile, gzip, bz2, struct, getopt
from time import time
import pyrpm


class CPIO:
    def __init__(self, fd):
        self.fd = fd
        self.EOF = 0

    def _readPadding(self, size):
        # skip padding
        l = 4 - (size % 4) % 4
        d = self.fd.read(l)
        if len(d) != l:
            raise IOError, "Short read"
        return d

    def readHeader(self):
        if self.EOF:
            return None
        
        hdr_data = self.fd.read(110)
        if len(hdr_data) != 110:
            raise IOError, "Short read"

        magic = hdr_data[0:6]    # magic: 6 bytes
        # CPIO ASCII hex, expanded device numbers (070702 with CRC)
        if magic not in ["070701", "070702"]:
            raise IOError, "Bad magic '%s' reading CPIO headers" % magic
        # Read filename and padding.

        inode = int(hdr_data[6:14], 16)    # inode: 8 bytes
        mode = int(hdr_data[14:22], 16)    # mode: 8 bytes
        uid = int(hdr_data[22:30], 16)    # uid: 8 bytes
        gid = int(hdr_data[30:38], 16)    # gid: 8 bytes
        nlink = int(hdr_data[38:46], 16)    # nlink: 8 bytes
        mtime = int(hdr_data[46:54], 16)    # mtime: 8 bytes
        filesize = int(hdr_data[54:62], 16)    # filesize: 8 bytes
        dev_major = int(hdr_data[62:70], 16)    # devMajor: 8 bytes
        dev_minor = int(hdr_data[70:78], 16)    # devMinor: 8 bytes
        rdev_major = int(hdr_data[78:86], 16)    # rdevMajor: 8 bytes
        rdev_minor = int(hdr_data[86:94], 16)    # rdevMinor: 8 bytes
        filenamesize = int(hdr_data[94:102], 16)    # namesize: 8 bytes
        crc = int(hdr_data[102:110], 16)    # crc: 8 bytes

        filename = self.fd.read(filenamesize-1)
        if len(filename) != filenamesize-1:
            raise IOError, "Short read"        

        # filename padding
        self._readPadding(110 + filenamesize)

        if filename == "TRAILER!!!":
            self.EOF = 1

        return (magic, inode, mode, uid, gid, nlink, mtime, filesize,
                dev_major, dev_minor, rdev_major, rdev_minor, filename)
        
    def readData(self, target_fd, filesize):
        if self.EOF:
            return None
        
        # write data
        while i < filesize:
            _data = fd.read(65536)
            if len(_data) == 0:
                print "Error: Source truncated, got %d of %d bytes." % \
                      (i, filesize)
                sys.exit(0)
            if target_fd:
                target_fd.write(data)
            i += len(_data)

        self._readPadding(filesize)

    def read(self, target_fd):
        if self.EOF:
            return None
        
        (magic, inode, mode, uid, gid, nlink, mtime, filesize, dev_major,
         dev_minor, rdev_major, rdev_minor, filename) = self.readHeader(fd)

        self.readData(target_fd, filesize)

        return (magic, inode, mode, uid, gid, nlink, mtime, filesize,
                dev_major, dev_minor, rdev_major, rdev_minor, filename, data)

    def _writePadding(self, size):
        # write padding
        for i in xrange((4 - (size % 4)) % 4):
            self.fd.write("%c" % 0)

    def writeHeader(self, magic, inode, mode, uid, gid, nlink, mtime, filesize,
                    dev_major, dev_minor, rdev_major, rdev_minor, filename):
        self.fd.write(magic)  # magic: 6 bytes
        self.fd.write("%08x" % inode)    # inode: 8 bytes
        self.fd.write("%08x" % mode)    # mode: 8 bytes
        self.fd.write("%08x" % uid)    # uid: 8 bytes
        self.fd.write("%08x" % gid)    # gid: 8 bytes
        self.fd.write("%08x" % nlink)    # nlink: 8 bytes
        self.fd.write("%08x" % mtime)    # mtime: 8 bytes
        self.fd.write("%08x" % filesize)    # filesize: 8 bytes
        self.fd.write("%08x" % dev_major)    # devMajor: 8 bytes
        self.fd.write("%08x" % dev_minor)    # devMinor: 8 bytes
        self.fd.write("%08x" % rdev_major)    # rdevMajor: 8 bytes
        self.fd.write("%08x" % rdev_minor)    # rdevMinor: 8 bytes

        self.fd.write("%08x" % (len(filename)+1))    # namesize: 8 bytes
        self.fd.write("%08x" % 0) # crc

        self.fd.write(filename)    # filename
        self.fd.write("%c" % 0)    # add terminating \0
        # filename padding
        self._writePadding(110 + len(filename) + 1)

    def writeData(self, source_fd, filesize):
        if source_fd:
            i = 0
            while i < filesize:
                data = source_fd.read(65536)
                if len(data) == 0:
                    print "Error: Source is truncated, got %d of %d bytes." % \
                          (i, filesize)
                    sys.exit(0)
                self.fd.write(data)
                i += len(data)
        else:
            for i in xrange(filesize):
                self.fd.write("%c" % 0)

        # data padding
        self._writePadding(filesize)

    def write(self, magic, inode, mode, uid, gid, nlink, mtime, filesize,
              dev_major, dev_minor, rdev_major, rdev_minor, filename,
              source_fd):
        # write header
        self.writeHeader(magic, inode, mode, uid, gid, nlink, mtime,
                         filesize, dev_major, dev_minor, rdev_major,
                         rdev_minor, filename)

        self.writeData(source_fd, filesize)

### CPIOFile class ###

class CPIOFile(CPIO):
    def __init__(self, filename, mode):
        self.open(filename, mode)

    def open(self, filename, mode):
        self.filename = filename
        self.fd = open(filename, mode)

    def close(self):
        if self.fd:
            self.fd.close()
            self.fd = -1

### RpmPackage class ###

class RpmPackage(dict):
    """
    name       : string: NEVRA
    header     : header filename
    cpio       : cpio filename
    """

    __getitem__ = dict.get

    def __init__(self, config, filename):
        dict.__init__(self)
        self.config = config
        self["filename"] = filename

    def load(self):
        pass
    
    def save(self):
        name = "%s/%s" % (os.getcwd(), self["filename"])
        pkg = pyrpm.RpmPackage(self.config, "file://%s" % self["hdr"])
        pkg.read()
        apkg = pyrpm.getRpmIOFactory(self.config, name)
        try:
            apkg.write(pkg)
            apkg.close()
        except IOError:
            print "Could not write package header"
            return None
        pkg.close()

        target_fd = open(name, "ab")
#        print "tell=%d" % target_fd.tell()

        gz_cpio = gzipFile(self["cpio"])
        gz_cpio_size = os.stat(gz_cpio).st_size
        fd = open(gz_cpio, "rb")
        size = 0
        while size < gz_cpio_size:
            if gz_cpio_size - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(gz_cpio_size - size)
#            if size == 0:
#                tmp_data = data[12:]
#                data = struct.pack("!cccccccccccc",
#                                   '\x1F', '\x8B', '\x08', '\x00',
#                                   '\x00', '\x00', '\x00', '\x00',
#                                   '\x00', '\x03', '\xD4', '\xBD')
#                data += tmp_data
            target_fd.write(data)
            size += len(data)
        fd.close()

        target_fd.close()

### RpmDeltaPackage class ###

class RpmDeltaPackage(dict):
    """
    FILE FORMAT
    -----------

    +-------+---------+---------+-------------+-
    | magic | version | release | compression | 
    |       |         |         |             | 
    +-------+---------+---------+-------------+-
    | 4B    | 4B      | 4B      | 2B          | 
    +-------+---------+---------+-------------+-

    -+------+--------+----+------+--------+----+------+--------+----+-
     | size : source : pa | size : source : pa | size : target : pa | 
     |      : NEVRA  : dd |      : sha1   : dd |      : NEVRA  : dd | 
    -+------+        : in +------+        : in +------+        : in +-
     | 4B   :        : g  | 4B   :        : g  | 4B   :        : g  | 
    -+------+--------+----+------+--------+----+------+--------+----+-
    
    -+-------+---------------+--------------+----+--------------+
     | delta | target header | cpio delta   : pa | target pkg   |
     | size  | size          | (compressed) : dd | header       |
     +-------+---------------+              : in | (compressed) |
     | 8B    | 8B            |              : g  |              |
    -+-------+---------------+--------------+----+--------------+

    Magic       : 0xedabf000
    Version     : 0x00000001   version: 1
    Release     : 0x00000000   release: 0
    Compression : 0x0001       compression: gzip
                  0x0002       compression: bzip2
                  0x0100       diff utility: edelta
                  0x0200       diff utility: bsdiff
                  0x0400       diff utility: bdelta

    PACKAGE USAGE
    -------------

    Dictionary:
    filename    : filename
    source_hdr  : source header filename (uncompressed data)
    target_hdr  : target header filename (uncompressed)
    delta       : delta filename (uncompressed data)

    """
    MAGIC  = '\xed\xab\xf0\x00'

    __getitem__ = dict.get

    def __init__(self, config, filename):
        dict.__init__(self)
        self.config = config
        self["version"] = 1
        self["release"] = 0
        self["compression"] = 0x0401
        self["filename"] = filename
        
    def load(self):
        self.fd = open(self["filename"], "r")

        data = pyrpm.readExact(self.fd, 14)
        (magic, version, release, compression) = struct.unpack("!4sIIH", data)

        if magic != self.MAGIC:
            raise ValueError, "wrong magic"

        if version != 1 or release != 0:
            raise ValueError, "unsupported version %d.%d" % (version, release)
        self["version"] = version
        self["release"] = release

        if not compression & 0x0001 and not compression & 0x0002:
            raise ValueError, "unsupported compression %s" % compression
        if not compression & 0x0100 and not compression & 0x0200 \
               and not compression & 0x0400:
            raise ValueError, "unsupported diff utility"
        self["compression"] = compression

        
        data = pyrpm.readExact(self.fd, 4)
        size = struct.unpack("!I", data)[0]
        self["source_nevra"] = pyrpm.readExact(self.fd, size-1)
        pyrpm.readExact(self.fd, 1)
#        print "'%s'" % self["source_nevra"]
        self._readPadding(size)

        data = pyrpm.readExact(self.fd, 4)
        size = struct.unpack("!I", data)[0]
        self["source_sha1"] = pyrpm.readExact(self.fd, size-1)
        pyrpm.readExact(self.fd, 1)
#        print self["source_sha1"]
        self._readPadding(size)

        data = pyrpm.readExact(self.fd, 4)
        size = struct.unpack("!I", data)[0]
        self["target_nevra"] = pyrpm.readExact(self.fd, size-1)
        pyrpm.readExact(self.fd, 1)
#        print "'%s'" % self["target_nevra"]
        self._readPadding(size)

        data = pyrpm.readExact(self.fd, 8)
        self["delta_size"] = struct.unpack("!Q", data)[0]
#        print self["delta_size"]
        
        data = pyrpm.readExact(self.fd, 8)
        self["target_header_size"] = struct.unpack("!Q", data)[0]
#        print self["target_header_size"]


        # read delta
        name = "%s/edelta" % (self.config.tempdir)
        self["delta"] = name
        target_fd = open(name, "w")
        if self["compression"] & 0x0001: #gzip
            fd = gzip.GzipFile(fileobj=self.fd)
        elif self["compression"] & 0x0002: #bzip2
            fd = BZIP2(fileobj=self.fd)

        size = 0
        tell = self.fd.tell()
        if self["delta_size"] >= 65536:
            data = fd.read(65536)
        else:
            data = fd.read(self["delta_size"] - size)
        while size < self["delta_size"]:
            size += len(data)
            target_fd.write(data)
            if self["delta_size"] - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(self["delta_size"] - size)
        target_fd.close()

        self._readPadding(self.fd.tell() - tell)
        
        # read target_hdr
        name = "%s/hdr_%s" % (self.config.tempdir, self["target_nevra"])
        self["target_hdr"] = name
        target_fd = open(name, "w")
        if self["compression"] & 0x0001: #gzip
            fd = gzip.GzipFile(fileobj=self.fd)
        elif self["compression"] & 0x0002: #bzip2
            fd = BZIP2(fileobj=self.fd)

        size = 0
        tell = self.fd.tell()
        if self["target_header_size"] >= 65536:
            data = fd.read(65536)
        else:
            data = fd.read(self["target_header_size"] - size)
        while size < self["target_header_size"]:
            size += len(data)
            target_fd.write(data)
            if self["target_header_size"] - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(self["target_header_size"] - size)
        target_fd.close()
        self._readPadding(self.fd.tell() - tell)

    def save(self, compression=None):
        if compression:
            self["compression"] = compression

        self.fd = open(self["filename"], "w")
#        print "writing %s" % self["filename"]
        
        self.fd.write(self.MAGIC)
        self.fd.write(struct.pack("!II", self["version"], self["release"]))
        self.fd.write(struct.pack("!H", self["compression"]))

        self.fd.write(struct.pack("!I", len(self["source_nevra"])+1))
        self.fd.write(self["source_nevra"])
        self.fd.write("%c" % 0) # add terminating \0
        self._writePadding(len(self["source_nevra"])+1)

        self.fd.write(struct.pack("!I", len(self["source_sha1"])+1))
        self.fd.write(self["source_sha1"])
        self.fd.write("%c" % 0) # add terminating \0
        self._writePadding(len(self["source_sha1"])+1)

        self.fd.write(struct.pack("!I", len(self["target_nevra"])+1))
        self.fd.write(self["target_nevra"])
        self.fd.write("%c" % 0) # add terminating \0
        self._writePadding(len(self["target_nevra"])+1)

        if self["compression"] & 0x0001:
            gz_delta = gzipFile(self["delta"])
        elif self["compression"] & 0x0002:
            gz_delta = bzip2File(self["delta"])
        gz_delta_size = os.stat(gz_delta).st_size
        self.fd.write(struct.pack("!Q", os.stat(self["delta"]).st_size))

        if self["compression"] & 0x0001:
            gz_hdr = gzipFile(self["target_hdr"])
        elif self["compression"] & 0x0002:
            gz_hdr = bzip2File(self["target_hdr"])
        gz_hdr_size = os.stat(gz_hdr).st_size
        self.fd.write(struct.pack("!Q", os.stat(self["target_hdr"]).st_size))

        fd = open(gz_delta, "r")
        size = 0
        while size < gz_delta_size:
            if gz_delta_size - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(gz_delta_size - size)
            self.fd.write(data)
            size += len(data)
        fd.close()
        self._writePadding(gz_delta_size)
        
        fd = open(gz_hdr, "r")
        size = 0
        while size < gz_hdr_size:
            if gz_hdr_size - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(gz_hdr_size - size)
            self.fd.write(data)
            size += len(data)
        fd.close()

        self.fd.close()
        
    def _readPadding(self, size):
        # skip padding
        for i in xrange((4 - (size % 4)) % 4):
            self.fd.read(1)

    def _writePadding(self, size):
        # write padding
        for i in xrange((4 - (size % 4)) % 4):
            self.fd.write("%c" % 0)

### RpmDelta class ###

class RpmDelta:
    def __init__(self, config, compression=None, verify=0):
        self.config = config
        self.tmpdir = self.config.tmpdir
        self.compression = 0x0401 # bdelta, gzip
        if compression:
            self.compression = compression
        self.verify = verify
        
    def apply(self, source_pkg, delta_pkg):
        # target_pkg = RpmPackage()
        # return target_pkg

        self.compression = delta_pkg["compression"]

        if source_pkg.getNEVRA() != delta_pkg["source_nevra"]:
            raise ValueError, "'%s' does not match '%s'" % \
                  (source_pkg.getNEVRA(), delta_pkg["source_nevra"])

        if source_pkg["signature"]["sha1header"] != delta_pkg["source_sha1"]:
            raise ValueError, "sha1 sum does not match"

        source_cpio = self.createCPIO(source_pkg)
        if source_cpio == None:
            print "Failed to generate CPIO from source package."
            return None

        target_cpio = self.applyDelta(source_cpio.filename, delta_pkg["delta"])
        if target_cpio == None:
            print "Failed to apply delta to source CPIO."
            return None

        # TODO: create package
        pkg = RpmPackage(self.config, "%s.rpm" % delta_pkg["target_nevra"])
        pkg["nevra"] = delta_pkg["target_nevra"]
        pkg["hdr"] = delta_pkg["target_hdr"]
        pkg["cpio"] = target_cpio

        return pkg    

    def create(self, source_pkg, target_pkg):
        if source_pkg["name"] != target_pkg["name"]:
            raise ValueError, \
                  "Source name '%s' does not match target name '%s'" % \
                  (source_pkg["name"],target_pkg["name"])

#        if source_pkg["installtid"] or 
        if target_pkg["installtid"]:
            raise ValueError, "Unable to create delta from installed packages"

        source_cpio = self.createCPIO(source_pkg)
        if source_cpio == None:
            print "Failed to generate CPIO from source package."
            return None

        target_cpio = self.getCPIO(target_pkg)
        if target_cpio == None:
            print "Failed to get CPIO from target package."
            return None
        
        delta = self.createDelta(source_cpio.filename, target_cpio.filename)
        if delta == None:
            print "Failed to generate delta."
            return None

        if self.verify:
            applied = self.applyDelta(source_cpio.filename, delta)
            s1 = os.stat(target_cpio.filename).st_size
            s2 = os.stat(applied).st_size
            if s1 != s2:
                raise Exception, "verify failed"
            stat = os.system("diff -q '%s' '%s'" % \
                             (target_cpio.filename, applied))
            if stat != 0:
                raise Exception, "verify failed"

        delta_pkg = RpmDeltaPackage(self.config,
                                    "%s.drpm" % target_pkg.getNEVRA())
        delta_pkg["name"] = target_pkg.getNEVRA()
        delta_pkg["source_nevra"] = source_pkg.getNEVRA()
        delta_pkg["source_sha1"] = source_pkg["signature"]["sha1header"]
        delta_pkg["target_nevra"] = target_pkg.getNEVRA()
        delta_pkg["target_hdr"] = self.getHdr(target_pkg)
        delta_pkg["delta"] = delta

        # TODO
        return delta_pkg

    def createCPIO(self, pkg):
        is_installed = 1
        if not pkg["installtid"]:
            is_installed = 0

            # write out temporary cpio (for seeks)
            source_name = tempfile.mktemp(prefix="createcpio_",
                                          dir=self.config.tempdir)
            _cpio = CPIOFile(source_name, "w")
            cpio_hash = { }
            for filename in pkg["filenames"]:
                fi = pkg.getRpmFileInfo(filename)
                if fi.flags & pyrpm.RPMFILE_GHOST:
                    continue
                (fname, cpio_fd, fsize) = pkg.io.read()
                cpio_hash[".%s" % fname] = _cpio.fd.tell()
                if self.config.verbose > 0:
                    print " %s\t%s\t offset:%d" % (fsize, fname, 
                                                   cpio_hash[".%s" % fname])
                _cpio.write("070701", 0, 0, 0, 0, 0, 0, fsize, 0, 0, 0, 0,
                           ".%s" % fname, cpio_fd)
            _cpio.write("070701", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                        "TRAILER!!!", 0)
            _cpio.close()
            source_fd = open(source_name, "r")
            source_cpio = pyrpm.CPIOFile(source_fd)

        hardlinks = { }
        last_hardlink = { }
        # generate hardlink hash
        for filename in pkg["filenames"]:
            fi = pkg.getRpmFileInfo(filename)
            hlid = fi.getHardLinkID()
            if not hardlinks.has_key(hlid):
                hardlinks[hlid] = [ ]
            hardlinks[hlid].append(filename)
        for filename in pkg["filenames"]:
            fi = pkg.getRpmFileInfo(filename)
            hlid = fi.getHardLinkID()
            if hardlinks.has_key(hlid):
                if len(hardlinks[hlid]) == 1:
                    # only one entry: no hardlink
                    del hardlinks[hlid]
                elif len(hardlinks[hlid]) > 1:
                    last_hardlink[hlid] = filename

        cpio_name = "%s/createcpio_%s" % (self.config.tempdir, pkg.getNEVRA())
        cpio = CPIOFile(cpio_name, "w")

        for filename in pkg["filenames"]:
            fi = pkg.getRpmFileInfo(filename)

            if fi.flags & pyrpm.RPMFILE_GHOST:
                continue

            if fi.flags & pyrpm.RPMFILE_CONFIG:
                # no config files
                is_config = 1
                if self.config.verbose > 0:
                    print "%s\t%s\t [config]" % (fi.filesize, filename)
            else:
                is_config = 0
                if self.config.verbose > 0:
                    print "%s\t%s" % (fi.filesize, filename)

            hlid = fi.getHardLinkID()

            fd2 = 0
            is_prelinked = 0
            if is_installed == 1:
                if stat.S_ISREG(fi.mode) and not stat.S_ISLNK(fi.mode):
                    if not is_config:
                        try:
                            fd2 = open(filename, "r")
                        except Exception, msg:
                            print msg
                            print "Error: Could not open file %s" % filename
                            return None
                        fsize = os.stat(filename).st_size

                        if hardlinks.has_key(hlid) and \
                               last_hardlink.has_key(hlid) and \
                               last_hardlink[hlid] != filename:
                            fsize = 0
                            fi.filesize = 0
                        if fi.filesize == 0:
                            fsize = 0

                        # prelinked? TODO: compare md5
                        if fi.filesize != fsize:
                            if self.config.verbose > 0:
                                print "Unprelinking %s" % filename
                            fname = "%s/base/%s" % (self.config.tempdir,
                                                    os.path.basename(filename))
                            os.system("prelink -u -o %s %s" % (fname,
                                                               filename))
                            fsize2 = os.stat(fname).st_size
                            if fsize2 != fi.filesize:
                                print "Error: File %s is modified" % filename
                                return None
                            is_prelinked = 1
                            fsize = fsize2
                            fd2.close()
                            try:
                                fd2 = open(fname, "r")
                            except Exception, msg:
                                print msg
                                print "Error: Could not open file %s" % fname
                                return None
                    else:
                        fsize = 0 #fi.filesize
                else:
                    fsize = 0
                if self.config.verbose > 0:
                    print " %s\t%s\t" % (fsize, filename)
            else:
                fd2 = source_cpio
                fd2.fd.seek(cpio_hash[".%s" % filename], 0)
                source_cpio.lastfilesize = 0
                (name, size) = source_cpio.getNextEntry()
                if hardlinks.has_key(hlid) and len(hardlinks[hlid]) > 1:
                    fname = ""
                    if filename != last_hardlink[hlid] and size != 0:
                        fname = last_hardlink[hlid]
                        fd2 = source_cpio
                        fd2.fd.seek(cpio_hash[".%s" % fname], 0)
                        source_cpio.lastfilesize = 0
                        (name, size) = source_cpio.getNextEntry()
                    if filename == last_hardlink[hlid] and size == 0:
                        for fname in hardlinks[hlid]:
                            fd2 = source_cpio
                            fd2.fd.seek(cpio_hash[".%s" % fname], 0)
                            source_cpio.lastfilesize = 0
                            (name, size) = source_cpio.getNextEntry()
                            if size != 0:
                                bCPIOFilereak
                fsize = size
                if stat.S_ISLNK(fi.mode) or stat.S_ISDIR(fi.mode):
                    fsize = 0

            if is_config:
                src_fd = 0
                fsize = 0
            else:
                src_fd = fd2

            cpio.write("070701", 0, 0, 0, 0, 0, 0, fsize, 0, 0, 0, 0,
                       ".%s" % filename, src_fd)

            if is_installed and stat.S_ISREG(fi.mode) and not is_config:
                fd2.close()
                if is_prelinked:
                    os.system("rm /tmp/%s" % os.path.basename(filename))

        # write trailer
        cpio.write("070701", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "TRAILER!!!", 0)

        if not is_installed:
            source_fd.close()

        return cpio

    def getCPIO(self, pkg):
        # TODO: rewind pkg and reread header to get to the correct position?

        tell = pkg.io.fd.tell()

        fd = pyrpm.PyGZIP(pkg.io.fd)

        cpio_name = "%s/getcpio_%s" % (self.config.tempdir, pkg.getNEVRA())

        payloadsize = pkg['signature']['payloadsize'][0]
        cpio_fd = open(cpio_name, "w")
        size = 0
        if payloadsize - size > 65536:
            data = fd.read(65536)
        else:
            data = fd.read(payloadsize - size)
        while size < payloadsize:
            size += len(data)
            cpio_fd.write(data)
            if payloadsize - size > 65536:
                data = fd.read(65536)
            else:
                data = fd.read(payloadsize - size)
        cpio_fd.close()

        pkg.io.fd.seek(tell, 0)

        cpio = CPIOFile(cpio_name, "r")

        return cpio

    def getHdr(self, pkg):
        hdr_name = "%s/hdr_%s" % (self.config.tempdir, pkg.getNEVRA())
        apkg = pyrpm.getRpmIOFactory(self.config, "file://%s" % hdr_name)
        try:
            apkg.write(pkg)
            apkg.close()
        except IOError:
            return None
        
        return hdr_name

    def createDelta(self, source_cpio, target_cpio):
        if self.compression & 0x0100:
            delta_name = "%s/edelta" % self.config.tempdir
            cmd = "edelta delta %s %s %s" % \
                  (source_cpio, target_cpio, delta_name)
        elif self.compression & 0x0200:
            delta_name = "%s/bsdiff" % self.config.tempdir
            cmd = "bsdiff %s %s %s" % (source_cpio, target_cpio, delta_name)
        elif self.compression & 0x0400:
            delta_name = "%s/bdelta" % self.config.tempdir
            cmd = "bdelta %s %s %s" % (source_cpio, target_cpio, delta_name)
#        print(cmd)
        os.system(cmd)
        return delta_name

    def applyDelta(self, source_cpio, delta):
        cpio_name = "%s/patched_cpio" % self.config.tempdir
        if self.compression & 0x0100:
            cmd = "edelta patch %s %s %s" % (source_cpio, delta, cpio_name)
        elif self.compression & 0x0200:
            cmd = "bspatch %s %s %s" % (source_cpio, cpio_name, delta)
        elif self.compression & 0x0400:
            cmd = "bpatch %s %s %s" % (source_cpio, cpio_name, delta)
#        print cmd
        os.system(cmd)
        return cpio_name

### functions ###

def gunzipFile(file):
    if not file.endswith(".gz"):
        raise Exception, "%s: no gz extension." % file

    source_fd = gzip.GzipFile(file, "rb")

    target_name = file[:-3]
    target_fd = open(target_name, "w")

    data = source_fd.read(65537)
    while data and len(data) > 0:
        target_fd.write(data)
        data = source_fd.read(65537)

    target_fd.flush()
    target_fd.close()

    source_fd.close()

    return target_name

def EXT_gzipFile(file):
    target_name = "%s.gz" % file

    os.system("gzip --best -nc '%s' > '%s'" % (file, target_name))
#    os.system("minigzip '%s'" % (file))
#    os.system("gzip -dc '%s' > '%s'" % (target_name, file))
    
    return target_name

def gzipFile(file):
    # TODO: -n flag
    source_fd = open(file, "r")

    target_name = "%s.gz" % file
    fd = open(target_name, "wb")
    target_fd = gzip.GzipFile(filename="", mode="wbn", fileobj=fd, compresslevel=9)

    data = source_fd.read(65536)
    while data:
        target_fd.write(data)
        data = source_fd.read(65536)

    target_fd.flush()
    target_fd.close()
    fd.close()

    source_fd.close()

    return target_name

def bunzip2File(file):
    if not file.endswith(".bz2"):
        raise Exception, "%s: no bz2 extension." % file

    source_fd = bz2.BZ2File(file, "r")

    target_name = file[:-4]
    target_fd = open(target_name, "w")

    data = source_fd.read(65536)
    while data:
        target_fd.write(data)
        data = source_fd.read(65536)

    target_fd.flush()
    target_fd.close()

    source_fd.close()

    return target_name

def bzip2File(file):
    source_fd = open(file, "r")

    target_name = "%s.bz2" % file
    target_fd = bz2.BZ2File(target_name, "w", 0, 9)

    data = source_fd.read(65536)
    while data:
        target_fd.write(data)
        data = source_fd.read(65536)

    target_fd.close()

    source_fd.close()

    return target_name

def openRPM(name):
    if os.path.isfile(name):
        # read package
        pkg = pyrpm.RpmPackage(pyrpm.rpmconfig, name)
        try:
            pkg.read()
        except Exception, msg:
            print "Loading of %s failed, ignoring." % name
            return None
    else:
        # installed package
        db = pyrpm.getRpmDBFactory(pyrpm.rpmconfig, pyrpm.rpmconfig.dbpath,
                                   pyrpm.rpmconfig.buildroot)
        db.open()
        if not db.read():
            raiseFatal("Couldn't read database")
        pkgs = pyrpm.findPkgByName(name, db.getPkgList())
        del db
        if len(pkgs) > 1:
            print "Error: name %s is not unique" % name
            None
        elif len(pkgs) == 0:
            print "Error: %s is not installed" % name
            None
        pkg = pkgs[0]

    return pkg

def openDelta(name):
    if not os.path.isfile(name):
        print "Could not find file %s." % name
        sys.exit(-1)
    pkg = RpmDeltaPackage(pyrpm.rpmconfig, name)
    try:
        pkg.load()
    except Exception, msg:
        print msg
        print "Loading of %s failed, ignoring." % name
        return None
    return pkg

def rm_rf(name):
    if not os.path.exists(name) or not os.path.isdir(name):
        return
    list = os.listdir(name)
    for file in list:
        if os.path.isdir(file):
            rm_rf(name+"/"+file)
        else:
            os.unlink(name+"/"+file)
    os.rmdir(name)

def usage():
    print """Usage: delta <options> <operation>

OPERATIONS
  create <from rpm package> <to rpm package>
  apply <from rpm package> <delta package>
  info <delta package>

GENERAL OPTIONS
  -h  | --help       print help
  -v  | --verbose    be verbose, and more, ..
  -q  | --quiet      be quiet
  -V  | --verify     verify created delta package

COMPRESSION OPTIONS
        --gzip       gzip compression
        --bzip2      bzip2 compression

DELTA OPTIONS
        --bsdiff     bsdiff delta (http://www.daemonology.net/bsdiff/)
        --edelta     edelta delta (http://www.diku.dk/~jacobg/edelta/)
        --bdelta     bdelta delta (http://sourceforge.net/projects/deltup)

Default options:
  --gzip --bdelta
"""

### main ###

quiet = 0
compression = 0x0401
verify = 0

(opts, args) = getopt.getopt(sys.argv[1:], "hvqV",
                             ["help", "verbose", "quiet", "verify",
                              "gzip", "bzip2", "bsdiff", "edelta", "bdelta"])
for (opt, val) in opts:
    if opt in ["-h", "--help"]:
        usage()
        sys.exit(1)
    elif opt in ["-v", "--verbose"]:
        pyrpm.rpmconfig.verbose += 1
    elif opt in ["-V", "--verify"]:
        verify = 1
    elif opt in ["-q", "--quiet"]:
        quiet = 1
        pyrpm.rpmconfig.debug = 0
        pyrpm.rpmconfig.warning = 0
        pyrpm.rpmconfig.verbose = 0
        pyrpm.rpmconfig.printhash = 0
    elif opt == "--gzip":
        compression = (compression & 0xFF00) + 1
    elif opt == "--bzip2":
        compression = (compression & 0xFF00) + 2
    elif opt == "--edelta":
        compression = (compression & 0x00FF) + 0x0100
    elif opt == "--bsdiff":
        compression = (compression & 0x00FF) + 0x0200
    elif opt == "--bdelta":
        compression = (compression & 0x00FF) + 0x0400

if not args or len(args) < 1 or \
       ((args[0] == "create" or args[0] == "apply") and len(args) != 3) or \
       (args[0] == "info" and len(args) != 2):
    usage()
    sys.exit(1)

operation = args[0]

### delta ###

pyrpm.rpmconfig.tempdir = tempfile.mkdtemp(prefix="rpmdelta_")

time1 = time()

rpmdelta = RpmDelta(pyrpm.rpmconfig, compression=compression,
                    verify=verify)

if operation == "create":
    source_name = args[1]
    target_name = args[2]

    source_pkg = openRPM(source_name)
    if not source_pkg:
        sys.exit(-1)
    target_pkg = openRPM(target_name)
    if not target_pkg:
        sys.exit(-1)

    
    delta_pkg = rpmdelta.create(source_pkg, target_pkg)

    if delta_pkg:
        delta_pkg.save(compression)

    delta_name = delta_pkg["filename"]

elif operation == "apply":
    source_name = args[1]
    delta_name = args[2]

    source_pkg = openRPM(source_name)
    if not source_pkg:
        sys.exit(-1)
    delta_pkg = openDelta(delta_name)
    if not delta_pkg:
        sys.exit(-1)
    
    target_pkg = rpmdelta.apply(source_pkg, delta_pkg)

    if target_pkg:
        target_pkg.save()

elif operation == "info":
    delta_name = args[1]
    delta_pkg = openDelta(delta_name)

    if delta_pkg["compression"] & 0x0001: #gzip
        compression = "gzip"
    elif delta_pkg["compression"] & 0x0002: #bzip2
        compression = "bzip2"
    else:
        compression = "- unknown -"
    
    if delta_pkg["compression"] & 0x0100:
        diff_utility = "edelta"
    elif delta_pkg["compression"] & 0x0200:
        diff_utility = "bsdiff"
    elif delta_pkg["compression"] & 0x0400:
        diff_utility = "bdelta"
    else:
        diff_utility = "- unknown -"

    print "%s:" % delta_name
    print "  source package: %s" % delta_pkg["source_nevra"]
    print "  target package: %s" % delta_pkg["target_nevra"]
    print "  version       : %d.%d" % (delta_pkg["version"],
                                       delta_pkg["release"])
    print "  compression   : %s" % compression
    print "  diff utility  : %s" % diff_utility

else:
    print "Error: operation %s is not supported" % operation

time2 = time() - time1

#print "------------------------"
#os.system("ls -la %s" % pyrpm.rpmconfig.tempdir)
#print "------------------------"

if operation == "create":
    delta_size = os.stat(delta_name).st_size
    target_size = os.stat(target_name).st_size
    if pyrpm.rpmconfig.verbose:
        print "%d\t%s" % (delta_size, delta_name)
        print "%d\t%s" % (target_size, target_name)
    if not quiet:
        print "%s:  %.02fs  %.02f%%" % (delta_name, time2, 
                                        100.0 * delta_size / target_size)
elif operation == "apply":
    if not quiet:
        print "%s:  %.02fs" % (target_pkg["filename"], time2)

if pyrpm.rpmconfig.tempdir != None and os.path.exists(pyrpm.rpmconfig.tempdir):
    rm_rf(pyrpm.rpmconfig.tempdir)
    # os.removedirs(pyrpm.rpmconfig.tempdir)
    pyrpm.rpmconfig.tempdir = None

sys.exit(0)
