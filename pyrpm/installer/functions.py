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

import os, os.path, stat, signal
import pyrpm.functions as functions
import pyrpm.database as database
import pyrpm.config
import config
from filesystem import *
from installer import Repository

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

def mounted_devices():
    # dict <mount point>:<filesystem type>
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
        mounted.append(margs[0])
    fd.close()
    return mounted

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
        if len(line) < 1 or line[0] == "#":
            continue
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

def get_installation_info(device, fstype, dir):
    # try to mount partition and search for release, fstab and
    # mdadm.conf
    if config.verbose:
        print "Mounting '%s' on '%s'" % (device, dir)
    try:
        mount(device, dir, fstype=fstype, options="ro")
    except Exception, msg:
        if config.verbose:
            print "Failed to mount '%s'." % device
            return None
    else:
        dict = { }
        # anaconda does not support updates where /etc is
        # an extra filesystem
        _release = load_release(dir)
        _fstab = load_fstab(dir)
        _mdadm = load_mdadm_conf(dir)
        if config.verbose:
            print "Umounting '%s' " % dir
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
    release = version = arch = date = None

    buildstamp = "%s/.buildstamp" % dir
    try:
        fd = open(buildstamp, "r")
    except Exception, msg:
        return None

    lines = fd.readlines()
    fd.close()

    if len(lines) < 3:
        if len(lines) == 1:
            # RHEL-2.1
            release = "Red Hat Enterprise Linux"
            version = "2.1"
        else:
            print "ERROR: Buildstamp information in '%s' is malformed." % dir
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
    release = version = arch = date = None

    # This should be using the cache to also work for http/ftp.
    try:
        fd = open(discinfo, "r")
    except Exception, msg:
        return None

    lines = fd.readlines()
    fd.close()

    if len(lines) < 4:
        print "ERROR: .discinfo in '%s' is malformed." % discinfo
        return None

    date = string.strip(lines[0])
    # fix bad fedora core 5 entry
    if string.strip(lines[1]) == "Fedora Core":
        lines[1] = "Fedora Core 5"
    i = string.rfind(string.strip(lines[1]), " ")
    if i == -1:
        print "ERROR: .discinfo in '%s' is malformed." % discinfo
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

def fuser(what):
    i = 0
    log = ""

    sig = signal.SIGTERM
    while 1:
        lsof = "/usr/sbin/lsof -t +D '%s' 2>/dev/null" % what
        (status, rusage, msg) = functions.runScript(script=lsof)
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
            os.kill(p, sig)
        i += 1
        if i == 20:
            print "ERROR: Failed to kill processes:"
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
            fstype[margs[1]] = margs[2]
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
    if mode != None:
        os.chmod("%s/%s" % (buildroot, target), mode)
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
            os.mknod("%s/%s" % (target_dir, s_linkto), stats.st_mode,
                     stats.st_rdev)
            create_dir(target_dir, os.path.dirname(target))
            os.symlink(s_linkto, t)
        else:
            os.mknod(t, stats.st_mode, stats.st_rdev)
    except Exception, msg:
        raise IOError, "Unable to copy device '%s': %s" % (s, msg)

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

def buildroot_copy(buildroot, source, target):
    copy_file(buildroot+source, buildroot+target)

def chroot_device(device, chroot=None):
    if chroot:
        return realpath(chroot, device)
    return device

def _compsLangsupport(pkgs, comps, languages, group):
    if not comps.grouphash.has_key(group):
        return

    if not comps.grouphash[group].has_key("langonly") or \
           not comps.grouphash[group]["langonly"] in languages:
        return

    # add grouplist
    if comps.grouphash[group].has_key("grouplist"):
        for _group in comps.grouphash[group]["grouplist"]["groupreqs"]:
            _compsLangsupport(pkgs, comps, languages, _group)
        for _group in comps.grouphash[group]["grouplist"]["metapkgs"]:
            _compsLangsupport(pkgs, comps, languages, _group)

    for name in comps.getPackageNames(group):
        if name in pkgs:
            continue
        print "Adding package '%s' for langsupport" % name
        pkgs.append(name)

    # old style conditional
    optional_list = comps.getOptionalPackageNames(group)
    for (name, requires) in optional_list:
        if name in pkgs:
            continue
        for req in requires:
            if req in pkgs:
                print "Adding package '%s' for langsupport" % name
                pkgs.append(name)
                break

    # new style conditional
    conditional_list = comps.getConditionalPackageNames(group)
    for (name, requires) in conditional_list:
        if name in pkgs:
            continue
        for req in requires:
            if req in pkgs:
                print "Adding package '%s' for langsupport" % name
                pkgs.append(name)
                break

