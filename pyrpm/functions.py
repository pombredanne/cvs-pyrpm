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


import fcntl, os, os.path, struct, sys, resource, re, getopt, errno
from types import TupleType, ListType
from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, S_ISBLK, S_IMODE, S_ISSOCK
from bsddb import hashopen
try:
    from tempfile import mkstemp, mkdtemp, _get_candidate_names, TMP_MAX
except:
    print >> sys.stderr, "Error: Couldn't import tempfile python module. Only check scripts available."

try:
    from urlgrabber import urlgrab
    from urlgrabber.grabber import URLGrabError
except:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module. Only check scripts available."


from io import *
import openpgp
import yumconfig
import package

from config import rpmconfig
from base import *

# Number of bytes to read from file at once when computing digests
DIGEST_CHUNK = 65536

# Use this filename prefix for all temp files to be able
# to search them and delete them again if they are left
# over from killed processes.
tmpprefix = "..pyrpm"

# Collection of class-indepedent helper functions
def mkstemp_file(dirname, pre):
    """Create a temporary file in dirname with prefix pre.

    Return (file descriptor with FD_CLOEXEC, absolute path name).  Raise
    IOError if no file name is available, OSError."""

    (fd, filename) = mkstemp(prefix=pre, dir=dirname)
    return (fd, filename)

def mkstemp_dir(dirname, pre):
    """Create a directory in dirname with prefix pre.

    Return absolute directory path.  Raise IOError if no directory name is
    available, OSError."""

    filename = mkdtemp(prefix=pre, dir=dirname)
    return filename

