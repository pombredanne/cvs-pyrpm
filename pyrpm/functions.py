#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
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


import os, os.path, sys, resource, re, getopt, errno
from urlgrabber import urlgrab
from urlgrabber.grabber import URLGrabError
from types import TupleType, ListType
from tempfile import mkstemp
from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, S_ISBLK, S_IMODE, S_ISSOCK
from config import rpmconfig
from base import *
from yumconfig import YumConf
import package

# Number of bytes to read from file at once when computing digests
DIGEST_CHUNK = 65536

# Collection of class indepedant helper functions
def runScript(prog=None, script=None, arg1=None, arg2=None, force=None):
    if prog == None:
        prog = "/bin/sh"
    if prog == "/bin/sh" and script == None:
        return 1
    if not os.path.exists("/var/tmp"):
        try:
            os.makedirs("/var", mode=0755)
        except:
            pass
        os.makedirs("/var/tmp", mode=01777)
    if isinstance(prog, TupleType):
        args = prog
    else:
        args = [prog]
    if not force and args == ["/sbin/ldconfig"] and script == None:
        if rpmconfig.delayldconfig == 1:
            rpmconfig.ldconfig += 1
        rpmconfig.delayldconfig = 1
        return 1
    elif rpmconfig.delayldconfig:
        rpmconfig.delayldconfig = 0
        runScript("/sbin/ldconfig", force=1)
    if script != None:
        (fd, tmpfilename) = mkstemp(dir="/var/tmp/", prefix="rpm-tmp.")
        if fd == None:
            return 0
        # test for open fds:
        # script = "ls -l /proc/$$/fd >> /$$.out\n" + script
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
    if pid == 0:
        os.close(rfd)
        if not os.path.exists("/dev"):
            os.mkdir("/dev")
        if not os.path.exists("/dev/null"):
            os.mknod("/dev/null", 0666, 259)
        fd = os.open("/dev/null", os.O_RDONLY)
        if fd != 0:
            os.dup2(fd, 0)
            os.close(fd)
        if wfd != 1:
            os.dup2(wfd, 1)
            os.close(wfd)
        os.dup2(1, 2)
        os.chdir("/")
        e = {"HOME": "/", "USER": "root", "LOGNAME": "root",
            "PATH": "/sbin:/bin:/usr/sbin:/usr/bin:/usr/X11R6/bin"}
        if isinstance(prog, TupleType):
            os.execve(prog[0], args, e)
        else:
            os.execve(prog, args, e)
        sys.exit(255)
    os.close(wfd)
    # no need to read in chunks if we don't pass on data to some output func
    cret = ""
    cout = os.read(rfd, 8192)
    while cout:
        cret += cout
        cout = os.read(rfd, 8192)
    os.close(rfd)
    (cpid, status) = os.waitpid(pid, 0)
    if script != None:
        os.unlink(tmpfilename)
    if status != 0: #or cret != "":
        if os.WIFEXITED(status):
            printError("Script %s ended with exit code %d:" % (str(args),
                os.WEXITSTATUS(status)))
        elif os.WIFSIGNALED(status):
            core = ""
            if os.WCOREDUMP(status):
                core = "(with coredump)"
            printError("Script %s killed by signal %d%s:" % (str(args),
                os.WTERMSIG(status), core))
        elif os.WIFSTOPPED(status):
            printError("Script %s stopped with signal %d:" % (str(args),
                os.WSTOPSIG(status)))
        else:
            printError("Script %s ended (fixme: reason unknown):" % str(args))
        if cret.endswith("\n"):
            cret = cret[:-1]
        printError(cret)
        return 0
    return 1

