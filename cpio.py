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
# Author: Phil Knirsch, Paul Nasrat, Florian La Roche
#

import os, os.path, commands, shutil

CP_IFMT  =  0170000
CP_IFIFO =  0010000
CP_IFCHR =  0020000
CP_IFDIR =  0040000
CP_IFBLK =  0060000
CP_IFREG =  0100000
CP_IFNWK =  0110000
CP_IFLNK =  0120000
CP_IFSOCK = 0140000

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
        filename = self.fd.read(size)
        filename = "/"+os.path.normpath("./"+filename.rstrip("\x00"))
        fsize = 110 + size
        self.fd.read((4 - (fsize % 4)) % 4)

        # Detect if we're at the end of the archive
        if filename == "/TRAILER!!!":
            return [None, None]

        # Contents
        filesize = filedata[CP_FDFILESIZE]
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

    def createLink(self, src, dst):
        try:
            # First try to unlink the defered file
            os.unlink(dst)
        except:
            pass
        # Behave exactly like cpio: If the hardlink fails (because of different
        # partitions), then it has to fail
        os.link(src, dst)
 
    def addToDefered(self, filename):
        self.defered.append((filename, self.filedata))

    def handleCurrentDefered(self, filename):
        # Check if we have a defered 0 byte file with the same inode, devmajor
        # and devminor and if yes, create a hardlink to the new file.
        for i in xrange(len(self.defered)-1, -1, -1):
            if self.defered[i][1][CP_FDINODE] == self.filedata[CP_FDINODE] and \
               self.defered[i][1][CP_FDDEVMAJOR] == self.filedata[CP_FDDEVMAJOR] and \
               self.defered[i][1][CP_FDDEVMINOR] == self.filedata[CP_FDDEVMINOR]:
                self.createLink(filename, self.defered[i][0])
                self.defered.pop(i)

    def postExtract(self):
        # In the end we need to process the remaining files in the defered
        # list and see if any of them need to be hardlinked, too.
        for i in xrange(len(self.defered)-1, -1, -1):
            # We mark already processed defered hardlinked files by setting
            # the inode of those files to -1. We have to skip those naturally.
            if self.defered[i][1][1] < 0:
                continue
            # Create empty file
            fd = open(self.defered[i][0], "w")
            fd.write("")
            fd.close()
            os.chmod(self.defered[i][0], (~CP_IFMT) & self.defered[i][1][CP_FDMODE])
            os.chown(self.defered[i][0], self.defered[i][1][CP_FDUID], self.defered[i][1][CP_FDGID])
            os.utime(self.defered[i][0], (self.defered[i][1][CP_FDMTIME], self.defered[i][1][CP_FDMTIME]))
            for j in xrange(i-1, -1, -1):
                if self.defered[i][1][CP_FDINODE] == self.defered[j][1][CP_FDINODE] and \
                   self.defered[i][1][CP_FDDEVMAJOR] == self.defered[j][1][CP_FDDEVMAJOR] and \
                   self.defered[i][1][CP_FDDEVMINOR] == self.defered[j][1][CP_FDDEVMINOR]:
                    self.createLink(filename, self.defered[i][0])

    def makeDirs(self, fullname):
        dirname = fullname[:fullname.rfind("/")]
        if not os.path.isdir(dirname):
                os.makedirs(dirname)

    def extractCurrentEntry(self, instroot=None):
        if self.filename == None or self.filedata == None:
            return 0
        if instroot == None:
            instroot = "/"
        if not os.path.isdir(instroot):
            return 0

        filetype = self.filedata[CP_FDMODE] & CP_IFMT
        fullname = instroot + self.filename
        if   filetype == CP_IFREG:
            self.makeDirs(fullname)
            # CPIO archives are sick: Hardlinks are stored as 0 byte long
            # regular files.
            # The last hardlinked file in the archive contains the data, so
            # we have to defere creating any 0 byte file until either:
            #  - We create a file with data and the inode/devmajor/devminor are
            #    identical
            #  - We have processed all files and can check the defered list for
            #    any more identical files (in which case they are hardlinked
            #    again)
            #  - For the rest in the end create 0 byte files as they were in
            #    fact really 0 byte files, not hardlinks.
            if self.filedata[CP_FDFILESIZE] == 0:
                self.addToDefered(fullname)
                return 1
            fd = open(fullname, "w")
            fd.write(self.filerawdata)
            fd.close()
            os.chown(fullname, self.filedata[CP_FDUID], self.filedata[CP_FDGID])
            os.chmod(fullname, (~CP_IFMT) & self.filedata[CP_FDMODE])
            os.utime(fullname, (self.filedata[CP_FDMTIME], self.filedata[CP_FDMTIME]))
            self.handleCurrentDefered(fullname)
        elif filetype == CP_IFDIR:
            if os.path.isdir(fullname):
                return 1
            os.makedirs(fullname)
            os.chown(fullname, self.filedata[CP_FDUID], self.filedata[CP_FDGID])
            os.chmod(fullname, (~CP_IFMT) & self.filedata[CP_FDMODE])
            os.utime(fullname, (self.filedata[CP_FDMTIME], self.filedata[CP_FDMTIME]))
        elif filetype == CP_IFLNK:
            symlinkfile = self.filerawdata.rstrip("\x00")
            if os.path.islink(fullname) and os.readlink(fullname) == symlinkfile:
                return 1
            self.makeDirs(fullname)
            os.symlink(symlinkfile, fullname)
        elif filetype == CP_IFCHR or filetype == CP_IFBLK or filetype == CP_IFSOCK or filetype == CP_IFIFO:
            if filetype == CP_IFCHR:
                devtype = "c"
            elif filetype == CP_IFBLK:
                devtype = "b"
            else:
                return 0
            self.makeDirs(fullname)
            ret = commands.getoutput("/bin/mknod "+fullname+" "+devtype+" "+str(self.filedata[CP_FDRDEVMAJOR])+" "+str(self.filedata[CP_FDRDEVMINOR]))
            if ret != "":
                print "Error creating device: "+ret
            else:
                os.chown(fullname, self.filedata[CP_FDUID], self.filedata[CP_FDGID])
                os.chmod(fullname, (~CP_IFMT) & self.filedata[CP_FDMODE])
                os.utime(fullname, (self.filedata[CP_FDMTIME], self.filedata[CP_FDMTIME]))
        else:
            raise ValueError, "%s: not a valid CPIO filetype" % (oct(filetype))

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
