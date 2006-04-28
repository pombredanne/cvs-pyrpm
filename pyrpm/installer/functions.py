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

import os, os.path, stat
import pyrpm.functions as functions
import pyrpm.database as database
import pyrpm.config
import config
from filesystem import *

def get_system_disks():
    disks = [ ]
    fd = open("/proc/partitions", "r")
    while 1:
        line = fd.readline()
        if not line:
            break
        line = line.strip()
        if len(line) < 1 or line[0] == '#':
            continue
        if line[:5] == "major":
            continue
        splits = line.split() # major, minor, blocks, name
        if len(splits) < 4:
            print "ERROR: '/proc/partitions' malformed."
            return
        if int(splits[1], 16) % 16 == 0: # minor%16=0 for harddisk devices
            hd = splits[3]
            if hd[0:4] == "loop":
                continue
            disks.append("/dev/"+hd)
    fd.close()
    return disks

def get_system_md_devices():
    map = { }
    fd = open("/proc/mdstat", "r")
    while 1:
        line = fd.readline()
        if not line:
            break
        line = line.strip()
        if len(line) < 1 or line[0] == '#':
            continue
        if line[:2] != "md":
            continue
        splits = line.split() # device : data
        if len(splits) < 3 or splits[1] != ":":
            print "ERROR: '/proc/mdstat' malformed."
            return
        map[splits[0]] = "/dev/%s" % splits[0]
    fd.close()
    return map

def load_release(chroot=""):
    f = "%s/etc/redhat-release" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    try:
        fd = open(f, "r")
    except:
        return None
    release = fd.readline()
    fd.close()
    return release.strip()
    
def load_fstab(chroot=""):
    f = "%s/etc/fstab" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    try:
        fd = open(f, "r")
    except:
        return None
    fstab = [ ]
    while 1:
        line = fd.readline()
        if not line:
            break
        line = line.strip()
        splits = line.split()
        if len(splits) != 6:
            continue
        if (splits[4] == "1" and splits[5] in ["1", "2"]) or \
               splits[1] == "swap":
            fstab.append(splits)
    fd.close()
    return fstab

def load_mdadm_conf(chroot=""):
    f = "%s/etc/mdadm.conf" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    try:
        fd = open(f, "r")
    except:
        return None
    conf = [ ]
    while 1:
        line = fd.readline()
        if not line:
            break
        line = line.strip()
        splits = line.split()
        if splits[0] == "ARRAY":
            dev = splits[1]
            if dev[:5] == "/dev/":
                dev = dev[5:]
            conf[dev] = { }
            for i in xrange(2, len(splits)):
                (key, value) = splits[i].split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "devices":
                    conf[dev][key] = [ ]
                    for val in value.split(","):
                        val.strip()
                        if val[:5] == "/dev/":
                            val = val[5:]
                        conf[dev][key].append(val)
                else:
                    conf[dev][key] = value
    fd.close()
    return conf    

def get_size_in_byte(size):
    _size = size.strip()
    if _size[-1] == "b" or _size[-1] == "B":
        _size = _size[:-1]
        _size = _size.strip()
    try:
        return long(_size)
    except:
        if _size[-1] in [ "k", "K", "m", "M", "g", "G", "t", "T" ]:
            s = long(_size[:-1].strip())
        else:
            raise ValueError, "'%s' is no valid size argument." % size
    if _size[-1] == "k":
        s *= 1024
    elif _size[-1] == "K":
        s *= 1000
    elif _size[-1] == "m":
        s *= 1024*1024
    elif _size[-1] == "M":
        s *= 1000*1000
    elif _size[-1] == "g":
        s *= 1024*1024*1024
    elif _size[-1] == "G":
        s *= 1000*1000*1000
    elif _size[-1] == "t":
        s *= 1024*1024*1024*1024
    elif _size[-1] == "T":
        s *= 1000*1000*1000*1000
    return s

