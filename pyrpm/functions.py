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
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
#


import os, os.path, sys, resource, re
from types import TupleType
from tempfile import mkstemp
from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, S_ISBLK, S_IMODE
from config import rpmconfig
from base import *


# Collection of class indepedant helper functions
def runScript(prog=None, script=None, arg1=None, arg2=None):
    if prog == None:
        prog = "/bin/sh"
    if not os.path.exists("/var/tmp"):
        os.makedirs("/var/tmp")
    args = [prog]
    if script != None:
        (fd, tmpfilename) = mkstemp(dir="/var/tmp/", prefix="rpm-tmp.")
        if fd == None:
            return 0
        os.write(fd, script)
        os.close(fd)
        fd = None
        args.append(tmpfilename)
        if arg1 != None:
            args.append(arg1)
        if arg2 != None:
            args.append(arg2)
    (rfd, wfd) = os.pipe()
    pid = os.fork()
    if pid != 0:
        os.close(wfd)
        cret = ""
        cout = os.read(rfd, 8192)
        while cout != "":
            cret += cout
            cout = os.read(rfd, 8192)
        os.close(rfd)
        (cpid, status) = os.waitpid(pid, 0)
    else:
        fd = os.open("/dev/null", os.O_RDONLY)
        if fd != 0:
            os.dup2(fd, 0)
        if wfd != 1:
            os.dup2(wfd, 1)
        os.dup2(1, 2)
        closeAllFDs()
        os.chdir("/")
        os.putenv("PATH", "/sbin:/bin:/usr/sbin:/usr/bin:/usr/X11R6/bin")
        os.execv(prog, args)
        sys.exit(255)
    if script != None:
        os.unlink(tmpfilename)
    if status != 0:
        printError("Error in running script:")
        printError(str(prog))
        printError(str(args))
        printError(cret)
        return 0
    return 1

def installFile(rfi, data):
    mode = rfi.mode
    if S_ISREG(mode):
        makeDirs(rfi.filename)
        (fd, tmpfilename) = mkstemp(dir=os.path.dirname(rfi.filename),
            prefix=rfi.filename + ".")
        if not fd:
            return 0
        if os.write(fd, data) < 0:
            os.close(fd)
            os.unlink(tmpfilename)
            return 0
        os.close(fd)
        if not setFileMods(tmpfilename, rfi.uid, rfi.gid, mode, rfi.mtime):
            os.unlink(tmpfilename)
            return 0
        if os.rename(tmpfilename, rfi.filename) != None:
            return 0
    elif S_ISDIR(mode):
        if os.path.isdir(rfi.filename):
            if not setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime):
                return 0
            return 1
        os.makedirs(rfi.filename)
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime):
            return 0
    elif S_ISLNK(mode):
        symlinkfile = data.rstrip("\x00")
        if os.path.islink(rfi.filename) \
            and os.readlink(rfi.filename) == symlinkfile:
            return 1
        makeDirs(rfi.filename)
        try:
            os.unlink(rfi.filename)
        except:
            pass
        os.symlink(symlinkfile, rfi.filename)
        if os.lchown(rfi.filename, rfi.uid, rfi.gid) != None:
            return 0
    elif S_ISFIFO(mode):
        makeDirs(rfi.filename)
        if not os.path.exists(rfi.filename) and os.mkfifo(rfi.filename) != None:
            return 0
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime):
            os.unlink(rfi.filename)
            return 0
    elif S_ISCHR(mode) or S_ISBLK(mode):
        makeDirs(rfi.filename)
        try:
            os.mknod(rfi.filename, mode, rfi.rdev)
        except:
            pass
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(mode))
    return 1

def setFileMods(filename, uid, gid, mode, mtime):
    try:
        os.chown(filename, uid, gid)
    except:
        return 0
    try:
        os.chmod(filename, S_IMODE(mode))
    except:
        return 0
    try:
        os.utime(filename, (mtime, mtime))
    except:
        return 0
    return 1

def makeDirs(fullname):
    idx = fullname.rfind("/")
    if idx > 0:
        dirname = fullname[:idx]
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

def listRpmDir(dirname):
    """List directory like standard or.listdir, but returns only .rpm files"""
    fls = os.listdir(dirname)
    files = [] 
    for f in fls:
        if f.endswith('.rpm'):
            files.append(f)
    return files

def createLink(src, dst):
    try:
        # First try to unlink the defered file
        os.unlink(dst)
    except:
        pass
    # Behave exactly like cpio: If the hardlink fails (because of different
    # partitions), then it has to fail
    if os.link(src, dst) != None:
        return 0
    return 1

def closeAllFDs():
    for fd in range(3, resource.getrlimit(resource.RLIMIT_NOFILE)[1]):
        try:
            os.close(fd)
        except:
            pass

