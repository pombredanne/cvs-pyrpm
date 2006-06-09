#
# Copyright (C) 2005,2006 Red Hat, Inc.
# Author: Thomas Woerner <twoerner@redhat.com>
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

import os, fcntl, struct, stat

# struct loop_info64 {
#        unsigned long long      lo_device;
#        unsigned long long      lo_inode;
#        unsigned long long      lo_rdevice;
#        unsigned long long      lo_offset;
#        unsigned long long      lo_sizelimit; /* bytes, 0 == max available */
#        unsigned int            lo_number;
#        unsigned int            lo_encrypt_type;
#        unsigned int            lo_encrypt_key_size;
#        unsigned int            lo_flags;
#        unsigned char           lo_file_name[LO_NAME_SIZE];
#        unsigned char           lo_crypt_name[LO_NAME_SIZE];
#        unsigned char           lo_encrypt_key[LO_KEY_SIZE];
#        unsigned long long      lo_init[2];
# }

################################## classes ##################################


class LOOP:
    LOOP_SET_FD       = 0x4C00
    LOOP_CLR_FD       = 0x4C01
    LOOP_SET_STATUS   = 0x4C02
    LOOP_GET_STATUS   = 0x4C03
    LOOP_SET_STATUS64 = 0x4C04
    LOOP_GET_STATUS64 = 0x4C05
    LO_NAME_SIZE      = 64
    LO_KEY_SIZE       = 32

    LOOP_MAX          = 256
    LOOP_NAME         = "/dev/loop%d"

    def __init__(self, device):
        self.clear()
        self.device = device
        try:
            self._getInfo()
        except:
            pass

    def clear(self):
        self.device = None
        self.lo_device = 0
        self.lo_inode = 0
        self.lo_rdevice = 0
        self.lo_offset = 0
        self.lo_sizelimit = 0
        self.lo_number = 0
        self.lo_encrypt_type = 0
        self.lo_encrypt_key_size = 0
        self.lo_flags = 2L
        self.lo_file_name = ""
        self.lo_crypt_name = ""
        self.lo_encrypt_key = ""
        self.lo_init = [0, 0]

    def getDevice(self):
        return self.device

    def setSizelimit(self, size):
        self._getInfo()
        self.lo_sizelimit = size
        self._setInfo()

    def setOffset(self, offset):
        self._getInfo()
        self.lo_offset = offset
        self._setInfo()

    def setup(self, filename, fd=None, offset=0):
        file_fd = fd
        # open filename if no fd is given
        if not file_fd:
            try:
                file_fd = open(filename, "r+") # rw
            except Exception, msg:
                return 0
        # open device
        try:
            lo_fd = open(self.device, "r+") # rw
        except Exception, msg:
            # close file if we have opened it
            if not fd:
                file_fd.close()
            return 0
        # bind loop device to file_fd
        try:
            fcntl.ioctl(lo_fd.fileno(), LOOP.LOOP_SET_FD, file_fd.fileno())
        except Exception, msg:
            lo_fd.close()
            if not fd:
                file_fd.close()
            return 0
        # close devices
        try:
            self._getInfo(fd=lo_fd)
        except Exception, msg:
            if not fd:
                file_fd.close()
            lo_fd.close()
            self.free()
            return 0
        # set filename and offset
        self.lo_file_name = filename
        self.lo_offset = offset
        try:
            self._setInfo(fd=lo_fd)
        except Exception, msg:
            lo_fd.close()
            if not fd:
                file_fd.close()
            self.free()
            return 0
        lo_fd.close()
        if not fd:
            file_fd.close()
        return 1

    def free(self):
        # open device
        try:
            lo_fd = open(self.device, "r")
        except Exception, msg:
            return 0
        self.clear()
        try:
            self._setInfo(fd=lo_fd)
        except Exception, msg:
            lo_fd.close()
            return 0
        try:
            fcntl.ioctl(lo_fd.fileno(), LOOP.LOOP_CLR_FD, 0)
        except:
            lo_fd.close()
            return 0
        lo_fd.close()
        return 1

    def inUse(device):
        l = LOOP(device)
        try:
            l._getInfo()
        except:
            return 0
        return 1
    inUse = staticmethod(inUse)

    def findUnused():
        for i in xrange(LOOP.LOOP_MAX):
            dev = LOOP.LOOP_NAME % i
            try:
                mode = os.stat(dev).st_mode
            except:
                continue
            if mode and stat.S_ISBLK(mode):
                if not LOOP.inUse(dev):
                    return dev
        return None
    findUnused = staticmethod(findUnused)

    def getMax():
        return LOOP.LOOP_MAX
    getMax = staticmethod(getMax)

    def createDevice(id, chroot=""):
        dev = "%s/dev/loop%i" % (chroot, id)
        if not os.path.exists(dev):
            os.mknod(dev, 0600 | stat.S_IFBLK, os.makedev(7, id))
    createDevice = staticmethod(createDevice)

    def _getInfo(self, fd=None):
        _fd = fd
        if not fd:
            try:
                _fd = open(self.device, "r")
            except:
                raise IOError, "ERROR: Could not open '%s'." % self.device
        info64 = self.__buildInfo64()
        try:
            info64 = fcntl.ioctl(_fd.fileno(), LOOP.LOOP_GET_STATUS64, info64)
        except Exception, msg:
            raise IOError, "ERROR: Could not get status64 on '%s'" % _fd
        self.__unpackInfo64(info64)
        if not fd:
            _fd.close()

    def _setInfo(self, fd=None):
        _fd = fd
        if not fd:
            try:
                _fd = open(self.device, "r+") # rw
            except:
                raise IOError, "ERROR: Could not open '%s'." % self.device
        info64 = self.__packInfo64()
        try:
            info64 = fcntl.ioctl(_fd.fileno(), LOOP.LOOP_SET_STATUS64, info64)
        except Exception, msg:
            raise IOError, "ERROR: Could not set status64 on '%s'" % \
                  self.device
        self.__unpackInfo64(info64)
        if not fd:
            _fd.close()

    def __buildInfo64(self):
        return struct.pack("QQQQQIIII%ds%ds%dsQQ" % (LOOP.LO_NAME_SIZE,
                                                     LOOP.LO_NAME_SIZE,
                                                     LOOP.LO_KEY_SIZE),
                           0, 0, 0, 0, 0, 0, 0, 0, 0, "", "", "", 0, 0)
    def __packInfo64(self):
        return struct.pack("QQQQQIIII%ds%ds%dsQQ" % (LOOP.LO_NAME_SIZE,
                                                     LOOP.LO_NAME_SIZE,
                                                     LOOP.LO_KEY_SIZE),
                           self.lo_device, self.lo_inode, self.lo_rdevice,
                           self.lo_offset, self.lo_sizelimit, self.lo_number,
                           self.lo_encrypt_type, self.lo_encrypt_key_size,
                           self.lo_flags, self.lo_file_name,
                           self.lo_crypt_name, self.lo_encrypt_key,
                           self.lo_init[0], self.lo_init[1])
    def __unpackInfo64(self, info64):
        (self.lo_device, self.lo_inode, self.lo_rdevice, self.lo_offset,
         self.lo_sizelimit, self.lo_number, self.lo_encrypt_type,
         self.lo_encrypt_key_size, self.lo_flags, self.lo_file_name,
         self.lo_crypt_name, self.lo_encrypt_key, self.lo_init[0],
         self.lo_init[1]) = \
         struct.unpack("QQQQQIIII%ds%ds%dsQQ" % \
                       (LOOP.LO_NAME_SIZE, LOOP.LO_NAME_SIZE,
                        LOOP.LO_KEY_SIZE), info64)

def losetup(filename, fd=None, device=None, offset=0):
    if not device:
        device = LOOP.findUnused()
    loop = LOOP(device)
    if not loop.setup(filename, fd=None, offset=0):
        return None
    return loop.getDevice()

def lolist():
    used = 0
    free = 0
    for i in xrange(LOOP.LOOP_MAX):
        dev = "/dev/loop%d" % i
        try:
            mode = os.stat(dev).st_mode
        except:
            continue
        if mode and stat.S_ISBLK(mode):
            l = LOOP(dev)
            try:
                l._getInfo()
            except:
                free += 1
                continue
            used += 1
            line = "%s: [%04x]:%d (%s)" % (dev, l.lo_device, l.lo_inode,
                                           l.lo_file_name)
            if l.lo_offset > 0:
                line += ", offset %d" % l.lo_offset
            if l.lo_sizelimit > 0:
                line += ", sizelimit %d" % l.lo_sizelimit
            if l.lo_flags & 1:
                line += ", readonly"
            print line
    print "%d/%d loop devices are in use." % (used, used+free)

def lofree(device):
    loop = LOOP(device)
    return loop.free()

# vim:ts=4:sw=4:showmatch:expandtab