def rpmdb_get(rpmdb, name):
    list = rpmdb.getPkgsByName(name)
    # sort by NEVRA
    _list = [ ]
    for pkg in list:
        found = 0
        for j in xrange(len(_list)):
            pkg2 = _list[j]
            if functions.pkgCompare(pkg, pkg2) > 0:
                _list.insert(j, pkg)
                found = 1
                break
        if not found:
            _list.append(pkg)
    return _list

def get_installed_kernels(chroot=None):
    kernels = [ ]
    rpmdb = database.getRpmDBFactory(pyrpm.config.rpmconfig, "/var/lib/rpm",
                                     chroot)
    rpmdb.open()
    if not rpmdb.read():
        return kernels
    list = rpmdb_get(rpmdb, "kernel-smp")
    list.extend(rpmdb_get(rpmdb, "kernel"))
    rpmdb.close()
    functions.normalizeList(list)
    kernels = [ "%s-%s" % (pkg["version"], pkg["release"]) for pkg in list ]
    return kernels

def umount_all(dir):
    # umount target dir and included mount points
    mounted = [ ]
    try:
        fd = open("/proc/mounts", "r")
    except Exception:
        print "ERROR: Unable to open '/proc/mounts' for reading."
        return
    while 1:
        line = fd.readline()
        if not line:
            break
        margs = line.split()
        i = margs[1].find(dir)
        if i == 0:
            mounted.append(margs[1])
    fd.close()
    # sort reverse
    mounted.sort()
    mounted.reverse()

    # try to umount 5 times
    count = 5
    i = 0
    failed = 0
    while len(mounted) > 0:
        dir = mounted[i]
        if config.verbose:
            print "Umounting '%s' " % dir
        failed = 0
        if umount(dir) == 1:
            failed = 1
            i += 1
        else:
            mounted.remove(dir)
        if i >= len(mounted) and count > 0:
            time.sleep(1)
            i = 0
            count -= 1

    return failed

def zero_device(device, size, offset=0):
    fd = open(device, "wb")
    fd.seek(offset)
    i = 0
    while i < size:
        fd.write("\0")
        i += 1
    fd.close()

def check_dir(buildroot, dir):
    d = buildroot+dir
    try:
        check_exists(buildroot, dir)
    except:
        print "ERROR: Directory '%s' does not exist." % dir
        return 0
    if not os.path.isdir(d):
        print "ERROR: '%s' is no directory." % dir
        return 0
    return 1

def create_dir(buildroot, dir):
    d = "%s/%s" % (buildroot, dir)
    try:
        check_exists(buildroot, dir)
    except:
        try:
            os.makedirs(d)
        except Exception, msg:
            raise IOError, "Unable to create '%d':" % dir, msg
    else:
        if not os.path.isdir(d):
            raise IOError, "'%s' is no directory." % dir

def create_link(buildroot, source, target):
    t = "%s/%s" % (buildroot, target)
    try:
        check_exists(buildroot, target)
    except:
        try:
            os.symlink("../%s" % source, t)
        except Exception, msg:
            raise IOError, "Unable to generate %s symlink:" % target, msg
    else:
        if not os.path.islink(t):
            raise IOError, "'%s' is not a link." % target

def realpath(buildroot, path):
    t = "%s/%s" % (buildroot, path)
    if os.path.islink(t):
        t = buildroot + os.readlink(t)
    return t    

def check_exists(buildroot, target):
    if not os.path.exists("%s/%s" % (buildroot, target)) and \
           not os.path.exists(realpath(buildroot, target)):
        raise IOError, "%s is missing." % target

def create_file(buildroot, target, content=None, force=0):
    try:
        check_exists(buildroot, target)
    except:
        pass
    else:
        if not force:
            return -1
    try:
        fd = open("%s/%s" % (buildroot, target), "w")
    except Exception, msg:
        print "ERROR: Unable to open '%s' for writing:" % target, msg
        return 0
    if content:
        try:
            for line in content:
                fd.write(line)
        except Exception, msg:
            print "ERROR: Unable to write to '%s':" % target, msg
            fd.close()
            return 0
    fd.close()
    return 1