def getFreeDiskspace(pkglist):
    freehash = {}
    dirhash = {}
    if rpmconfig.buildroot:
        br = rpmconfig.buildroot
    else:
        br = "/"
    for pkg in pkglist:
        if not pkg.has_key("dirnames"):
            continue
        for dirname in pkg["dirnames"]:
            if not dirhash.has_key(dirname):
                devdir = br + dirname
                while not os.path.exists(devdir):
                    devdir = os.path.dirname(devdir)
                dev = os.stat(devdir)[2]
                dirhash[dirname] = dev
                if not freehash.has_key(dev):
                    (f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, f_files, f_ffree, f_favail, f_flag, f_namemax) = os.statvfs(devdir)
                    freehash[dev] = f_bsize * f_bavail
        filenames = pkg["filenames"]
        for i in xrange(len(filenames)):
            dirname = pkg["dirnames"][pkg["dirindexes"][i]]
            freehash[dirhash[dirname]] -= pkg["filesizes"][i]
    return freehash

# Error handling functions
def printDebug(level, msg):
    if level <= rpmconfig.debug_level:
        sys.stdout.write("Debug: %s\n" % msg)
        sys.stdout.flush()
    return 0

def printInfo(level, msg):
    if level <= rpmconfig.verbose_level:
        sys.stdout.write(msg)
        sys.stdout.flush()
    return 0

def printWarning(level, msg):
    if level <= rpmconfig.warning_level:
        sys.stdout.write("Warning: %s\n" % msg)
        sys.stdout.flush()
    return 0

def printError(msg):
    sys.stderr.write("Error: %s\n" % msg)
    sys.stderr.flush()
    return 0

def raiseFatal(msg):
    raise ValueError, "Fatal: %s\n" % msg

# ----------------------------------------------------------------------------

# split EVR in epoch, version and release
def evrSplit(evr):
    i = 0
    p = evr.find(":") # epoch
    if p != -1:
        epoch = evr[:p]
        i = p + 1
    else:
        epoch = "0"
    p = evr.find("-", i) # version
    if p != -1:
        version = evr[i:p]
        release = evr[p+1:]
    else:
        version = evr[i:]
        release = ""
    return (epoch, version, release)

# split [e:]name-version-release.arch into the 4 possible subcomponents.
def envraSplit(envra):
    # Find the epoch separator
    i = envra.find(":")
    if i >= 0:
        epoch = envra[:i]
        envra = envra[i+1:]
    else:
        epoch = None
    # Search for last '.' and the last '-'
    i = envra.rfind(".")
    j = envra.rfind("-")
    # Arch can't have a - in it, so we can only have an arch if the last '.'
    # is found after the last '-'
    if i >= 0 and i>j:
        arch = envra[i+1:]
        envra = envra[:i]
    else:
        arch = None
    # If we found a '-' we assume for now it's the release
    if j >= 0:
        release = envra[j+1:]
        envra = envra[:j]
    else:
        release = None
    # Look for second '-' and store in version
    i = envra.rfind("-")
    if i >= 0:
        version = envra[i+1:]
        envra = envra[:i]
    else:
        version = None
    # If we only found one '-' it has to be the version but was stored in
    # release, so we need to swap them (version would be None in that case)
    if version == None and release != None:
        version = release
        release = None
    return (epoch, envra, version, release, arch)


# locale independend string methods
def _xislower(chr): return (chr >= 'a' and chr <= 'z')
def _xisupper(chr): return (chr >= 'A' and chr <= 'Z')
def _xisalpha(chr): return (_xislower(chr) or _xisupper(chr))
def _xisdigit(chr): return (chr >= '0' and chr <= '9')
def _xisalnum(chr): return (_xisalpha(chr) or _xisdigit(chr))

