#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
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


import fcntl, os, os.path, sys, resource, getopt, errno, signal, shutil
from types import TupleType
from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, S_ISBLK, S_IMODE, S_ISSOCK
try:
    from tempfile import mkstemp, mkdtemp, _get_candidate_names, TMP_MAX
except ImportError:
    print >> sys.stderr, "Error: Couldn't import tempfile python module. Only check scripts available."

import se_linux
import package

from config import rpmconfig
from base import *
from pyrpm import __version__
from pyrpm.logger import log

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

def runScript(prog=None, script=None, otherargs=[], force=False, rusage=False,
              tmpdir="/var/tmp", chroot='', prefixes=None):
    """Run (script otherargs) with interpreter prog (which can be a list
    containing initial arguments).

    If prefixes is supplied, it's used to populate environment.
    The following env. variables are defined: RPM_INSTALL_PREFIX.

    Return (exit status, getrusage() stats, script output).  Use None instead
    of getrusage() data if !rusage.  Disable ldconfig optimization if force.
    Raise IOError, OSError."""

    if chroot is None:
        chroot = ''
    # FIXME? hardcodes config.rpmconfig usage
    if prog == None:
        prog = "/bin/sh"
    if prog == "/bin/sh" and script == None:
        return (0, None, "")
    tdir = chroot + tmpdir
    if not os.path.exists(tdir):
        try:
            os.makedirs(os.path.dirname(tdir), mode=0755)
        except OSError:
            pass
        try:
            os.makedirs(tdir, mode=01777)
        except OSError:
            return (0, None, "")
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
        return (0, None, "")
    elif rpmconfig.delayldconfig:
        rpmconfig.delayldconfig = 0
        runScript("/sbin/ldconfig", force=1, chroot=chroot)
    if script != None:
        (fd, tmpfilename) = mkstemp_file(tdir, "rpm-tmp.")
        # test for open fds:
        # script = "ls -l /proc/$$/fd >> /$$.out\n" + script
        os.write(fd, script)
        os.close(fd)
        fd = None
        args.append(tmpfilename[len(chroot):])
        args += otherargs
    (rfd, wfd) = os.pipe()

    if rusage:
        rusage_old = resource.getrusage(resource.RUSAGE_CHILDREN)

    pid = os.fork()
    if pid == 0:
        try:
            if chroot:
                os.chroot(chroot)
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
            # FIXME: what about PATH=%{_install_script_path}?
            e = {"HOME": "/", "USER": "root", "LOGNAME": "root",
                 "PATH": "/sbin:/bin:/usr/sbin:/usr/bin:/usr/X11R6/bin",
                 "PYRPM_VERSION" : __version__}
            if prefixes:
                e["RPM_INSTALL_PREFIX"] = prefixes[0]
                idx = 1
                for prefix in prefixes:
                    e["RPM_INSTALL_PREFIX%d" % idx] = prefix
                    idx += 1
            if rpmconfig.selinux_enabled and se_linux.is_selinux_enabled():
                _env = [ "%s=%s" % (key, e[key]) for key in e.keys() ]
                se_linux.rpm_execcon(0, args[0], args, _env)
            else:
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

    return (status, rusage_val, cret)

__symlinkhash__ = {}
def brRealPath(prefix, filename):
    # In case we aren't in a buildroot just return the realpath() of filename
    if prefix == None:
        return filename
    # Otherwise we need to manually expand the given filename and it's symlinks
    # relative to the prefix. Use a global hash to save stat() calls.
    global __symlinkhash__
    dirs = os.path.normpath(filename).split("/")[1:]
    p = ""
    for i in xrange(len(dirs)-1):
        p += "/" + dirs[i]
        # Build hash entry in case it doesn't exist
        if not __symlinkhash__.has_key(p):
            # If it's symlink...
            if os.path.islink(prefix+p):
                result = os.readlink(prefix+p)
                # set hash entry to normalized path if symlink is relative
                if result[0] != "/":
                    __symlinkhash__[p] = os.path.join(os.path.dirname(p), result)
                # otherwise just use the result we got
                else:
                    __symlinkhash__[p] = result
            # in case it isn't a symlink also mark it in the hash
            else:
                __symlinkhash__[p] = False
        # In case p is a symlink call brRealPath with fixed filename
        if __symlinkhash__[p] != False:
            return brRealPath(prefix, __symlinkhash__[p] +"/"+ "/".join(dirs[i+1:]))
    return prefix + filename
            
