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
# Copyright 2004, 2005 Red Hat, Inc.
#
# Author: Phil Knirsch, Paul Nasrat, Florian La Roche, Karel Zak
#


# file data indexes
CP_FDMAGIC = 0
CP_FDINODE = 1
CP_FDMODE = 2
CP_FDUID = 3
CP_FDGID = 4
CP_FDNLINK = 5
CP_FDMTIME = 6
CP_FDFILESIZE = 7
CP_FDDEVMAJOR = 8
CP_FDDEVMINOR = 9
CP_FDRDEVMAJOR = 10
CP_FDRDEVMINOR = 11
CP_FDNAMESIZE = 12
CP_FDCHECKSUM = 13


class CPIOFile:
    """ Read ASCII CPIO files. """

    def __init__(self, fd):
        self.filelist = {}              # hash of CPIO headers and stat data
        self.fd = fd                    # file descript from which we read
        self.defered = []               # list of defered files for extract
        self.filename = None            # current filename
        self.filedata = None            # current file stat data
        self.filerawdata = None         # raw data of current file

    def getNextHeader(self):
        data = self.fd.read(110)

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

        size = filedata[CP_FDNAMESIZE]
        filename = self.fd.read(size).rstrip("\x00")
        self.fd.read((4 - ((110 + size) % 4)) % 4)
        # Detect if we're at the end of the archive
        if filename == "TRAILER!!!":
            return [None, None]
        if filename.startswith("./"):
            filename = filename[1:]
        if not filename.startswith("/"):
            filename = "%s%s" % ("/", filename)
        if filename.endswith("/") and len(filename) > 1:
            filename = filename[:-1]
        #filename = "/" + os.path.normpath("./" + filename)
        return [filename, filedata]

    def _read_cpio_headers(self):
        while 1:
            [filename, filedata] = self.getNextHeader()
            if filename == None:
                break
            # Contents
            filesize = filedata[CP_FDFILESIZE]
            self.fd.read(filesize)
            self.fd.read((4 - (filesize % 4)) % 4)
            self.filelist[filename] = filedata

    def getCurrentEntry(self):
        return [self.filename, self.filedata, self.filerawdata]

    def getNextEntry(self):
        [filename, filedata] = self.getNextHeader()
        if filename == None:
            return [None, None, None]

        # Contents
        filesize = filedata[CP_FDFILESIZE]
        filerawdata = self.fd.read(filesize)
        self.fd.read((4 - (filesize % 4)) % 4)
        self.filename = filename
        self.filedata = filedata
        self.filerawdata = filerawdata
        return self.getCurrentEntry()

    def resetEntry(self):
        self.fd.seek(0)
        self.filename = None
        self.filedata = None
        self.filerawdata = None
        self.defered = []

    def read(self):
        """Read an parse cpio archive."""
        self._read_cpio_headers()


if __name__ == "__main__":
    import sys
    from functions import printError
    for f in sys.argv[1:]:
        if f == "-":
            c = CPIOFile(sys.stdin)
        else:
            c = CPIOFile(f)
        try:
            c.read()
        except IOError, e:
            printError (1, "error reading cpio: %s" % e)
        print c.filelist

# vim:ts=4:sw=4:showmatch:expandtab