def installFile(rfi, infd, size):
    """Install a file described by RpmFileInfo rfi, with input of given size
    from CPIOFile infd.

    infd can be None if size == 0.  Raise IOError, OSError."""

    mode = rfi.mode
    if S_ISREG(mode):
        makeDirs(rfi.filename)
        (fd, tmpfilename) = mkstemp(dir=os.path.dirname(rfi.filename),
            prefix=rfi.filename + ".")
        try:
            try:
                data = "1"
                while size > 0 and data:
                    data = infd.read(65536)
                    if data:
                        size -= len(data)
                        os.write(fd, data)
            finally:
                os.close(fd)
            setFileMods(tmpfilename, rfi.uid, rfi.gid, mode, rfi.mtime)
        except (IOError, OSError):
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, rfi.filename)
    elif S_ISDIR(mode):
        if not os.path.isdir(rfi.filename):
            os.makedirs(rfi.filename)
        setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime)
    elif S_ISLNK(mode):
        data = infd.read(size)
        symlinkfile = data.rstrip("\x00")
        if os.path.islink(rfi.filename) \
            and os.readlink(rfi.filename) == symlinkfile:
            return
        makeDirs(rfi.filename)
        try:
            os.unlink(rfi.filename)
        except OSError:
            pass
        os.symlink(symlinkfile, rfi.filename)
        os.lchown(rfi.filename, rfi.uid, rfi.gid)
    elif S_ISFIFO(mode):
        makeDirs(rfi.filename)
        if not os.path.exists(rfi.filename):
            os.mkfifo(rfi.filename)
        try:
            setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime)
        except OSError:
            os.unlink(rfi.filename)
            raise
    elif S_ISCHR(mode) or S_ISBLK(mode):
        makeDirs(rfi.filename)
        try:
            os.mknod(rfi.filename, mode, rfi.rdev)
        except OSError:
            pass # FIXME: why?
        try:
            setFileMods(rfi.filename, rfi.uid, rfi.gid, mode, rfi.mtime)
        except OSError:
            os.unlink(rfi.filename)
            raise
    elif S_ISSOCK(mode):
        raise ValueError("UNIX domain sockets can't be packaged.")
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(mode))

def setFileMods(filename, uid, gid, mode, mtime):
    """Set owner, group, mode and mtime of filename to the specified values.

    Raise OSError."""
    
    os.chown(filename, uid, gid)
    os.chmod(filename, S_IMODE(mode))
    os.utime(filename, (mtime, mtime))

def makeDirs(fullname):
    idx = fullname.rfind("/")
    if idx > 0:
        dirname = fullname[:idx]
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

def listRpmDir(dirname):
    """List directory like standard or.listdir, but returns only .rpm files"""
    files = []
    for f in os.listdir(dirname):
        if f.endswith('.rpm'):
            files.append(f)
    return files

def createLink(src, dst):
    """Create a link from src to dst.

    Raise OSError."""
    
    try:
        # First try to unlink the defered file
        os.unlink(dst)
    except OSError:
        pass
    # Behave exactly like cpio: If the hardlink fails (because of different
    # partitions), then it has to fail
    os.link(src, dst)

def tryUnlock(lockfile):
    if not os.path.exists(lockfile):
        return 0
    fd = open(lockfile, 'r')
    try:
        oldpid = int(fd.readline())
    except ValueError:
        unlink(lockfile) # bogus data
    else:
        try:
            os.kill(oldpid, 0)
        except OSError, e:
            if e[0] == errno.ESRCH:
                unlink(lockfile) # pid doesn't exist
            else:
                return 1
        else:
            return 1
    return 0

def doLock(filename):
    try:
        fd = os.open(filename, os.O_EXCL|os.O_CREAT|os.O_WRONLY, 0666)
        os.write(fd, str(os.getpid()))
        os.close(fd)
    except OSError, msg:
        if not msg.errno == errno.EEXIST:
            raise msg
        return 0
    return 1

def unlink(file):
    try:
        os.unlink(file)
    except:
        pass

def setCloseOnExec():
    import fcntl
    for fd in range(3, resource.getrlimit(resource.RLIMIT_NOFILE)[1]):
        try:
            fcntl.fcntl(fd, fcntl.F_SETFD, 1)
        except:
            pass

def closeAllFDs():
    # should not be used
    raise Exception, "Please use setCloseOnExec!"
    for fd in range(3, resource.getrlimit(resource.RLIMIT_NOFILE)[1]):
        try:
            os.close(fd)
            sys.stderr.write("Closed fd=%d\n" % fd)
        except:
            pass

def readExact(fd, size):
    """Read exactly size bytes from fd.

    Raise IOError on I/O error or unexpected EOF."""

    data = fd.read(size)
    if len(data) != size:
        raise IOError, "Unexpected EOF"
    return data

