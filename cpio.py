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

#import filetree

class CPIOFile:
    """ Read ASCII CPIO files. """

    def __init__(self, file):
        self.filelist = []              # list of CPIO header dicts
        if isinstance(file, basestring):
            self.filename = file
            self.fp = open(file, "rb")
        else:
            self.filename = getattr(file, 'name', None)
            self.fp = file

    def _read_cpio_headers(self):
        while 1:
            data = self.fp.read(110)

            # CPIO ASCII hex, expanded device numbers (070702 with CRC)
            if data[0:6] not in ["070701", "070702"]:
                raise IOError, "Bad magic reading CPIO headers %s" % data[0:6]

            #(magic, inode, mode, uid, gid, nlink, mtime, filesize, devMajor, \
            #    devMinor, rdevMajor, rdevMinor, namesize, checksum)
            filedata = [data[0:6], data[6:14], \
                oct(int(data[14:22], 16)), int(data[22:30], 16), \
                int(data[30:38], 16), int(data[38:46], 16), \
                int(data[46:54], 16), int(data[54:62], 16), \
                int(data[62:70], 16), int(data[70:78], 16), \
                int(data[78:86], 16), int(data[86:94], 16), \
                int(data[94:102], 16), data[102:110]]

            size = filedata[12]
            filename = self.fp.read(size).rstrip("\x00")
            fsize = 110 + size
            self.fp.read((4 - (fsize % 4)) % 4)

            # Detect if we're at the end of the archive
            if filename == "TRAILER!!!":
                break

            # Contents
            filesize = filedata[7]
            self.fp.read(filesize)
            self.fp.read((4 - (filesize % 4)) % 4)
            self.filelist.append(filename)

    def namelist(self):
        """Return a list of file names in the archive."""
        return self.filelist

    def read(self):
        """Return file bytes."""
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
