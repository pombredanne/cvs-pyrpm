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

import os, os.path, stat, signal, string, time, resource, struct
from pyrpm.functions import normalizeList, runScript, labelCompare, evrSplit
from pyrpm.database import getRpmDB
from config import log, flog, rpmconfig
import pyrpm.se_linux as se_linux

################################## functions ##################################

def get_system_disks():
    disks = [ ]
    fd = None
    try:
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
                log.error("'/proc/partitions' malformed.")
                return
            if int(splits[1]) % 16 == 0: # minor%16=0 for harddisk devices
                hd = splits[3]
                if hd[0:4] == "loop":
                    continue
                disks.append("/dev/"+hd)
    finally:
        if fd:
            fd.close()
    return disks

def get_system_md_devices():
    map = { }
    fd = None
    try:
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
                log.error("'/proc/mdstat' malformed.")
                return
            map[splits[0]] = "/dev/%s" % splits[0]
    finally:
        if fd:
            fd.close()
    return map

def mounted_devices():
    # dict <mount point>:<filesystem type>
    mounted = [ ]
    fd = None
    try:
        try:
            fd = open("/proc/mounts", "r")
        except Exception, msg:
            log.error("Unable to open '/proc/mounts' for reading: %s", msg)
            return
        while 1:
            line = fd.readline()
            if not line:
                break
            margs = line.split()
            mounted.append(margs[0])
    finally:
        if fd:
            fd.close()
    return mounted

def load_release(chroot=""):
    f = "%s/etc/redhat-release" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    fd = None
    try:
        try:
            fd = open(f, "r")
        except:
            return None
        release = fd.readline()
    finally:
        if fd:
            fd.close()
    return release.strip()

def load_fstab(chroot=""):
    f = "%s/etc/fstab" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    fd = None
    try:
        try:
            fd = open(f, "r")
        except:
            return None
        fstab = [ ]
        while 1:
            line = fd.readline()
            if not line:
                break
            if len(line) < 1 or line[0] == "#":
                continue
            line = line.strip()
            splits = line.split()
            if len(splits) != 6:
                continue
            if (splits[4] == "1" and splits[5] in ["1", "2"]) or \
                   splits[1] == "swap":
                fstab.append(splits)
    finally:
        if fd:
            fd.close()
    return fstab

def load_mdadm_conf(chroot=""):
    f = "%s/etc/mdadm.conf" % chroot
    if not (os.path.exists(f) and os.path.isfile(f)):
        return None
    fd = None
    try:
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
    finally:
        if fd:
            fd.close()
    return conf

def get_installation_info(device, fstype, dir):
    # try to mount partition and search for release, fstab and
    # mdadm.conf
    log.info2("Mounting '%s' on '%s'", device, dir)
    try:
        mount(device, dir, fstype=fstype, options="ro")
    except Exception, msg:
        log.info2("Failed to mount '%s'.", device)
    else:
        dict = { }
        # anaconda does not support updates where /etc is
        # an extra filesystem
        _release = load_release(dir)
        _fstab = load_fstab(dir)
        _mdadm = load_mdadm_conf(dir)
        log.info2("Umounting '%s' ", dir)
        umount(dir)
        dict["release"] = "-- unknown --"
        if _release:
            dict["release"] = _release
        if _mdadm:
            dict["mdadm-conf"] = _mdadm
        if _fstab:
            dict["fstab"] = _fstab
            return dict
    return None

def get_buildstamp_info(dir):
    release = version = arch = None
    buildstamp = "%s/.buildstamp" % dir
    fd = None
    try:
        try:
            fd = open(buildstamp, "r")
        except Exception, msg:
            return None
        lines = fd.readlines()
    finally:
        if fd:
            fd.close()

    if len(lines) < 3:
        if len(lines) == 1:
            # RHEL-2.1
            release = "Red Hat Enterprise Linux"
            version = "2.1"
        else:
            log.error("Buildstamp information in '%s' is malformed.", dir)
            return None

    date = string.strip(lines[0])
    if len(lines) > 2:
        release = string.strip(lines[1])
        version = string.strip(lines[2])
    i = date.find(".")
    if i != -1 and len(date) > i+1:
        arch = date[i+1:]
        date = date[:i]
    del lines

    return (release, version, arch)