# compare two strings
def stringCompare(str1, str2):
    if str1 == "" and str2 == "": return 0;
    elif str1 == "" and str2 != "": return -1;
    elif str1 != "" and str2 == "": return 1;
    elif str1 == str2: return 0;

    i1 = i2 = 0
    while i1 < len(str1) and i2 < len(str2):
        # remove leading separators
        while i1 < len(str1) and not _xisalnum(str1[i1]): i1 += 1
        while i2 < len(str2) and not _xisalnum(str2[i2]): i2 += 1
        j1 = i1
        j2 = i2

        # search for numbers and comprare them
        while j1 < len(str1) and _xisdigit(str1[j1]): j1 += 1
        while j2 < len(str2) and _xisdigit(str2[j2]): j2 += 1
        if j1 > i1 or j2 > i1:
            if j1 == i1: return -1
            if j2 == i2: return 1
            if j1-i1 < j2-i2: return -1
            if j1-i1 > j2-i2: return 1
            while i1 < j1 and i2 < j2:
                if int(str1[i1]) < int(str2[i2]): return -1
                if int(str1[i1]) > int(str2[i2]): return 1
                i1 += 1
                i2 += 1
            # found right side 
            if i1 == len(str1): return -1
            if i2 == len(str2): return 1
        if i2 == len(str2): return -1

        # search for alphas and compare them
        while j1 < len(str1) and _xisalpha(str1[j1]): j1 += 1
        while j2 < len(str2) and _xisalpha(str2[j2]): j2 += 1
        if j1 > i1 or j2 > i1:
            if j1 == i1: return -1
            if j2 == i2: return 1
            if str1[i1:j1] < str2[i2:j2]: return -1
            if str1[i1:j1] > str2[i2:j2]: return 1
            # found right side 
            i1 = j1
            i2 = j2

    # still no difference
    if i2 == len(str2):
        return 0
    else:
        if i1 == len(str1):
            return -1
        else:
            return 1

# internal EVR compare, uses stringCompare to compare epochs, versions and
# release versions
def labelCompare(e1, e2):
    if e2[2] == "": # no release
        e1 = (e1[0], e1[1], "")

    r = stringCompare(e1[0], e2[0])
    if r == 0: r = stringCompare(e1[1], e2[1])
    if r == 0: r = stringCompare(e1[2], e2[2])
# TODO: where is ignore_epoch from?
#    elif ignore_epoch == 1:
#        if stringCompare(e1[1], e2[1]) == 0:
#            if stringCompare(e1[2], e2[2]) == 0:
#                r = 0
    return r

# compares two EVR's with comparator
def evrCompare(evr1, comp, evr2):
    res = -1
    if isinstance(evr1, TupleType):
        e1 = evr1
    else:
        e1 = evrSplit(evr1)
    e2 = evrSplit(evr2)
    r = labelCompare(e1, e2)
    if r == -1:
        if comp & RPMSENSE_LESS:
            res = 1
    elif r == 0:
        if comp & RPMSENSE_EQUAL:
            res = 1
    else: # res == 1
        if comp & RPMSENSE_GREATER:
            res = 1
    return res

def depOperatorString(flag):
    """ generate readable operator """
    op = ""
    if flag & RPMSENSE_LESS:
        op = "<"
    if flag & RPMSENSE_GREATER:
        op += ">"
    if flag & RPMSENSE_EQUAL:
        op += "="
    return op

def depString((name, flag, version)):
    if version == "":
        return name
    return "%s %s %s" % (name, depOperatorString(flag), version)


def filterArchCompat(list, arch=None):
    # stage 1: filter packages which are not in compat arch
    if arch != None and arch != "noarch":
        i = 0
        while i < len(list):
            pkg = list[i]
            if not possible_archs.has_key(pkg["arch"]):
                printWarning(0, "%s: Unknow rpm package architecture %s" \
                    % (pkg.source, pkg["arch"]))
                list.pop(i)
                continue
            if pkg["arch"] != arch and pkg["arch"] not in arch_compats[arch]:
                printWarning(0, "%s: Architecture not compatible with machine %s" % (pkg.source, arch))
                list.pop(i)
                continue
            i += 1
    return 1

def filterArchDuplicates(list):
    # stage 1: filert duplicates: order by name.arch
    myhash = {}
    i = 0
    while i < len(list):
        pkg = list[i]
        key = "%s.%s" % (pkg["name"], pkg["arch"])
        if not myhash.has_key(key):
            myhash[key] = pkg
            i += 1
        else:
            r = myhash[key]
            ret = labelCompare((r.getEpoch(), r["version"], r["release"]),
                (pkg.getEpoch(), pkg["version"], pkg["release"]))
            if ret < 0:
                printWarning(0, "%s was already added, replacing with %s" % \
                                   (r.getNEVRA(), pkg.getNEVRA()))
                myhash[key] = pkg
                list.remove(r)
            elif ret == 0:
                printWarning(1, "%s was already added" % \
                                   pkg.getNEVRA())
                list.pop(i)
            else:
                i += 1
    del myhash

    # stage 2: filter duplicates: order by name
    myhash = {}
    i = 0
    while i < len(list):
        pkg = list[i]
        removed = 0
        if not myhash.has_key(pkg["name"]):
            myhash[pkg["name"]] = [ ]
            myhash[pkg["name"]].append(pkg)
        else:
            j = 0
            while myhash[pkg["name"]] and j < len(myhash[pkg["name"]]) and \
                      removed == 0:
                r = myhash[pkg["name"]][j]
                if pkg["arch"] != r["arch"] and \
                       buildarchtranslate[pkg["arch"]] != \
                       buildarchtranslate[r["arch"]]:
                    j += 1
                elif r["arch"] in arch_compats[pkg["arch"]]:
                    printWarning(0, "%s was already added, replacing with %s" % \
                                       (r.getNEVRA(), pkg.getNEVRA()))
                    myhash[pkg["name"]].remove(r)
                    myhash[pkg["name"]].append(pkg)
                    list.remove(r)
                    removed = 1
                elif pkg["arch"] == r["arch"]:
                    printWarning(0, "%s was already added" % \
                                       pkg.getNEVRA())
                    list.pop(i) # remove 'pkg'
                    removed = 1
                else:
                    j += 1
            if removed == 0:
                myhash[pkg["name"]].append(pkg)
        if removed == 0:
            i += 1
    del myhash

    return 1