def mkstemp_link(dirname, pre, linkfile):
    """Create a temporary link to linkfile in dirname with prefix pre.

    Return absolute file path, or None if such a link can not be made.  Raise
    IOError if no file name is available, OSError."""
    
    names = _get_candidate_names() # FIXME: internal function
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = os.path.join(dirname, "%s.%s" % (pre, name))
        try:
            os.link(linkfile, filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            # make sure we have a fallback if hardlinks cannot be done
            # on this partition
            if e.errno in (errno.EXDEV, errno.EPERM):
                return None
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_symlink(dirname, pre, symlinkfile):
    """Create a temporary symlink to symlinkfile in dirname with prefix pre.

    Return absolute file path.  Raise IOError if no file name is available,
    OSError."""

    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = os.path.join(dirname, "%s.%s" % (pre, name))
        try:
            os.symlink(symlinkfile, filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_mkfifo(dirname, pre):
    """Create a temporary named pipe in dirname with prefix pre.

    Return absolute file path.  Raise IOError if no file name is available,
    OSError."""
    
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = os.path.join(dirname, "%s.%s" % (pre, name))
        try:
            os.mkfifo(filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_mknod(dirname, pre, mode, rdev):
    """Create a temporary device file for rdev with mode in dirname with prefix
    pre.

    Return absolute file path.  Raise IOError if no file name is available,
    OSError."""

    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = os.path.join(dirname, "%s.%s" % (pre, name))
        try:
            os.mknod(filename, mode, rdev)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def runScript(prog=None, script=None, otherargs=[], force=False, rusage=False):
    """Run (script otherargs) with interpreter prog (which can be a list
    containing initial arguments).

    Return None, or getrusage() stats of the script if rusage.  Disable
    ldconfig optimization if force.  Raise IOError, OSError."""

    # FIXME? hardcodes config.rpmconfig usage
    if prog == None:
        prog = "/bin/sh"
    if prog == "/bin/sh" and script == None:
        return None
    if not os.path.exists("/var/tmp"):
        try:
            os.makedirs("/var", mode=0755)
        except OSError:
            pass
        os.makedirs("/var/tmp", mode=01777)
    if isinstance(prog, TupleType):
        args = prog
    else:
        args = [prog]
    if not force and args == ["/sbin/ldconfig"] and script == None:
        if rpmconfig.delayldconfig == 1:
            rpmconfig.ldconfig += 1
        # FIXME: assumes delayldconfig is checked after all runScript
        # invocations
        rpmconfig.delayldconfig = 1
        return None
    elif rpmconfig.delayldconfig:
        rpmconfig.delayldconfig = 0
        runScript("/sbin/ldconfig", force=1)
    if script != None:
        (fd, tmpfilename) = mkstemp_file("/var/tmp/", "rpm-tmp.")
        # test for open fds:
        # script = "ls -l /proc/$$/fd >> /$$.out\n" + script
        os.write(fd, script)
        os.close(fd)
        fd = None
        args.append(tmpfilename)

        args += otherargs
    (rfd, wfd) = os.pipe()

    if rusage:
        rusage_old = resource.getrusage(resource.RUSAGE_CHILDREN)

    pid = os.fork()
    if pid == 0:
        try:
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
            os.execve(args[0], args, e)
        finally:
            os._exit(255)
    os.close(wfd)
    # no need to read in chunks if we don't pass on data to some output func
    cret = ""
    cout = os.read(rfd, 8192)
    while cout:
        cret += cout
        cout = os.read(rfd, 8192)
    os.close(rfd)
    (cpid, status) = os.waitpid(pid, 0)

    if rusage:
        rusage_new = resource.getrusage(resource.RUSAGE_CHILDREN)
        rusage_val = [rusage_new[i] - rusage_old[i]
                      for i in xrange(len(rusage_new))]
    else:
        rusage_val = None

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
        elif os.WIFSTOPPED(status):     # Can't happen, needs os.WUNTRACED
            printError("Script %s stopped with signal %d:" % (str(args),
                os.WSTOPSIG(status)))
        else:
            printError("Script %s ended (fixme: reason unknown):" % str(args))
        if cret.endswith("\n"):
            cret = cret[:-1]
        printError(cret)
        raise OSError, "Script %s failed" % (args,)
    # FIXME: should we be swallowing the script output?
    return rusage_val

def installFile(rfi, infd, size, useAttrs=True):
    """Install a file described by RpmFileInfo rfi, with input of given size
    from CPIOFile infd.

    infd can be None if size == 0.  Ignore file attributes in rfi if useAttrs
    is False.  Raise ValueError on invalid mode, IOError, OSError."""

    mode = rfi.mode
    if S_ISREG(mode):
        makeDirs(rfi.filename)
        (fd, tmpfilename) = mkstemp_file(os.path.dirname(rfi.filename), tmpprefix)
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
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
        except (IOError, OSError):
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, rfi.filename)
    elif S_ISDIR(mode):
        if not os.path.isdir(rfi.filename):
            os.makedirs(rfi.filename)
        if useAttrs:
            _setFileAttrs(rfi.filename, rfi)
    elif S_ISLNK(mode):
        data = infd.read(size)
        symlinkfile = data.rstrip("\x00")
        if os.path.islink(rfi.filename) \
            and os.readlink(rfi.filename) == symlinkfile:
            return
        makeDirs(rfi.filename)
        tmpfilename = mkstemp_symlink(os.path.dirname(rfi.filename), tmpprefix,
                                      symlinkfile)
        try:
            if useAttrs:
                os.lchown(tmpfilename, rfi.uid, rfi.gid)
        except OSError:
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, rfi.filename)
    elif S_ISFIFO(mode):
        makeDirs(rfi.filename)
        tmpfilename = mkstemp_mkfifo(os.path.dirname(rfi.filename), tmpprefix)
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
        except OSError:
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, rfi.filename)
    elif S_ISCHR(mode) or S_ISBLK(mode):
        makeDirs(rfi.filename)
        try:
            tmpfilename = mkstemp_mknod(os.path.dirname(rfi.filename),
                                        tmpprefix, mode, rfi.rdev)
        except OSError:
            return # FIXME: why?
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
        except OSError:
            os.unlink(rfi.filename)
            raise
        os.rename(tmpfilename, rfi.filename)
    elif S_ISSOCK(mode):
        # Sockets are useful only when bound, but what do we care...
        # Note that creating sockets using mknod is not SUSv3-mandated, quite
        # likely Linux-specific.
        makeDirs(rfi.filename)
        tmpfilename = mkstemp_mknod(os.path.dirname(rfi.filename), tmpprefix,
                                    mode, 0)
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
        except OSError:
            os.unlink(rfi.filename)
            raise
        os.rename(tmpfilename, rfi.filename)
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(mode))