def installFile(rfi, infd, size, useAttrs=True, pathPrefix=None,
                useSEcontext=True):
    """Install a file described by RpmFileInfo rfi, with input of given size
    from CPIOFile infd.

    infd can be None if size == 0.  Ignore file attributes in rfi if useAttrs
    is False.  Prefix filenames by pathPrefix if defined.  Raise ValueError on
    invalid mode, IOError, OSError."""

    filename = rfi.filename
    if pathPrefix is not None:
        filename = brRealPath(pathPrefix, filename)
    mode = rfi.mode
    if S_ISREG(mode):
        makeDirs(filename)
        (fd, tmpfilename) = mkstemp_file(os.path.dirname(filename), tmpprefix)
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
            if useSEcontext:
                _setSEcontext(tmpfilename, rfi)
        except (IOError, OSError):
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, filename)
    elif S_ISDIR(mode):
        if not os.path.isdir(filename):
            os.makedirs(filename)
        if useAttrs:
            _setFileAttrs(filename, rfi)
        if useSEcontext:
            _setSEcontext(filename, rfi)
    elif S_ISLNK(mode):
        global __symlinkhash__
        data1 = rfi.linkto
        data2 = infd.read(size)
        data2 = data2.rstrip("\x00")
        symlinkfile = data1
        if data1 != data2:
            log.waring("Warning: Symlink information differs between rpm "
                       "header and cpio for %s -> %s", rfi.filename, data1)
        if os.path.islink(filename) and os.readlink(filename) == symlinkfile:
            return
        makeDirs(filename)
        tmpfilename = mkstemp_symlink(os.path.dirname(filename), tmpprefix,
                                      symlinkfile)
        try:
            if useAttrs:
                os.lchown(tmpfilename, rfi.uid, rfi.gid)
            if useSEcontext:
                _setSEcontext(tmpfilename, rfi)
        except OSError:
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, filename)
        if __symlinkhash__.has_key(rfi.filename):
            del __symlinkhash__[rfi.filename]
    elif S_ISFIFO(mode):
        makeDirs(filename)
        tmpfilename = mkstemp_mkfifo(os.path.dirname(filename), tmpprefix)
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
            if useSEcontext:
                _setSEcontext(tmpfilename, rfi)
        except OSError:
            os.unlink(tmpfilename)
            raise
        os.rename(tmpfilename, filename)
    elif S_ISCHR(mode) or S_ISBLK(mode):
        makeDirs(filename)
        try:
            tmpfilename = mkstemp_mknod(os.path.dirname(filename),
                                        tmpprefix, mode, rfi.rdev)
        except OSError:
            return # FIXME: why?
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
            if useSEcontext:
                _setSEcontext(tmpfilename, rfi)
        except OSError:
            os.unlink(filename)
            raise
        os.rename(tmpfilename, filename)
    elif S_ISSOCK(mode):
        # Sockets are useful only when bound, but what do we care...
        # Note that creating sockets using mknod is not SUSv3-mandated, quite
        # likely Linux-specific.
        # Also, only 1 know package has a socket packaged, and that was dev in
        # RH-5.2.
        makeDirs(filename)
        tmpfilename = mkstemp_mknod(os.path.dirname(filename), tmpprefix,
                                    mode, 0)
        try:
            if useAttrs:
                _setFileAttrs(tmpfilename, rfi)
            if useSEcontext:
                _setSEcontext(tmpfilename, rfi)
        except OSError:
            os.unlink(filename)
            raise
        os.rename(tmpfilename, filename)
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(mode))

def _setFileAttrs(filename, rfi):
    """Set owner, group, mode and mtime of filename data from RpmFileInfo rfi.

    Raise OSError."""

    os.chown(filename, rfi.uid, rfi.gid)
    os.chmod(filename, S_IMODE(rfi.mode))
    os.utime(filename, (rfi.mtime, rfi.mtime))

def _setSEcontext(filename, rfi):
    """Set SELinux context of filename data from RpmFileInfo rfi.

    Raise OSError."""

    if se_linux.is_selinux_enabled() >= 0:
        context = se_linux.matchpathcon(rfi.filename, rfi.mode)
        se_linux.lsetfilecon(filename, context[1])
    else:
        raise ImportError, "selinux module is not available"