def filterArchList(list, arch=None):
    filterArchCompat(list, arch)
    filterArchDuplicates(list)

def normalizeList(list):
    """ normalize list """
    if len(list) < 2:
        return
    h = {}
    i = 0
    while i < len(list):
        item = list[i]
        if h.has_key(item):
            list.pop(i)
        else:
            h[item] = 1
            i += 1

def getBuildArchList(list):
    """Returns list of build architectures used in 'list' of packages"""
    archs = []
    for p in list:
        a = p['arch']
        if a == 'noarch':
            continue
        if a not in archs:
            archs.append(a)
    return archs

def tagsearch(searchtags, list, regex=None):
    pkglist = []
    st = []
    if regex:
        for (key, val) in searchtags:
            st.append([key, normalizeRegex(val)])
        searchtags = st
    for pkg in list:
        # If we have an epoch we need to check it
        found = 1
        for (key, val) in searchtags:
            if not pkg.has_key(key):
                found = 0
                break
            if key == "epoch":
                pval = str(pkg[key][0])
            else:
                pval = pkg[key]
            if not regex:
                if val != pval:
                    found = 0
                    break
            else:
                if not re.match(val, pval):
                    found = 0
                    break
        if found:
            pkglist.append(pkg)
    return pkglist

def normalizeRegex(regex):
    regex = regex.replace(".", "\.")
    regex = regex.replace("*", ".*")
    return regex

EPOCHTAG=0
NAMETAG=1
VERSIONTAG=2
RELEASETAG=3
ARCHTAG=4

def constructName(nametags, namevals):
    ret = ""
    for tag in nametags:
        if tag == EPOCHTAG:
            if namevals[EPOCHTAG] != None:
                ret += namevals[EPOCHTAG]
        if tag == NAMETAG:
            if namevals[NAMETAG] != None:
                if ret != "":
                    ret += ":"
                ret += namevals[NAMETAG]
        if tag == VERSIONTAG:
            if namevals[VERSIONTAG] != None:
                if ret != "":
                    ret += "-"
                ret += namevals[VERSIONTAG]
        if tag == RELEASETAG:
            if namevals[RELEASETAG] != None:
                if ret != "":
                    ret += "-"
                ret += namevals[RELEASETAG]
        if tag == ARCHTAG:
            if namevals[ARCHTAG] != None:
                if ret != "":
                    ret += "."
                ret += namevals[ARCHTAG]
    return ret

def __findPkgByName(pkgname, list, regex=None):
    """Find a package by name in a given list. Name can contain version,
release and arch. Returns a list of all matching packages, starting with
best match."""
    pkglist = []
    envra = envraSplit(pkgname)
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    if envra[RELEASETAG] != None:
        tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG], envra)), \
                ("version", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, list, regex))
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG], envra)), \
            ("version", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    if envra[RELEASETAG] != None:
        tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
                ("version", constructName([VERSIONTAG], envra)), \
                ("release", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, list, regex))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG], envra)), \
            ("release", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))

    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    if envra[RELEASETAG] != None:
        tags = [("epoch", constructName([EPOCHTAG], envra)), \
                ("name", constructName([NAMETAG, VERSIONTAG], envra)), \
                ("version", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, list, regex))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG], envra)), \
            ("version", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    if envra[RELEASETAG] != None:
        tags = [("epoch", constructName([EPOCHTAG], envra)), \
                ("name", constructName([NAMETAG], envra)), \
                ("version", constructName([VERSIONTAG], envra)), \
                ("release", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, list, regex))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG], envra)), \
            ("release", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, list, regex))
    filterArchList(pkglist)
    return pkglist

def findPkgByName(pkgname, list):
    pkglist = __findPkgByName(pkgname, list, None)
    if len(pkglist) == 0:
        pkglist = __findPkgByName(pkgname, list, 1)
    return pkglist

# vim:ts=4:sw=4:showmatch:expandtab