def copy_device(source, target_dir, source_dir="", target=None):
    if not os.path.isdir(target_dir):
        raise IOError, "'%s' is no directory." % target_dir
    if not target:
        target = source

    s = "%s/%s" % (source_dir, source)
    s_linkto = None
    if os.path.islink(s):
        s_linkto = os.readlink(s)
        s = "%s/%s" % (source_dir, s_linkto)
    stats = os.stat(s)
    if not stats.st_rdev:
        raise IOError, "'%s' is no device." % s

    t = "%s/%s" % (target_dir, target)
    try:
        if s_linkto:
            create_dir(target_dir, os.path.dirname(s_linkto))
            os.mknod("%s/%s" % (target_dir, s_linkto), stats.st_mode,
                     stats.st_rdev)
            create_dir(target_dir, os.path.dirname(target))
            os.symlink(s_linkto, t)
        else:
            os.mknod(t, stats.st_mode, stats.st_rdev)
    except Exception, msg:
        raise IOError, "Unable to copy device '%s': %s" % (s, msg)

#def copy_device(buildroot, source, target=None):
#    if not target:
#        target = source
#    t = "%s/%s" % (buildroot, target)
#    try:
#        check_exists(buildroot, target)
#    except:
#        stats = os.stat(source)
#        try:
#            os.mknod(t, stats.st_mode, stats.st_rdev)
#        except Exception, msg:
#            raise IOError, "Unable to generate device '%s/%s':" % \
#                  (buildroot, target), msg

def create_device(buildroot, name, stat, major, minor):
    if not os.path.exists(buildroot+name):
        os.mknod(buildroot+name, stat, os.makedev(major, minor))

def create_min_devices(buildroot):
    if not os.path.exists(buildroot+"/dev/console"):
        os.mknod(buildroot+"/dev/console", 0666 | stat.S_IFCHR,
                 os.makedev(5, 1))
    if not os.path.exists(buildroot+"/dev/null"):
        os.mknod(buildroot+"/dev/null", 0666 | stat.S_IFCHR, os.makedev(1, 3))
    if not os.path.exists(buildroot+"/dev/urandom"):
        os.mknod(buildroot+"/dev/urandom", 0666 | stat.S_IFCHR,
                 os.makedev(1, 9))
    if not os.path.exists(buildroot+"/dev/zero"):
        os.mknod(buildroot+"/dev/zero", 0666 | stat.S_IFCHR, os.makedev(1, 5))

def getName(name):
    tmp = name[:]
    while len(tmp) > 0 and tmp[-1] >= '0' and tmp[-1] <= '9':
        tmp = tmp[:-1]
    if len(tmp) < 1:
        raise ValueError, "'%s' contains no name" % name
    return tmp

def getId(name):
    tmp = name[:]
    if tmp[-1] < '0' or tmp[-1] > '9':
        raise ValueError, "'%s' contains no id" % name
    i = 0
    while len(tmp) > 0 and tmp[-1] >= '0' and tmp[-1] <= '9':
        i *= 10
        i += int(tmp[-1])
        tmp = tmp[:-1]
    return i

def copy_file(source, target):
    try:
        source_fd = open(source, "r")
    except Exception, msg:
        print "ERROR: Failed to open '%s':" % source, msg
        return 1
    try:
        target_fd = open(target, "w")
    except Exception, msg:
        print "ERROR: Failed to open '%s':" % target, msg
        source_fd.close()
        return 1
    data = source_fd.read(65536)
    while data:
        target_fd.write(data)
        data = source_fd.read(65536)
    source_fd.close()
    target_fd.close()

def buildroot_copy(source, target):
    copy_file(buildroot+source, buildroot+target)

def chroot_device(device, chroot=None):
    if chroot:
        return realpath(chroot, device)
    return device

def compsLangsupport(comps, languages):
    pkgs = [ ]
    for group in comps.grouphash.keys():
        if comps.grouphash[group].has_key("langonly") and \
               comps.grouphash[group]["langonly"] in languages:
            optional_list = comps.getOptionalPackageNames(group)
            for (name, requires) in optional_list:
                for req in requires:
                    if req in pkgs:
                        print "Adding '%s' for langsupport" % name
                        pkgs.append(name)
                        break
    return pkgs