def _setFileAttrs(filename, rfi):
    """Set owner, group, mode and mtime of filename data from RpmFileInfo rfi.

    Raise OSError."""

    os.chown(filename, rfi.uid, rfi.gid)
    os.chmod(filename, S_IMODE(rfi.mode))
    os.utime(filename, (rfi.mtime, rfi.mtime))

def makeDirs(fullname):
    """Create a parent directory of fullname if it does not already exist.

    Raise OSError."""

    dirname = os.path.dirname(fullname)
    if len(dirname) > 1 and not os.path.isdir(dirname):
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
    # FIXME: use mkstemp... and os.rename?
    os.link(src, dst)

def tryUnlock(lockfile):
    """If lockfile exists and is a stale lock, remove it.

    Return 1 if lockfile is a live lock, 0 otherwise.  Raise IOError."""
    
    if not os.path.exists(lockfile):
        return 0
    fd = open(lockfile, 'r')
    try:
        oldpid = int(fd.readline())
    except ValueError:
        _unlink(lockfile) # bogus data
        return 0
    try:
        os.kill(oldpid, 0)
    except OSError, e:
        if e.errno == errno.ESRCH:
            _unlink(lockfile) # pid doesn't exist
            return 0
    return 1

def doLock(filename):
    """Create a lock file filename.

    Return 1 on success, 0 if the file already exists.  Raise OSError."""
    
    try:
        fd = os.open(filename, os.O_EXCL|os.O_CREAT|os.O_WRONLY, 0666)
        try:
            os.write(fd, str(os.getpid()))
        finally:
            os.close(fd)
    except OSError, msg:
        if not msg.errno == errno.EEXIST:
            raise
        return 0
    return 1

def _unlink(file):
    """Unlink file, ignoring errors."""
    
    try:
        os.unlink(file)
    except OSError:
        pass

def setCloseOnExec():
    """Set all file descriptors except for 0, 1, 2, to close on exec."""

    for fd in xrange(3, resource.getrlimit(resource.RLIMIT_NOFILE)[1]):
        try:
            old = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, old | fcntl.FD_CLOEXEC)
        except IOError:
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

def getFreeCachespace(config, operations):
    """Check if there is enough diskspace for caching the rpms for the given
    operations.

    Return 1 if there is enough space (with 30 MB slack), 0 otherwise."""
    
    cachedir = "/var/cache/pyrm/"
    while 1:
        try:
            dev = os.stat(cachedir).st_dev
            break
        except OSError:
            cachedir = os.path.dirname(cachedir)
    statvfs = os.statvfs(cachedir)
    freespace = statvfs[0] * statvfs[4]
    for (op, pkg) in operations:
        # No packages will get downloaded for erase operations.
        if op == OP_ERASE:
            continue
        # Also local files won't be cached either.
        if pkg.source.startswith("file:/") or pkg.source[0] == "/":
            continue
        try:
            freespace -= pkg['signature']['size_in_sig'][0]+pkg.range_header[0]
        except KeyError:
            raise ValueError, "Missing signature:size_in sig in package"
        print freespace
    if freespace < 31457280:
        config.printInfo(0, "Less than 30MB of diskspace left on %s for caching rpms\n" % mountpoint[dev])
        return 0
    return 1