def get_discinfo(discinfo):
    release = version = arch = None

    # This should be using the cache to also work for http/ftp.
    fd = None
    try:
        try:
            fd = open(discinfo, "r")
        except Exception, msg:
            return None
        lines = fd.readlines()
    finally:
        if fd:
            fd.close()

    if len(lines) < 4:
        log.error("Discinfo in '%s' is malformed.", discinfo)
        return None

    #date = string.strip(lines[0])
    # fix bad fedora core 5 entry
    if string.strip(lines[1]) == "Fedora Core":
        lines[1] = "Fedora Core 5"
    i = string.rfind(string.strip(lines[1]), " ")
    if i == -1:
        log.error("Discinfo in '%s' is malformed.", discinfo)
        return None
    release = string.strip(lines[1][:i])
    version = string.strip(lines[1][i:])
    arch = string.strip(lines[2])
    del lines

    return (release, version, arch)

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

def get_installed_kernels(chroot=None):
    kernels = [ ]

    rpmdb = getRpmDB(rpmconfig, "/var/lib/rpm", chroot)
    rpmdb.open()
    if not rpmdb.read():
        return kernels
    hash = rpmdb.searchProvides("kernel", 0, "")
    rpmdb.close()

    version = { }
    for pkg in hash:
        ver = "%s-%s" % (pkg["version"], pkg["release"])
        if pkg["name"][:7] == "kernel-":
            ver += pkg["name"][7:]
        version[pkg] = ver

    sorted_list = [ ]
    for pkg in hash:
        found = False
        evr = evrSplit(version[pkg])
        for j in xrange(len(sorted_list)):
            pkg2 = sorted_list[j]
            evr2 = evrSplit(version[pkg2])
            if labelCompare(evr, evr2) > 0:
                sorted_list.insert(j, pkg)
                found = True
                break
        if not found:
            sorted_list.append(pkg)

    kernels = [ version[pkg] for pkg in sorted_list ]
    return kernels

def fuser(what):
    # first stage: close own files
    i = 0
    mypid = os.getpid()
    while 1:
        lsof = "/usr/sbin/lsof -Fpf +D '%s' 2>/dev/null" % what
        (status, rusage, msg) = runScript(script=lsof)
        if msg == "":
            break
        lines = msg.strip().split()
        for j in xrange(len(lines)):
            line = lines[j].strip()
            if not line or len(line) < 1 or line[0] != "p":
                continue
            if line != "p%d" % mypid:
                continue
            while j + 1 < len(lines):
                line = lines[j+1].strip()
                if not line or len(line) < 1 or line[0] != "f":
                    break
                try:
                    fd = int(line[1:])
                except:
                    pass
                else:
                    log.info2("Closing dangling fd %d", fd)
                    try:
                        os.close(fd)
                    except:
                        pass
                j += 1
        i += 1
        if i == 20:
            log.error("Failed to close open files.")
            break

    # second stage: kill programs
    i = 0
    sig = signal.SIGTERM
    while 1:
        lsof = "/usr/sbin/lsof -t +D '%s' 2>/dev/null" % what
        (status, rusage, msg) = runScript(script=lsof)
        if msg == "":
            break
        pids = msg.strip().split()
        if len(pids) == 0:
            break
        for pid in pids:
            try:
                p = int(pid)
            except:
                continue
            if p == os.getpid():
                # do not kill yourself
                continue
            try:
                os.kill(p, sig)
            except:
                continue
        i += 1
        if i == 20:
            log.error("Failed to kill processes:")
            os.system("/usr/sbin/lsof +D '%s'" % what)
            break
        if i > 15:
            time.sleep(1)
        if i > 10:
            sig = signal.SIGKILL