def makeDirs(fullname):
    """Create a parent directory of fullname if it does not already exist.

    Raise OSError."""

    dirname = os.path.dirname(fullname)
    if len(dirname) > 1 and not os.path.exists(dirname):
        os.makedirs(dirname)

def createLink(src, dst):
    """Create a link from src to dst.

    Raise IOError, OSError."""

    try:
        # First try to unlink the defered file
        os.unlink(dst)
    except OSError:
        pass
    # Behave exactly like cpio: If the hardlink fails (because of different
    # partitions), then it has to fail
    # NEW: Don't use original cpio behaviour, we can do better: I the mkstemp
    # hardlink fails we copy the original file over retaining all modes.
    tmpfilename = mkstemp_link(os.path.dirname(dst), tmpprefix, src)
    if tmpfilename:
        os.rename(tmpfilename, dst)
    else:
        shutil.copy2(src, dst)

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
        fd = os.open(filename, os.O_EXCL|os.O_CREAT|os.O_WRONLY, 0644)
        try:
            os.write(fd, str(os.getpid()))
        finally:
            os.close(fd)
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise
        return 0
    return 1

def setSignals(handler):
    """Set the typical signals to handler, save previous handlers."""

    signals = { }
    for key in rpmconfig.supported_signals:
        signals[key] = signal.signal(key, handler)
    return signals

def unblockSignals(signals):
    """Restore previously saved handlers of the typical signals."""

    for (key, value) in signals.iteritems():
        signal.signal(key, value)

def blockSignals():
    """Blocks the typical signals to avoid interruption during critical code
    segments. Save previous handlers."""

    return setSignals(signal.SIG_IGN)

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
        except OSError:
            pass

def readExact(fd, size):
    """Read exactly size bytes from fd.

    Raise IOError on I/O error or unexpected EOF."""

    data = fd.read(size)
    if len(data) != size:
        raise IOError, "Unexpected EOF"
    return data

def updateDigestFromFile(digest, fd, bytes=None):
    """Update digest with data from fd, until EOF or only specified bytes.

    Return the number of bytes processed."""

    res = 0
    while True:
        chunk = DIGEST_CHUNK
        if bytes is not None and chunk > bytes:
            chunk = bytes
        data = fd.read(chunk)
        if not data:
            break
        digest.update(data)
        res += len(data)
        if bytes is not None:
            bytes -= len(data)
    return res

def _shellQuoteString(s):
    """Returns its argument properly quoted for parsing by a POSIX shell."""

    # Leave trivial cases unchanged
    for c in s:
        if not _xisalnum(c):
            break
    else:
        if len(s) > 0:
            return s
    res = "'"
    for c in s:
        if c != "'":
            res += c
        else:
            res += "'\\''"
    res += "'"
    return res

def shellCommandLine(args):
    """Returns a properly quoted POSIX shell command line for its arguments."""

    return " ".join([_shellQuoteString(s) for s in args])

def isSelinuxRunning():
    """Returns True if selinux is running (premissive or enforcing), false
    otherwise."""
    # No selinuxenabled check: Surely no selinux on the machine.
    if not os.path.isfile("/usr/sbin/selinuxenabled"):
        return False
    # selinuxenabled returns 0 if selinux is running
    return (os.system("/usr/sbin/selinuxenabled") == 0)