# Things not done for disksize calculation, might stay this way:
# - no hardlink detection
# - no information about not-installed files like multilib files, left out
#   docu files etc
def getFreeDiskspace(config, operations):
    """Check there is enough disk space for operations, a list of
    (operation, RpmPackage).

    Use RpmConfig config.  Return 1 if there is enough space (with 30 MB
    slack), 0 otherwise."""
    
    freehash = {} # device number => [currently counted free bytes, block size]
    # device number => [minimal encountered free bytes, block size]
    minfreehash = {} 
    dirhash = {}                        # directory name => device number
    mountpoint = { }                    # device number => mount point path
    ret = 1

    if config.buildroot:
        br = config.buildroot
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
                    dev = os.stat(devname).st_dev
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
            if not mountpoint.has_key(dev):
                while len(dirname) > 0:
                    if os.path.ismount(dirname):
                        mountpoint[dev] = dirname
                        break
                    dirname = os.path.dirname(dirname)
        dirindexes = pkg["dirindexes"]
        filesizes = pkg["filesizes"]
        filemodes = pkg["filemodes"]
        if not dirindexes or not filesizes or not filemodes:
            continue
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
        for (dev, val) in minfreehash.iteritems():
            # Less than 30MB space left on device?
            if val[0] < 31457280:
                config.printInfo(1, "%s: Less than 30MB of diskspace left on %s\n" % (pkg.getNEVRA(), mountpoint[dev]))

    for (dev, val) in minfreehash.iteritems():
        if val[0] < 31457280:
            config.printInfo(0, "Less than 30MB of diskspace left on %s for operation\n" % mountpoint[dev])
            ret = 0

    return ret

def cacheLocal(url, subdir, force=0):
    """Copy file from HTTP url to subdir/$(basename url).

    Return local file path, or None on failure.  If the local file is already
    present, use it if the timestamp is not too old unless force is true."""
    
    if not url.startswith("http://"): # FIXME: ftp:// ?
        return url
    destdir = os.path.join("/var/cache/pyrpm", subdir)
    if not os.path.isdir(destdir):
        os.makedirs(destdir)
    destfile = os.path.join(destdir, os.path.basename(url))
    try:
        if force:
            f = urlgrab(url, destfile)
        else:
            f = urlgrab(url, destfile, reget='check_timestamp')
    except URLGrabError, e:
        # urlgrab fails with invalid range for already completely transfered
        # files, pretty strange to me to be honest... :)
        if e[0] == 9:
            return destfile
        else:
            return None
    return f

def parseBoolean(str):
    """Convert str to a boolean.

    Return the resulting value, default to False if str is unrecognized."""

    return str.lower() in ("yes", "true", "1", "on")

# Parse yum config options. Needed for several yum-like scripts
def parseYumOptions(argv, yum):
    """Parse yum-like config options from argv to config.rpmconfig and RpmYum
    yum.

    Return list of non-option operands on success, None if a help message
    should be written.  sys.exit () on --version, some invalid arguments
    or errors in config files."""
    
    # Argument parsing
    try:
      opts, args = getopt.getopt(argv, "?vhc:r:y",
        ["help", "verbose",
         "hash", "version", "quiet", "dbpath=", "root=",
         "force", "ignoresize", "ignorearch", "exactarch", "justdb", "test",
         "noconflicts", "fileconflicts", "nodeps", "nodigest", "nosignature",
         "noorder", "noscripts", "notriggers", "oldpackage", "autoerase",
         "servicehack", "installpkgs=", "arch=", "checkinstalled", "rusage"])
    except getopt.error, e:
        # FIXME: all to stderr
        print "Error parsing command-line arguments: %s" % e
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
        elif opt == "--rusage":
            rpmconfig.rusage = 1
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
            print >> sys.stderr, "Arch option can only be used for tests"
            sys.exit(1)
        if not buildarchtranslate.has_key(rpmconfig.arch):
            print >> sys.stderr, "Unknown arch %s" % rpmconfig.arch
            sys.exit(1)
        rpmconfig.machine = rpmconfig.arch

    if not args:
        print "No command given" # FIXME: all to stderr
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
    """Read yum configuration file and add repositories it uses to RpmYum yum.

    sys.exit() on error."""
    
    try:
        conf = yumconfig.YumConf("3", rpmconfig.machine,
                                 buildarchtranslate[rpmconfig.machine],
                                 rpmconfig.buildroot, file, "")
    except IOError, e:
        printError("Error reading configuration: %s" % e)
        sys.exit(1)
    for key in conf.keys():
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
            yum.addRepo(baseurl, excludes, key) # FIXME: not documented yet
            if rpmconfig.compsfile == None:
                # May stay None on download error
                rpmconfig.compsfile = cacheLocal(baseurl + "/repodata/comps.xml", key)