def umount_all(dir):
    # umount target dir and included mount points
    mounted = [ ]
    fstype = { }
    fd = None
    try:
        try:
            fd = open("/proc/mounts", "r")
        except Exception, msg:
            log.error("Unable to open '/proc/mounts' for reading: %s", msg)
            return
        while 1:
            line = fd.readline()
            if not line:
                break
            margs = line.split()
            i = margs[1].find(dir)
            if i == 0:
                mounted.append(margs[1])
                fstype[margs[1]] = margs[2]
    finally:
        if fd:
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
        log.info2("Umounting '%s' ", dir)
        failed = 0
        if fstype[dir] not in [ "sysfs", "proc" ]:
            fuser(dir)
        if umount(dir) == 1:
            failed = 1
            i += 1
        else:
            mounted.pop(i)
        if i >= len(mounted):
            time.sleep(1)
            i = 0
            count -= 1

    return failed

def zero_device(device, size, offset=0):
    fd = None
    try:
        fd = open(device, "wb")
        fd.seek(offset)
        i = 0
        while i < size:
            fd.write("\0")
            i += 1
    finally:
        if fd:
            fd.close()

def check_dir(buildroot, dir):
    d = buildroot+dir
    try:
        check_exists(buildroot, dir)
    except:
        log.error("Directory '%s' does not exist.", dir)
        return 0
    if not os.path.isdir(d):
        log.error("'%s' is no directory.", dir)
        return 0
    return 1

def create_dir(buildroot, dir, mode=None):
    d = "%s/%s" % (buildroot, dir)
    try:
        check_exists(buildroot, dir)
    except:
        try:
            os.makedirs(d)
        except Exception, msg:
            raise IOError, "Unable to create '%s': %s" % (dir, msg)
    else:
        if not os.path.isdir(d):
            raise IOError, "'%s' is no directory." % dir
    if mode != None:
        os.chmod(d, mode)
    set_SE_context(buildroot, dir)

def create_link(buildroot, source, target):
    t = "%s/%s" % (buildroot, target)
    try:
        check_exists(buildroot, target)
    except:
        try:
            os.symlink("../%s" % source, t)
        except Exception, msg:
            raise IOError, "Unable to generate %s symlink: %s" % (target, msg)
    else:
        if not os.path.islink(t):
            raise IOError, "'%s' is not a link." % target
    set_SE_context(buildroot, target)

def realpath(buildroot, path):
    t = "%s/%s" % (buildroot, path)
    if os.path.islink(t):
        t = buildroot + os.readlink(t)
    return t

def check_exists(buildroot, target):
    if not os.path.exists("%s/%s" % (buildroot, target)) and \
           not os.path.exists(realpath(buildroot, target)):
        raise IOError, "%s is missing." % target

def create_file(buildroot, target, content=None, force=0, mode=None):
    t = "%s/%s" % (buildroot, target)
    try:
        check_exists(buildroot, target)
    except:
        pass
    else:
        if not force:
            return -1
    fd = None
    try:
        try:
            fd = open(t, "w")
        except Exception, msg:
            log.error("Unable to open '%s' for writing: %s", target, msg)
            return 0
        if content:
            try:
                for line in content:
                    fd.write(line)
            except Exception, msg:
                log.error("Unable to write to '%s': %s", target, msg)
                return 0
    finally:
        if fd:
            fd.close()
    if mode != None:
        os.chmod(t, mode)
    set_SE_context(buildroot, target)

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
    if os.path.exists(t):
        return
    try:
        if s_linkto:
            create_dir(target_dir, os.path.dirname(s_linkto))
            create_device(target_dir, s_linkto, stats.st_mode,
                          os.major(stats.st_rdev), os.minor(stats.st_rdev))
            create_dir(target_dir, os.path.dirname(target))
            os.symlink(s_linkto, t)
        else:
            create_device(target_dir, target, stats.st_mode,
                          os.major(stats.st_rdev), os.minor(stats.st_rdev))
    except Exception, msg:
        raise IOError, "Unable to copy device '%s': %s" % (s, msg)