def compsLangsupport(pkgs, comps, languages):
    for group in comps.grouphash.keys():
        _compsLangsupport(pkgs, comps, languages, group)

def addPkgByFileProvide(repo, name, pkgs, description):
    s = repo.searchFilenames(name)
    if len(s) == 0:
        if not repo._matchesFile(name):
            repo.importFilelist()
            s = repo.searchFilenames(name)
    if len(s) > 0:
        found = False
        for pkg in s:
            if pkg["name"] in pkgs:
                found = True
                break
        if not found:
            pkg = s[0]
            print "Adding package '%s' for %s." % (pkg["name"], description)
            pkgs.append(pkg["name"])
    else:
        raise ValueError, "Could not find package providing '%s'" % (name) + \
              "needed for %s." % (description)

def load_source_repo(ks, source_dir):
    source = Repository(pyrpm.rpmconfig, source_dir, "base")

    exclude = None
    if ks.has_key("cdrom"):
        url = "cdrom"
        if ks["cdrom"].has_key("exclude"):
            exclude = ks["cdrom"]["exclude"]
    elif ks.has_key("nfs"):
        url = "nfs://%s:%s" % (ks["nfs"]["server"], ks["nfs"]["dir"])
        if ks["nfs"].has_key("exclude"):
            exclude = ks["nfs"]["exclude"]
    else:
        url = ks["url"]["url"]
        if ks["url"].has_key("exclude"):
            exclude = ks["url"]["exclude"]

    print "Reading repodata from installation source ..."
    if not source.load(url, exclude=exclude):
        raise IOError, "Loading of source failed."

    if not source.comps:
        raise IOError, "There is no comps.xml in installation source."

    return source

def load_repos(ks, repos_dir):
    if not ks.has_key("repo"):
        return { }

    repos = { }
    failed = [ ]
    for repo in ks["repo"]:
        repos[repo] = Repository(pyrpm.rpmconfig,
                                 "%s/%s" % (repos_dir, repo), repo)
        print "Reading repodata from repository '%s'" % repo
        baseurl = mirrorlist = exclude = None
        if ks["repo"][repo].has_key("baseurl"):
            baseurl = ks["repo"][repo]["baseurl"]
        if ks["repo"][repo].has_key("mirrorlist"):
            # TODO: as soon as RepoDB supports mirrorlist directly...
            mirrorlist = ks["repo"][repo]["mirrorlist"]
        if ks["repo"][repo].has_key("exclude"):
            exclude = ks["repo"][repo]["exclude"]
        if not repos[repo].load(baseurl, mirrorlist=mirrorlist,
                                exclude=exclude):
            failed.append(repo)

    if len(failed) > 0:
        raise IOError, "Loading of repo '%s' failed." % "', '".join(failed)

    return repos

def release_info(source):
    # get source information via release package
    release = "Red Hat Enterprise Linux"
    pkgs = source.repo.getPkgsByName("redhat-release")
    if len(pkgs) == 0:
        release = "Fedora Core"
        pkgs = source.repo.getPkgsByName("fedora-release")
    if len(pkgs) == 0:
        raise ValueError, "Could not find release package in source."
    if len(pkgs) > 1:
        raise ValueError, "Found more than one release package, exiting."
    version = pkgs[0]["version"]
    arch = pkgs[0]["arch"]
    # drop all letters from version
    version = version.strip(string.letters)
    if len(version) == 0:
        raise ValueError, "No valid version of installation source"
    i = string.find(pkgs[0]["release"], "rawhide")
    if i != -1 and string.find(version, ".") == -1:
        version += ".90" # bad fix for rawhide
    del i

    if arch == "noarch":
        # get installation arch
        pkgs = source.repo.getPkgsByName("filesystem")
        if len(pkgs) != 1 or pkgs[0]["arch"] == "noarch":
            pkgs = source.repo.getPkgsByName("coreutils")
        if len(pkgs) != 1 or pkgs[0]["arch"] == "noarch":
            raise ValueError, "Could not determine installation architecture."
        arch = pkgs[0]["arch"]

    return (release, version, arch)

def run_script(dict, chroot):
    interpreter = "/bin/sh"
    if dict.has_key("interpreter"):
        interpreter = dict["interpreter"]
    (status, rusage, msg) = pyrpm.runScript(interpreter, dict["script"],
                                            chroot=chroot)
    if status != 0:
        info(msg)
        if dict.has_key("erroronfail"):
            print "ERROR: Script failed, aborting."
            return 0
        else:
            print "WARNING: Script failed."
    else:
        log(msg)

    return 1

# vim:ts=4:sw=4:showmatch:expandtab