def selectNewestPkgs(pkglist):
    """Select the "best" packages for each base arch from RpmPackage list
    pkglist.

    Return a list of the "best" packages, selecting the highest EVR.arch for
    each base arch."""

    # %name.noarch => some RpmPackage with that %name
    # %name.$basearch => RpmPackage with highest EVR for that %name.$basearch
    rethash = {}
    for pkg in pkglist:
        key1 = pkg["name"]+".noarch"
        key2 = pkg["name"]+"."+buildarchtranslate[pkg["arch"]]
        if not rethash.has_key(key1):
            rethash[key1] = pkg
            rethash[key2] = pkg
            continue
        if rethash.has_key(key2):
            opkg = rethash[key2]
        else:
            opkg = rethash[key1]
        if pkg["arch"] != "noarch" and opkg["arch"] != "noarch" and \
           not archDuplicate(pkg["arch"], opkg["arch"]):
            assert not rethash.has_key(key2)
            rethash[key2] = pkg
            continue
        ret = pkgCompare(opkg, pkg)
        if   ret < 0:
            rethash[key1] = pkg
            rethash[key2] = pkg
        elif ret == 0 and \
             opkg["arch"] in arch_compats[pkg["arch"]]:
            rethash[key1] = pkg
            rethash[key2] = pkg
    for key in rethash.keys():
        if key.endswith(".noarch") and rethash[key]["arch"] != "noarch":
            # FIXME: why the try: except:?
            try:
                del rethash[key]
            except:
                pass
    retlist = []
    for pkg in pkglist:
        if pkg in rethash.values():
            retlist.append(pkg)
    return retlist

def readPackages(dbpath):
    """Read packages from rpmdb dbpath/Packages.

    Return ({ package id => RpmPackage }, PGPKeyRing).  Raise bsddb.error.
    Skip invalid packages and invalid tags, using config.rpmconfig to warn."""
    
    packages = {}
    keyring = openpgp.PGPKeyRing()
    db = hashopen(os.path.join(dbpath, "Packages"), "r")
    for key in db.keys():
        rpmio = RpmFileIO(rpmconfig, "dummy", verify=1)
        pkg = package.RpmPackage(rpmconfig, "dummy")
        data = db[key]
        try:
            val = struct.unpack("I", key)[0] # FIXME: native endian?
        except struct.error:
            rpmconfig.printError("Invalid key %s in rpmdb" % repr(key))
            continue
        if val != 0:
            try:
                (indexNo, storeSize) = struct.unpack("!2I", data[0:8])
            except struct.error:
                rpmconfig.printError("Value for key %s in rpmdb is too short"
                                     % repr(key))
                continue
            if len(data) < indexNo*16 + 8:
                rpmconfig.printError("Value for key %s in rpmdb is too short"
                                     % repr(key))
                continue
            indexdata = data[8:indexNo*16+8]
            storedata = data[indexNo*16+8:]
            pkg["signature"] = {}
            for idx in xrange(0, indexNo):
                try:
                    (tag, tagval) = rpmio.getHeaderByIndex(idx, indexdata,
                                                           storedata)
                except ValueError, e:
                    rpmconfig.printError("Invalid header entry %s in %s: %s"
                                         % (idx, repr(key), e))
                    continue
                if   tag == 257:
                    pkg["signature"]["size_in_sig"] = tagval
                elif tag == 261:
                    pkg["signature"]["md5"] = tagval
                elif tag == 262:
                    pkg["signature"]["gpg"] = tagval
                elif tag == 264:
                    pkg["signature"]["badsha1_1"] = tagval
                elif tag == 265:
                    pkg["signature"]["badsha1_2"] = tagval
                elif tag == 267:
                    pkg["signature"]["dsaheader"] = tagval
                elif tag == 269:
                    pkg["signature"]["sha1header"] = tagval
                if rpmtag.has_key(tag):
                    if rpmtagname[tag] == "archivesize":
                        pkg["signature"]["payloadsize"] = tagval
                    else:
                        pkg[rpmtagname[tag]] = tagval
            if pkg["name"] == "gpg-pubkey":
                continue # FIXME
                try:
                    keys = openpgp.parsePGPKeys(pkg["description"])
                except ValueError, e:
                    rpmconfig.printError("Invalid key package %s: %s"
                                         % (pkg["name"], e))
                    continue
                for k in keys:
                    keyring.addKey(k)
                pkg["group"] = (pkg["group"],)
            pkg.generateFileNames()
            pkg.source = "rpmdb:"+os.path.join(dbpath, pkg.getNEVRA())
            packages[val] = pkg
            rpmio.hdr = {}
    return packages, keyring