def create_device(buildroot, name, stat, major, minor):
    t = "%s/%s" % (buildroot, name)
    if not os.path.exists(t):
        os.mknod(t, stat, os.makedev(major, minor))
        set_SE_context(buildroot, name)

def set_SE_context(buildroot, filename):
    t = "%s/%s" % (buildroot, filename)
    if rpmconfig.selinux_enabled:
        st = os.stat(t)
        context = se_linux.matchpathcon(filename, st.st_mode)
        se_linux.lsetfilecon(t, context[1])

def create_min_devices(buildroot):
    create_device(buildroot, "/dev/console", 0666 | stat.S_IFCHR, 5, 1)
    create_device(buildroot, "/dev/null", 0666 | stat.S_IFCHR, 1, 3)
    create_device(buildroot, "/dev/urandom", 0666 | stat.S_IFCHR, 1, 9)
    create_device(buildroot, "/dev/zero", 0666 | stat.S_IFCHR, 1, 5)

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
    source_fd = target_fd = None
    try:
        try:
            source_fd = open(source, "r")
        except Exception, msg:
            log.error("Failed to open '%s': %s", source, msg)
            return 1
        try:
            target_fd = open(target, "w")
        except Exception, msg:
            log.error("Failed to open '%s': %s", target, msg)
            return 1
        data = source_fd.read(65536)
        while data:
            target_fd.write(data)
            data = source_fd.read(65536)
    finally:
        if source_fd:
            source_fd.close()
        if target_fd:
            target_fd.close()

def buildroot_copy(buildroot, source, target):
    copy_file(buildroot+source, buildroot+target)

def chroot_device(device, chroot=None):
    if chroot:
        return realpath(chroot, device)
    return device

def mount_cdrom(dir):
    what = "/dev/cdrom"
    log.debug1("Mounting '%s' on '%s'", what, dir)
    mount(what, dir, fstype="auto", options="ro")
    return "file://%s" % dir

def mount_nfs(url, dir, options=None):
    if url[:6] != "nfs://":
        raise ValueError, "'%s' is no valid nfs url." % url

    what = url[6:]
    splits = what.split("/", 1)
    if splits[0][-1] != ":":
        what = ":/".join(splits)
    del splits
    if not options:
        options = "ro,rsize=32768,wsize=32768,hard,nolock"
    # mount nfs source
    log.debug1("Mounting '%s' on '%s'", what, dir)
    mount(what, dir, fstype="nfs", options=options)
    return "file://%s" % dir

def run_script(command, chroot=''):
    if chroot != '':
        flog.debug1("'%s' in '%s'", command, chroot, nofmt=1)
    else:
        flog.debug1(command, nofmt=1)
    (status, rusage, msg) = runScript(script=command, chroot=chroot)
    flog.info1(msg, nofmt=1)
    return status

def run_ks_script(dict, chroot):
    interpreter = "/bin/sh"
    if dict.has_key("interpreter"):
        interpreter = dict["interpreter"]
    (status, rusage, msg) = runScript(interpreter, dict["script"],
                                      chroot=chroot)
    flog.info1(msg, nofmt=1)
    if status != 0:
        if dict.has_key("erroronfail"):
            log.error("Script failed, aborting.")
            return 0
        else:
            log.warning("Script failed.")

    return 1

############################ filesystem functions ############################

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
    mount = "/bin/mount %s %s %s '%s' '%s' 2>/dev/null" % (args, opts,
                                                           _fstype, what,
                                                           where)
    stat = os.system(mount)
    if stat != 0:
        raise IOError, "mount of '%s' on '%s' failed" % (what , where)