def updateDigestFromFile(digest, fd, bytes = None):
    """Update digest with data from fd, until EOF or only specified bytes."""

    while True:
        chunk = DIGEST_CHUNK
        if bytes is not None and chunk > bytes:
            chunk = bytes
        data = fd.read(chunk)
        if not data:
            break
        digest.update(data)
        if bytes is not None:
            bytes -= len(data)

# Things not done for disksize calculation, might stay this way:
# - no hardlink detection
# - no information about not-installed files like multilib files, left out
#   docu files etc
def getFreeDiskspace(operations):
    freehash = {}
    minfreehash = {}
    dirhash = {}
    if rpmconfig.buildroot:
        br = rpmconfig.buildroot
    else:
        br = "/"
    for (op, pkg) in operations:
        dirnames = pkg["dirnames"]
        if dirnames == None:
            continue
        for dirname in dirnames:
            while dirname.endswith("/") and len(dirname) > 1:
                dirname = dirname[:-1]
            if dirhash.has_key(dirname):
                continue
            dnames = []
            devname = br + dirname
            while 1:
                dnames.append(dirname)
                try:
                    dev = os.stat(devname)[2]
                    break
                except:
                    dirname = os.path.dirname(dirname)
                    devname = os.path.dirname(devname)
                    if dirhash.has_key(dirname):
                        dev = dirhash[dirname]
                        break
            for d in dnames:
                dirhash[d] = dev
            if not freehash.has_key(dev):
                statvfs = os.statvfs(devname)
                freehash[dev] = [statvfs[0] * statvfs[4], statvfs[0]]
                minfreehash[dev] = [statvfs[0] * statvfs[4], statvfs[0]]
        dirindexes = pkg["dirindexes"]
        filesizes = pkg["filesizes"]
        filemodes = pkg["filemodes"]
        for i in xrange(len(dirindexes)):
            if not S_ISREG(filemodes[i]):
                continue
            dirname = dirnames[dirindexes[i]]
            while dirname.endswith("/") and len(dirname) > 1:
                dirname = dirname[:-1]
            dev = freehash[dirhash[dirname]]
            mdev = minfreehash[dirhash[dirname]]
            filesize = ((filesizes[i] / dev[1]) + 1) * dev[1]
            if op == OP_ERASE:
                dev[0] += filesize
            else:
                dev[0] -= filesize
            if mdev[0] > dev[0]:
                mdev[0] = dev[0]
        for dev in minfreehash.keys():
            # Less than 30MB space left on device?
            if minfreehash[dev][0] < 31457280:
                printInfo(1, "%s: Less than 30MB of diskspace left on device %s\n" % (pkg.getNEVRA(), hex(dev)))
    return minfreehash

def cacheLocal(url, subdir):
    if not url.startswith("http://"):
        return url
    if not os.path.isdir("/var/cache/pyrpm/%s" % subdir):
        os.makedirs("/var/cache/pyrpm/%s" % subdir)
    try:
        f = urlgrab(url, "/var/cache/pyrpm/%s/%s" % 
                    (subdir, os.path.basename(url)),
                    reget='simple')
    except URLGrabError, e:
        # urlgrab fails with invalid range for already completely transfered
        # files, pretty strange to me to be honest... :)
        if e[0] == 9:
            return "/var/cache/pyrpm/%s/%s" % (subdir, os.path.basename(url))
        else:
            return None
    return f

def parseBoolean(str):
    lower = str.lower()
    if lower in ("yes", "true", "1", "on"):
        return 1
    return 0