# Error handling functions

# FIXME: not used
def printDebug(level, msg):
    if level <= rpmconfig.debug:
        sys.stdout.write("Debug: %s\n" % msg)
        sys.stdout.flush()
    return 0

# FIXME: not used
def printInfo(level, msg):
    if level <= rpmconfig.verbose:
        sys.stdout.write(msg)
        sys.stdout.flush()
    return 0

# FIXME: used
def printWarning(level, msg):
    if level <= rpmconfig.warning:
        sys.stdout.write("Warning: %s\n" % msg)
        sys.stdout.flush()
    return 0

# FIXME: used
def printError(msg):
    sys.stderr.write("Error: %s\n" % msg)
    sys.stderr.flush()
    return 0

def raiseFatal(msg):
    raise ValueError, "Fatal: %s\n" % msg

# ----------------------------------------------------------------------------

def evrSplit(evr):
    """Split evr to components.

    Return (E, V, R).  Default epoch to 0, release to "" if not specified."""

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

def envraSplit(envra):
    """split [e:]name-version-release.arch into the 4 possible subcomponents.

    Return (E, N, V, R, A).  Default epoch, version, release and arch to None
    if not specified."""
    
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


# locale independent string methods
def _xisalpha(chr):
    return (chr >= 'a' and chr <= 'z') or (chr >= 'A' and chr <= 'Z')
def _xisdigit(chr):
    return chr >= '0' and chr <= '9'
def _xisalnum(chr):
    return (chr >= 'a' and chr <= 'z') or (chr >= 'A' and chr <= 'Z') \
        or (chr >= '0' and chr <= '9')

# compare two strings
def stringCompare(str1, str2):
    """Compare version strings str1, str2 like rpm does.

    Return an integer with the same sign as (str1 - str2).  Loop through each
    version segment (alpha or numeric) of str1 and str2 and compare them."""

    if str1 == str2: return 0
    lenstr1 = len(str1)
    lenstr2 = len(str2)
    i1 = 0
    i2 = 0
    while i1 < lenstr1 and i2 < lenstr2:
        # remove leading separators
        while i1 < lenstr1 and not _xisalnum(str1[i1]): i1 += 1
        while i2 < lenstr2 and not _xisalnum(str2[i2]): i2 += 1
        # start of the comparison data, search digits or alpha chars
        j1 = i1
        j2 = i2
        if j1 < lenstr1 and _xisdigit(str1[j1]):
            while j1 < lenstr1 and _xisdigit(str1[j1]): j1 += 1
            while j2 < lenstr2 and _xisdigit(str2[j2]): j2 += 1
            isnum = 1
        else:
            while j1 < lenstr1 and _xisalpha(str1[j1]): j1 += 1
            while j2 < lenstr2 and _xisalpha(str2[j2]): j2 += 1
            isnum = 0
        # check if we already hit the end
        # FIXME: return 0 if both at end?
        if j1 == i1: return -1
        if j2 == i2:
            if isnum: return 1 # FIXME: why only if isnum?
            return -1
        if isnum:
            # ignore leading "0" for numbers (1 == 000001)
            while i1 < j1 and str1[i1] == "0": i1 += 1
            while i2 < j2 and str2[i2] == "0": i2 += 1
            # longer size of digits wins
            if j1 - i1 > j2 - i2: return 1
            if j2 - i2 > j1 - i1: return -1
        x = cmp(str1[i1:j1], str2[i2:j2])
        if x: return x
        # move to next comparison start
        i1 = j1
        i2 = j2
    if i1 == lenstr1:
        if i2 == lenstr2: return 0
        return -1
    return 1