def umount(what):
    stat = os.system("/bin/umount '%s' 2>/dev/null" % what)
    if stat != 0:
        log.error("Umount of '%s' failed.", what)
        return 1

    return 0

def swapon(device):
    swapon = "/sbin/swapon '%s'" % device
    log.info1("Enable swap on '%s'.", device)
    if run_script(swapon) != 0:
        log.error("swapon failed.")
        return 1
    return 0

def swapoff(device):
    swapoff = "/sbin/swapoff '%s'" % device
    log.info1("Disable swap on '%s'.", device)
    if run_script(swapoff) != 0:
        log.error("swapoff failed.")
        return 1
    return 0

def detectFstype(device):
    pagesize = resource.getpagesize()

    # open device
    fd = None
    try:
        try:
            fd = open(device, "r")
        except Exception, msg:
            log.debug2(msg)
            return None

        # read pagesize bytes (at least needed for swap)
        try:
            buf = fd.read(pagesize)
        except: # ignore message
            return None
        if len(buf) < pagesize:
            return None

        ext2magic = ext2_journal = ext2_has_journal = 0
        try:
            (ext2magic,) = struct.unpack("H", buf[1024+56:1024+56+2])
            (ext2_journal,) = struct.unpack("I", buf[1024+96:1024+96+4])
            (ext2_has_journal,) = struct.unpack("I", buf[1024+92:1024+92+4])
        except Exception, msg:
            raise Exception, msg

        if ext2magic == 0xEF53:
            if ext2_journal & 0x0008 == 0x0008 or \
                   ext2_has_journal & 0x0004 == 0x0004:
                return "ext3"
            return "ext2"

        elif buf[pagesize - 10:] == "SWAP_SPACE" or \
               buf[pagesize - 10:] == "SWAPSPACE2":
            return "swap"
        elif buf[0:4] == "XFSB":
            return "xfs"

        # check for jfs
        try:
            fd.seek(32768, 0)
            buf = fd.read(180)
        except: # ignore message
            return None
        if len(buf) < 180:
            return None
        if buf[0:4] == "JFS1":
            return "jfs"
    finally:
        if fd:
            fd.close()

    return None

def ext2Label(device):
    # open device
    fd = None
    try:
        try:
            fd = open(device, "r")
        except: # ignore message
            return None
        # read 1160 bytes
        try:
            fd.seek(1024, 0)
            buf = fd.read(136)
        except: # ignore message
            return None
    finally:
        if fd:
            fd.close()

    label =None
    if len(buf) == 136:
        (ext2magic,) = struct.unpack("H", buf[56:56+2])
        if ext2magic == 0xEF53:
            label = string.rstrip(buf[120:120+16],"\0x00")
    return label


def xfsLabel(device):
    # open device
    fd = None
    try:
        try:
            fd = open(device, "r")
        except: # ignore message
            return None
        # read 128 bytes
        try:
            buf = fd.read(128)
        except: # ignore message
            return None
    finally:
        if fd:
            fd.close()

    label =None
    if len(buf) == 128 and buf[0:4] == "XFSB":
        label = string.rstrip(buf[108:120],"\0x00")
    return label

def jfsLabel(device):
    # open device
    fd = None
    try:
        try:
            fd = open(device, "r")
        except: # ignore message
            return None
        # seek to 32768, read 180 bytes
        try:
            fd.seek(32768, 0)
            buf = fd.read(180)
        except: # ignore message
            return None
    finally:
        if fd:
            fd.close()

    label =None
    if len(buf) == 180 and buf[0:4] == "JFS1":
        label = string.rstrip(buf[152:168],"\0x00")
    return label

def swapLabel(device):
    pagesize = resource.getpagesize()

    # open device
    fd = None
    try:
        try:
            fd = open(device, "r")
        except: # ignore message
            return None
        # read pagesize bytes
        try:
            buf = fd.read(pagesize)
        except: # ignore message
            return None
    finally:
        if fd:
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
