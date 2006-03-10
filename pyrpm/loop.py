#
# Copyright (C) 2005 Red Hat, Inc.
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

import os, fcntl, struct

LOOP_SET_FD       = 0x4C00
LOOP_CLR_FD       = 0x4C01
LOOP_SET_STATUS   = 0x4C02
LOOP_GET_STATUS   = 0x4C03
LOOP_SET_STATUS64 = 0x4C04
LOOP_GET_STATUS64 = 0x4C05
LO_NAME_SIZE      = 64
LO_KEY_SIZE       = 32

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

################################## functions ##################################

def lo_get_info64(device):
    try:
        fd = open(device, "rwb")
    except:
        raise IOError, "ERROR: Could not open '%s'" % device
    info64 = struct.pack("QQQQQIIIIBBBQ",
                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    try:
        info64 = fcntl.ioctl(fd.fileno(), LOOP_GET_STATUS64, info64)
    except:
        raise IOError, "ERROR: Could not get status64 on '%s'" % device    
    info = struct.unpack("QQQQQIIIIBBBQ", info64)
    fd.close()
    return info

def lo_set_info64(device, info):
    try:
        fd = open(device, "rwb")
    except:
        raise IOError, "ERROR: Could not open '%s'" % device
    info64 = struct.pack("QQQQQIIIIBBBQ",
                         info[0], info[1], info[2], info[3],
                         info[4], info[5], info[6], info[7],
                         info[8], info[9], info[10], info[11],
                         info[12])
    try:
        fcntl.ioctl(fd.fileno(), LOOP_SET_STATUS64, info64)
    except:
        raise IOError, "ERROR: Could not set status64 on '%s'" % device    
    fd.close()

# set maxsize of loop device in bytes
def lo_set_maxsize(device, size):
    info = lo_get_info64(device)
    lo_set_info64(device, (info[0], info[1], info[2], info[3],
                        size, info[5], info[6], info[7],
                        info[8], info[9], info[10], info[11],
                        info[12]))

def lolist():
    list = os.listdir("/dev/")
    list.sort()
    free = 0
    for file in list:
        if file[:4] != "loop":
            continue
        status = os.system("/sbin/losetup '/dev/%s' 2>/dev/null" % file)
        if status != 0:
            free += 1
    if free == 0:
        print "All loop devices are in use."
        print "You should generate additional loop devices or free some, which are not used by this program."
    else:
        print "You have %d free loop devices available." % free

def losetup(target, offset=0):
    i = 0
    loop_device = None
    offset_string = ""
    if offset:
        offset_string = "-o%d" % offset
    while not loop_device and i < 100:
        (child_stdin, child_stdout) = os.popen2("/sbin/losetup -f 2>/dev/null")
        loop_device = child_stdout.read()
        loop_device = loop_device.strip()
        i += 1
        if loop_device:
            status = os.system("/sbin/losetup %s '%s' '%s'" % \
                               (offset_string, loop_device, target))
            if status != 0:
                loop_device = None
    return loop_device

def lofree(device):
    return (os.system("/sbin/losetup -d '%s'" % device) == 0)