def getFreeCachespace(config, operations):
    """Check if there is enough diskspace for caching the rpms for the given
    operations.

    Return 1 if there is enough space (with 30 MB slack), 0 otherwise (after
    warning the user)."""

    return 1
    cachedir = rpmconfig.cachedir
    while 1:
        try:
            os.stat(cachedir)
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
    if freespace < 31457280:
        log.info1("Less than 30MB of diskspace left in %s for caching rpms",
                  cachedir)
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
    slack), 0 otherwise (after warning the user)."""

    if config.ignoresize:
        return 1
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
        if op == OP_UPDATE or op == OP_INSTALL or op == OP_FRESHEN:
            try:
                pkg.reread(config.diskspacetags)
            except Exception, e:
                log.error("Error rereading package: %s: %s", pkg.source, e)
                return 0
        dirnames = pkg["dirnames"]
        if dirnames == None:
            continue
        for dirname in dirnames:
            while dirname[-1:] == "/" and len(dirname) > 1:
                dirname = dirname[:-1]
            if dirname in dirhash:
                continue
            dnames = []
            devname = br + dirname
            while 1:
                dnames.append(dirname)
                try:
                    dev = os.stat(devname).st_dev
                    break
                except OSError:
                    dirname = os.path.dirname(dirname)
                    devname = os.path.dirname(devname)
                    if dirname in dirhash:
                        dev = dirhash[dirname]
                        break
            for d in dnames:
                dirhash[d] = dev
            if dev not in freehash:
                statvfs = os.statvfs(devname)
                freehash[dev] = [statvfs[0] * statvfs[4], statvfs[0]]
                minfreehash[dev] = [statvfs[0] * statvfs[4], statvfs[0]]
            if dev not in mountpoint:
                fulldir = os.path.normpath(br+"/"+dirname)
                while len(fulldir) > 0:
                    if os.path.ismount(fulldir):
                        mountpoint[dev] = dirname
                        break
                    dirname = os.path.dirname(dirname)
                    fulldir = os.path.dirname(fulldir)
        dirindexes = pkg["dirindexes"]
        filesizes = pkg["filesizes"]
        filemodes = pkg["filemodes"]
        if not dirindexes or not filesizes or not filemodes:
            continue
        for i in xrange(len(dirindexes)):
            if not S_ISREG(filemodes[i]):
                continue
            dirname = dirnames[dirindexes[i]]
            while dirname[-1:] == "/" and len(dirname) > 1:
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
                log.debug1("%s: Less than 30MB of diskspace left on %s",
                          pkg.getNEVRA(), mountpoint[dev])
        pkg.close()
        pkg.clear(ntags=config.nevratags)
    for (dev, val) in minfreehash.iteritems():
        if val[0] < 31457280:
            log.error("%sMB more diskspace required on %s for operation",
                      30 - val[0]/1024/1024, mountpoint[dev])
            ret = 0
    return ret

def int2str(val, binary=True):
    """Convert an integer to a string of the format X[.Y] [SI prefix]"""
    units = "kMGTPEZYND"
    #small_units = "munpfazy"
    if binary:
        divider = 1024
    else:
        divider = 1000

    if val>999:
        mantissa = float(val)
        exponent = -1
        while mantissa>999 and exponent<len(units)-1:
            exponent += 1
            mantissa /= divider
        if mantissa>9:
            return "%i %s" % (mantissa, units[exponent])
        else:
            return "%.1f %s" % (mantissa, units[exponent])
    else:
        return "%i" % val

def _uriToFilename(uri):
    """Convert a file:/ URI or a local path to a local path."""

    if not uri.startswith("file:/"):
        filename = uri
    else:
        filename = uri[5:]
        if len(filename) > 1 and filename[1] == "/":
            idx = filename[2:].find("/")
            if idx != -1:
                filename = filename[idx+2:]
    return filename

def parseBoolean(str):
    """Convert str to a boolean.

    Return the resulting value, default to False if str is unrecognized."""

    return str.lower() in ("yes", "true", "1", "on")

# Parse yum config options. Needed for several yum-like scripts
def parseYumOptions(argv, yum):
    """Parse yum-like config options from argv to config.rpmconfig and RpmYum
    yum.

    Return a (possibly empty) list of non-option operands on success, None on
    error (if a help message should be written).  sys.exit () on --version,
    some invalid arguments or errors in config files."""

    # Argument parsing
    try:
      opts, args = getopt.getopt(argv, "?hvqc:r:yd:R:C",
        ["help", "verbose",
         "hash", "version", "quiet", "dbpath=", "root=", "installroot=",
         "force", "ignoresize", "ignorearch", "exactarch", "justdb", "test",
         "noconflicts", "fileconflicts", "nodeps", "signature", "noorder",
         "noscripts", "notriggers", "excludedocs", "excludeconfigs",
         "oldpackage", "autoerase", "autoeraseexclude=", "servicehack",
         "installpkgs=", "arch=", "archlist=", "checkinstalled", "rusage",
         "srpmdir=", "enablerepo=", "disablerepo=", "nocache", "cachedir=",
         "exclude=", "obsoletes", "noplugins", "diff", "verifyallconfig",
         "languages=", "releaseversion=", "disablerhn"])
    except getopt.error, e:
        # FIXME: all to stderr
        log.error("Error parsing command-line arguments: %s", e)
        return None

    verbose = log.INFO2

    # Argument handling
    new_yumconf = 0
    for (opt, val) in opts:
        if   opt in ['-?', "--help"]:
            return None
        elif opt in ["-v", "--verbose"]:
            verbose += 1
        elif opt in ["-q", "--quiet"]:
            verbose -= 1
        elif opt in ["-r", "--root", "--installroot"]:
            rpmconfig.buildroot = val
        elif opt == "-c":
            if not new_yumconf:
                rpmconfig.yumconf = []
                new_yumconf = 1
            rpmconfig.yumconf.append(val)
        elif opt == "-R":
            # Basically we ignore this for now, just don't throw an error ;)
            pass
        elif opt == "-C":
            # Basically we ignore this for now, just don't throw an error ;)
            pass
        elif opt == "--autoerase":
            yum.setAutoerase(1)
        elif opt == "--autoeraseexclude":
            yum.setAutoeraseExclude(val.split())
        elif opt == "--version":
            print "pyrpmyum", __version__
            sys.exit(0)
        elif opt == "-y":
            yum.setConfirm(0)
        elif opt == "-d":
            val = val.split(':', 1)
            if len(val) == 1:
                level = val[0]
                domain = '*'
            else:
                domain, level = val
            try:
                level = int(level)
            except ValueError:
                print "Invalid debug level"
                return None
            log.setDebugLogLevel(level, domain)
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
        elif opt == "--signature":
            rpmconfig.nosignature = 0
        elif opt == "--noorder":
            rpmconfig.noorder = 1
        elif opt == "--noscripts":
            rpmconfig.noscripts = 1
        elif opt == "--notriggers":
            rpmconfig.notriggers = 1
        elif opt == "--excludedocs":
            rpmconfig.excludedocs = 1
        elif opt == "--excludeconfigs":
            rpmconfig.excludeconfigs = 1
        elif opt == "--servicehack":
            rpmconfig.service = 1
        elif opt == "--arch":
            rpmconfig.arch = val
        elif opt == "--archlist":
            rpmconfig.archlist = val.split()
        elif opt == "--checkinstalled":
            rpmconfig.checkinstalled = 1
        elif opt == "--srpmdir":
            rpmconfig.srpmdir = val
        elif opt == "--enablerepo":
            rpmconfig.enablerepo.append(val)
        elif opt == "--disablerepo":
            rpmconfig.disablerepo.append(val)
        elif opt == "--nocache":
            rpmconfig.nocache = 1
        elif opt == "--cachedir":
            rpmconfig.cachedir = val
        elif opt == "--exclude":
            rpmconfig.excludes.append(val)
        elif opt == "--obsoletes":
            # Basically we ignore this for now, just don't throw an error ;)
            pass
        elif opt == "--noplugins":
            # Basically we ignore this for now, just don't throw an error ;)
            pass
        elif opt == "--diff":
            rpmconfig.diff = True
        elif opt == "--verifyallconfig":
            rpmconfig.verifyallconfig = True
        elif opt == "--languages":
            yum.langs = val.split()
        elif opt == "--releaseversion":
            rpmconfig.relver = val
        elif opt == "--disablerhn":
            yum.rhnenabled = False

    log.setInfoLogLevel(verbose)

    if rpmconfig.arch != None:
        if not rpmconfig.test and \
           not rpmconfig.justdb and \
           not rpmconfig.ignorearch:
            log.error("Arch option can only be used for tests")
            sys.exit(1)
        if rpmconfig.arch not in buildarchtranslate:
            log.error("Unknown arch %s", rpmconfig.arch)
            sys.exit(1)
        rpmconfig.machine = rpmconfig.arch

    return args

def calcDistanceHash(arch):
    """Calculate a machine distance hash for all arches for the given arch"""

    disthash = {}
    for tarch in arch_compats.keys():
        disthash[tarch] = machineDistance(arch, tarch)
    return disthash

def raw_input2(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()
    return raw_input()

def is_this_ok():
    choice = raw_input2("Is this ok [y/N]: ")
    if len(choice) == 0 or (choice[0] != "y" and choice[0] != "Y"):
        return 0
    return 1

# Exact reimplementation of glibc's bsearch algorithm. Used by rpm to
# generate dirnames, dirindexes and basenames from oldfilenames (and we need
# to do it the same way).
def bsearch(key, list):
    l = 0
    u = len(list)
    while l < u:
        idx = (l + u) / 2;
        if   key < list[idx]:
            u = idx
        elif key > list[idx]:
            l = idx + 1
        else:
            return idx
    return -1

# ----------------------------------------------------------------------------

def evrSplit(evr, defaultepoch="0"):
    """Split evr to components.

    Return (E, V, R).  Default epoch to defaultepoch and release to ""
    if not specified."""
    epoch = defaultepoch
    i = evr.find(":")
    if i != -1 and evr[:i].isdigit():
        epoch = evr[:i]
    j = evr.rfind("-", i + 1)
    if j != -1:
        return (epoch, evr[i + 1:j], evr[j + 1:])
    return (epoch, evr[i + 1:], "")

def evrMerge(e, v, r):
    result = v or ""
    if r:
        result = "%s-%s" % (result, r)
    if e:
        result = "%s:%s" % (e, result)
    return result

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

    if str1 == str2:
        return 0
    lenstr1 = len(str1)
    lenstr2 = len(str2)
    i1 = 0
    i2 = 0
    while i1 < lenstr1 and i2 < lenstr2:
        # remove leading separators
        while i1 < lenstr1 and not _xisalnum(str1[i1]):
            i1 += 1
        while i2 < lenstr2 and not _xisalnum(str2[i2]):
            i2 += 1
        if i1 == lenstr1 or i2 == lenstr2: # bz 178798
            break
        # start of the comparison data, search digits or alpha chars
        j1 = i1
        j2 = i2
        if j1 < lenstr1 and _xisdigit(str1[j1]):
            while j1 < lenstr1 and _xisdigit(str1[j1]):
                j1 += 1
            while j2 < lenstr2 and _xisdigit(str2[j2]):
                j2 += 1
            isnum = 1
        else:
            while j1 < lenstr1 and _xisalpha(str1[j1]):
                j1 += 1
            while j2 < lenstr2 and _xisalpha(str2[j2]):
                j2 += 1
            isnum = 0
        # check if we already hit the end
        if j1 == i1:
            return -1
        if j2 == i2:
            if isnum:
                return 1
            return -1
        if isnum:
            # ignore leading "0" for numbers (1 == 000001)
            while i1 < j1 and str1[i1] == "0":
                i1 += 1
            while i2 < j2 and str2[i2] == "0":
                i2 += 1
            # longer size of digits wins
            if j1 - i1 > j2 - i2:
                return 1
            if j2 - i2 > j1 - i1:
                return -1
        x = cmp(str1[i1:j1], str2[i2:j2])
        if x:
            return x
        # move to next comparison start
        i1 = j1
        i2 = j2
    if i1 == lenstr1:
        if i2 == lenstr2:
            return 0
        return -1
    return 1

def labelCompare(e1, e2):
    """Compare (E, V, R) tuples e1 and e2.

    Return an integer with the same sign as (e1 - e2).  If either of the tuples
    has empty release, ignore releases in comparison."""

    r = stringCompare(e1[0], e2[0])
    if r == 0:
        r = stringCompare(e1[1], e2[1])
        if r == 0:
            if e1[2] == "" or e2[2] == "": # no release
                return 0
            r = stringCompare(e1[2], e2[2])
    return r

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

def doesObsolete(pkg1, pkg2):
    """Checks whether pk1 obsoletes pkg2. Return 1 if it does, 0 otherwise."""
    
    for obs in pkg1["obsoletes"]:
        for pro in pkg2["provides"]:
            if obs[0] != pro[0]:
                continue
            if rangeCompare(obs[1], evrSplit(obs[2]), pro[1], evrSplit(pro[2])):
                return 1
    return 0

def depString((name, flag, version)):
    """Return a string representation of (name, RPMSENSE_* flag, version)
    condition."""

    if version == "":
        return name
    return "%s %s %s" % (name, rpmFlag2Str(flag), version)

def archCompat(parch, arch):
    """Return True if package with architecture parch can be installed on
    machine with arch arch."""

    try:
        return (arch == "noarch" or parch in arch_compats[arch])
    except KeyError:
        return False

def archDuplicate(parch, arch):
    """Return True if parch and arch have the same base arch."""

    return (parch == arch
        or buildarchtranslate.get(parch, parch) == buildarchtranslate.get(arch, arch))

def filterArchCompat(list, arch):
    """Modify RpmPackage list list to contain only packages that can be
    installed on arch arch.

    Warn using config.rpmconfig about dropped packages."""

    i = 0
    while i < len(list):
        if archCompat(list[i]["arch"], arch):
            i += 1
        else:
            log.warning("%s: Architecture not compatible with %s",
                        list[i].source, arch)
            list.pop(i)

def normalizeList(l):
    """Modify list to contain every entry at most once.
    Doesn't use a stable algorithm anymore!
    """
    l[:] = set(l)

def pkgmdcmp((pkg1, md1), (pkg2, md2)):
    # Need a special comparator function for this as pkg equality atm isn't
    # really working as intended and screws us bigtime.
    # We need to order pkg NEVRs ascending and machine distance descending,
    # thats why the return values are counterwise for pkg and md comparisons.
    if   pkg1 < pkg2:
        return -1
    elif pkg1 > pkg2:
        return 1
    if   md1 < md2:
        return 1
    elif md1 > md2:
        return -1
    return 0

def orderList(list, arch):
    """Order RpmPackage list by "distance" to arch (ascending) and EVR
    (descending), in that order."""

    tmplist = [(l, machineDistance(l["arch"], arch)) for l in list ]
    tmplist.sort(pkgmdcmp)
    tmplist.reverse()
    list[:] = [l[0] for l in tmplist]

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
    if arch2 in arch_compats.get(arch1, []):
        return arch_compats[arch1].index(arch2) + 2
    elif arch1 in arch_compats.get(arch2, []):
        return arch_compats[arch2].index(arch1) + 2
    else:
        return 999   # incompatible archs, distance is very high ;)

def readRpmPackage(config, source, verify=None, hdronly=None,
                   db=None, tags=None):
    """Read RPM package from source and close it.

    tags, if defined, specifies tags to load.  Raise ValueError on invalid
    data, IOError."""

    pkg = package.RpmPackage(config, source, verify, hdronly, db)
    try:
        pkg.read(tags=tags)
        pkg.close()
    except (IOError, ValueError), e:
        log.error("%s: %s\n", pkg, e)
        return None
    if not config.ignorearch and \
       not archCompat(pkg["arch"], config.machine) and \
       not pkg.isSourceRPM():
        log.info3("%s: Package excluded because of arch "
                   "incompatibility", pkg.getNEVRA())
        return None
    return pkg

def readDir(dir, list, rtags=None):
    """Append RpmPackage's for *.rpm in the subtree rooted at dir to list.

    Read only rtags if rtags is not None."""

    if not os.path.isdir(dir):
        return
    for f in os.listdir(dir):
        if os.path.isdir("%s/%s" % (dir, f)):
            readDir("%s/%s" % (dir, f), list)
        elif f.endswith(".rpm"):
            pkg = readRpmPackage(rpmconfig, dir+"/"+f, tags=rtags)
            if pkg == None:
                continue
            log.info3("Reading package %s.", pkg.getNEVRA())
            list.append(pkg)

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
        log.info2("Starting profil statistics. This takes some time...")
        s = hotshot.stats.load(htfilename)
        s.strip_dirs().sort_stats("time").print_stats(100)
        s.strip_dirs().sort_stats("cumulative").print_stats(100)
        os.unlink(htfilename)
    else:
        return main()

def pathsplit(filename):
    i = filename.rfind("/") + 1
    return (filename[:i].rstrip("/") or "/", filename[i:])
    #return os.path.split(filename)

def pathdirname(filename):
    j = filename.rfind("/") + 1
    return filename[:j].rstrip("/") or "/"
    #return pathsplit(filename)[0]
    #return os.path.dirname(filename)

def pathsplit2(filename):
    i = filename.rfind("/") + 1
    return (filename[:i], filename[i:])
    #(dirname, basename) = os.path.split(filename)
    #if dirname[-1:] != "/" and dirname != "":
    #    dirname += "/"
    #return (dirname, basename)

# vim:ts=4:sw=4:showmatch:expandtab