# Parse yum config options. Neede for several yum-like scripts
def parseYumOptions(argv, yum):
    # Argument parsing
    try:
      opts, args = getopt.getopt(argv, "?vhc:r:y",
        ["help", "verbose", 
         "hash", "version", "quiet", "dbpath=", "root=",
         "force", "ignoresize", "ignorearch", "exactarch", "justdb", "test",
         "noconflicts", "fileconflicts", "nodeps", "nodigest", "nosignature",
         "noorder", "noscripts", "notriggers", "oldpackage", "autoerase",
         "servicehack", "installpkgs=", "arch=", "checkinstalled"])
    except getopt.error, e:
        print "Error parsing command list arguments: %s" % e
        return None

    # Argument handling
    for (opt, val) in opts:
        if   opt in ['-?', "--help"]:
            return None
        elif opt in ["-v", "--verbose"]:
            rpmconfig.verbose += 1
        elif opt in ["-r", "--root"]:
            rpmconfig.buildroot = val
        elif opt == "-c":
            rpmconfig.yumconf = val
        elif opt == "--quiet":
            rpmconfig.debug = 0
            rpmconfig.warning = 0
            rpmconfig.verbose = 0
            rpmconfig.printhash = 0
        elif opt == "--autoerase":
            yum.setAutoerase(1)
        elif opt == "--version":
            print "pyrpmyum", __version__
            sys.exit(0)
        elif opt == "-y":
            yum.setConfirm(0)
        elif opt == "--dbpath":
            rpmconfig.dbpath = val
        elif opt == "--installpkgs":
            yum.always_install = val.split()
        elif opt == "--force":
            rpmconfig.force = 1
        elif opt in ["-h", "--hash"]:
            rpmconfig.printhash = 1
        elif opt == "--oldpackage":
            rpmconfig.oldpackage = 1
        elif opt == "--justdb":
            rpmconfig.justdb = 1
            rpmconfig.noscripts = 1
            rpmconfig.notriggers = 1
        elif opt == "--test":
            rpmconfig.test = 1
            rpmconfig.noscripts = 1
            rpmconfig.notriggers = 1
            rpmconfig.timer = 1
        elif opt == "--ignoresize":
            rpmconfig.ignoresize = 1
        elif opt == "--ignorearch":
            rpmconfig.ignorearch = 1
        elif opt == "--noconflicts":
            rpmconfig.noconflicts = 1
        elif opt == "--fileconflicts":
            rpmconfig.nofileconflicts = 0
        elif opt == "--nodeps":
            rpmconfig.nodeps = 1
        elif opt == "--nodigest":
            rpmconfig.nodigest = 1
        elif opt == "--nosignature":
            rpmconfig.nosignature = 1
        elif opt == "--noorder":
            rpmconfig.noorder = 1
        elif opt == "--noscripts":
            rpmconfig.noscripts = 1
        elif opt == "--notriggers":
            rpmconfig.notriggers = 1
        elif opt == "--servicehack":
            rpmconfig.service = 1
        elif opt == "--arch":
            rpmconfig.arch = val
        elif opt == "--checkinstalled":
            rpmconfig.checkinstalled = 1

    if rpmconfig.verbose > 1:
        rpmconfig.warning = rpmconfig.verbose - 1
    if rpmconfig.verbose > 2:
        rpmconfig.debug = rpmconfig.verbose - 2

    if rpmconfig.arch != None:
        if not rpmconfig.test:
            print "Arch option can only be used for tests"
            sys.exit(1)
        if not buildarchtranslate.has_key(rpmconfig.arch):
            print "Unknown arch %s" % rpmconfig.arch
            sys.exit(1)
        rpmconfig.machine = rpmconfig.arch

    if not args:
        print "No command given"
        return None

    # Handle yum config file. By default we set the reposdir to "", meaning no
    # repo dirs. If it is specified in the config file we use that though (as
    # expected)
    if os.path.isfile(rpmconfig.yumconf):
        addRepo(yum, rpmconfig.yumconf)
    else:
        printWarning(1, "Couldn't find given yum config file, skipping read of repos")
    return args

def addRepo(yum, file):
    conf = YumConf("3", rpmconfig.machine, buildarchtranslate[rpmconfig.machine], rpmconfig.buildroot, file, "")
    for key in conf.vars.keys():
        if key == "main":
            pass
        else:
            sec = conf[key]
            if not sec.has_key("baseurl"):
                printError("%s: No baseurl for this section in conf file." % key)
                sys.exit(1)
            baseurl = sec["baseurl"][0]
            if not sec.has_key("exclude"):
                excludes = ""
            else:
                excludes = sec["exclude"]
            yum.addRepo(baseurl, excludes, key)
            if rpmconfig.compsfile == None:
                rpmconfig.compsfile = cacheLocal(baseurl + "/repodata/comps.xml", key)