def labelCompare(e1, e2):
    """Compare (E, V, R) tuples e1 and e2.

    Return an integer with the same sign as (e1 - e2).  If either of the tuples
    has empty release, ignore releases in comparison."""

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

def evrCompare(evr1, comp, evr2):
    """Check whether evr1 matches comp (RPMSENSE_*) evr2.

    Return True if it does, False otherwise.  Each of evr1 and evr2 can be
    a string or an (E, V, R) string tuple."""

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
    res = False
    if r == -1:
        if comp & RPMSENSE_LESS:
            res = True
    elif r == 0:
        if comp & RPMSENSE_EQUAL:
            res = True
    else: # res == 1
        if comp & RPMSENSE_GREATER:
            res = True
    return res

def pkgCompare(p1, p2):
    """Compare EVR of RpmPackage's p1 and p2.

    Return an integer with the same sign as (p1 - p2).  The packages should
    have same %name for the comparison to be meaningful."""
    
    return labelCompare((p1.getEpoch(), p1["version"], p1["release"]),
                        (p2.getEpoch(), p2["version"], p2["release"]))

def rangeCompare(flag1, evr1, flag2, evr2):
    """Check whether (RPMSENSE_* flag, (E, V, R) evr) pairs (flag1, evr1)
    and (flag2, evr2) intersect.

    Return 1 if they do, 0 otherwise.  Assumes at least one of RPMSENSE_EQUAL,
    RPMSENSE_LESS or RPMSENSE_GREATER is each of flag1 and flag2."""
    
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
    """Return a string representation of RPMSENSE_* comparison operator."""

    op = ""
    if flag & RPMSENSE_LESS:
        op = "<"
    if flag & RPMSENSE_GREATER:
        op += ">"
    if flag & RPMSENSE_EQUAL:
        op += "="
    return op

def depString((name, flag, version)):
    """Return a string representation of (name, RPMSENSE_* flag, version)
    condition."""

    if version == "":
        return name
    return "%s %s %s" % (name, depOperatorString(flag), version)

def archCompat(parch, arch):
    """Return True if package with architecture parch can be installed on
    machine with arch arch."""
    
    return parch == "noarch" or arch == "noarch" or parch == arch or \
           (arch_compats.has_key(arch) and parch in arch_compats[arch])

def archDuplicate(parch, arch):
    """Return True if parch and arch have the same base arch."""
    
    return (parch == arch
            or buildarchtranslate[parch] == buildarchtranslate[arch])

def filterArchCompat(list, arch):
    """Modify RpmPackage list list to contain only packages that can be
    installed on arch arch.

    Warn using config.rpmconfig about dropped packages."""
    
    i = 0
    while i < len(list):
        if archCompat(list[i]["arch"], arch):
            i += 1
        else:
            printWarning(1, "%s: Architecture not compatible with %s" % \
                         (list[i].source, arch))
            list.pop(i)

def normalizeList(list):
    """Modify list to contain every entry at most once."""
    
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
    """Order RpmPackage list by "distance" to arch (ascending) and EVR
    (descending), in that order."""

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
    """Return machine distance between arch1 and arch2, as defined by
    arch_compats."""

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

# FIXME: not used
def getBuildArchList(list):
    """Return a list of non-noarch architectures of RpmPackage's in list."""

    archs = []
    for p in list:
        a = p['arch']
        if a == 'noarch':
            continue
        if a not in archs:
            archs.append(a)
    return archs

def tagsearch(searchtags, list, wildcard=False):
    """Return a list of RpmPackage's from list matching searchtags.

    searchtags is a list of (tag name, value to match).  If wildcard, value is
    a pattern possibly containing the '*' character."""

    if wildcard:
        st = [(key, re.compile(_patternToRegex(val)))
              for (key, val) in searchtags]
        searchtags = st
    pkglist = []
    for pkg in list:
        found = 1
        for (key, val) in searchtags:
            if not pkg.has_key(key):
                found = 0
                break
            if key == "epoch":
                pval = str(pkg[key][0])
            else:
                pval = pkg[key]
            if not wildcard:
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

