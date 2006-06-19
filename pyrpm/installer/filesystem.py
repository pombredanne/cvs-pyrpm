#
# Copyright (C) 2005, 2006 Red Hat, Inc.
# Author: Thomas Woerner
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

import os, stat, string, time, resource, struct
import pyrpm.functions as functions

################################## functions ##################################

# TODO: add chroot support to all functions

def mount(what, where, fstype="ext3", options=None, arguments=None):
    opts = ""
    if options:
        opts = "-o '%s'" % options
    args = ""
    if arguments:
        args = string.join(arguments)
    if fstype:
        _fstype = "-t '%s'" % fstype
    else:
        _fstype = ""
    mount = "/bin/mount %s %s %s '%s' '%s'" % (args, opts, _fstype, what,
                                               where)
    stat = os.system(mount)
    if stat != 0:
        raise IOError, "mount of '%s' on '%s' failed" % (what , where)


def umount(what):
    if not os.path.ismount(what):
        # TODO: ismount is not working for bind mounts
        stat = os.system("/bin/umount '%s' 2>/dev/null" % what)
        if stat != 0:
            return 1
        return 0

    i = 0
    log = ""
    while os.system("/usr/sbin/lsof '%s' >/dev/null 2>&1" % what) == 0:
        sig = "TERM"
        if i == 20:
            print "ERROR: Failed to kill processes in '%s': %s." % (what, log)
            return 1
        elif i >= 15:
            time.sleep(1)
        elif i >= 10:
            sig = "SIGKILL"
        fuser = "/sbin/fuser -k -%s '%s'" % (sig, what)
        (status, rusage, log) = functions.runScript(script=fuser)
        if status == 256:
            # nothing to do
            break
        i += 1

    stat = os.system("/bin/umount '%s' 2>/dev/null" % what)
    if stat != 0:
        print "ERROR: Umount of '%s' failed" % what
        return 1

    return 0

def swapon(device):
    swapon = "/sbin/swapon '%s'" % device
    print "Enable swap on '%s'" % device
    (status, rusage, log) = functions.runScript(script=swapon)
    if status != 0:
        print "ERROR: swapon failed."
        return 1
    return 0

def swapoff(device):
    swapoff = "/sbin/swapoff '%s'" % device
    print "Disable swap on '%s'" % device
    (status, rusage, log) = functions.runScript(script=swapoff)
    if status != 0:
        print "ERROR: swapoff failed."
        return 1
    return 0

def detectFstype(device):
    pagesize = resource.getpagesize()

    # open device
    try:
        fd = open(device, "r")
    except Exception, msg:
        print msg
        return None

    # read pagesize bytes (at least needed for swap)
    try:
        buf = fd.read(pagesize)
    except:
        fd.close()
        return None
    if len(buf) < pagesize:
        fd.close()
        return None

    ext2magic = ext2_journal = ext2_has_journal = 0
    try:
        (ext2magic,) = struct.unpack("H", buf[1024+56:1024+56+2])
        (ext2_journal,) = struct.unpack("I", buf[1024+96:1024+96+4])
        (ext2_has_journal,) = struct.unpack("I", buf[1024+92:1024+92+4])
    except Exception, msg:
        fd.close()
        raise Exception, msg

    if ext2magic == 0xEF53:
        if ext2_journal & 0x0008 == 0x0008 or \
               ext2_has_journal & 0x0004 == 0x0004:
            return "ext3"
        return "ext2"

    elif buf[pagesize - 10:] == "SWAP_SPACE" or \
           buf[pagesize - 10:] == "SWAPSPACE2":
        fd.close()
        return "swap"
    elif buf[0:4] == "XFSB":
        fd.close()
        return "xfs"

    # check for jfs
    try:
        fd.seek(32768, 0)
        buf = fd.read(180)
    except:
        fd.close()
        return None
    if len(buf) < 180:
        fd.close()
        return None
    if buf[0:4] == "JFS1":
        return "jfs"

    return None

def ext2Label(device):
    # open device
    try:
        fd = open(device, "r")
    except:
        return None
    # read 1160 bytes
    try:
        fd.seek(1024, 0)
        buf = fd.read(136)
    except:
        fd.close()
        return None
    fd.close()

    label =None
    if len(buf) == 136:
        (ext2magic,) = struct.unpack("H", buf[56:56+2])
        if ext2magic == 0xEF53:
            label = string.rstrip(buf[120:120+16],"\0x00")
    return label


def xfsLabel(device):
    # open device
    try:
        fd = open(device, "r")
    except:
        return None
    # read 128 bytes
    try:
        buf = fd.read(128)
    except:
        fd.close()
        return None
    fd.close()

    label =None
    if len(buf) == 128 and buf[0:4] == "XFSB":
        label = string.rstrip(buf[108:120],"\0x00")
    return label

def jfsLabel(device):
    # open device
    try:
        fd = open(device, "r")
    except:
        return None
    # seek to 32768, read 180 bytes
    try:
        fd.seek(32768, 0)
        buf = fd.read(180)
    except:
        fd.close()
        return None
    fd.close()

    label =None
    if len(buf) == 180 and buf[0:4] == "JFS1":
        label = string.rstrip(buf[152:168],"\0x00")
    return label

def swapLabel(device):
    pagesize = resource.getpagesize()

    # open device
    try:
        fd = open(device, "r")
    except:
        return None
    # read pagesize bytes
    try:
        buf = fd.read(pagesize)
    except:
        fd.close()
        return None
    fd.close()

    label = None
    if len(buf) == pagesize and (buf[pagesize - 10:] == "SWAP_SPACE" or \
                                 buf[pagesize - 10:] == "SWAPSPACE2"):
        label = string.rstrip(buf[1052:1068], "\0x00")
    return label

def getLabel(device):
    label = ext2Label(device)
    if not label:
        label = swapLabel(device)
    if not label:
        label = xfsLabel(device)
    if not label:
        label = jfsLabel(device)
    return label

# vim:ts=4:sw=4:showmatch:expandtab