def selectNewestPkgs(pkglist):
    """Filter the newest packages from given list and return new list"""
    rethash = {}
    for pkg in pkglist:
        key1 = pkg["name"]+".noarch"
        key2 = pkg["name"]+"."+buildarchtranslate[pkg["arch"]]
        if not rethash.has_key(key1):
            rethash[key1] = pkg
            rethash[key2] = pkg
            continue
        opkg = rethash[key1]
        key3 = opkg["name"]+"."+buildarchtranslate[opkg["arch"]]
        ret = pkgCompare(opkg, pkg)
        if   ret < 0:
            try:
                del rethash[key3]
            except:
                pass
            rethash[key1] = pkg
            rethash[key2] = pkg
        elif ret == 0 and \
             opkg["arch"] in arch_compats[pkg["arch"]]:
            try:
                del rethash[key3]
            except:
                pass
            rethash[key1] = pkg
            rethash[key2] = pkg
    for key in rethash.keys():
        if key.endswith(".noarch") and rethash[key]["arch"] != "noarch":
            try:
                del rethash[key]
            except:
                pass
    retlist = []
    for pkg in pkglist:
        if pkg in rethash.values():
            retlist.append(pkg)
    return retlist

# Error handling functions
def printDebug(level, msg):
    if level <= rpmconfig.debug:
        sys.stdout.write("Debug: %s\n" % msg)
        sys.stdout.flush()
    return 0

def printInfo(level, msg):
    if level <= rpmconfig.verbose:
        sys.stdout.write(msg)
        sys.stdout.flush()
    return 0

def printWarning(level, msg):
    if level <= rpmconfig.warning:
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
    if str1 == "":
        if str2 == "": return 0
        return -1
    elif str2 == "":   return 1
    elif str1 == str2: return 0

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
    if i1 == len(str1):
        return -1
    return 1

# internal EVR compare, uses stringCompare to compare epochs, versions and
# release versions
def labelCompare(e1, e2):
    if e2[2] == "": # no release
        e1 = (e1[0], e1[1], "")
    elif e1[2] == "": # no release
        e2 = (e2[0], e2[1], "")
    r = stringCompare(e1[0], e2[0])
    if r == 0:
        r = stringCompare(e1[1], e2[1])
    if r == 0:
        r = stringCompare(e1[2], e2[2])
    return r

# compares two EVR's with comparator
def evrCompare(evr1, comp, evr2):
    res = -1
    if isinstance(evr1, TupleType):
        e1 = evr1
    else:
        e1 = evrSplit(evr1)
    if isinstance(evr2, TupleType):
        e2 = evr2
    else:
        e2 = evrSplit(evr2)
    #if rpmconfig.ignore_epoch:
    #    if comp == RPMSENSE_EQUAL and e1[1] == e2[1]:
    #        e1 = ("0", e1[1], e1[2])
    #        e2 = ("0", e2[1], e2[2])
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

def pkgCompare(p1, p2):
    return labelCompare((p1.getEpoch(), p1["version"], p1["release"]),
                        (p2.getEpoch(), p2["version"], p2["release"]))

def rangeCompare(flag1, evr1, flag2, evr2):
    sense = labelCompare(evr1, evr2)
    result = 0
    if sense < 0 and  \
           (flag1 & RPMSENSE_GREATER or flag2 & RPMSENSE_LESS):
        result = 1
    elif sense > 0 and \
             (flag1 & RPMSENSE_LESS or flag2 & RPMSENSE_GREATER):
        result = 1
    elif sense == 0 and \
             ((flag1 & RPMSENSE_EQUAL and flag2 & RPMSENSE_EQUAL) or \
              (flag1 & RPMSENSE_LESS and flag2 & RPMSENSE_LESS) or \
              (flag1 & RPMSENSE_GREATER and flag2 & RPMSENSE_GREATER)):
        result = 1
    return result

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

def archCompat(parch, arch):
    if parch == "noarch" or arch == "noarch" or \
           parch == arch or \
           (arch_compats.has_key(arch) and parch in arch_compats[arch]):
        return 1
    return 0

def archDuplicate(parch, arch):
    if parch == arch or \
           buildarchtranslate[parch] == buildarchtranslate[arch]:
        return 1
    return 0

def filterArchCompat(list, arch):
    # stage 1: filter packages which are not in compat arch
    i = 0
    while i < len(list):
        if archCompat(list[i]["arch"], arch):
            i += 1
        else:
            printWarning(1, "%s: Architecture not compatible with %s" % \
                         (list[i].source, arch))
            list.pop(i)

def filterArchDuplicates(list):
    raise Exception, "deprecated"