def _patternToRegex(pattern):
    """Return a regex matching the original pattern, in which '*' matches any
    number of characters."""
    
    regex = pattern.replace(".", "\.")
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
    return regex + "$"

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
    """Return a string containing tags from (ascending) *TAG list nametags,
    describing (E, N, V, R, A) namevals."""

    ret = ""
    for tag in nametags:
        assert tag in __delimeter.keys()
        if namevals[tag]:
            if ret:
                ret += __delimeter[tag]
            ret += namevals[tag]
    return ret

def __findPkgByName(pkgname, pkgs, wildcard=False):
    """Return a list of RpmPackage's from pkgs matching pkgname.

    pkgname can contain version, release and arch (but simple names are
    prefered).  The returned list contains "better" matches first.  If
    wildcard, '*' in pkgname matches any number of characters."""

    # For a pattern like *-*.* we don't know which fields match which parts
    # of the package's ENVRA, so we try several possibilities.
    pkglist = []
    envra = envraSplit(pkgname)
    if not wildcard:
        # Filter out packages that can't possibly match
        tmplist = [pkg for pkg in pkgs if pkg["name"].find(envra[1]) >= 0]
        pkgs = tmplist
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    if envra[RELEASETAG] != None:
        tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG], envra)), \
                ("version", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("name", constructName([EPOCHTAG, NAMETAG, VERSIONTAG], envra)), \
            ("version", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    if envra[RELEASETAG] != None:
        tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
                ("version", constructName([VERSIONTAG], envra)), \
                ("release", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("name", constructName([EPOCHTAG, NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG], envra)), \
            ("release", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))

    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    if envra[RELEASETAG] != None:
        tags = [("epoch", constructName([EPOCHTAG], envra)), \
                ("name", constructName([NAMETAG, VERSIONTAG], envra)), \
                ("version", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG, VERSIONTAG], envra)), \
            ("version", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG, ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG, RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    if envra[RELEASETAG] != None:
        tags = [("epoch", constructName([EPOCHTAG], envra)), \
                ("name", constructName([NAMETAG], envra)), \
                ("version", constructName([VERSIONTAG], envra)), \
                ("release", constructName([RELEASETAG, ARCHTAG], envra))]
        pkglist.extend(tagsearch(tags, pkgs, wildcard))
    tags = [("epoch", constructName([EPOCHTAG], envra)), \
            ("name", constructName([NAMETAG], envra)), \
            ("version", constructName([VERSIONTAG], envra)), \
            ("release", constructName([RELEASETAG], envra)), \
            ("arch", constructName([ARCHTAG], envra))]
    pkglist.extend(tagsearch(tags, pkgs, wildcard))
    normalizeList(pkglist)
    return pkglist

def findPkgByName(pkgname, pkgs):
    """Return a list of RpmPackage's from pkgs matching pkgname.

    pkgname can contain version, release and arch (but simple names are
    prefered).  The returned list contains "better" matches first.  '*' is
    interpreted literally; if that results in no matches, '*' matches any
    number of characters."""

    pkglist = __findPkgByName(pkgname, pkgs, None)
    if len(pkglist) == 0 and pkgname.find("*") >= 0:
        pkglist = __findPkgByName(pkgname, pkgs, 1)
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

def run_main(main):
    """Run main, handling --hotshot.

    The return value from main, if not None, is a return code."""
    
    dohotshot = 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--hotshot":
        dohotshot = 1
        sys.argv.pop(1)
    if dohotshot:
        import hotshot, hotshot.stats
        htfilename = mkstemp_file("/tmp", tmpprefix)[1]
        prof = hotshot.Profile(htfilename)
        prof.runcall(main)
        prof.close()
        del prof
        print "Starting profil statistics. This takes some time..."
        s = hotshot.stats.load(htfilename)
        s.strip_dirs().sort_stats("time").print_stats(100)
        s.strip_dirs().sort_stats("cumulative").print_stats(100)
        os.unlink(htfilename)
    else:
        ret = main()
        if ret != None:
            sys.exit(ret)

# vim:ts=4:sw=4:showmatch:expandtab
