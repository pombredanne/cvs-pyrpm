#!/usr/bin/python
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
# Copyright 2004 Red Hat, Inc.
#
# Author: Paul Nasrat, Florian La Roche
#

import os, os.path

CP_IFMT  =  0170000
CP_IFIFO =  0010000
CP_IFCHR =  0020000
CP_IFDIR =  0040000
CP_IFBLK =  0060000
CP_IFREG =  0100000
CP_IFNWK =  0110000
CP_IFLNK =  0120000
CP_IFSOCK = 0140000


class CPIOFile:
    """ Read ASCII CPIO files. """

    def __init__(self, data):
        self.filelist = {}              # hash of CPIO headers and stat data
        self.cpiodata = data
#        if isinstance(file, basestring):
#            self.filename = file
#            self.fp = open(file, "rb")
#        else:
#            self.filename = getattr(file, 'name', None)
#            self.fp = file
        self.pos = 0
        self.filename = None
        self.filedata = None
        self.filerawdata = None

    def getNextHeader(self, pos):
        data = self.cpiodata[pos:pos+110]
        pos = pos + 110

        # CPIO ASCII hex, expanded device numbers (070702 with CRC)
        if data[0:6] not in ["070701", "070702"]:
            raise IOError, "Bad magic reading CPIO headers %s" % data[0:6]

        #(magic, inode, mode, uid, gid, nlink, mtime, filesize, devMajor, \
        #    devMinor, rdevMajor, rdevMinor, namesize, checksum)
        filedata = [data[0:6], int(data[6:14], 16), \
            int(data[14:22], 16), int(data[22:30], 16), \
            int(data[30:38], 16), int(data[38:46], 16), \
            int(data[46:54], 16), int(data[54:62], 16), \
            int(data[62:70], 16), int(data[70:78], 16), \
            int(data[78:86], 16), int(data[86:94], 16), \
            int(data[94:102], 16), data[102:110]]

        size = filedata[12]
        filename = self.cpiodata[pos:pos+size].rstrip("\x00")
        pos = pos + size
        fsize = 110 + size
        pos = pos + ((4 - (fsize % 4)) % 4)

        # Detect if we're at the end of the archive
        if filename == "TRAILER!!!":
            return [0, filename, None]

        # Contents
        filesize = filedata[7]
        self.filelist[filename[1:]] = filedata
        return [pos, filename, filedata]
        

    def _read_cpio_headers(self):
        pos = 0
        while 1:
            [pos, filename, filedata] = self.getNextHeader(pos)
            if filename == "TRAILER!!!":
                break

            # Contents
            filesize = filedata[7]
            pos = pos + filesize
            pos = pos + ((4 - (filesize % 4)) % 4)
            self.filelist[filename[1:]] = filedata

    def extractCurrentEntry(self, instroot=None):
        if self.filename == None or self.filedata == None:
            return 0
        if instroot == None:
            instroot = "/"
        if not os.path.isdir(instroot):
            return 0

        filetype = self.filedata[2] & CP_IFMT
        fullname = instroot + self.filename
        if   filetype == CP_IFREG:
            dirname = fullname[:fullname.rfind("/")]
            if not os.path.isdir(dirname):
                os.makedirs(dirname)
            fd = open(fullname, "w")
            fd.write(self.filerawdata)
            fd.close()
        elif filetype == CP_IFDIR:
            if os.path.isdir(fullname):
#                print "directory already exists, skipping..."
                return 1
            os.makedirs(fullname)
        elif filetype == CP_IFLNK:
            symlinkfile = self.filerawdata.rstrip("\x00")
            if os.path.islink(fullname) and os.readlink(fullname) == symlinkfile:
                return 1
            os.symlink(symlinkfile, fullname)
        elif filetype == CP_IFCHR or filetype == CP_IFBLK or filetype == CP_IFSOCK or filetype == CP_IFIFO:
            print "device files not supported yet..."
        else:
            raise ValueErrorm, "%s: not a valid CPIO filetype" % (oct(filetype))
        return 1

    def getCurrentEntry(self):
        return [self.filename, self.filedata, self.filerawdata]

    def getNextEntry(self):
        [self.pos, filename, filedata] = self.getNextHeader(self.pos)
        if filename == "TRAILER!!!":
            return [None, None, None]

        # Contents
        filesize = filedata[7]
        filerawdata = self.cpiodata[self.pos:self.pos+filesize]
        self.pos = self.pos + filesize
        self.pos = self.pos + ((4 - (filesize % 4)) % 4)
        self.filename = filename
        self.filedata = filedata
        self.filerawdata = filerawdata
        return self.getCurrentEntry()

    def resetEntry(self):
        self.pos = 0
        self.filename = None
        self.filedata = None
        self.filerawdata = None

    def namelist(self):
        """Return a list of file names in the archive."""
        return self.filelist

    def read(self):
        """Read an parse cpio archive."""
        self._read_cpio_headers()


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        if f == "-":
            c = CPIOFile(sys.stdin)
        else:
            c = CPIOFile(f)
        try:
            c.read()
        except IOError, e:
            print "error reading cpio: %s" % e
        print c.filelist

# vim:ts=4:sw=4:showmatch:expandtab