def filterArchList(list, arch=None):
    raise Exception, "deprecated"

def normalizeList(list):
    """ normalize list """
    if len(list) < 2:
        return
    h = { }
    i = 0
    while i < len(list):
        item = list[i]
        if h.has_key(item):
            list.pop(i)
        else:
            h[item] = 1
            i += 1

def orderList(list, arch):
    """ order list by machine distance and evr """
    distance = [ machineDistance(l["arch"], arch) for l in list ]
    for i in xrange(len(list)):
        for j in xrange(i + 1, len(list)):
            if distance[i] > distance[j]:
                (list[i], list[j]) = (list[j], list[i])
                (distance[i], distance[j]) = (distance[j], distance[i])
                continue
            if distance[i] == distance[j] and list[i] < list[j]:
                (list[i], list[j]) = (list[j], list[i])
                (distance[i], distance[j]) = (distance[j], distance[i])
                continue

def machineDistance(arch1, arch2):
    """ return machine distance as by arch_compats """
    # Noarch is always very good ;)
    if arch1 == "noarch" or arch2 == "noarch":
        return 0
    # Second best: same arch
    if arch1 == arch2:
        return 1
    # Everything else is determined by the "distance" in the arch_compats
    # array. If both archs are not compatible we return an insanely high
    # distance.
    if   arch_compats.has_key(arch1) and arch2 in arch_compats[arch1]:
        return arch_compats[arch1].index(arch2)+2
    elif arch_compats.has_key(arch2) and arch1 in arch_compats[arch2]:
        return arch_compats[arch2].index(arch1)+2
    else:
        return 999   # incompatible archs, distance is very high ;)

def getBuildArchList(list):
    """Returns list of build architectures used in 'list' of packages."""
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
            st.append([key, re.compile(normalizeRegex(val))])
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
                if not val.match(pval):
                    found = 0
                    break
        if found:
            pkglist.append(pkg)
    return pkglist

def normalizeRegex(regex):
    regex = regex.replace(".", "\.")
    regex = regex.replace("*", ".*")
    regex = regex.replace("+", "\+")
    regex = regex.replace("\\", "\\\\")
    regex = regex.replace("^", "\^")
    regex = regex.replace("$", "\$")
    regex = regex.replace("?", "\?")
    regex = regex.replace("{", "\{")
    regex = regex.replace("}", "\}")
    regex = regex.replace("[", "\[")
    regex = regex.replace("]", "\]")
    regex = regex.replace("|", "\|")
    regex = regex.replace("(", "\(")
    regex = regex.replace(")", "\)")
    return regex

EPOCHTAG=0
NAMETAG=1
VERSIONTAG=2
RELEASETAG=3
ARCHTAG=4

__delimeter = { EPOCHTAG : None,
                NAMETAG : ":",
                VERSIONTAG : "-",
                RELEASETAG : "-",
                ARCHTAG : "." }

def constructName(nametags, namevals):
    ret = ""
    for tag in nametags:
        if tag in __delimeter.keys():
            if namevals[tag]:
                if ret:
                    ret += __delimeter[tag]
                ret += namevals[tag]
    return ret

def __findPkgByName(pkgname, list, regex=None):
    """Find a package by name in a given list. Name can contain version,
release and arch. Returns a list of all matching packages, starting with
best match."""
    pkglist = []
    envra = envraSplit(pkgname)
    if not regex:
        tmplist = []
        for pkg in list:
            if pkg["name"].find(envra[1]) >= 0:
                tmplist.append(pkg)
        list = tmplist
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
    normalizeList(pkglist)
    return pkglist

def findPkgByName(pkgname, list):
    pkglist = __findPkgByName(pkgname, list, None)
    if len(pkglist) == 0:
        if pkgname.find("*") < 0:
            return [ ]
        pkglist = __findPkgByName(pkgname, list, 1)
    return pkglist

def readRpmPackage(config, source, verify=None, strict=None, hdronly=None,
                   db=None, tags=None):
    """Read RPM package from source and close it.

    tags, if defined, specifies tags to load.  Raise ValueError on invalid
    data, IOError."""
    
    pkg = package.RpmPackage(config, source, verify, strict, hdronly, db)
    pkg.read(tags=tags)
    pkg.close()
    return pkg

# vim:ts=4:sw=4:showmatch:expandtab
