#!/usr/bin/python
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
# Copyright 2004, 2005, 2006, 2007 Red Hat, Inc.
#
# Author: Paul Nasrat, Florian La Roche, Phil Knirsch, Thomas Woerner,
#         Florian Festi
#

#
# Read .rpm packages from python. Implemented completely in python without
# using the librpm C library. Use "oldpyrpm.py -h" to get a list of possible
# options and http://people.redhat.com/laroche/pyrpm/ also has some docu.
# This python script depends on libxml2 and urlgrabber for some functionality.
#
# Tested with all rpm packages from RHL5.2, 6.x, 7.x, 8.0, 9,
# Fedora Core 1/2/3/4/5/6/development, Fedora Extras, livna, freshrpms,
# Mandriva 10.2, Open SuSE 10RC1 and other distributions.
# No output should be generated if rpm packages are verified via this python
# implementation, so all possible quirks in the binary packages are taken
# care of and can be read in this code.
#
# Known problem areas of /bin/rpm and this pyrpm script:
# - Signing a second time can corrupt packages with older /bin/rpm releases.
# - Packages built with a broken kernel that does not mmap() files with
#   size 0 just have that filemd5sum set to "" and "rpm -V" also fails.
# - Verify mode warns about a few packages from RHL5.x (rpm-2.x).
# - CentOS 3.7/ia64 and 4.3/alpha rpm packages cannot be read, might be
#   endian problems showing up?
#

#
# TODO:
# git repos:
# - Optionally import the full tree for the initial import (e.g. FC releases).
# - Optionally also sort by time for e.g. FC updates dirs.
# general:
# - Separate out the parts which are distro-specific and support more
#   distro variants.
# - Should we get rid of doRead()?
# - How todo save shell escapes for os.system()
# - Better error handling in PyGZIP.
# - streaming read for cpio files
# - use setPerms() in doLnOrCopy()
# - Change "strict" and "verify" into "debug/verbose" and have one integer
#   specify debug and output levels. (Maybe also "nodigest" can move in?)
# - Whats the difference between "cookie" and "buildhost" + "buildtime".
# - Locking done for read/write rpmdb access. Check /bin/rpm and yum.
# - Should we delete the __db* cache files? What about db4 config settings?
# rpm header:
# - write tag 61 if no region tag exists
# - --checkrpmdb --enablerepos: allow changed signatures in packages
# - check against current upstream rpm development
# - Can doVerify() be called on rpmdb data or if the sig header is
#   missing?
# - allow a --rebuilddb into a new directory and a diff between two rpmdb
# - rpmdb cleanup to remove duplicate rpm entries (yum-utils has this already)
# - check OpenGPG signatures
#   - allow src.rpm selection based on OpenGPG signature. Prefer GPG signed.
# - add a new writeHeader2() that copies the existing rpm header and then
#   writes new entries to the end. This is more robust than the existing
#   writeHeader().
# - For reading rpmdb we could first try to detect the region tag, then
#   read all additional added tags into a separate hash. This would really
#   clean up data handling and how duplicate tags are taken care off.
#   This should now be done on the write side, the reading part should
#   probably stay as it is.
# - Bring extractCpio and verifyCpio closer together again.
# - Cpio extract should only set hardlinks for files who have already shown
#   up in the cpio earlier (before the data).
# - i386 rpm extraction on ia64? (This is stored like relocated rpms in
#   duplicated file tags.)
# yum.conf/repos:
# - For repos stop switching to another server once repomd.xml is read in.
#   Currently also all rpms are associated/hardcoded with the first server.
#   Rpms could be cached regardless of the mirror they come from. By sha1sum?
# - cacheLocal:
#   - If we get data from several mirrors, how should we combine data without
#     refetching data too often or overriding data too soon? If we know a
#     checksum for all data, we could store data by checksum filename?
#   - check if local files really exist with os.stat()?,
#     maybe only once per repo? (for repo sorting)
#   - sort several urls to list local ones first, add mirror speed check
#   - Read the complete file into memory, no local files for: repomd.xml
#     and mirrorlist.
# - Can we cache the mirrorlist for some time?
# things to be noted, probably not getting fixed:
# - "badsha1_2" has the size added in reversed order to compute the final
#   sha1 sum. A patch to python shamodule.c could allow to verify also these
#   old broken entries.
# things that look even less important to implement:
# - add streaming support to bzip2 compressed payload
# - lua scripting support
# possible changes for /bin/rpm:
# - Do not generate filecontexts tags if they are empty, maybe not at all.
# - "rhnplatform" could go away if it is not required.
#

__version__ = "0.69"
__doc__ = """Manage everything around Linux RPM packages."""


# Look at "pylint --list-msgs" to find these out:
# pylint: disable-msg=C0103,C0111
# pylint: disable-msg=R0902,R0903,R0911,R0912,R0913,R0914,R0915
# pylint: disable-msg=W0142,W0201,W0511,W0704

import sys
if sys.version_info < (2, 2):
    sys.exit("error: Python 2.2 or later required")
import os, os.path, zlib, gzip, errno, re, time
import md5, sha, signal
from types import IntType, ListType
from struct import pack, unpack
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
uselibxml = 0
try:
    # python-2.5 layout:
    from xml.etree.cElementTree import iterparse
except ImportError:
    try:
        # often older python versions add this to site-packages:
        from cElementTree import iterparse
    except ImportError:
        try:
            # maybe the python-only version is available?
            from ElementTree import iterparse
        except:
            # ok, we give up and use libxml then:
            uselibxml = 1
#if uselibxml:
try:
    import libxml2
    TYPE_ELEMENT = libxml2.XML_READER_TYPE_ELEMENT
    TYPE_END_ELEMENT = libxml2.XML_READER_TYPE_END_ELEMENT
except ImportError:
    print "libxml2 is not imported, do not try to use repodata."

# python-only
if sys.version_info < (2, 3):
    from types import StringType
    basestring = StringType # pylint: disable-msg=W0622

    TMP_MAX = 10000
    from random import Random
    class _RandomNameSequence:
        """An instance of _RandomNameSequence generates an endless
        sequence of unpredictable strings which can safely be incorporated
        into file names.  Each string is six characters long.

        _RandomNameSequence is an iterator."""

        characters = ("abcdefghijklmnopqrstuvwxyz" +
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
                      "0123456789-_")

        def __init__(self):
            self.rng = Random()
            self.normcase = os.path.normcase

        def __iter__(self):
            return self

        def next(self):
            c = self.characters
            choose = self.rng.choice
            letters = [choose(c) for _ in "123456"]
            return self.normcase("".join(letters))

    _name_sequence = None

    def _get_candidate_names():
        """Common setup sequence for all user-callable interfaces."""
        global _name_sequence # pylint: disable-msg=W0603
        if _name_sequence == None:
            _name_sequence = _RandomNameSequence()
        return _name_sequence
else:
    from tempfile import _get_candidate_names, TMP_MAX
# python-only-end
# pyrex-code
#from tempfile import _get_candidate_names, TMP_MAX
#cdef extern from "string.h":
#    int strlen(char *)
#cdef extern from "netinet/in.h":
#    unsigned int ntohl(unsigned int netlong)
#cdef extern from "Python.h":
#    object PyString_FromStringAndSize(char *s, int len)
# pyrex-code-end

# optimized routines instead of:
#from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, \
#   S_ISBLK, S_ISSOCK
# python-only
def S_ISREG(mode):
    return (mode & 0170000) == 0100000
def S_ISLNK(mode):
    return (mode & 0170000) == 0120000
def S_ISDIR(mode):
    return (mode & 0170000) == 0040000
def S_ISFIFO(mode):
    return (mode & 0170000) == 0010000
def S_ISCHR(mode):
    return (mode & 0170000) == 0020000
def S_ISBLK(mode):
    return (mode & 0170000) == 0060000
def S_ISSOCK(mode):
    return (mode & 0170000) == 0140000
# python-only-end
# pyrex-code
#cdef S_ISREG(int mode):
#    return (mode & 0170000) == 0100000
#cdef S_ISLNK(int mode):
#    return (mode & 0170000) == 0120000
#cdef S_ISDIR(int mode):
#    return (mode & 0170000) == 0040000
#cdef S_ISFIFO(int mode):
#    return (mode & 0170000) == 0010000
#cdef S_ISCHR(int mode):
#    return (mode & 0170000) == 0020000
#cdef S_ISBLK(int mode):
#    return (mode & 0170000) == 0060000
#cdef S_ISSOCK(int mode):
#    return (mode & 0170000) == 0140000
# pyrex-code-end

# Use this filename prefix for all temp files to be able
# to search them and delete them again if they are left
# over from killed processes.
tmpprefix = "..pyrpm"

tmpdir = os.environ.get("TMPDIR", "/tmp")

openflags = os.O_RDWR | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOINHERIT"):
    openflags |= os.O_NOINHERIT # pylint: disable-msg=E1101
if hasattr(os, "O_NOFOLLOW"):
    openflags |= os.O_NOFOLLOW  # pylint: disable-msg=E1101

def mkstemp_file(dirname, pre=tmpprefix, special=0):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
            if special:
                fd = open(filename, "wb")
            else:
                fd = os.open(filename, openflags, 0600)
            #_set_cloexec(fd)
            return (fd, filename)
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_link(dirname, pre, linkfile):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
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

def mkstemp_dir(dirname, pre=tmpprefix):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
            os.mkdir(filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_symlink(dirname, pre, symlinkfile):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
            os.symlink(symlinkfile, filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_mkfifo(dirname, pre):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
            os.mkfifo(filename)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def mkstemp_mknod(dirname, pre, mode, rdev):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
            os.mknod(filename, mode, rdev)
            return filename
        except OSError, e:
            if e.errno == errno.EEXIST:
                continue # try again
            raise
    raise IOError, (errno.EEXIST, "No usable temporary file name found")

def doLnOrCopy(src, dst):
    """Hardlink or copy a file "src" to a new file "dst"."""
    dstdir = pathdirname(dst)
    tmp = mkstemp_link(dstdir, tmpprefix, src)
    if tmp == None:
        # no hardlink possible, copy the data into a new file
        (fd, tmp) = mkstemp_file(dstdir)
        fsrc = open(src, "rb")
        while 1:
            buf = fsrc.read(16384)
            if not buf:
                break
            os.write(fd, buf)
        fsrc.close()
        os.close(fd)
        st = os.stat(src)
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.chmod(tmp, st.st_mode & 0170000)
        if os.geteuid() == 0:
            os.lchown(tmp, st.st_uid, st.st_gid)
    os.rename(tmp, dst)

def doRead(fd, size):
    data = fd.read(size)
    if len(data) != size:
        raise IOError, "failed to read data (%d instead of %d)" \
            % (len(data), size)
    return data

def getChecksum(fd, digest="md5"):
    if isinstance(fd, basestring):
        try:
            fd = open(fd, "rb")
        except IOError:
            return None
    if digest == "md5":
        ctx = md5.new()
    else:
        ctx = sha.new()
    while 1:
        data = fd.read(16384)
        if not data:
            break
        ctx.update(data)
    return ctx.hexdigest()

def getMD5(fpath):
    return getChecksum(fpath, "md5")

supported_signals = [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]
#supported_signals.extend([signal.SIGSEGV, signal.SIGBUS, signal.SIGABRT,
# signal.SIGILL, signal.SIGFPE])

def setSignals(handler, supported_signals2):
    signals = {}
    for key in supported_signals2:
        signals[key] = signal.signal(key, handler)
    return signals

def blockSignals():
    return setSignals(signal.SIG_IGN, supported_signals)

def resetSignals(signals):
    for (key, value) in signals.iteritems():
        signal.signal(key, value)


def _doprint(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()

class PrintHash:
    """'numobjects' indicates how often we will call.nectObject()
    and 'hashlength' gives the number of '#' hash chars we want to
    output.  """

    def __init__(self, numobjects=100, hashlength=30):
        # Make sure we don't get a division by zero.
        if not numobjects:
            numobjects = 1
        self.numobjects = numobjects
        self.hashlength = hashlength
        self.num = 0
        # Immediately output something to indicate a first start:
        self.hashpos = 1
        _doprint("#")

    def nextObject(self, finish=None):
        if finish:
            # Output the rest of the hashes now:
            npos = self.hashlength
        else:
            self.num += 1
            npos = (self.num * self.hashlength) / self.numobjects
            # In case we call .nextObject() too often:
            if npos > self.hashlength:
                npos = self.hashlength
        msg = ""
        if self.hashpos < npos:
            msg = "#" * (npos - self.hashpos)
            self.hashpos = npos
        if finish:
            msg += "\n"
        if msg:
            _doprint(msg)


# Optimized routines that use zlib to extract data, since
# "import gzip" doesn't give good data handling (old code
# can still easily be enabled to compare performance):

class PyGZIP:
    def __init__(self, filename, fd, datasize, readsize):
        self.filename = filename
        if fd == None:
            fd = open(filename, "rb")
        self.fd = fd
        self.length = 0 # length of all decompressed data
        self.length2 = datasize
        self.readsize = readsize
        if self.readsize != None:
            self.readsize -= 10
        self.enddata = "" # remember last 8 bytes for crc/length check
        self.pos = 0
        self.data = ""
        data = doRead(self.fd, 10)
        if data[:3] != "\037\213\010":
            raise ValueError, "Not a gzipped file: %s" % self.filename
        # flag (1 byte), modification time (4 bytes), extra flags (1), OS (1)
        flag = ord(data[3])
        if flag & 4: # extra field
            xlen = ord(self.fd.read(1))
            xlen += 256 * ord(self.fd.read(1))
            doRead(self.fd, xlen)
            if self.readsize != None:
                self.readsize -= 2 + xlen
        if flag & 8: # filename
            while self.fd.read(1) != "\000":
                if self.readsize != None:
                    self.readsize -= 1
            if self.readsize != None:
                self.readsize -= 1
        if flag & 16: # comment string
            while self.fd.read(1) != "\000":
                if self.readsize != None:
                    self.readsize -= 1
            if self.readsize != None:
                self.readsize -= 1
        if flag & 2:
            doRead(self.fd, 2) # 16-bit header CRC
            if self.readsize != None:
                self.readsize -= 2
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")

    def read(self, bytes):
        decompdata = []
        obj = self.decompobj
        while bytes:
            if self.data:
                if len(self.data) - self.pos <= bytes:
                    decompdata.append(self.data[self.pos:])
                    bytes -= len(self.data) - self.pos
                    self.data = ""
                    continue
                end = self.pos + bytes
                decompdata.append(self.data[self.pos:end])
                self.pos = end
                break
            readsize = 32768
            if self.readsize != None and self.readsize < 32768:
                readsize = self.readsize
            data = self.fd.read(readsize)
            if not data:
                break
            if self.readsize != None:
                self.readsize -= len(data)
            if len(data) >= 8:
                self.enddata = data[-8:]
            else:
                self.enddata = self.enddata[len(data) - 8:] + data
            x = obj.decompress(data)
            self.crcval = zlib.crc32(x, self.crcval)
            self.length += len(x)
            if len(x) <= bytes:
                bytes -= len(x)
                decompdata.append(x)
            else:
                decompdata.append(x[:bytes])
                self.data = x
                self.pos = bytes
                break
        return "".join(decompdata)

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def __del__(self):
        # Sanity check.
        if self.data:
            self.printErr("PyGZIP: bytes left to read: %d" % \
                (len(self.data) - self.pos))
        if self.readsize != None:
            # zlib sometimes adds one or two additional bytes that it also
            # does not need to decompress all data again.
            data = doRead(self.fd, 8 + self.readsize)
            self.enddata = data[-8:]
        else:
            data = self.fd.read()
            if len(data) >= 8:
                self.enddata = data[-8:]
            else:
                self.enddata = self.enddata[len(data) - 8:] + data
        (crc32, isize) = unpack("<iI", self.enddata)
        if crc32 != self.crcval:
            print self.filename, "CRC check failed:", crc32, self.crcval
        if isize != self.length:
            print self.filename, "Incorrect length of data produced:", \
                isize, self.length
        if isize != self.length2 and self.length2 != None:
            print self.filename, "Incorrect length of data produced:", \
                self.length2


class GzipFile(gzip.GzipFile):
    def _write_gzip_header(self):
        self.fileobj.write("\037\213\010") # magic header + compression method
        fname = self.filename[:-3]
        flags = "\000"
        if fname:
            flags = "\010"
        self.fileobj.write(flags + "\000\000\000\000\002\377")
        if fname:
            self.fileobj.write(fname + "\000")


cachedir = "/var/cache/pyrpm/"
opensuse = 0


def setProxyOptions(o):
    import urlparse
    proxies = {}
    proxy_string = o.get("proxy", None)
    if proxy_string not in (None, "", "_none_"):
        proxy_username = o.get("proxy_username", None)
        if proxy_username != None:
            password = o.get("proxy_password", "")
            if password:
                password = ":" + password
            parsed = urlparse.urlsplit(proxy_string, allow_fragments=0)
            proxy_string = "%s://%s%s@%s%s" % (parsed[0], proxy_username,
                password, parsed[1], parsed[2] + "?" + parsed[3])
        proxies["http"] = proxy_string
        proxies["https"] = proxy_string
        proxies["ftp"] = proxy_string
    o["proxies"] = proxies

def setOptions(yumconf={}, repo=None): # pylint: disable-msg=W0102
    # Default values:
    o = {
        "timeout": "20.0",
        "keepalive": "0",
        "retries": "3",
        "http_caching": "all",
        "proxy": None,
        "proxy_username": None,
        "proxy_password": None,
        # Set the proxy settings from above into urlgrabber data:
        "proxies": {},
        "http_headers": None
    }
    # Override with "main" settings:
    for (key, value) in yumconf.get("main", {}).iteritems():
        o[key] = value
    # Override with repo-specific settings:
    for (key, value) in yumconf.get(repo, {}).iteritems():
        o[key] = value
    # Set proxy items:
    setProxyOptions(o)
    # Set http headers:
    headers = []
    # If we should not cache and we don't already contain
    # a Pragma header, then add it...
    nocache = ("Pragma", "no-cache")
    if o["http_caching"] != "all" and nocache not in headers:
        headers.append(nocache)
    o["http_headers"] = headers
    return o

urloptions = setOptions()


# rpm tag types
#RPM_NULL = 0
RPM_CHAR = 1
RPM_INT8 = 2 # currently unused
RPM_INT16 = 3
RPM_INT32 = 4
RPM_INT64 = 5 # currently unused
RPM_STRING = 6
RPM_BIN = 7
RPM_STRING_ARRAY = 8
RPM_I18NSTRING = 9
# new types internal to this tool:
# RPM_STRING_ARRAY for app + params, otherwise a single RPM_STRING
RPM_ARGSTRING = 12
RPM_GROUP = 13
# pyrex-code
#cdef int cRPM_CHAR, cRPM_INT8, cRPM_INT16, cRPM_INT32, cRPM_INT64
#cdef int cRPM_STRING, cRPM_BIN, cRPM_STRING_ARRAY, cRPM_I18NSTRING
#cdef int cRPM_ARGSTRING, cRPM_GROUP
#cRPM_CHAR = 1
#cRPM_INT8 = 2
#cRPM_INT16 = 3
#cRPM_INT32 = 4
#cRPM_INT64 = 5
#cRPM_STRING = 6
#cRPM_BIN = 7
#cRPM_STRING_ARRAY = 8
#cRPM_I18NSTRING = 9
#cRPM_ARGSTRING = 12
#cRPM_GROUP = 13
# pyrex-code-end

# RPMSENSEFLAGS
RPMSENSE_ANY        = 0
RPMSENSE_SERIAL     = (1 << 0)          # legacy
RPMSENSE_LESS       = (1 << 1)
RPMSENSE_GREATER    = (1 << 2)
RPMSENSE_EQUAL      = (1 << 3)
RPMSENSE_PROVIDES   = (1 << 4)          # only used internally by builds
RPMSENSE_CONFLICTS  = (1 << 5)          # only used internally by builds
RPMSENSE_PREREQ     = (1 << 6)          # legacy
RPMSENSE_OBSOLETES  = (1 << 7)          # only used internally by builds
RPMSENSE_INTERP     = (1 << 8)          # Interpreter used by scriptlet.
RPMSENSE_SCRIPT_PRE = ((1 << 9) | RPMSENSE_PREREQ)   # %pre dependency
RPMSENSE_SCRIPT_POST = ((1 << 10)|RPMSENSE_PREREQ)   # %post dependency
RPMSENSE_SCRIPT_PREUN = ((1 << 11)|RPMSENSE_PREREQ)  # %preun dependency
RPMSENSE_SCRIPT_POSTUN = ((1 << 12)|RPMSENSE_PREREQ) # %postun dependency
RPMSENSE_SCRIPT_VERIFY = (1 << 13)      # %verify dependency
RPMSENSE_FIND_REQUIRES = (1 << 14)      # find-requires generated dependency
RPMSENSE_FIND_PROVIDES = (1 << 15)      # find-provides generated dependency
RPMSENSE_TRIGGERIN  = (1 << 16)         # %triggerin dependency
RPMSENSE_TRIGGERUN  = (1 << 17)         # %triggerun dependency
RPMSENSE_TRIGGERPOSTUN = (1 << 18)      # %triggerpostun dependency
RPMSENSE_MISSINGOK  = (1 << 19)         # suggests/enhances/recommends hint
RPMSENSE_SCRIPT_PREP = (1 << 20)        # %prep build dependency
RPMSENSE_SCRIPT_BUILD = (1 << 21)       # %build build dependency
RPMSENSE_SCRIPT_INSTALL = (1 << 22)     # %install build dependency
RPMSENSE_SCRIPT_CLEAN = (1 << 23)       # %clean build dependency
RPMSENSE_RPMLIB     = ((1 << 24) | RPMSENSE_PREREQ) # rpmlib(feature) dependency
RPMSENSE_TRIGGERPREIN = (1 << 25)       # @todo Implement %triggerprein
RPMSENSE_KEYRING    = (1 << 26)
RPMSENSE_PATCHES    = (1 << 27)
RPMSENSE_CONFIG     = (1 << 28)

RPMSENSE_SENSEMASK  = 15 # Mask to get senses: serial, less, greater, equal.


RPMSENSE_TRIGGER = (RPMSENSE_TRIGGERIN | RPMSENSE_TRIGGERUN
    | RPMSENSE_TRIGGERPOSTUN)

_ALL_REQUIRES_MASK  = (RPMSENSE_INTERP | RPMSENSE_SCRIPT_PRE
    | RPMSENSE_SCRIPT_POST | RPMSENSE_SCRIPT_PREUN | RPMSENSE_SCRIPT_POSTUN
    | RPMSENSE_SCRIPT_VERIFY | RPMSENSE_FIND_REQUIRES | RPMSENSE_SCRIPT_PREP
    | RPMSENSE_SCRIPT_BUILD | RPMSENSE_SCRIPT_INSTALL | RPMSENSE_SCRIPT_CLEAN
    | RPMSENSE_RPMLIB | RPMSENSE_KEYRING)

def _notpre(x):
    return (x & ~RPMSENSE_PREREQ)

_INSTALL_ONLY_MASK = _notpre(RPMSENSE_SCRIPT_PRE | RPMSENSE_SCRIPT_POST
    | RPMSENSE_RPMLIB | RPMSENSE_KEYRING)
_ERASE_ONLY_MASK   = _notpre(RPMSENSE_SCRIPT_PREUN | RPMSENSE_SCRIPT_POSTUN)

def isLegacyPreReq(x):
    return (x & _ALL_REQUIRES_MASK) == RPMSENSE_PREREQ
def isInstallPreReq(x):
    return (x & _INSTALL_ONLY_MASK) != 0
def isErasePreReq(x):
    return (x & _ERASE_ONLY_MASK) != 0


# RPM file attributes
RPMFILE_NONE        = 0
RPMFILE_CONFIG      = (1 <<  0)    # from %%config
RPMFILE_DOC         = (1 <<  1)    # from %%doc
RPMFILE_ICON        = (1 <<  2)    # from %%donotuse.
RPMFILE_MISSINGOK   = (1 <<  3)    # from %%config(missingok)
RPMFILE_NOREPLACE   = (1 <<  4)    # from %%config(noreplace)
RPMFILE_SPECFILE    = (1 <<  5)    # .spec file in source rpm
RPMFILE_GHOST       = (1 <<  6)    # from %%ghost
RPMFILE_LICENSE     = (1 <<  7)    # from %%license
RPMFILE_README      = (1 <<  8)    # from %%readme
RPMFILE_EXCLUDE     = (1 <<  9)    # from %%exclude, internal
RPMFILE_UNPATCHED   = (1 << 10)    # placeholder (SuSE)
RPMFILE_PUBKEY      = (1 << 11)    # from %%pubkey
RPMFILE_POLICY      = (1 << 12)    # from %%policy


# List of all rpm tags we care about. We mark older tags which are
# not anymore in newer rpm packages (Fedora Core development tree) as
# "legacy".
# tagname: [tag, type, how-many, flags:legacy=1,
#           src-only=2,bin-only=4,signed-int=8]
rpmtag = {
    # basic info
    "name": [1000, RPM_STRING, None, 0],
    "epoch": [1003, RPM_INT32, 1, 0],
    "version": [1001, RPM_STRING, None, 0],
    "release": [1002, RPM_STRING, None, 0],
    "arch": [1022, RPM_STRING, None, 0],

    # dependencies: provides, requires, obsoletes, conflicts
    "providename": [1047, RPM_STRING_ARRAY, None, 0],
    "provideflags": [1112, RPM_INT32, None, 0],
    "provideversion": [1113, RPM_STRING_ARRAY, None, 0],
    "requirename": [1049, RPM_STRING_ARRAY, None, 0],
    "requireflags": [1048, RPM_INT32, None, 0],
    "requireversion": [1050, RPM_STRING_ARRAY, None, 0],
    "obsoletename": [1090, RPM_STRING_ARRAY, None, 4],
    "obsoleteflags": [1114, RPM_INT32, None, 4],
    "obsoleteversion": [1115, RPM_STRING_ARRAY, None, 4],
    "conflictname": [1054, RPM_STRING_ARRAY, None, 0],
    "conflictflags": [1053, RPM_INT32, None, 0],
    "conflictversion": [1055, RPM_STRING_ARRAY, None, 0],
    # triggers:
    "triggername": [1066, RPM_STRING_ARRAY, None, 4],
    "triggerflags": [1068, RPM_INT32, None, 4],
    "triggerversion": [1067, RPM_STRING_ARRAY, None, 4],
    "triggerscripts": [1065, RPM_STRING_ARRAY, None, 4],
    "triggerscriptprog": [1092, RPM_STRING_ARRAY, None, 4],
    "triggerindex": [1069, RPM_INT32, None, 4],

    # scripts
    "prein": [1023, RPM_STRING, None, 4],
    "preinprog": [1085, RPM_ARGSTRING, None, 4],
    "postin": [1024, RPM_STRING, None, 4],
    "postinprog": [1086, RPM_ARGSTRING, None, 4],
    "preun": [1025, RPM_STRING, None, 4],
    "preunprog": [1087, RPM_ARGSTRING, None, 4],
    "postun": [1026, RPM_STRING, None, 4],
    "postunprog": [1088, RPM_ARGSTRING, None, 4],
    "verifyscript": [1079, RPM_STRING, None, 4],
    "verifyscriptprog": [1091, RPM_ARGSTRING, None, 4],

    # addon information:
    "rpmversion": [1064, RPM_STRING, None, 0],
    "payloadformat": [1124, RPM_STRING, None, 0],    # "cpio"
    "payloadcompressor": [1125, RPM_STRING, None, 0],# "gzip" or "bzip2"
    "i18ntable": [100, RPM_STRING_ARRAY, None, 0],   # list of available langs
    "summary": [1004, RPM_I18NSTRING, None, 0],
    "description": [1005, RPM_I18NSTRING, None, 0],
    "url": [1020, RPM_STRING, None, 0],
    "license": [1014, RPM_STRING, None, 0],
    "sourcerpm": [1044, RPM_STRING, None, 4], # name of src.rpm for binary rpms
    "changelogtime": [1080, RPM_INT32, None, 8],
    "changelogname": [1081, RPM_STRING_ARRAY, None, 0],
    "changelogtext": [1082, RPM_STRING_ARRAY, None, 0],
    "prefixes": [1098, RPM_STRING_ARRAY, None, 4], # relocatable rpm packages
    "optflags": [1122, RPM_STRING, None, 4], # optimization flags for gcc
    "pubkeys": [266, RPM_STRING_ARRAY, None, 4],
    "sourcepkgid": [1146, RPM_BIN, 16, 4], # md5 from srpm (header+payload)
    "immutable": [63, RPM_BIN, 16, 0],
    # less important information:
    "buildtime": [1006, RPM_INT32, 1, 8], # time of rpm build
    "buildhost": [1007, RPM_STRING, None, 0], # hostname where rpm was built
    "cookie": [1094, RPM_STRING, None, 0], # build host and time
    "group": [1016, RPM_GROUP, None, 0], # comps.xml/groupfile is used now
    "size": [1009, RPM_INT32, 1, 0],                # sum of all file sizes
    "distribution": [1010, RPM_STRING, None, 0],
    "vendor": [1011, RPM_STRING, None, 0],
    "packager": [1015, RPM_STRING, None, 0],
    "os": [1021, RPM_STRING, None, 0],              # always "linux"
    "payloadflags": [1126, RPM_STRING, None, 0],    # "9"
    "rhnplatform": [1131, RPM_STRING, None, 4],     # == arch
    "platform": [1132, RPM_STRING, None, 0],

    # rpm source packages:
    "source": [1018, RPM_STRING_ARRAY, None, 2],
    "patch": [1019, RPM_STRING_ARRAY, None, 2],
    "buildarchs": [1089, RPM_STRING_ARRAY, None, 2],
    "excludearch": [1059, RPM_STRING_ARRAY, None, 2],
    "exclusivearch": [1061, RPM_STRING_ARRAY, None, 2],
    "exclusiveos": [1062, RPM_STRING_ARRAY, None, 2], # ["Linux"] or ["linux"]

    # information about files
    "dirindexes": [1116, RPM_INT32, None, 0],
    "dirnames": [1118, RPM_STRING_ARRAY, None, 0],
    "basenames": [1117, RPM_STRING_ARRAY, None, 0],
    "fileusername": [1039, RPM_STRING_ARRAY, None, 0],
    "filegroupname": [1040, RPM_STRING_ARRAY, None, 0],
    "filemodes": [1030, RPM_INT16, None, 0],
    "filemtimes": [1034, RPM_INT32, None, 8],
    "filedevices": [1095, RPM_INT32, None, 0],
    "fileinodes": [1096, RPM_INT32, None, 0],
    "filesizes": [1028, RPM_INT32, None, 0],
    "filemd5s": [1035, RPM_STRING_ARRAY, None, 0],
    "filerdevs": [1033, RPM_INT16, None, 0],
    "filelinktos": [1036, RPM_STRING_ARRAY, None, 0],
    "fileflags": [1037, RPM_INT32, None, 0],
    # less common used data:
    "fileverifyflags": [1045, RPM_INT32, None, 0],
    "filelangs": [1097, RPM_STRING_ARRAY, None, 0],
    "filecolors": [1140, RPM_INT32, None, 0],
    "fileclass": [1141, RPM_INT32, None, 0],
    "filedependsx": [1143, RPM_INT32, None, 0],
    "filedependsn": [1144, RPM_INT32, None, 0],
    "classdict": [1142, RPM_STRING_ARRAY, None, 0],
    "dependsdict": [1145, RPM_INT32, None, 0],
    # data from files marked with "%policy" in specfiles
    "policies": [1150, RPM_STRING_ARRAY, None, 0],
    "filecontexts": [1147, RPM_STRING_ARRAY, None, 0], # selinux filecontexts

    # tags not in Fedora Core development trees anymore:
    "capability": [1105, RPM_INT32, None, 1],
    "xpm": [1013, RPM_BIN, None, 1],
    "gif": [1012, RPM_BIN, None, 1],
    # bogus RHL5.2 data in XFree86-libs, ash, pdksh
    "verifyscript2": [15, RPM_STRING, None, 1],
    "nosource": [1051, RPM_INT32, None, 1],
    "nopatch": [1052, RPM_INT32, None, 1],
    "disturl": [1123, RPM_STRING, None, 1],
    "oldfilenames": [1027, RPM_STRING_ARRAY, None, 1],
    "triggerin": [1100, RPM_STRING, None, 5],
    "triggerun": [1101, RPM_STRING, None, 5],
    "triggerpostun": [1102, RPM_STRING, None, 5],
    "archivesize": [1046, RPM_INT32, 1, 1],
    # tags used in openSuSE:
    "suggestsname": [1156, RPM_STRING_ARRAY, None, 5],
    "suggestsversion": [1157, RPM_STRING_ARRAY, None, 5],
    "suggestsflags": [1158, RPM_INT32, None, 5],
    "enhancesname": [1159, RPM_STRING_ARRAY, None, 5],
    "enhancesversion": [1160, RPM_STRING_ARRAY, None, 5],
    "enhancesflags": [1161, RPM_INT32, None, 5],
    "posttrans": [1152, RPM_STRING, None, 5],
    "posttransprog": [1154, RPM_STRING, None, 5],
}
# Add a reverse mapping for all tags plus the name again.
for _v in rpmtag.keys():
    rpmtag[_v].append(_v)
for _v in rpmtag.values():
    rpmtag[_v[0]] = _v
    if len(_v) != 5:
        raise ValueError, "rpmtag has wrong entries"
del _v

# Additional tags which can be in the rpmdb /var/lib/rpm/Packages.
# Some of these have the data copied over from the signature
# header which is not stored in rpmdb.
rpmdbtag = {
    "origdirindexes": [1119, RPM_INT32, None, 1],
    "origdirnames": [1121, RPM_STRING_ARRAY, None, 1],
    "origbasenames": [1120, RPM_STRING_ARRAY, None, 1],
    "install_size_in_sig": [257, RPM_INT32, 1, 0],
    "install_md5": [261, RPM_BIN, 16, 0],
    "install_gpg": [262, RPM_BIN, None, 0],
    "install_dsaheader": [267, RPM_BIN, 16, 0],
    "install_sha1header": [269, RPM_STRING, None, 0],
    "installtime": [1008, RPM_INT32, 1, 8],
    "filestates": [1029, RPM_CHAR, None, 0],
    # set for relocatable packages
    "instprefixes": [1099, RPM_STRING_ARRAY, None, 0],
    # installcolor is set at /bin/rpm compile time based on arch
    "installcolor": [1127, RPM_INT32, None, 0],
    # unique number per installed rpm package
    "installtid": [1128, RPM_INT32, None, 0],
    "install_badsha1_1": [264, RPM_STRING, None, 1],
    "install_badsha1_2": [265, RPM_STRING, None, 1],
    "immutable1": [61, RPM_BIN, 16, 1]
}
# List of special rpmdb tags, like also visible above.
install_keys = {}
for _v in rpmdbtag.keys():
    install_keys[_v] = 1
    rpmdbtag[_v].append(_v)
for _v in rpmdbtag.values():
    rpmdbtag[_v[0]] = _v
    if len(_v) != 5:
        raise ValueError, "rpmdbtag has wrong entries"
for _v in rpmtag.keys():
    rpmdbtag[_v] = rpmtag[_v]
del _v
# These entries have the same ID as entries already in the list
# to store duplicate tags that get written to the rpmdb for
# relocated packages or ia64 compat packages (i386 on ia64).
rpmdbtag["dirindexes2"] = [1116, RPM_INT32, None, 0, "dirindexes2"]
rpmdbtag["dirnames2"] = [1118, RPM_STRING_ARRAY, None, 0, "dirnames2"]
rpmdbtag["basenames2"] = [1117, RPM_STRING_ARRAY, None, 0, "basenames2"]
install_keys["dirindexes2"] = 1
install_keys["dirnames2"] = 1
install_keys["basenames2"] = 1

importanttags = {"name":1, "epoch":1, "version":1, "release":1, "arch":1,
    "providename":1, "provideflags":1, "provideversion":1,
    "requirename":1, "requireflags":1, "requireversion":1,
    "obsoletename":1, "obsoleteflags":1, "obsoleteversion":1,
    "conflictname":1, "conflictflags":1, "conflictversion":1,
    "triggername":1, "triggerflags":1, "triggerversion":1,
    "triggerscripts":1, "triggerscriptprog":1, "triggerindex":1,
    "prein":1, "preinprog":1, "postin":1, "postinprog":1,
    "preun":1, "preunprog":1, "postun":1, "postunprog":1,
    "verifyscript":1, "verifyscriptprog":1,
    "payloadformat":1, "payloadcompressor":1, "immutable":1,
    "oldfilenames":1, "dirindexes":1, "dirnames":1, "basenames":1,
    "fileusername":1, "filegroupname":1, "filemodes":1,
    "filemtimes":1, "filedevices":1, "fileinodes":1, "filesizes":1,
    "filemd5s":1, "filerdevs":1, "filelinktos":1, "fileflags":1,
    "filecolors":1, "archivesize":1}
for _v in importanttags.keys():
    _value = rpmtag[_v]
    importanttags[_v] = _value
    importanttags[_value[0]] = _value
versiontag = {"version":1}
for _v in versiontag.keys():
    _value = rpmtag[_v]
    versiontag[_v] = _value
    versiontag[_value[0]] = _value
del _value
del _v


# Info within the sig header.
rpmsigtag = {
    # size of gpg/dsaheader sums differ between 64/65(contains "\n")
    "dsaheader": [267, RPM_BIN, None, 0], # only about header
    "gpg": [1005, RPM_BIN, None, 0], # header+payload
    "header_signatures": [62, RPM_BIN, 16, 0],
    "payloadsize": [1007, RPM_INT32, 1, 0],
    "size_in_sig": [1000, RPM_INT32, 1, 0],
    "sha1header": [269, RPM_STRING, None, 0],
    "md5": [1004, RPM_BIN, 16, 0],
    # legacy entries in older rpm packages:
    "pgp": [1002, RPM_BIN, None, 1],
    "badsha1_1": [264, RPM_STRING, None, 1],
    "badsha1_2": [265, RPM_STRING, None, 1] # size added in reversed order
}
# Add a reverse mapping for all tags plus the name again.
for _v in rpmsigtag.keys():
    rpmsigtag[_v].append(_v)
for _v in rpmsigtag.values():
    rpmsigtag[_v[0]] = _v
    if len(_v) != 5:
        raise ValueError, "rpmsigtag has wrong entries"
del _v

# How to sync signature and normal header for rpmdb.
# "pgp" should also have a matching entry.
headermatch = (
    ("dsaheader", "install_dsaheader"),
    ("md5", "install_md5"),
    ("gpg", "install_gpg"),
    ("sha1header", "install_sha1header"),
    ("size_in_sig", "install_size_in_sig"),
    ("badsha1_1", "install_badsha1_1"),
    ("badsha1_2", "install_badsha1_2"),
    ("payloadsize", "archivesize"),
    # need to be generated for the rpmdb:
    #"installtime", "filestates", "instprefixes", "installcolor", "installtid"
)

# Names of all possible kernel packages:
kernelpkgs = ["kernel", "kernel-PAE", "kernel-bigmem", "kernel-enterprise",
    "kernel-hugemem", "kernel-summit", "kernel-smp", "kernel-largesmp",
    "kernel-xen", "kernel-xen0", "kernel-xenU", "kernel-kdump", "kernel-BOOT"]
# Packages which are always installed and not updated:
installonlypkgs = kernelpkgs[:]
installonlypkgs.extend( ["gpg-pubkey",
    "kernel-debug", "kernel-devel", "kernel-debug-devel", "kernel-PAE-debug",
    "kernel-PAE-debug-devel", "kernel-PAE-devel", "kernel-hugemem-devel",
    "kernel-smp-devel", "kernel-largesmp-devel", "kernel-xen-devel",
    "kernel-xen0-devel", "kernel-xenU-devel", "kernel-kdump-devel",
    "kernel-source", "kernel-unsupported", "kernel-modules"] )

# This is RPMCANONCOLOR in /bin/rpm source, values change over time.
def getInstallColor(arch):
    if arch == "ia64": # also "0" and "3" have been here
        return 2
    elif arch in ("ia32e", "amd64", "x86_64", "sparc64", "s390x",
        "powerpc64") or arch.startswith("ppc"):
        return 3
    return 0

# Buildarchtranslate table for multilib stuff
buildarchtranslate = {
    "osfmach3_i686": "i386",
    "osfmach3_i586": "i386",
    "osfmach3_i486": "i386",
    "osfmach3_i386": "i386",
    "athlon": "i386",
    "pentium4": "i386",
    "pentium3": "i386",
    "i686": "i386",
    "i586": "i386",
    "i486": "i386",

    "alphaev5": "alpha",
    "alphaev56": "alpha",
    "alphapca56": "alpha",
    "alphaev6": "alpha",
    "alphaev67": "alpha",

    "sun4c": "sparc",
    "sun4d": "sparc",
    "sun4m": "sparc",
    "sparcv8": "sparc",
    "sparcv9": "sparc",

    "sun4u": "sparc64",

    "osfmach3_ppc": "ppc",
    "powerpc": "ppc",
    "powerppc": "ppc",
    "ppc8260": "ppc",
    "ppc8560": "ppc",
    "ppc32dy4": "ppc",
    "ppciseries": "ppc",
    "ppcpseries": "ppc",

    "ppc64pseries": "ppc64",
    "ppc64iseries": "ppc64",

    "atarist": "m68kmint",
    "atariste": "m68kmint",
    "ataritt": "m68kmint",
    "falcon": "m68kmint",
    "atariclone": "m68kmint",
    "milan": "m68kmint",
    "hades": "m68kmint",

    "amd64": "x86_64",
    "ia32e": "x86_64"
}

# arch => compatible archs, best match first
arch_compats = {
    "athlon": ["i686", "i586", "i486", "i386"],
    "i686": ["i586", "i486", "i386"],
    "i586": ["i486", "i386"],
    "i486": ["i386",],

    "x86_64": ["amd64", "athlon", "i686", "i586", "i486", "i386"],
    "amd64": ["x86_64", "athlon", "i686", "i586", "i486", "i386"],
    "ia32e": ["x86_64", "athlon", "i686", "i586", "i486", "i386"],

    "ia64": ["i686", "i586", "i486", "i386"],

    "alphaev67": ["alphaev6", "alphapca56", "alphaev56", "alphaev5", "alpha",
        "axp"],
    "alphaev6": ["alphapca56", "alphaev56", "alphaev5", "alpha", "axp"],
    "alphapca56": ["alphaev56", "alphaev5", "alpha", "axp"],
    "alphaev56": ["alphaev5", "alpha", "axp"],
    "alphaev5": ["alpha", "axp"],
    "alpha": ["axp",],

    "osfmach3_i686": ["i686", "osfmach3_i586", "i586", "osfmach3_i486", "i486",
        "osfmach3_i386", "i486", "i386"],
    "osfmach3_i586": ["i586", "osfmach3_i486", "i486", "osfmach3_i386", "i486",
        "i386"],
    "osfmach3_i486": ["i486", "osfmach3_i386", "i486", "i386"],
    "osfmach3_i386": ["i486", "i386"],

    "osfmach3_ppc": ["ppc", "rs6000"],
    "powerpc": ["ppc", "rs6000"],
    "powerppc": ["ppc", "rs6000"],
    "ppc8260": ["ppc", "rs6000"],
    "ppc8560": ["ppc", "rs6000"],
    "ppc32dy4": ["ppc", "rs6000"],
    "ppciseries": ["ppc", "rs6000"],
    "ppcpseries": ["ppc", "rs6000"],
    "ppc64": ["ppc", "rs6000"],
    "ppc": ["rs6000",],
    "ppc64pseries": ["ppc64", "ppc", "rs6000"],
    "ppc64iseries": ["ppc64", "ppc", "rs6000"],

    "sun4c": ["sparc",],
    "sun4d": ["sparc",],
    "sun4m": ["sparc",],
    "sun4u": ["sparc64", "sparcv9", "sparc"],
    "sparc64": ["sparcv9", "sparc"],
    "sparcv9": ["sparc",],
    "sparcv8": ["sparc",],

    "hppa2.0": ["hppa1.2", "hppa1.1", "hppa1.0", "parisc"],
    "hppa1.2": ["hppa1.1", "hppa1.0", "parisc"],
    "hppa1.1": ["hppa1.0", "parisc"],
    "hppa1.0": ["parisc",],

    "armv4l": ["armv3l",],

    "atarist": ["m68kmint",],
    "atariste": ["m68kmint",],
    "ataritt": ["m68kmint",],
    "falcon": ["m68kmint",],
    "atariclone": ["m68kmint",],
    "milan": ["m68kmint",],
    "hades": ["m68kmint",],

    "s390x": ["s390",],
}

def setMachineDistance(arch, archlist=None):
    h = {}
    h["noarch"] = 0 # noarch is best
    h[arch] = 1     # second best is same arch
    ind = 2
    if archlist == None:
        archlist = arch_compats.get(arch, [])
    for a in archlist:
        h[a] = ind
        ind += 1
    return h

# check arch names against this list
possible_archs = {
    "noarch":1, "i386":1, "i486":1, "i586":1, "i686":1,
    "athlon":1, "pentium3":1, "pentium4":1, "x86_64":1, "ia32e":1, "ia64":1,
    "alpha":1, "alphaev56":1, "alphaev6":1, "axp":1, "sparc":1, "sparc64":1,
    "s390":1, "s390x":1,
    "ppc":1, "ppc64":1, "ppc64iseries":1, "ppc64pseries":1, "ppcpseries":1,
    "ppciseries":1, "ppcmac":1, "ppc8260":1, "m68k":1,
    "arm":1, "armv4l":1, "mips":1, "mipseb":1, "mipsel":1, "hppa":1, "sh":1,
}

possible_scripts = {
    None: 1,
    "/bin/sh": 1,
    "/sbin/ldconfig": 1,
    "/usr/bin/fc-cache": 1,
    "/usr/bin/scrollkeeper-update": 1,
    "/usr/sbin/build-locale-archive": 1,
    "/usr/sbin/glibc_post_upgrade": 1,
    "/usr/sbin/glibc_post_upgrade.i386": 1,
    "/usr/sbin/glibc_post_upgrade.i686": 1,
    "/usr/sbin/glibc_post_upgrade.ppc": 1,
    "/usr/sbin/glibc_post_upgrade.ppc64": 1,
    "/usr/sbin/glibc_post_upgrade.ia64": 1,
    "/usr/sbin/glibc_post_upgrade.s390": 1,
    "/usr/sbin/glibc_post_upgrade.s390x": 1,
    "/usr/sbin/glibc_post_upgrade.x86_64": 1,
    "/usr/sbin/libgcc_post_upgrade": 1,
    "/usr/bin/rebuild-gcj-db": 1,
    "/usr/libexec/twisted-dropin-cache": 1,
    "/usr/bin/texhash": 1,
}


def writeHeader(pkg, tags, taghash, region, skip_tags, useinstall, rpmgroup):
    """Use the data "tags" and change it into a rpmtag header."""
    (offset, store, stags1, stags2, stags3) = (0, [], [], [], [])
    # Sort by number and also first normal tags, then install_keys tags
    # and at the end the region tag.
    for tagname in tags.iterkeys():
        tagnum = taghash[tagname][0]
        if tagname == region:
            stags3.append((tagnum, tagname))
        elif tagname in skip_tags:
            pass
        elif useinstall and tagname in install_keys:
            stags2.append((tagnum, tagname))
        else:
            stags1.append((tagnum, tagname))
    stags1.sort()
    newregion = None
    genprovs = None
    genindexes = None
    if not stags3:
        noffset = -(len(stags1) * 16) - 16
        tags["immutable1"] = pack("!2IiI", 61, RPM_BIN, noffset, 16)
        stags3.append((61, "immutable1"))
        newregion = 1
        if pkg and pkg["providename"] == None:
            genprovs = 1
            pkg["providename"] = (pkg["name"],)
            pkg["provideflags"] = (RPMSENSE_EQUAL,)
            pkg["provideversion"] = (pkg.getEVR(),)
            stags2.append((1047, "providename"))
            stags2.append((1112, "provideflags"))
            stags2.append((1113, "provideversion"))
        if pkg and pkg["dirindexes"] == None:
            genindexes = 1
            (pkg["basenames"], pkg["dirindexes"], pkg["dirnames"]) \
                = genBasenames(pkg["oldfilenames"])
            stags2.append((1116, "dirindexes"))
            stags2.append((1117, "basenames"))
            stags2.append((1118, "dirnames"))
    stags2.sort()
    stags1.extend(stags3)
    stags1.extend(stags2)
    indexdata = []
    for (tagnum, tagname) in stags1:
        value = tags[tagname]
        ttype = taghash[tagnum][1]
        count = len(value)
        pad = 0
        if ttype == RPM_ARGSTRING:
            if isinstance(value, basestring):
                ttype = RPM_STRING
            else:
                ttype = RPM_STRING_ARRAY
        elif ttype == RPM_GROUP:
            ttype = RPM_I18NSTRING
            if rpmgroup:
                ttype = rpmgroup
        if ttype == RPM_INT32:
            if taghash[tagnum][3] & 8:
                data = pack("!%di" % count, *value)
            else:
                data = pack("!%dI" % count, *value)
            pad = (4 - (offset % 4)) % 4
        elif ttype == RPM_STRING:
            count = 1
            data = "%s\x00" % value
        elif ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
            # python-only
            data = "".join( [ "%s\x00" % value[i] for i in xrange(count) ] )
            # python-only-end
            # pyrex-code
            #k = []
            #for i in xrange(count):
            #    k.append("%s\x00" % value[i])
            #data = "".join(k)
            # pyrex-code-end
        elif ttype == RPM_BIN:
            data = value
        elif ttype == RPM_INT16:
            data = pack("!%dH" % count, *value)
            pad = (2 - (offset % 2)) % 2
        elif ttype == RPM_CHAR or ttype == RPM_INT8:
            data = pack("!%dB" % count, *value)
        elif ttype == RPM_INT64:
            data = pack("!%dQ" % count, *value)
            pad = (8 - (offset % 8)) % 8
        if pad:
            offset += pad
            store.append("\x00" * pad)
        store.append(data)
        index = pack("!4I", tagnum, ttype, offset, count)
        offset += len(data)
        if tagname == region: # data for region tag is first
            indexdata.insert(0, index)
        else:
            indexdata.append(index)
    if newregion:
        del tags["immutable1"]
    if genprovs:
        del pkg["providename"]
        del pkg["provideflags"]
        del pkg["provideversion"]
    if genindexes:
        del pkg["basenames"]
        del pkg["dirindexes"]
        del pkg["dirnames"]
    indexNo = len(stags1)
    store = "".join(store)
    indexdata = "".join(indexdata)
    return (indexNo, len(store), indexdata, store)


# locale independend string methods
def _xisalpha(c):
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z")
def _xisdigit(c):
    return c >= "0" and c <= "9"
def _xisalnum(c):
    return ((c >= "a" and c <= "z") or (c >= "A" and c <= "Z")
         or (c >= "0" and c <= "9"))

# compare two strings, rpm/lib/rpmver.c:rpmvercmp()
def stringCompare(str1, str2):
    """ Loop through each version segment (alpha or numeric) of
        str1 and str2 and compare them. """
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
            # ignore leading "0" for numbers (1.01 == 1.000001)
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


# EVR compare: uses stringCompare to compare epoch/version/release
def labelCompare(e1, e2):
    # remove comparison of the release string if one of them is missing
    r = stringCompare(e1[0], e2[0])
    if r == 0:
        r = stringCompare(e1[1], e2[1])
        if r == 0 and e1[2] != "" and e2[2] != "":
            r = stringCompare(e1[2], e2[2])
    return r

def pkgCompare(one, two):
    return labelCompare((one.getEpoch(), one["version"], one["release"]),
                        (two.getEpoch(), two["version"], two["release"]))

def rangeCompare(flag1, evr1, flag2, evr2):
    """Check whether (RPMSENSE_* flag, (E, V, R) evr) pairs (flag1, evr1)
    and (flag2, evr2) intersect.
    Return 1 if they do, 0 otherwise.  Assumes at least one of RPMSENSE_EQUAL,
    RPMSENSE_LESS or RPMSENSE_GREATER is each of flag1 and flag2."""
    sense = labelCompare(evr1, evr2)
    if sense < 0:
        if (flag1 & RPMSENSE_GREATER) or (flag2 & RPMSENSE_LESS):
            return 1
    elif sense > 0:
        if (flag1 & RPMSENSE_LESS) or (flag2 & RPMSENSE_GREATER):
            return 1
    else: # elif sense == 0:
        if ((flag1 & RPMSENSE_EQUAL) and (flag2 & RPMSENSE_EQUAL)) or \
           ((flag1 & RPMSENSE_LESS) and (flag2 & RPMSENSE_LESS)) or \
           ((flag1 & RPMSENSE_GREATER) and (flag2 & RPMSENSE_GREATER)):
            return 1
    return 0

def isCommentOnly(script):
    """Return 1 is script contains only empty lines or lines
    starting with "#". """
    for line in script.split("\n"):
        line2 = line.strip()
        if line2 and line2[0] != "#":
            return 0
    return 1

def makeDirs(dirname):
    if not os.path.isdir(dirname):
        os.makedirs(dirname)

def setPerms(filename, uid, gid, mode, mtime):
    if uid != None:
        os.lchown(filename, uid, gid)
    if mode != None:
        os.chmod(filename, mode & 07777)
    if mtime != None:
        os.utime(filename, (mtime, mtime))

def Uri2Filename(filename):
    """Try changing a file:// url into a local filename, pass
    everything else through."""
    if filename[:6] == "file:/":
        filename = filename[5:]
        if filename[1] == "/":
            idx = filename.index("/", 2)
            filename = filename[idx:]
    return filename

def isUrl(filename):
    for url in ("http://", "ftp://", "file://"):
        if filename.startswith(url):
            return 1
    return 0


def parseFile(filename, requested):
    rethash = {}
    for l in open(filename, "r").readlines():
        tmp = l.split(":")
        if tmp[0] in requested:
            rethash[tmp[0]] = int(tmp[2])
    return rethash

class UGid:
    """Store a list of user- and groupnames and transform them in uids/gids."""

    def __init__(self, names=None):
        self.ugid = {}
        if names:
            for name in names:
                self.ugid.setdefault(name, name)

    def transform(self, buildroot):
        pass

class Uid(UGid):
    def transform(self, buildroot):
        # "uid=0" if no /etc/passwd exists at all.
        if not os.path.exists(buildroot + "/etc/passwd"):
            for uid in self.ugid.iterkeys():
                self.ugid[uid] = 0
                if uid != "root":
                    print "Warning: user %s not found, using uid 0." % uid
            return
        # Parse /etc/passwd if glibc is not yet installed.
        if buildroot or not os.path.exists(buildroot + "/sbin/ldconfig"):
            uidhash = parseFile(buildroot + "/etc/passwd", self.ugid)
            for uid in self.ugid.iterkeys():
                if uid in uidhash:
                    self.ugid[uid] = uidhash[uid]
                else:
                    print "Warning: user %s not found, using uid 0." % uid
                    self.ugid[uid] = 0
            return
        # Normal lookup of users via glibc.
        for uid in self.ugid.iterkeys():
            if uid == "root":
                self.ugid[uid] = 0
            else:
                try:
                    import pwd
                    self.ugid[uid] = pwd.getpwnam(uid)[2]
                except KeyError:
                    print "Warning: user %s not found, using uid 0." % uid
                    self.ugid[uid] = 0

class Gid(UGid):
    def transform(self, buildroot):
        # "gid=0" if no /etc/group exists at all.
        if not os.path.exists(buildroot + "/etc/group"):
            for gid in self.ugid.iterkeys():
                self.ugid[gid] = 0
                if gid != "root":
                    print "Warning: group %s not found, using gid 0." % gid
            return
        # Parse /etc/group if glibc is not yet installed.
        if buildroot or not os.path.exists(buildroot + "/sbin/ldconfig"):
            gidhash = parseFile(buildroot + "/etc/group", self.ugid)
            for gid in self.ugid.iterkeys():
                if gid in gidhash:
                    self.ugid[gid] = gidhash[gid]
                else:
                    print "Warning: group %s not found, using gid 0." % gid
                    self.ugid[gid] = 0
            return
        # Normal lookup of users via glibc.
        for gid in self.ugid.iterkeys():
            if gid == "root":
                self.ugid[gid] = 0
            else:
                try:
                    import grp
                    self.ugid[gid] = grp.getgrnam(gid)[2]
                except KeyError:
                    print "Warning: group %s not found, using gid 0." % gid
                    self.ugid[gid] = 0


class CPIO:
    """Read a cpio archive."""

    def __init__(self, filename, fd, issrc, size=None):
        self.filename = filename
        self.fd = fd
        self.issrc = issrc
        self.size = size

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def __readDataPad(self, size, pad=0):
        data = doRead(self.fd, size)
        pad = (4 - ((size + pad) % 4)) % 4
        doRead(self.fd, pad)
        if self.size != None:
            self.size -= size + pad
        return data

    def readCpio(self, func, filenamehash, devinode, filenames, extract, db):
        while 1:
            # (magic, inode, mode, uid, gid, nlink, mtime, filesize,
            # devMajor, devMinor, rdevMajor, rdevMinor, namesize, checksum)
            data = doRead(self.fd, 110)
            if self.size != None:
                self.size -= 110
            # CPIO ASCII hex, expanded device numbers (070702 with CRC)
            if data[0:6] not in ("070701", "070702"):
                self.printErr("bad magic reading CPIO header")
                return None
            namesize = int(data[94:102], 16)
            filename = self.__readDataPad(namesize, 110).rstrip("\x00")
            if filename == "TRAILER!!!":
                if self.size != None and self.size != 0:
                    self.printErr("failed cpiosize check")
                    return None
                return 1
            if filename[:2] == "./":
                filename = filename[1:]
            if not self.issrc and filename[:1] != "/":
                filename = "%s%s" % ("/", filename)
            if filename[-1:] == "/" and filename != "/":
                filename = filename[:-1]
            if extract:
                func(filename, int(data[54:62], 16), self.__readDataPad,
                    filenamehash, devinode, filenames, db)
            else:
                # (name, inode, mode, nlink, mtime, filesize, dev, rdev)
                filedata = (filename, int(data[6:14], 16),
                    long(data[14:22], 16), int(data[38:46], 16),
                    long(data[46:54], 16), int(data[54:62], 16),
                    int(data[62:70], 16) * 256 + int(data[70:78], 16),
                    int(data[78:86], 16) * 256 + int(data[86:94], 16))
                func(filedata, self.__readDataPad, filenamehash, devinode,
                    filenames, db)
        return None


class HdrIndex:
    def __init__(self):
        self.hash = {}
        self.__len__ = self.hash.__len__
        self.__getitem__ = self.hash.get
        self.get = self.hash.get
        self.__delitem__ = self.hash.__delitem__
        self.__setitem__ = self.hash.__setitem__
        self.__contains__ = self.hash.__contains__
        self.has_key = self.hash.has_key
        #self.__repr__ = self.hash.__repr__

    def getOne(self, key):
        value = self[key]
        if value != None:
            return value[0]
        return value

class ReadRpm: # pylint: disable-msg=R0904
    """Read (Linux) rpm packages."""

    def __init__(self, filename, verify=None, fd=None, strict=None,
                 nodigest=None):
        self.filename = filename
        self.verify = verify # enable/disable more data checking
        self.fd = fd # filedescriptor
        self.strict = strict
        self.nodigest = nodigest # check md5sum/sha1 digests
        self.issrc = 0
        self.buildroot = "" # do we have a chroot-like start?
        self.owner = None # are uid/gid set?
        self.uid = None
        self.gid = None
        self.relocated = None
        self.rpmgroup = None
        # Further data posibly created later on:
        #self.leaddata = first 96 bytes of lead data
        #self.sigdata = binary blob of signature header
        #self.sig = signature header parsed as HdrIndex()
        #self.sigdatasize = size of signature header
        #self.hdrdata = binary blob of header data
        #self.hdr = header parsed as HdrIndex()
        #self.hdrdatasize = size of header

    def __repr__(self):
        return self.getFilename()

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def raiseErr(self, err):
        raise ValueError, "%s: %s" % (self.filename, err)

    def __openFd(self, offset=None, headerend=None):
        if not self.fd:
            if isUrl(self.filename):
                import urlgrabber
                hrange = None
                if offset or headerend:
                    hrange = (offset, headerend)
                try:
                    self.fd = urlgrabber.urlopen(self.filename, range=hrange,
                        timeout=float(urloptions["timeout"]),
                        retry=int(urloptions["retries"]),
                        keepalive=int(urloptions["keepalive"]),
                        proxies=urloptions["proxies"],
                        http_headers=urloptions["http_headers"])
                except urlgrabber.grabber.URLGrabError: #, e:
                    self.printErr("could not open file")
                    #print str(e)
                    return 1
            else:
                try:
                    self.fd = open(self.filename, "rb")
                except IOError:
                    self.printErr("could not open file")
                    return 1
                if offset:
                    self.fd.seek(offset, 1)
        return None

    def closeFd(self):
        if self.fd != None:
            self.fd.close()
        self.fd = None

    def __relocatedFile(self, filename):
        for (old, new) in self.relocated:
            if not filename.startswith(old):
                continue
            if filename == old:
                filename = new
            elif filename[len(old)] == "/":
                filename = new + filename[len(old):]
        return filename

    def __verifyLead(self, leaddata):
        (_, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4s2B2H66s2H16x", leaddata)
        failed = None
        if (major not in (3, 4) or minor != 0 or
            rpmtype not in (0, 1) or sigtype != 5 or
            osnum not in (1, 21, 255, 256)):
            failed = 1
        name = name.rstrip("\x00")
        if self.strict:
            if not os.path.basename(self.filename).startswith(name):
                failed = 1
        if failed:
            print major, minor, rpmtype, arch, name, osnum, sigtype
            self.printErr("wrong data in rpm lead")

    def __readIndex(self, pad, rpmdb=None):
        if rpmdb:
            data = self.fd.read(8)
            (indexNo, storeSize) = unpack("!2I", data)
            magic = "\x8e\xad\xe8\x01\x00\x00\x00\x00"
            data = magic + data
            if indexNo < 1:
                self.raiseErr("bad index magic")
        else:
            data = self.fd.read(16)
            (magic, indexNo, storeSize) = unpack("!8s2I", data)
            if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
                self.raiseErr("bad index magic")
        fmt = self.fd.read(16 * indexNo)
        fmt2 = self.fd.read(storeSize)
        padfmt = ""
        padlen = 0
        if pad != 1:
            padlen = (pad - (storeSize % pad)) % pad
            padfmt = self.fd.read(padlen)
        if (len(fmt) != 16 * indexNo or len(fmt2) != storeSize or
            padlen != len(padfmt)):
            self.raiseErr("did not read Index correctly")
        return (indexNo, storeSize, data, fmt, fmt2,
            16 + len(fmt) + storeSize + padlen)

# pyrex-code
#    def __parseIndex(self, indexNo, fmt, fmt2, dorpmtag):
#        cdef int i, j, indexNo2, tag, ttype, offset, count, datalen
#        cdef char * fmtsp, * fmt2sp
#        cdef int * fmtp, * fmt2p
#        indexNo2 = indexNo
#        fmtsp = fmt
#        fmt2sp = fmt2
#        fmtp = <int *>fmtsp
#        hdr = HdrIndex()
#        if not dorpmtag:
#            return hdr
#        for i from 0 <= i < indexNo2:
#            j = i * 4
#            tag = ntohl(fmtp[j])
#            myrpmtag = dorpmtag.get(tag)
#            if not myrpmtag:
#                continue
#            nametag = myrpmtag[4]
#            ttype = ntohl(fmtp[j + 1])
#            offset = ntohl(fmtp[j + 2])
#            count = ntohl(fmtp[j + 3])
#            if ttype == cRPM_STRING:
#                data = PyString_FromStringAndSize(fmt2sp + offset,
#                    strlen(fmt2sp + offset))
#                if nametag == "group":
#                    self.rpmgroup = ttype
#            elif ttype == cRPM_INT32:
#                # distinguish between signed and unsigned ints
#                if myrpmtag[3] & 8:
#                    #fmt2p = <int *>(fmt2sp + offset)
#                    #data = []
#                    #for j from 0 <= j < count:
#                    #    data.append(ntohl(fmt2p[count]))
#                    data = unpack("!%di" % count,
#                        fmt2[offset:offset + count * 4])
#                else:
#                    #fmt2p = <int *>(fmt2sp + offset)
#                    #data = []
#                    #for j from 0 <= j < count:
#                    #    data.append(ntohl(fmt2p[count]))
#                    data = unpack("!%dI" % count,
#                        fmt2[offset:offset + count * 4])
#            elif ttype == cRPM_STRING_ARRAY or ttype == cRPM_I18NSTRING:
#                data = []
#                for j from 0 <= j < count:
#                    datalen = strlen(fmt2sp + offset)
#                    data.append(PyString_FromStringAndSize(fmt2sp + offset,
#                       datalen))
#                    offset = offset + datalen + 1
#            elif ttype == cRPM_BIN:
#                data = fmt2[offset:offset + count]
#            elif ttype == cRPM_INT16:
#                data = unpack("!%dH" % count, fmt2[offset:offset + count * 2])
#            elif ttype == cRPM_CHAR or ttype == cRPM_INT8:
#                data = unpack("!%dB" % count, fmt2[offset:offset + count])
#            elif ttype == cRPM_INT64:
#                data = unpack("!%dQ" % count, fmt2[offset:offset + count * 8])
# pyrex-code-end
# python-only
    def __parseIndex(self, indexNo, fmt, fmt2, dorpmtag):
        hdr = HdrIndex()
        if not dorpmtag:
            return hdr
        for i in xrange(0, indexNo * 16, 16):
            (tag, ttype, offset, count) = unpack("!4I", fmt[i:i + 16])
            myrpmtag = dorpmtag.get(tag)
            if not myrpmtag:
                #print "unknown tag:", (tag,ttype,offset,count), self.filename
                continue
            nametag = myrpmtag[4]
            if ttype == RPM_STRING:
                data = fmt2[offset:fmt2.index("\x00", offset)]
                if nametag == "group":
                    self.rpmgroup = ttype
            elif ttype == RPM_INT32:
                # distinguish between signed and unsigned ints
                if myrpmtag[3] & 8:
                    data = unpack("!%di" % count,
                        fmt2[offset:offset + count * 4])
                else:
                    data = unpack("!%dI" % count,
                        fmt2[offset:offset + count * 4])
            elif ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
                data = []
                for _ in xrange(count):
                    end = fmt2.index("\x00", offset)
                    data.append(fmt2[offset:end])
                    offset = end + 1
            elif ttype == RPM_BIN:
                data = fmt2[offset:offset + count]
            elif ttype == RPM_INT16:
                data = unpack("!%dH" % count, fmt2[offset:offset + count * 2])
            elif ttype == RPM_CHAR or ttype == RPM_INT8:
                data = unpack("!%dB" % count, fmt2[offset:offset + count])
            elif ttype == RPM_INT64:
                data = unpack("!%dQ" % count, fmt2[offset:offset + count * 8])
# python-only-end
            else:
                self.raiseErr("unknown tag header")
                data = None
            # Ignore duplicate entries as long as they are identical.
            # They happen for packages signed with several keys or for
            # relocated packages in the rpmdb.
            if hdr.has_key(nametag):
                if nametag == "dirindexes":
                    nametag = "dirindexes2"
                elif nametag == "dirnames":
                    nametag = "dirnames2"
                elif nametag == "basenames":
                    nametag = "basenames2"
                else:
                    if self.strict or hdr[nametag] != data:
                        self.printErr("duplicate tag %d" % tag)
                    continue
            hdr[nametag] = data
        return hdr

    def setHdr(self):
        self.__getitem__ = self.hdr.__getitem__
        self.__delitem__ = self.hdr.__delitem__
        self.__setitem__ = self.hdr.__setitem__
        self.__contains__ = self.hdr.__contains__
        self.has_key = self.hdr.has_key
        #self.__repr__ = self.hdr.__repr__

    def readHeader(self, sigtags, hdrtags, keepdata=None, rpmdb=None,
        headerend=None):
        if rpmdb == None:
            if self.__openFd(None, headerend):
                return 1
            leaddata = self.fd.read(96)
            if leaddata[:4] != "\xed\xab\xee\xdb" or len(leaddata) != 96:
                #from binascii import b2a_hex
                self.printErr("no rpm magic found")
                #print "wrong lead: %s" % b2a_hex(leaddata[:4])
                return 1
            self.issrc = (leaddata[7] == "\x01")
            if self.verify:
                self.__verifyLead(leaddata)
            sigdata = self.__readIndex(8)
            self.sigdatasize = sigdata[5]
        hdrdata = self.__readIndex(1, rpmdb)
        self.hdrdatasize = hdrdata[5]
        if keepdata:
            if rpmdb == None:
                self.leaddata = leaddata
                self.sigdata = sigdata
            self.hdrdata = hdrdata

        if not sigtags and not hdrtags:
            return None

        if self.verify or sigtags:
            (sigindexNo, _, _, sigfmt, sigfmt2, _) = sigdata
            self.sig = self.__parseIndex(sigindexNo, sigfmt, sigfmt2, sigtags)
        (hdrindexNo, _, _, hdrfmt, hdrfmt2, _) = hdrdata
        self.hdr = self.__parseIndex(hdrindexNo, hdrfmt, hdrfmt2, hdrtags)
        self.setHdr()
        if self.verify and self.__doVerify():
            return 1
        # hack: Save a tiny bit of memory by compressing the fileusername
        # and filegroupname strings to be only stored once. Evil and maybe
        # this does not make sense at all. At least this belongs into an
        # extra function and not into the default path.
        #for i in ("fileusername", "filegroupname"):
        #    if not self[i]:
        #        continue
        #    y = []
        #    z = {}
        #    for j in self[i]:
        #        z.setdefault(j, j)
        #        y.append(z[j])
        #    self[i] = y
        return None

    def setOwner(self, owner):
        self.owner = owner
        if owner:
            self.uid = Uid(self["fileusername"])
            self.uid.transform(self.buildroot)
            self.gid = Gid(self["filegroupname"])
            self.gid.transform(self.buildroot)

    def verifyCpio(self, filedata, read_data, filenamehash, devinode, _, dummy):
        # pylint: disable-msg=W0612,W0613
        # Overall result is that apart from the filename information
        # we should not depend on any data from the cpio header.
        # Data is also stored in rpm tags and the cpio header has
        # been broken in enough details to ignore it.
        (filename, inode, mode, nlink, mtime, filesize, dev, rdev) = filedata
        data = ""
        if filesize:
            data = read_data(filesize)
        fileinfo = filenamehash.get(filename)
        if fileinfo == None:
            self.printErr("cpio file %s not in rpm header" % filename)
            return
        (fn, flag, mode2, mtime2, dev2, inode2, user, group, rdev2,
            linkto, md5sum, i) = fileinfo
        del filenamehash[filename]
        # printconf-0.3.61-4.1.i386.rpm is an example where paths are
        # stored like: /usr/share/printconf/tests/../mf.magic
        # This makes the normapth() check fail and also gives trouble
        # for the algorithm finding hardlinks as the files are also
        # included with their normal path. So same dev/inode pairs
        # can be hardlinks or they can be wrongly packaged rpms.
        if self.strict and filename != os.path.normpath(filename):
            self.printErr("failed: normpath(%s)" % filename)
        isreg = S_ISREG(mode)
        if self.strict:
            if isreg and inode != inode2:
                self.printErr("wrong fileinode for %s" % filename)
            if mode != mode2:
                self.printErr("wrong filemode for %s" % filename)
        # uid/gid are ignored from cpio
        # device/inode are only set correctly for regular files
        di = None
        if isreg:
            di = devinode.get((dev, inode, md5sum))
        if di == None:
            ishardlink = 0
            # nlink is only set correctly for hardlinks, so disable this check:
            #if nlink != 1:
            #    self.printErr("wrong number of hardlinks")
        else:
            ishardlink = 1
            di.remove(i)
            if not di:
                if not data:
                    self.printErr("must be 0-size hardlink: %s" % filename)
                del devinode[(dev, inode, md5sum)]
            else:
                if data:
                    self.printErr("non-zero hardlink file, " + \
                        "but not the last: %s" % filename)
            # Search for "normpath" to read why hardlinks might not
            # be hardlinks, but only double stored files with "/../"
            # stored in their filename. Broken packages out there...
            ##XXX; Move this test to the setup time.
            ##if self.strict and nlink != len(di):
            ##    self.printErr("wrong number of hardlinks %s, %d / %d" % \
            ##        (filename, nlink, len(di)))
            # This case also happens e.g. in RHL6.2: procps-2.0.6-5.i386.rpm
            # where nlinks is greater than the number of actual hardlinks.
            #elif nlink > len(di):
            #   self.printErr("wrong number of hardlinks %s, %d / %d" % \
            #       (filename, nlink, len(di)))
        if self.strict and mtime != mtime2:
            self.printErr("wrong filemtimes for %s" % filename)
        if isreg and filesize != self["filesizes"][i] and ishardlink == 0:
            self.printErr("wrong filesize for %s" % filename)
        if isreg and dev != dev2:
            self.printErr("wrong filedevice for %s" % filename)
        if self.strict and rdev != rdev2:
            self.printErr("wrong filerdevs for %s" % filename)
        if S_ISLNK(mode):
            if data.rstrip("\x00") != linkto:
                self.printErr("wrong filelinkto for %s" % filename)
        elif isreg:
            if not (filesize == 0 and ishardlink == 1):
                ctx = md5.new()
                ctx.update(data)
                if ctx.hexdigest() != md5sum:
                    if self["filesizes"][i] != 0 and self["arch"] != "sparc":
                        self.printErr("wrong filemd5s for %s: %s, %s" \
                            % (filename, ctx.hexdigest(), md5sum))

    def extractCpio(self, filename, datasize, read_data, filenamehash,
            devinode, filenames, db):
        # pylint: disable-msg=W0612
        data = ""
        if datasize:
            data = read_data(datasize)
        fileinfo = filenamehash.get(filename)
        if fileinfo == None:
            self.printErr("cpio file %s not in rpm header" % filename)
            return
        (fn, flag, mode, mtime, dev, inode, user, group, rdev,
            linkto, md5sum, i) = fileinfo
        del filenamehash[filename]
        uid = gid = None
        if self.owner:
            uid = self.uid.ugid[user]
            gid = self.gid.ugid[group]
        if self.relocated:
            filename = self.__relocatedFile(filename)
        filename = "%s%s" % (self.buildroot, filename)
        dirname = pathdirname(filename)
        makeDirs(dirname)
        doextract = 1
        if db:
            try:
                (mode2, inode2, dev2, nlink2, uid2, gid2, filesize2,
                    atime2, mtime2, ctime2) = os.stat(filename)
                # XXX consider reg / non-reg files
                if (flag & RPMFILE_CONFIG) and S_ISREG(mode):
                    changedfile = 1
                    # XXX go through db if we find a same file
                    if changedfile:
                        if flag & RPMFILE_NOREPLACE:
                            filename += ".rpmnew"
                        else:
                            pass # ln file -> file.rpmorig
                else:
                    pass # XXX higher arch and our package not noarch
                    #doextract = 0
            except OSError:
                pass
        if not doextract:
            return
        if S_ISREG(mode):
            di = devinode.get((dev, inode, md5sum))
            if di == None or data:
                (fd, tmpfilename) = mkstemp_file(dirname)
                os.write(fd, data)
                os.close(fd)
                setPerms(tmpfilename, uid, gid, mode, mtime)
                os.rename(tmpfilename, filename)
                if di:
                    di.remove(i)
                    for j in di:
                        fn2 = filenames[j]
                        if self.relocated:
                            fn2 = self.__relocatedFile(fn2)
                        fn2 = "%s%s" % (self.buildroot, fn2)
                        dirname = pathdirname(fn2)
                        makeDirs(dirname)
                        tmpfilename = mkstemp_link(dirname, tmpprefix, filename)
                        if tmpfilename == None:
                            (fd, tmpfilename) = mkstemp_file(dirname)
                            os.write(fd, data)
                            os.close(fd)
                            setPerms(tmpfilename, uid, gid, mode, mtime)
                        os.rename(tmpfilename, fn2)
                    del devinode[(dev, inode, md5sum)]
        elif S_ISDIR(mode):
            makeDirs(filename)
            setPerms(filename, uid, gid, mode, None)
        elif S_ISLNK(mode):
            #if (os.path.islink(filename) and
            #    os.readlink(filename) == linkto):
            #    return
            tmpfile = mkstemp_symlink(dirname, tmpprefix, linkto)
            setPerms(tmpfile, uid, gid, None, None)
            os.rename(tmpfile, filename)
        elif S_ISFIFO(mode):
            tmpfile = mkstemp_mkfifo(dirname, tmpprefix)
            setPerms(tmpfile, uid, gid, mode, mtime)
            os.rename(tmpfile, filename)
        elif S_ISCHR(mode) or S_ISBLK(mode):
            if self.owner:
                tmpfile = mkstemp_mknod(dirname, tmpprefix, mode, rdev)
                setPerms(tmpfile, uid, gid, mode, mtime)
                os.rename(tmpfile, filename)
            # if not self.owner: we could give a warning here
        elif S_ISSOCK(mode):
            raise ValueError, "UNIX domain sockets can't be packaged."
        else:
            raise ValueError, "%s: not a valid filetype" % (oct(mode))

    def getFilenames(self):
        oldfilenames = self["oldfilenames"]
        if oldfilenames != None:
            return oldfilenames
        basenames = self["basenames"]
        if basenames == None:
            return []
        dirnames = self["dirnames"]
        dirindexes = self["dirindexes"]
        # python-only
        return [ "%s%s" % (dirnames[dirindexes[i]], basenames[i])
                 for i in xrange(len(basenames)) ]
        # python-only-end
        # pyrex-code
        #ret = []
        #for i in xrange(len(basenames)):
        #    ret.append("%s%s" % (dirnames[dirindexes[i]], basenames[i]))
        #return ret
        # pyrex-code-end

    def readPayload(self, func, filenames=None, extract=None, db=None):
        self.__openFd(96 + self.sigdatasize + self.hdrdatasize)
        # pylint: disable-msg=W0612
        devinode = {}     # this will contain possibly hardlinked files
        filenamehash = {} # full filename of all files
        if filenames == None:
            filenames = self.getFilenames()
        if filenames:
            fileinfo = zip(filenames, self["fileflags"], self["filemodes"],
                self["filemtimes"], self["filedevices"], self["fileinodes"],
                self["fileusername"], self["filegroupname"], self["filerdevs"],
                self["filelinktos"], self["filemd5s"],
                xrange(len(self["fileinodes"])))
            for (fn, flag, mode, mtime, dev, inode, user, group,
                rdev, linkto, md5sum, i) in fileinfo:
                if flag & (RPMFILE_GHOST | RPMFILE_EXCLUDE):
                    continue
                filenamehash[fn] = fileinfo[i]
                if S_ISREG(mode):
                    devinode.setdefault((dev, inode, md5sum), []).append(i)
        for di in devinode.keys():
            if len(devinode[di]) <= 1:
                del devinode[di]
        # sanity check hardlinks
        if self.verify:
            for hardlinks in devinode.itervalues():
                j = hardlinks[0]
                mode = self["filemodes"][j]
                mtime = self["filemtimes"][j]
                size = self["filesizes"][j]
                for j in hardlinks[1:]:
                    # dev/inode/md5sum are already guaranteed to be the same
                    if self["filemodes"][j] != mode:
                        self.printErr("modes differ for hardlink")
                    if self["filemtimes"][j] != mtime:
                        self.printErr("mtimes differ for hardlink")
                    if self["filesizes"][j] != size:
                        self.printErr("sizes differ for hardlink")
        cpiosize = self.sig.getOne("payloadsize")
        archivesize = self.hdr.getOne("archivesize")
        if archivesize != None:
            if cpiosize == None:
                cpiosize = archivesize
            elif cpiosize != archivesize:
                self.printErr("wrong archive size")
        size_in_sig = self.sig.getOne("size_in_sig")
        if size_in_sig != None:
            size_in_sig -= self.hdrdatasize
        if self["payloadcompressor"] in [None, "gzip"]:
            if size_in_sig != None and size_in_sig >= 8:
                size_in_sig -= 8
            fd = PyGZIP(self.filename, self.fd, cpiosize, size_in_sig)
            #fd = gzip.GzipFile(fileobj=self.fd)
        elif self["payloadcompressor"] == "bzip2":
            import bz2
            if size_in_sig != None:
                payload = self.fd.read(size_in_sig)
            else:
                payload = self.fd.read()
            fd = StringIO(bz2.decompress(payload))
        else:
            self.printErr("unknown payload compression")
            return
        if self["payloadformat"] not in [None, "cpio"]:
            self.printErr("unknown payload format")
            return
        c = CPIO(self.filename, fd, self.issrc, cpiosize)
        if c.readCpio(func, filenamehash, devinode, filenames,
            extract, db) == None:
            pass # error output is already done
        else:
            for filename in filenamehash.iterkeys():
                self.printErr("file not in cpio: %s" % filename)
            if extract and devinode.keys():
                self.printErr("hardlinked files remain from cpio")
        # python-only
        del c, fd
        # python-only-end
        self.closeFd()

    def getSpecfile(self, filenames=None):
        fileflags = self["fileflags"]
        for i in xrange(len(fileflags)):
            if fileflags[i] & RPMFILE_SPECFILE:
                return i
        if filenames == None:
            filenames = self.getFilenames()
        for i in xrange(len(filenames)):
            if filenames[i].endswith(".spec"):
                return i
        return None

    def getEpoch(self, default="0"):
        e = self["epoch"]
        if e == None:
            return default
        return str(e[0])

    def getArch(self):
        if self.issrc:
            return "src"
        return self["arch"]

    def getNVR(self):
        return "%s-%s-%s" % (self["name"], self["version"], self["release"])

    def getNVRA(self):
        return "%s-%s-%s.%s" % (self["name"], self["version"], self["release"],
            self.getArch())

    def getNA(self):
        return "%s.%s" % (self["name"], self["arch"])

    def getEVR(self):
        """Return [%epoch:]%version-%release."""
        e = self["epoch"]
        if e != None:
            return "%d:%s-%s" % (e[0], self["version"], self["release"])
        return "%s-%s" % (self["version"], self["release"])

    def getNEVRA(self):
        """Return %name-[%epoch:]%version-%release.%arch."""
        return "%s-%s.%s" % (self["name"], self.getEVR(), self.getArch())

    def getNEVR0(self):
        """Return %name-[%epoch:]%version-%release."""
        return "%s-%s:%s-%s" % (self["name"], self.getEpoch(),
            self["version"], self["release"])

    def getNEVRA0(self):
        """Return %name-[%epoch:]%version-%release.%arch."""
        return "%s-%s:%s-%s.%s" % (self["name"], self.getEpoch(),
            self["version"], self["release"], self.getArch())

    def getFilename(self):
        return "%s-%s-%s.%s.rpm" % (self["name"], self["version"],
            self["release"], self.getArch())

    def getFilename2(self):
        return "%s-%s-%s.%s" % (self["name"], self["version"],
            self["release"], self.getArch())

    def __verifyDeps(self, name, flags, version):
        n = self[name]
        f = self[flags]
        v = self[version]
        if n == None:
            if f != None or v != None:
                self.printErr("wrong dep data")
        else:
            if (f == None and v != None) or (f != None and v == None):
                self.printErr("wrong dep data")
            if f == None:
                f = [None] * len(n)
            if v == None:
                v = [None] * len(n)
            if len(n) != len(f) or len(f) != len(v):
                self.printErr("wrong length of deps for %s" % name)

    def _getDeps(self, name, flags, version):
        n = self[name]
        if n == None:
            return []
        f = self[flags]
        v = self[version]
        if f == None:
            f = [None] * len(n)
        if v == None:
            v = [None] * len(n)
        return zip(n, f, v)

    def getProvides(self):
        provs = self._getDeps("providename", "provideflags", "provideversion")
        if not self.issrc:
            provs.append( (self["name"], RPMSENSE_EQUAL, self.getEVR()) )
        return provs

    def addProvides(self, phash):
        for (name, flag, version) in self.getProvides():
            phash.setdefault(name, []).append((flag, version, self))

    def removeProvides(self, phash):
        for (name, flag, version) in self.getProvides():
            phash[name].remove((flag, version, self))

    def getRequires(self):
        return self._getDeps("requirename", "requireflags", "requireversion")

    def getObsoletes(self):
        return self._getDeps("obsoletename", "obsoleteflags",
            "obsoleteversion")

    def getConflicts(self):
        return self._getDeps("conflictname", "conflictflags",
            "conflictversion")

    def addDeps(self, name, flag, version, phash):
        for (n, f, v) in self._getDeps(name, flag, version):
            phash.setdefault((n, f, v), []).append(self)

    def removeDeps(self, name, flag, version, phash):
        for (n, f, v) in self._getDeps(name, flag, version):
            phash[(n, f, v)].remove(self)

    def getTriggers(self):
        deps = self._getDeps("triggername", "triggerflags", "triggerversion")
        index = self["triggerindex"]
        scripts = self["triggerscripts"]
        progs = self["triggerscriptprog"]
        if self.verify:
            if deps == []:
                if index != None or scripts != None or progs != None:
                    self.printErr("wrong triggers still exist")
            else:
                if len(scripts) != len(progs):
                    self.printErr("wrong triggers")
                if index == None:
                    if len(deps) != len(scripts):
                        self.printErr("wrong triggers")
                else:
                    if len(deps) != len(index):
                        self.printErr("wrong triggers")
    # python-only
        if index == None:
            return [ (deps[i][0], deps[i][1], deps[i][2], progs[i], scripts[i])
                for i in xrange(len(deps)) ]
        return [ (deps[i][0], deps[i][1], deps[i][2], progs[index[i]],
                scripts[index[i]]) for i in xrange(len(deps)) ]
    # python-only-end
    # pyrex-code
    #    return []
    # pyrex-code-end

    def genSigHeader(self):
        """Take data from the signature header and append it to the hdr."""
        for (sig, hdr) in headermatch:
            if self[hdr] != None and self.sig[sig] == None:
                self.sig[sig] = self[hdr]

    def genRpmdbHeader(self):
        """Take the rpmdb header data to again create a signature header."""
        for (sig, hdr) in headermatch:
            if self.sig[sig] != None and self[hdr] == None:
                self[hdr] = self.sig[sig]

    def isInstallonly(self):
        """Can several packages be installed at the same time or should this
        rpm be normally installed only once?"""
        if (self["name"] in installonlypkgs or
            self["name"].startswith("kernel-module") or
            "kernel-modules" in self.hdr.get("providename", [])):
            return 1
        return 0

    def buildOnArch(self, arch):
        # do not build if this arch is in the exclude list
        exclude = self["excludearch"]
        if exclude and arch in exclude:
            return None
        # do not build if this arch is not in the exclusive list
        exclusive = self["exclusivearch"]
        if exclusive and arch not in exclusive:
            return None
        # return 2 if this will build into a "noarch" rpm
        if self["buildarchs"] == ["noarch"]:
            return 2
        # otherwise build this rpm normally for this arch
        return 1

    def getChangeLog(self, num=-1, newer=None):
        """ Return the changlog entry in one string. """
        ctext = self["changelogtext"]
        if not ctext:
            return ""
        cname = self["changelogname"]
        ctime = self["changelogtime"]
        if num == -1 or num > len(ctext):
            num = len(ctext)
        data = []
        for i in xrange(num):
            if newer != None and ctime[i] <= newer:
                break
            data.append("* %s %s\n%s\n\n" % (time.strftime("%a %b %d %Y",
                time.gmtime(ctime[i])), cname[i], ctext[i]))
        return "".join(data)

    def __verifyWriteHeader(self, hdrhash, taghash, region, hdrdata,
        useinstall, rpmgroup):
        (indexNo, storeSize, fmt, fmt2) = writeHeader(None, hdrhash, taghash,
            region, {}, useinstall, rpmgroup)
        if (indexNo, storeSize, fmt, fmt2) != (hdrdata[0], hdrdata[1],
            hdrdata[3], hdrdata[4]):
            self.printErr("(rpm-%s) writeHeader() would write a different " \
                "normal header" % self["rpmversion"])

    def getImmutableRegion(self):
        """rpmdb data has the original header data and then adds some items
           from the signature header and some other info about the installed
           package. This routine tries to get the unmodified data of the
           original rpm header."""
        # "immutable1" is set for old rpm headers for the entry in rpmdb.
        if self["immutable1"] != None:
            (tag, ttype, offset, count) = unpack("!4I", self.hdrdata[3][0:16])
            if tag != 61 or ttype != RPM_BIN or count != 16:
                return None
            storeSize = offset
            (tag, ttype, offset, count) = unpack("!2IiI",
                self.hdrdata[4][offset:offset + 16])
            if (tag != 61 or (-offset % 16 != 0) or
                ttype != RPM_BIN or count != 16):
                return None
            indexNo = (-offset - 16) / 16
            fmt = self.hdrdata[3][16:(indexNo + 1) * 16]
            fmt2 = self.hdrdata[4][:storeSize]
            return (indexNo, storeSize, fmt, fmt2)
        if self["immutable"] == None:
            return None
        (tag, ttype, offset, count) = unpack("!4I", self.hdrdata[3][0:16])
        if tag != rpmtag["immutable"][0] or ttype != RPM_BIN or count != 16:
            return None
        storeSize = offset + 16
        (tag, ttype, offset, count) = unpack("!2IiI",
            self.hdrdata[4][offset:storeSize])
        if (tag != rpmtag["immutable"][0] or (-offset % 16 != 0) or
            ttype != RPM_BIN or count != 16):
            return None
        indexNo = -offset / 16
        fmt = self.hdrdata[3][:indexNo * 16]
        fmt2 = self.hdrdata[4][:storeSize]
        return (indexNo, storeSize, fmt, fmt2)

    def __doVerify(self):
        if self.rpmgroup not in (None, RPM_STRING, RPM_I18NSTRING):
            self.printErr("rpmgroup out of range")
        self.__verifyWriteHeader(self.hdr.hash, rpmtag,
            "immutable", self.hdrdata, 1, self.rpmgroup)
        if self.strict:
            self.__verifyWriteHeader(self.sig.hash, rpmsigtag,
                "header_signatures", self.sigdata, 0, None)
        # disable the utf-8 test per default, should check against self.verbose:
        if self.strict and not opensuse:
            for i in ("summary", "description", "changelogtext"):
                if self[i] == None:
                    continue
                for j in self[i]:
                    try:
                        j.decode("utf-8")
                    except UnicodeDecodeError:
                        self.printErr("not utf-8 in %s" % i)
                        #self.printErr("text: %s" % j)
                        break
        if not self.issrc and (self.strict and
            self["name"][:6] == "kernel" and
            self["name"] not in ("kernel-utils", "kernel-doc",
            "kernel-pcmcia-cs", "kernel-debuginfo", "kernel-ib",
            "kernel-headers") and not self.isInstallonly()):
            self.printErr("possible kernel rpm")
        for i in ("md5",):
            if not self.sig.has_key(i):
                self.printErr("sig header is missing: %s" % i)
        for i in ("name", "version", "release", "arch", "rpmversion"):
            if not self.hdr.has_key(i):
                self.printErr("hdr is missing: %s" % i)
        size_in_sig = self.sig.getOne("size_in_sig")
        if size_in_sig != None and not isUrl(self.filename):
            rpmsize = os.stat(self.filename).st_size
            if rpmsize != 96 + self.sigdatasize + size_in_sig:
                self.printErr("wrong size in rpm package: %d / %d" % \
                    (rpmsize, 96 + self.sigdatasize + size_in_sig))
        filenames = self.getFilenames()
        if self.issrc:
            i = self.getSpecfile(filenames)
            if i == None:
                self.printErr("no specfile found in src.rpm")
            else:
                if self.strict and not filenames[i].endswith(".spec"):
                    self.printErr("specfile does not end with .spec")
                #if self.strict and filenames[i] != self["name"] + ".spec":
                #    self.printErr("specfile not using default name: %s" % \
                #        filenames[i])
            if self["sourcerpm"] != None:
                self.printErr("binary rpm does contain sourcerpm tag")
        else:
            if self["sourcerpm"] == None:
                self.printErr("source rpm does not contain sourcerpm tag")
        if self["triggerscripts"] != None:
            if len(self["triggerscripts"]) != len(self["triggerscriptprog"]):
                self.printErr("wrong trigger lengths")
        if self.strict:
            for i in ("-", ":"):
                if i in self["version"] or i in self["release"]:
                    self.printErr("version/release contains wrong char")
            for i in (",", " ", "\t"):
                if (i in self["name"] or i in self["version"] or
                    i in self["release"]):
                    self.printErr("name/version/release contains wrong char")
            for i in self.hdr.get("provideversion", []) + \
                self.hdr.get("requireversion", []) + \
                self.hdr.get("obsoleteversion", []) + \
                self.hdr.get("conflictversion", []):
                j = i.find(":")
                if (j != -1 and not i[:j].isdigit()) or i.count(":") > 1:
                    self.printErr("wrong char ':' in deps")
                if " " in i or "," in i or "\t" in i:
                    self.printErr("wrong char [ ,\\t] in deps")
                if i.count("-") >= 2:
                    self.printErr("too many '-' in deps")
                if i[:1] and not i[:1].isdigit():
                    self.printErr("dependency version starts " +
                        "with non-digit: %s" % i)
                if "%" in i:
                    self.printErr("dependency version contains %%: %s" % i)
        if self["payloadformat"] not in [None, "cpio", "drpm"]:
            self.printErr("wrong payload format %s" % self["payloadformat"])
        if self.strict:
            if opensuse:
                if self["payloadcompressor"] not in [None, "gzip", "bzip2"]:
                    self.printErr("no gzip/bzip2 compressor: %s" % \
                        self["payloadcompressor"])
            else:
                if self["payloadcompressor"] not in [None, "gzip"]:
                    self.printErr("no gzip compressor: %s" % \
                        self["payloadcompressor"])
        else:
            if self["payloadcompressor"] not in [None, "gzip", "bzip2"]:
                self.printErr("no gzip/bzip2 compressor: %s" % \
                    self["payloadcompressor"])
        if self.strict and self["payloadflags"] not in ["9"]:
            self.printErr("no payload flags: %s" % self["payloadflags"])
        if self.strict and self["os"] not in ["Linux", "linux"]:
            self.printErr("bad os: %s" % self["os"])
        elif self["os"] not in ["Linux", "linux", "darwin"]:
            self.printErr("bad os: %s" % self["os"])
        if self.strict:
            if opensuse:
                if self["packager"] not in ("http://bugs.opensuse.org",):
                    self.printErr("unknown packager: %s" % self["packager"])
                if self["vendor"] not in (
                    "SUSE LINUX Products GmbH, Nuernberg, Germany",):
                    self.printErr("unknown vendor: %s" % self["vendor"])
            else:
                if self["packager"] not in (None, "Koji",
                    "Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>",
                    "Fedora Project <http://bugzilla.redhat.com/bugzilla>",
                    "Fedora Project",
                    "Matthias Saou <matthias@rpmforge.net>"):
                    self.printErr("unknown packager: %s" % self["packager"])
                if self["vendor"] not in (None, "Red Hat, Inc.", "Koji",
                    "Fedora Project", "Livna.org RPMS", "Freshrpms.net"):
                    self.printErr("unknown vendor: %s" % self["vendor"])
                if self["distribution"] not in (None, "Red Hat",
                    "Red Hat Linux", "Red Hat FC-3", "Red Hat (FC-3)",
                    "Red Hat (FC-4)", "Red Hat (FC-5)", "Red Hat (FC-6)",
                    "Red Hat (FC-7)", "Fedora Extras", "Red Hat (scratch)",
                    "Red Hat (RHEL-3)", "Red Hat (RHEL-4)",
                    "Red Hat (RHEL-5)", "Unknown"):
                    self.printErr("unknown distribution: %s" % \
                        self["distribution"])
        arch = self["arch"]
        if self["rhnplatform"] not in (None, arch):
            self.printErr("unknown arch for rhnplatform")
        if self.strict:
            if os.path.basename(self.filename) != self.getFilename():
                self.printErr("bad filename: %s" % self.filename)
            if opensuse:
                if self["platform"] not in (None, "",
                  arch + "-suse-linux", "noarch-suse-linux"):
                    self.printErr("unknown arch %s" % self["platform"])
            elif self["platform"] not in (None, "", arch + "-redhat-linux-gnu",
                arch + "-redhat-linux", "--target=${target_platform}",
                arch + "-unknown-linux",
                "--target=${TARGET_PLATFORM}", "--target=$TARGET_PLATFORM"):
                self.printErr("unknown arch %s" % self["platform"])
        if self["exclusiveos"] not in (None, ["Linux"], ["linux"]):
            self.printErr("unknown os %s" % self["exclusiveos"])
        if self.strict:
            if self["buildarchs"] not in (None, ["noarch"]):
                self.printErr("bad buildarch: %s" % self["buildarchs"])
            if self["excludearch"] != None:
                for i in self["excludearch"]:
                    if i not in possible_archs:
                        self.printErr("new possible arch %s" % i)
            if self["exclusivearch"] != None:
                for i in self["exclusivearch"]:
                    if i not in possible_archs:
                        self.printErr("new possible arch %s" % i)
        for (s, p) in (("prein", "preinprog"), ("postin", "postinprog"),
            ("preun", "preunprog"), ("postun", "postunprog"),
            ("verifyscript", "verifyscriptprog")):
            (script, prog) = (self[s], self[p])
            if script != None and prog == None:
                self.printErr("no prog")
            if self.strict:
                if ((not isinstance(prog, basestring) and prog != None) or
                     prog not in possible_scripts):
                    self.printErr("unknown prog: %s" % prog)
                if script == None and prog == "/bin/sh" and not opensuse:
                    self.printErr("empty script: %s" % s)
                if script != None and isCommentOnly(script):
                    self.printErr("empty(2) script: %s" % s)
        # some verify tests are also in these functions:
        for (n, f, v) in (("providename", "provideflags", "provideversion"),
            ("requirename", "requireflags", "requireversion"),
            ("obsoletename", "obsoleteflags", "obsoleteversion"),
            ("conflictname", "conflictflags", "conflictversion"),
            ("triggername", "triggerflags", "triggerversion")):
            self.__verifyDeps(n, f, v)
        if not self.issrc:
            provs = self._getDeps("providename", "provideflags",
                "provideversion")
            mydep = (self["name"], RPMSENSE_EQUAL, self.getEVR())
            ver = self["rpmversion"]
            # AS2.1 still has compat rpms which need this:
            if ver != None and ver[:4] < "4.3." and mydep not in provs:
                provs.append(mydep)
            if mydep not in provs:
                self.printErr("no provides for own rpm package, rpm=%s" % ver)
        self.getTriggers()
        # Check for /tmp/ and /usr/src in the provides:
        if self.strict and self["providename"]:
            for n in self["providename"]:
                if n.find("/tmp/") != -1 or n.find("/usr/src") != -1:
                    self.printErr("suspicous provides: %s" % n)

        # check file* tags to be consistent:
        reqfiletags = ["fileusername", "filegroupname", "filemodes",
            "filemtimes", "filedevices", "fileinodes", "filesizes",
            "filemd5s", "filerdevs", "filelinktos", "fileflags"]
        filetags = ["fileverifyflags", "filelangs", "filecolors", "fileclass",
            "filedependsx", "filedependsn"]
        x = self[reqfiletags[0]]
        lx = None
        if x != None:
            lx = len(x)
            for t in reqfiletags:
                if self[t] == None or len(self[t]) != lx:
                    self.printErr("wrong length for tag %s" % t)
            for t in filetags:
                if self[t] != None and len(self[t]) != lx:
                    self.printErr("wrong length for tag %s" % t)
        else:
            for t in reqfiletags[:] + filetags[:]:
                if self[t] != None:
                    self.printErr("non-None tag %s" % t)
        if self["oldfilenames"]:
            if (self["dirindexes"] != None or
                self["dirnames"] != None or
                self["basenames"] != None):
                self.printErr("new filetag still present")
            if lx != len(self["oldfilenames"]):
                self.printErr("wrong length for tag oldfilenames")
        elif self["dirindexes"]:
            if (len(self["dirindexes"]) != lx or len(self["basenames"]) != lx
                or self["dirnames"] == None):
                self.printErr("wrong length for file* tag")
            # Would genBasenames() generate the same output?
            if (self["basenames"], list(self["dirindexes"]),
                self["dirnames"]) != genBasenames(filenames):
                self.printErr("dirnames/dirindexes is generated differently")
        filemodes = self["filemodes"]
        filemd5s = self["filemd5s"]
        fileflags = self["fileflags"]
        if filemodes:
            for x in xrange(len(filemodes)):
                if fileflags[x] & RPMFILE_EXCLUDE:
                    self.printErr("exclude flag set in rpm")
                if fileflags[x] & (RPMFILE_GHOST | RPMFILE_EXCLUDE):
                    continue
                if S_ISREG(filemodes[x]):
                    # All regular files except 0-sized files must have
                    # a md5sum.
                    if not filemd5s[x] and self["filesizes"][x] != 0:
                        self.printErr("missing filemd5sum, %d, %s" % (x,
                                filenames[x]))
                elif filemd5s[x] != "":
                    print filemd5s[x]
                    self.printErr("non-regular file has filemd5sum")

        # Verify count/flags for rpmheader tags.
        for (indexNo, fmt, dorpmtag) in ((self.hdrdata[0], self.hdrdata[3],
             rpmtag), (self.sigdata[0], self.sigdata[3], rpmsigtag)):
            for i in xrange(0, indexNo * 16, 16):
                (tag, ttype, offset, count) = unpack("!4I", fmt[i:i + 16])
                t = dorpmtag[tag]
                if t[2] != None and t[2] != count:
                    self.printErr("tag %d has wrong count %d" % (tag, count))
                if self.strict and (t[3] & 1):
                    if not opensuse or tag not in (1012, 1013, 1123, 1152,
                        1154, 1156, 1157, 1158, 1159, 1160, 1161):
                        self.printErr("tag %d is old" % tag)
                if self.issrc:
                    if (t[3] & 4):
                        self.printErr("tag %d should be for binary rpms" % tag)
                else:
                    if (t[3] & 2):
                        self.printErr("tag %d should be for src rpms" % tag)

        # Verify region headers have sane data. We do not support more than
        # one region header at this point.
        if self["immutable"] != None:
            (tag, ttype, offset, count) = unpack("!4I", self.hdrdata[3][0:16])
            if tag != rpmtag["immutable"][0] or ttype != RPM_BIN or count != 16:
                self.printErr("region tag not at the beginning of the header")
            elif offset + 16 != self.hdrdata[1]:
                self.printErr("wrong length of tag header detected")
        for (data, regiontag) in ((self["immutable"], rpmtag["immutable"][0]),
            (self.sig["header_signatures"], rpmsigtag["header_signatures"][0])):
            if data == None:
                continue
            (tag, ttype, offset, count) = unpack("!2IiI", data)
            if tag != regiontag or ttype != RPM_BIN or count != 16:
                self.printErr("region has wrong tag/type/count")
            if -offset % 16 != 0:
                self.printErr("region has wrong offset")
            if (regiontag == rpmtag["immutable"][0] and
                -offset / 16 != self.hdrdata[0]):
                self.printErr("region tag %s only for partial header: %d, %d" \
                    % (regiontag, self.hdrdata[0], -offset / 16))

        if self.nodigest:
            return 0

        # sha1 of the header
        sha1header = self.sig["sha1header"]
        if sha1header:
            ctx = sha.new()
            ctx.update(self.hdrdata[2])
            ctx.update(self.hdrdata[3])
            ctx.update(self.hdrdata[4])
            if ctx.hexdigest() != sha1header:
                self.printErr("wrong sha1: %s / %s" % (sha1header,
                    ctx.hexdigest()))
                return 1
        # md5sum of header plus payload
        md5sum = self.sig["md5"]
        if md5sum:
            ctx = md5.new()
            ctx.update(self.hdrdata[2])
            ctx.update(self.hdrdata[3])
            ctx.update(self.hdrdata[4])
            data = self.fd.read(65536)
            while data:
                ctx.update(data)
                data = self.fd.read(65536)
            # make sure we re-open this file if we read the payload
            self.closeFd()
            if ctx.digest() != md5sum:
                from binascii import b2a_hex
                self.printErr("wrong md5: %s / %s" % (b2a_hex(md5sum),
                    ctx.hexdigest()))
                return 1
        return 0


def unlinkRpmdbCache(dbpath):
    for i in xrange(9):
        try:
            os.unlink(dbpath + "__db.00%d" % i)
        except OSError:
            pass

def readReleaseVer(distroverpkg, buildroot="", rpmdbpath="/var/lib/rpm/"):
    """Search for distroverpkg within the Provides: of the rpmdb.
    Return with the very first entry found."""
    import bsddb
    dbpath = buildroot + rpmdbpath
    unlinkRpmdbCache(dbpath) # XXX needed for read-only access???
    providename_db = None # XXX Create a class to access/cache access?
    packages_db = None
    for rpmname in distroverpkg:
        if providename_db == None:
            providename_db = bsddb.hashopen(dbpath + "Providename", "r")
        data = providename_db.get(rpmname, "")     # pylint: disable-msg=E1101
        for i in xrange(0, len(data), 8):
            if packages_db == None:
                packages_db = bsddb.hashopen(dbpath + "Packages", "r")
            data1 = packages_db.get(data[i:i + 4]) # pylint: disable-msg=E1101
            if data1:
                fd = StringIO(data1)
                pkg = ReadRpm("rpmdb", fd=fd)
                pkg.readHeader(None, versiontag, rpmdb=1)
                return pkg["version"]
    return None


class RpmDB:

    #zero = pack("I", 0)

    def __init__(self, buildroot="", rpmdbpath="/var/lib/rpm/"):
        self.buildroot = buildroot
        self.rpmdbpath = rpmdbpath
        self._pkgs = {}
        self.openDB4()

    def openDB4(self):
        import bsddb
        dbpath = self.buildroot + self.rpmdbpath
        makeDirs(dbpath)
        unlinkRpmdbCache(dbpath)
        flag = "c"
        self.basenames_db = bsddb.hashopen(dbpath + "Basenames", flag)
        self.conflictname_db = bsddb.hashopen(dbpath + "Conflictname", flag)
        self.dirnames_db = bsddb.btopen(dbpath + "Dirnames", flag)
        self.filemd5s_db = bsddb.hashopen(dbpath + "Filemd5s", flag)
        self.group_db = bsddb.hashopen(dbpath + "Group", flag)
        self.installtid_db = bsddb.btopen(dbpath + "Installtid", flag)
        self.name_db = bsddb.hashopen(dbpath + "Name", flag)
        self.packages_db = bsddb.hashopen(dbpath + "Packages", flag)
        self.providename_db = bsddb.hashopen(dbpath + "Providename", flag)
        self.provideversion_db = bsddb.btopen(dbpath + "Provideversion", flag)
        self.requirename_db = bsddb.hashopen(dbpath + "Requirename", flag)
        self.requireversion_db = bsddb.btopen(dbpath + "Requireversion", flag)
        self.sha1header_db  = bsddb.hashopen(dbpath + "Sha1header", flag)
        self.sigmd5_db = bsddb.hashopen(dbpath + "Sigmd5", flag)
        self.triggername_db = bsddb.hashopen(dbpath + "Triggername", flag)

    #def getPkgById(self, id2):
    #    if self._pkgs.has_key(id2):
    #        return self._pkgs[id2]
    #    else:
    #        #pkg = self.readRpm(id2, self.packages_db, self.tags)
    #        #if pkg is not None:
    #        #    self._pkgs[id2] = pkg
    #        #return pkg
    #        return None

    def searchFilenames(self, filename):
        (dirname, basename) = pathsplit2(filename)
        data1 = self.basenames_db.get(basename, "") # pylint: disable-msg=E1101
        data2 = self.dirnames_db.get(dirname, "")   # pylint: disable-msg=E1101
        dirname_ids = {}
        for i in xrange(0, len(data2), 8):
            id_ = data2[i:i + 4]
            dirname_ids[id_] = None
        result = []
        for i in xrange(0, len(data1), 8):
            id_ = data1[i:i + 4]
            if id_ not in dirname_ids:
                continue
            idx = unpack("I", data1[i + 4:i + 8])[0]
            #pkg = self.getPkgById(id_)
            #if pkg and pkg.iterFilenames()[idx] == filename:
            #    result.append(pkg)
            result.append( (id_, idx) )
        return result


def readRpm(filenames, sigtag, tag):
    rpms = []
    for filename in filenames:
        rpm = ReadRpm(filename)
        if rpm.readHeader(sigtag, tag):
            print "Cannot read %s.\n" % filename
            continue
        rpm.closeFd()
        rpms.append(rpm)
    return rpms

def verifyRpm(filename, verify, strict, payload, nodigest, hdrtags, keepdata,
    headerend):
    """Read in a complete rpm and verify its integrity."""
    rpm = ReadRpm(filename, verify, strict=strict, nodigest=nodigest)
    if not nodigest or payload:
        headerend = None
    if rpm.readHeader(rpmsigtag, hdrtags, keepdata, headerend=headerend):
        return None
    if payload:
        rpm.readPayload(rpm.verifyCpio)
    rpm.closeFd()
    return rpm

def extractRpm(filename, buildroot, owner=None, db=None):
    """Extract a rpm into a directory."""
    if isinstance(filename, basestring):
        rpm = ReadRpm(filename)
        if rpm.readHeader(rpmsigtag, rpmtag):
            return None
    else:
        rpm = filename
    rpm.buildroot = buildroot
    if rpm.issrc:
        if buildroot[-1:] != "/" and buildroot != "":
            buildroot += "/"
    else:
        buildroot = buildroot.rstrip("/")
    rpm.buildroot = buildroot
    rpm.setOwner(owner)
    rpm.readPayload(rpm.extractCpio, extract=1, db=db)

def sameSrcRpm(a, b):
    # Packages with the same md5sum for the payload are the same.
    amd5sum = a.sig["md5"]
    if amd5sum != None and amd5sum == b.sig["md5"]:
        return 1
    # Check if all regular files are the same in both packages.
    amd5s = []
    for (md5sum, name, mode) in zip(a["filemd5s"], a.getFilenames(),
        a["filemodes"]):
        if S_ISREG(mode):
            amd5s.append((md5sum, name))
    amd5s.sort()
    bmd5s = []
    for (md5sum, name, mode) in zip(b["filemd5s"], b.getFilenames(),
        b["filemodes"]):
        if S_ISREG(mode):
            bmd5s.append((md5sum, name))
    bmd5s.sort()
    return amd5s == bmd5s

def ignoreBinary():
    return "\.gz$\n\.tgz$\n\.taz$\n\.tbz$\n\.bz2$\n\.z$\n\.Z$\n\.zip$\n" \
        "\.ttf$\n\.db$\n\.jar$\n\.pdf$\n\.sdf$\n\.war$\n\.gsi$\n"

def isBinary(filename):
    for i in (".gz", ".tgz", ".taz", ".tbz", ".bz2", ".z", ".Z", ".zip",
        ".ttf", ".db", ".jar", ".pdf", ".sdf", ".war", ".gsi"):
        if filename.endswith(i):
            return 1
    return 0

def explodeFile(filename, dirname, version):
    if filename.endswith(".tar.gz"):
        explode = "z"
        dirn = filename[:-7]
    elif filename.endswith(".tar.bz2"):
        explode = "j"
        dirn = filename[:-8]
    else:
        return
    newdirn = dirn
    if newdirn.endswith(version):
        newdirn = newdirn[:- len(version)]
    while newdirn[-1] in "-_.0123456789":
        newdirn = newdirn[:-1]
    os.system("cd " + dirname + " && { tar x" + explode + "f " + filename \
              + "; for i in * ; do test -d \"$i\" && mv \"$i\" " + newdirn \
              + "; done; }")
    return newdirn

delim = "--- -----------------------------------------------------" \
    "---------------------\n"

def diffTwoSrpms(oldsrpm, newsrpm, explode=None):
    from commands import getoutput

    ret = ""
    # If they are identical don't output anything.
    if oldsrpm == newsrpm:
        return ret
    orpm = ReadRpm(oldsrpm)
    if orpm.readHeader(rpmsigtag, rpmtag):
        return ret
    nrpm = ReadRpm(newsrpm)
    if nrpm.readHeader(rpmsigtag, rpmtag):
        return ret
    if sameSrcRpm(orpm, nrpm):
        return ret

    ret = ret + delim
    ret = ret + "--- Look at changes from "
    if orpm["name"] != nrpm["name"]:
        ret = ret + os.path.basename(oldsrpm) + " to " + \
            os.path.basename(newsrpm) + ".\n"
    else:
        ret = ret + orpm["name"] + " " + orpm["version"] + "-" + \
            orpm["release"] + " to " + nrpm["version"] + "-" + \
            nrpm["release"] + ".\n"

    obuildroot = orpm.buildroot = mkstemp_dir(tmpdir) + "/"
    nbuildroot = nrpm.buildroot = mkstemp_dir(tmpdir) + "/"

    sed1 = "sed 's#^--- " + obuildroot + "#--- #'"
    sed2 = "sed 's#^+++ " + nbuildroot + "#+++ #'"
    sed = sed1 + " | " + sed2

    extractRpm(orpm, obuildroot)
    ofiles = orpm.getFilenames()
    ospec = orpm.getSpecfile(ofiles)
    extractRpm(nrpm, nbuildroot)
    nfiles = nrpm.getFilenames()
    nspec = nrpm.getSpecfile(nfiles)

    # Search identical files and remove them. Also remove/explode
    # old binary files.
    for f in xrange(len(ofiles)):
        if ofiles[f] not in nfiles:
            if isBinary(ofiles[f]):
                if explode:
                    explodeFile(ofiles[f], obuildroot, orpm["version"])
                ret = ret + "--- " + ofiles[f] + " is removed\n"
                os.unlink(obuildroot + ofiles[f])
            continue
        g = nfiles.index(ofiles[f])
        if (orpm["filemd5s"][f] == nrpm["filemd5s"][g] and
            f != ospec and g != nspec):
            os.unlink(obuildroot + ofiles[f])
            os.unlink(nbuildroot + nfiles[g])
    # Search new binary files.
    for f in nfiles:
        if not isBinary(f) or f in ofiles:
            continue
        if explode:
            explodeFile(f, nbuildroot, nrpm["version"])
        ret = ret + "--- " + f + " is added\n"
        os.unlink(nbuildroot + f)

    # List all old and new files.
    ret = ret + "old:\n"
    ret = ret + getoutput("ls -l " + obuildroot)
    ret = ret + "\nnew:\n"
    ret = ret + getoutput("ls -l " + nbuildroot)
    ret = ret + "\n"

    # Generate the diff for the spec file first.
    if ospec != None and nspec != None:
        ospec = obuildroot + ofiles[ospec]
        nspec = nbuildroot + nfiles[nspec]
        ret = ret + getoutput("diff -u " + ospec + " " + nspec + " | " + sed)
        os.unlink(ospec)
        os.unlink(nspec)

    # Diff the rest.
    ret = ret + getoutput("diff -urN " + obuildroot + " " + nbuildroot + \
        " | " + sed)
    os.system("rm -rf " + obuildroot + " " + nbuildroot)
    return ret

def TreeDiff(dir1, dir2):
    import glob
    new = []
    changed = []
    files2 = os.listdir(dir2)
    files2.sort()
    for f in files2:
        # only look at .rpm files
        if f[-4:] != ".rpm":
            continue
        # continue if the same file already existed
        if os.path.exists("%s/%s" % (dir1, f)):
            continue
        # read the new rpm header
        rpm = ReadRpm("%s/%s" % (dir2, f))
        if rpm.readHeader(rpmsigtag, rpmtag):
            print "Cannot read %s.\n" % f # XXX traceback instead of print?
            continue
        # Is there a previous rpm?
        oldf = glob.glob("%s/%s*" % (dir1, rpm["name"]))
        if not oldf:
            # No previous, so list this as new package.
            new.append("New package %s\n\t%s\n" % (rpm["name"],
                rpm["summary"][0]))
        else:
            # Output the new changes:
            orpm = ReadRpm(oldf[0])
            if orpm.readHeader(rpmsigtag, rpmtag):
                print "Cannot read %s.\n" % oldf[0]
                continue
            (changelognum, changelogtime) = getChangeLogFromRpm(rpm, orpm)
            clist = "\n"
            if changelognum != -1 or changelogtime != None:
                clist = rpm.getChangeLog(changelognum, changelogtime)
            nvr = rpm.getNVR()
            changed.append("%s (from %s-%s)\n%s\n%s" % (nvr, orpm["version"],
                orpm["release"], "-" * len(nvr), clist))
    # List all removed packages:
    removed = []
    files1 = os.listdir(dir1)
    files1.sort()
    for f in files1:
        # only look at .rpm files
        if f[-4:] != ".rpm":
            continue
        # continue if the same file still exists
        if os.path.exists("%s/%s" % (dir2, f)):
            continue
        # read the old rpm header
        rpm = ReadRpm("%s/%s" % (dir1, f))
        if rpm.readHeader(rpmsigtag, rpmtag):
            print "Cannot read %s.\n" % f
            continue
        # Is there a new rpm?
        if not glob.glob("%s/%s*" % (dir2, rpm["name"])):
            removed.append("Removed package %s\n" % rpm["name"])
    
    if not changed:
        changed = ["(none)",]
    return  "".join(("\n".join(new), "\n\n", "\n".join(removed),
        "\n\nUpdated Packages:\n\n", "".join(changed)))


class HashList:
    """ hash list """

    def __init__(self):
        self.list = []
        self.hash = {}
        self.__len__ = self.list.__len__
        self.__repr__ = self.list.__repr__
        self.index = self.list.index
        self.has_key = self.hash.has_key
        self.keys = self.hash.keys
        self.get = self.hash.get

    def __getitem__(self, key):
        if isinstance(key, IntType):
            return self.list[key]
        return self.hash.get(key)

    def __contains__(self, key):
        if isinstance(key, IntType):
            return self.list.__contains__(key)
        return self.hash.__contains__(key)

    def __setitem__(self, key, value):
        if not self.hash.has_key(key):
            self.list.append(key)
        self.hash[key] = value
        return value

    def __delitem__(self, key):
        if self.hash.has_key(key):
            del self.hash[key]
            self.list.remove(key)
            return key
        return None

    def pop(self, idx):
        key = self.list.pop(idx)
        del self.hash[key]
        return key

    def add(self, key, value):
        if not key in self:
            self[key] = []
        self[key].append(value)

    def extend(self, key, value):
        if not key in self:
            self[key] = []
        self[key].extend(value)

    def remove(self, key, value):
        l = self[key]
        l.remove(value)
        if len(l) == 0:
            del self[key]

    def setdefault(self, key, defvalue):
        if not self.has_key(key):
            self[key] = defvalue
        return self[key]


# Exact reimplementation of glibc's bsearch algorithm. Used by /bin/rpm to
# generate dirnames, dirindexes and basenames from oldfilenames (and we want
# to do it the same way).
def bsearch(key, list2):
    l = 0
    u = len(list2)
    while l < u:
        idx = (l + u) / 2
        r = cmp(key, list2[idx])
        if r < 0:
            u = idx
        elif r > 0:
            l = idx + 1
        else:
            return idx
    return -1

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

def genBasenames(oldfilenames):
    """Split oldfilenames into basenames, dirindexes, dirnames. Do this
    exactly like /bin/rpm does. A faster version would cache the last result
    and also use "dirindex = dirnames.index(dirname)", but we use this only
    to verify rpm packages until now."""
    (basenames, dirindexes, dirnames) = ([], [], [])
    for filename in oldfilenames:
        (dirname, basename) = pathsplit2(filename)
        dirindex = bsearch(dirname, dirnames)
        if dirindex < 0:
            dirindex = len(dirnames)
            dirnames.append(dirname)
        basenames.append(basename)
        dirindexes.append(dirindex)
    return (basenames, dirindexes, dirnames)

def genBasenames2(oldfilenames):
    (basenames, dirnames) = ([], [])
    for filename in oldfilenames:
        (dirname, basename) = pathsplit2(filename)
        basenames.append(basename)
        dirnames.append(dirname)
    return (basenames, dirnames)


class FilenamesList:
    """A mapping from filenames to rpm packages."""

    def __init__(self, checkfileconflicts):
        self.checkfileconflicts = checkfileconflicts
        self.path = {} # dirname => {basename => (RpmPackage, index)}

    def addPkg(self, pkg):
        """Add all files from RpmPackage pkg to self."""
        path = self.path
        basenames = pkg["basenames"]
        if basenames != None:
            dirindexes = pkg["dirindexes"]
            dirnames = pkg["dirnames"]
            for dirname in dirnames:
                path.setdefault(dirname, {})
            # python-only
            dirnames = [ dirnames[di] for di in dirindexes ]
            # python-only-end
            # pyrex-code
            #dirnames2 = []
            #for di in dirindexes:
            #    dirnames2.append(dirnames[di])
            #dirnames = dirnames2
            # pyrex-code-end
        else:
            if pkg["oldfilenames"] == None:
                return
            # genBasenames2() is called for addPkg() and removePkg()
            (basenames, dirnames) = genBasenames2(pkg["oldfilenames"])
            for dirname in dirnames:
                path.setdefault(dirname, {})
        if self.checkfileconflicts:
            for i in xrange(len(basenames)):
                path[dirnames[i]].setdefault(basenames[i], []).append((pkg, i))
        else:
            for i in xrange(len(basenames)):
                path[dirnames[i]].setdefault(basenames[i], []).append(pkg)

    def removePkg(self, pkg):
        """Remove all files from RpmPackage pkg from self."""
        basenames = pkg["basenames"]
        if basenames != None:
            dirindexes = pkg["dirindexes"]
            dirnames = pkg["dirnames"]
            # python-only
            dirnames = [ dirnames[di] for di in dirindexes ]
            # python-only-end
            # pyrex-code
            #dirnames2 = []
            #for di in dirindexes:
            #    dirnames2.append(dirnames[di])
            #dirnames = dirnames2
            # pyrex-code-end
        else:
            if pkg["oldfilenames"] == None:
                return
            (basenames, dirnames) = genBasenames2(pkg["oldfilenames"])
        if self.checkfileconflicts:
            for i in xrange(len(basenames)):
                self.path[dirnames[i]][basenames[i]].remove((pkg, i))
        else:
            for i in xrange(len(basenames)):
                self.path[dirnames[i]][basenames[i]].remove(pkg)

    def searchDependency(self, name):
        """Return list of packages providing file with name."""
        (dirname, basename) = pathsplit2(name)
        ret = self.path.get(dirname, {}).get(basename, [])
        if self.checkfileconflicts:
            # python-only
            return [ r[0] for r in ret ]
            # python-only-end
            # pyrex-code
            #ret2 = []
            #for r in ret:
            #    ret2.append(r[0])
            #return ret2
            # pyrex-code-end
        return ret


# split EVR string in epoch, version and release
def evrSplit(evr):
    epoch = "0"
    i = evr.find(":")
    if i != -1 and evr[:i].isdigit():
        epoch = evr[:i]
    j = evr.rfind("-", i + 1)
    if j != -1:
        return (epoch, evr[i + 1:j], evr[j + 1:])
    return (epoch, evr[i + 1:], "")

flagmap2 = {
    RPMSENSE_EQUAL: "=",
    RPMSENSE_LESS: "<",
    RPMSENSE_GREATER: ">",
    RPMSENSE_EQUAL | RPMSENSE_LESS: "<=",
    RPMSENSE_EQUAL | RPMSENSE_GREATER: ">="
}

def depString(name, flag, version):
    if version == "":
        return name
    return "(%s %s %s)" % (name, flagmap2[flag & RPMSENSE_SENSEMASK], version)

def searchDependency(name, flag, version, mydeps):
    deps = mydeps.get(name, [])
    if not deps:
        return []
    if isinstance(version, basestring):
        evr = evrSplit(version)
    else:
        evr = version
    ret = []
    for (f, v, rpm) in deps:
        if rpm in ret:
            continue
        if version == "" or rangeCompare(flag, evr, f, evrSplit(v)):
            ret.append(rpm)
        elif v == "":
            if rpm.strict:
                print "Warning:", rpm.getFilename(), \
                    "should have a flag/version added for the provides", \
                    depString(name, flag, version)
            ret.append(rpm)
    return ret


class RpmResolver:

    def __init__(self, rpms, checkfileconflicts):
        self.rpms = []
        self.requires_list = {}
        self.filenames_list = FilenamesList(checkfileconflicts)
        self.provides_list = {}
        self.obsoletes_list = {}
        self.conflicts_list = {}
        for r in rpms:
            if r["name"] != "gpg-pubkey":
                self.addPkg(r)

    def addPkg(self, pkg):
        self.rpms.append(pkg)
        pkg.addDeps("requirename", "requireflags", "requireversion",
            self.requires_list)
        if pkg.issrc:
            return
        self.filenames_list.addPkg(pkg)
        pkg.addProvides(self.provides_list)
        pkg.addDeps("obsoletename", "obsoleteflags", "obsoleteversion",
            self.obsoletes_list)
        pkg.addDeps("conflictname", "conflictflags", "conflictversion",
            self.conflicts_list)

    def removePkg(self, pkg):
        self.rpms.remove(pkg)
        pkg.removeDeps("requirename", "requireflags", "requireversion",
            self.requires_list)
        if pkg.issrc:
            return
        self.filenames_list.removePkg(pkg)
        pkg.removeProvides(self.provides_list)
        pkg.removeDeps("obsoletename", "obsoleteflags", "obsoleteversion",
            self.obsoletes_list)
        pkg.removeDeps("conflictname", "conflictflags", "conflictversion",
            self.conflicts_list)

    def searchDependency(self, name, flag, version):
        s = searchDependency(name, flag, version, self.provides_list)
        if name[0] == "/" and version == "":
            s += self.filenames_list.searchDependency(name)
        return s


OP_INSTALL = "install"
OP_UPDATE = "update"
OP_ERASE = "erase"
OP_FRESHEN = "freshen"

def operationFlag(flag, operation):
    """Return dependency flag for RPMSENSE_* flag during operation."""
    if (isLegacyPreReq(flag) or
           (operation == OP_ERASE and isErasePreReq(flag)) or
           (operation != OP_ERASE and isInstallPreReq(flag))):
        return 1
    return 0


class RpmRelation:
    """Pre and post relations for a package (a node in the dependency
    graph)."""

    def __init__(self):
        self.pre = {}          # RpmPackage => flag
        self.post = {}         # RpmPackage => 1 (value is not used)
        self.weight = 0        # # of pkgs depending on this package
        self.weight_edges = 0

    def __str__(self):
        return "%d %d" % (len(self.pre), len(self.post))


class RpmRelations(dict):
    """List of relations for each package (a dependency graph)."""
    # RpmPackage => RpmRelation
    def __init__(self, rpms):
        dict.__init__()
        for pkg in rpms:
            self[pkg] = RpmRelation()

    def addRelation(self, pkg, pre, flag):
        """Add an arc from RpmPackage pre to RpmPackage pkg with flag.
        pre can be None to add pkg to the graph with no arcs."""
        i = self[pkg]
        if flag or pre not in i.pre:
            # prefer hard requirements, do not overwrite with soft req
            i.pre[pre] = flag
            self[pre].post[pkg] = 1

    def remove(self, pkg):
        """Remove RpmPackage pkg from the dependency graph."""
        rel = self[pkg]
        # remove all post relations for the matching pre relation packages
        for r in rel.pre:
            del self[r].post[pkg]
        # remove all pre relations for the matching post relation packages
        for r in rel.post:
            del self[r].pre[pkg]
        del self[pkg]

    def removeRelation(self, node, next):
        """Drop the "RpmPackage node requires RpmPackage next" arc."""
        del self[node].pre[next]
        del self[next].post[node]

    def collect(self, pkg, order):
        """Move package from the relations graph to the order list
        Handle ConnectedComponent."""
        if isinstance(pkg, ConnectedComponent):
            pkg.breakUp(order)
        else:
            order.append(pkg)
        self.remove(pkg)

    def separatePostLeafNodes(self, list2):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list2.

        Stop when each remaining package has successor (implies a dependency
        loop)."""
        i = 0
        found = 0
        while len(self) > 0:
            pkg = self[i]
            if len(self[pkg].post) == 0:
                list2.append(pkg)
                self.remove(pkg)
                found = 1
            else:
                i += 1
            if i == len(self):
                if found == 0:
                    break
                i = 0
                found = 0

    def _calculateWeights2(self, pkg, leafs):
        """For each package generate a dict of all packages that depend on it.
        At last use the length of the dict as weight."""
        # Uncomment weight line in ConnectedComponent.__init__() to use this
        if self[pkg].weight == 0:
            weight = {pkg: pkg}
        else:
            weight = self[pkg].weight

        for p in self[pkg].pre:
            rel = self[p]
            if rel.weight == 0:
                rel.weight = weight.copy()
                rel.weight[p] = p
            else:
                rel.weight.update(weight)
            rel.weight_edges += 1
            if rel.weight_edges == len(rel.post):
                leafs.append(p)

        if self[pkg].weight == 0:
            self[pkg].weight = 1
        else:
            self[pkg].weight = len(weight)

    def _calculateWeights(self, pkg, leafs):
        """Weight of a package is sum of the (weight+1) of all packages
        depending on it."""
        weight = self[pkg].weight + 1
        for p in self[pkg].pre:
            rel = self[p]
            rel.weight += weight
            rel.weight_edges += 1
            if rel.weight_edges == len(rel.post):
                leafs.append(p)

    def calculateWeights(self):
        leafs = []
        for pkg in self:
            if not self[pkg].post: # post leaf node
                self._calculateWeights(pkg, leafs)
        while leafs:
            self._calculateWeights(leafs.pop(), leafs)
        weights = {}
        for pkg in self:
            weights.setdefault(self[pkg].weight, []).append(pkg)
        return weights

    def processLeafNodes(self, order, leaflist=None):
        """Move topologically sorted "trailing" packages from
        orderer.RpmRelations relations to start of list."""
        if leaflist is None:
            leaflist = self # loop over all pkgs

        # do a bucket sort
        leafs = {} # len(post) -> [leaf pkgs]
        for pkg in leaflist:
            if not self[pkg].pre:
                post = len(self[pkg].post)
                leafs.setdefault(post, []).append(pkg)

        if leafs:
            max_post = max(leafs)

        while leafs:
            # remove leaf node
            leaf = leafs[max_post].pop()
            rels = self[leaf]
            self.collect(leaf, order)
            #self.config.printDebug(2, "%s" % (leaf.getNEVRA()))
            # check post nodes if they got a leaf now
            new_max = max_post
            for pkg in rels.post:
                if not self[pkg].pre:
                    post = len(self[pkg].post)
                    leafs.setdefault(post, []).append(pkg)
                    if post > new_max:
                        new_max = post
            # select new (highest) bucket
            if not leafs[max_post]:
                del leafs[max_post]
                if leafs:
                    max_post = max(leafs)
            else:
                max_post = new_max

    def genOrder(self):
        """Order rpms in orderer.RpmRelations relations.
        Return an ordered list of RpmPackage's on success, None on error."""
        length = len(self)
        order = []
        connected_components = ConnectedComponentsDetector(self).detect(self)
        #if connected_components:
        #    self.config.printDebug(1, "-- STRONLY CONNECTED COMPONENTS --")
        #    if self.config.debug > 1:
        #        for i in xrange(len(connected_components)):
        #            s = ", ".join([pkg.getNEVRA() for pkg in
        #                           connected_components[i].pkgs])
        #            self.config.printDebug(2, "  %d: %s" % (i, s))
        self.processLeafNodes(order)
        if len(order) != length:
            print "%d Packages of %d in order list! Number of connected " \
                "components: %d " % (len(order), length,
                len(connected_components))
            raise
        return order


class ConnectedComponent:
    """Contains a Strongly Connected Component (SCC).
    This is a (maximal) set of nodes that are all reachable from
    each other. In other words the component consists of loops touching
    each other.

    Automatically changes all relations of its pkgs from/to outside the
    component to itself. After all components have been created the relations
    graph is cycle free.

    Mimics RpmPackage.
    """

    def __init__(self, relations, pkgs):
        """relations: the RpmRelations object containing the loops."""

        self.relations = relations
        # add myself to the list
        relations[self] = RpmRelation()
        self.pkgs = {}
        for pkg in pkgs:
            self.pkgs[pkg] = pkg
            relations[pkg].weight = -1

        # remove all relations this connected component is replacing
        for pkg in pkgs:
            to_remove = []
            for pre in relations[pkg].pre:
                if not pre in self.pkgs:
                    to_remove.append(pre)
            for p in to_remove:
                flag = relations[pkg].pre[p]
                relations.removeRelation(pkg, p)
                relations.addRelation(self, p, flag)


            to_remove = []
            for post in relations[pkg].post:
                if not post in self.pkgs:
                    to_remove.append(post)
            for p in to_remove:
                flag = relations[pkg].post[p]
                relations.removeRelation(p, pkg)
                relations.addRelation(p, self, flag)

        relations[self].weight = len(self.pkgs)
        # uncomment for use of the dict based weight algorithm
        # relations[self].weight = self.pkgs.copy()

    def __len__(self):
        return len(self.pkgs)

    def __str__(self):
        return repr(self)

    def getNEVRA(self):
        # python-only
        return "Component: " + \
            ",".join([ pkg.getNEVRA() for pkg in self.pkgs ])
        # python-only-end
        # pyrex-code
        #ret = []
        #for pkg in self.pkgs:
        #    ret.append(pkg.getNEVRA())
        #return "Component: " + ",".join(ret)
        # pyrex-code-end

    def processLeafNodes(self, order):
        """Remove all leaf nodes with the component and append them to order.
        """
        while 1:
            # Without the requirement of max(rel.pre) this could be O(1)
            next = None
            next_post_len = -1
            for pkg in self.pkgs:
                if (len(self.relations[pkg].pre) == 0 and
                    len(self.relations[pkg].post) > next_post_len):
                    next = pkg
                    next_post_len = len(self.relations[pkg].post)
            if next:
                self.relations.collect(next, order)
                del self.pkgs[next]
            else:
                return

    def removeSubComponent(self, component):
        """Remove all packages of a sub component from own package list."""
        for pkg in component.pkgs:
            del self.pkgs[pkg]

    def breakUp(self, order):
        hard_requirements = []
        for pkg in self.pkgs:
            for (p, req) in self.relations[pkg].pre.iteritems():
                if req:
                    hard_requirements.append((pkg, p))
        # pick requirement to delete
        weights = {}
        # calculate minimal distance to a pre req
        for (pkg, nextpkg) in hard_requirements:
            # dijkstra
            edge = [nextpkg]
            weights[nextpkg] = 0
            while edge:
                node = edge.pop()
                weight = weights[node] + 1
                for (next_node, ishard) in self.relations[node].pre.iteritems():
                    if ishard:
                        continue
                    w = weights.get(next_node, None)
                    if w is not None and w < weight:
                        continue
                    weights[next_node] = weight
                    edge.append(next_node)
                edge.sort()
                edge.reverse()
        if weights:
            # get pkg with largest minimal distance
            weight = -1
            for (p, w) in weights.iteritems():
                if w > weight:
                    (weight, pkg2) = (w, p)
            # get the predesessor with largest minimal distance
            weight = -1
            for p in self.relations[pkg2].post:
                w = weights[p]
                if w > weight:
                    (weight, pkg1) = (w, p)
        else:
            # search the relation that will most likely set a pkg free:
            # relations that are the last post (pre) of the start (end) pkg
            # are good, if there are lots of pre/post at the side
            # where the relation is the last it is even better
            # to make less relations better we use the negative values
            weight = None
            for p1 in self.pkgs:
                pre = len(self.relations[p1].pre)
                post = len(self.relations[p1].post)
                for p2 in self.relations[p1].pre.iterkeys():
                    pre2 = len(self.relations[p2].pre)
                    post2 = len(self.relations[p2].post)
                    if pre < post2: # start is more interesting
                        w = (-pre, post, -post2, pre)
                    elif pre > post2: #  end is more interesting
                        w = (-post2, pre2, -pre, post2)
                    else: # == both same, add the numbers of per and post
                        w = (-pre, post+pre2)
                    if w > weight:
                        # python handles comparison of tuples from left to
                        #  right (like strings)
                        weight = w
                        (pkg1, pkg2) = (p1, p2)
        if self.relations[pkg1].pre[pkg2]:
            print "Breaking pre requirement for %s: %s" % (pkg1.getNEVRA(),
                pkg2.getNEVRA())
        # remove this requirement
        self.relations.removeRelation(pkg1, pkg2)
        # rebuild components
        components = ConnectedComponentsDetector(self.relations
            ).detect(self.pkgs)
        for component in components:
            self.removeSubComponent(component)
            self.pkgs[component] = component
        # collect nodes
        self.processLeafNodes(order)


class ConnectedComponentsDetector:
    """Use Gabow algorithm to detect strongly connected components:
        Do a depth first traversal and number the nodes.
        "root node": the node of a SCC that is visited first
        Keep two stacks:
          1. stack of all still possible root nodes
          2. stack of all visited but still unknown nodes (pkg stack)
        If we reach a unknown node just descent.
        If we reach an unprocessed node it has a smaller number than the
         node we came from and all nodes with higher numbers than this
         node can be reach from it. So we must remove those nodes
         from the root stack.
        If we reach a node already processed (part of a SCC (of possibly
         only one node size)) there is no way form this node to our current.
         Just ignore this way.
        If we go back in the recursion the following can happen:
        1. Our node has been removed from the root stack. It is part of a
           SCC -> do nothing
        2. Our node is top on the root stack: the pkg stack contains a SCC
           from the position of our node up -> remove it including our node
           also remove the node from the root stack
        """

    def __init__(self, relations):
        self.relations = relations

    def detect(self, pkgs):
        """Returns a list of all strongly ConnectedComponents."""
        self.states = {}      # attach numbers to packages
        self.root_stack = []  # stack of possible root nodes
        self.pkg_stack = []   # stack of all nodes visited and not processed yet
        self.sccs = []        # already found strongly connected components
        self.pkg_cnt = 0      # number of current package

        # continue until all nodes have been visited
        for pkg in pkgs:
            if pkg not in self.states:
                self._process(pkg)
        # python-only
        return [ ConnectedComponent(self.relations, pkgs) \
            for pkgs in self.sccs ]
        # python-only-end
        # pyrex-code
        #ret = []
        #for pkgs in self.sccs:
        #    ret.append(ConnectedComponent(self.relations, pkgs))
        #return ret
        # pyrex-code-end

    def _process(self, pkg):
        """Descent recursivly"""
        states = self.states
        root_stack = self.root_stack
        pkg_stack = self.pkg_stack

        self.pkg_cnt += 1
        states[pkg] = self.pkg_cnt
        # push pkg to both stacks
        pkg_stack.append(pkg)
        root_stack.append(pkg)

        for next in self.relations[pkg].pre:
            if next in states:
                if states[next] > 0:
                    # if visited but not finished
                    # remove all pkgs with higher number from root stack
                    i = len(root_stack) - 1
                    while i >= 0 and states[root_stack[i]] > states[next]:
                        i -= 1
                    del root_stack[i + 1:]
            else:
                # visit
                self._process(next)

        # going up in the recursion
        # if pkg is a root node (top on root stack)
        if root_stack[-1] is pkg:
            if pkg_stack[-1] is pkg:
                # only one node SCC, drop it
                pkg_stack.pop()
                states[pkg] = 0 # set to "already processed"
            else:
                # get non trivial SCC from stack
                idx = pkg_stack.index(pkg)
                scc = pkg_stack[idx:]
                del pkg_stack[idx:]
                for p in scc:
                    states[p] = 0 # set to "already processed"
                self.sccs.append(scc)
            root_stack.pop()


class RpmOrderer:

    def __init__(self, installs, updates, obsoletes, erases, resolver):
        """Initialize.
        installs is a list of added RpmPackage's
        erases a list of removed RpmPackage's (including updated/obsoleted)
        updates is a hash: new RpmPackage => ["originally" installed RpmPackage
            removed by update]
        obsoletes is a hash: new RpmPackage => ["originally" installed
            RpmPackage removed by update]
        installs, updates and obsoletes can be None."""
        self.installs = installs
        self.updates = updates
        # Only explicitly removed packages, not updated/obsoleted.
        self.erases = erases
        if self.updates:
            for pkg in self.updates:
                for p in self.updates[pkg]:
                    if p in self.erases:
                        self.erases.remove(p)
        self.obsoletes = obsoletes
        if self.obsoletes:
            for pkg in self.obsoletes:
                for p in self.obsoletes[pkg]:
                    if p in self.erases:
                        self.erases.remove(p)
        self.resolver = resolver

    def _genEraseOps(self, list2):
        """Return a list of (operation, RpmPackage) for erasing RpmPackage's
        in list2."""
        if len(list2) == 1:
            return [(OP_ERASE, list2[0])]
        return RpmOrderer({}, {}, {}, list2, self.resolver).order()

    def genRelations(self, rpms, operation):
        """Return orderer.Relations between RpmPackage's in list rpms for
        operation."""
        resolver = self.resolver
        relations = RpmRelations(rpms)
        for ((n, f, v), rpms) in resolver.requires_list.iteritems():
            if n[:7] in ("rpmlib(", "config("):
                continue
            resolved = resolver.searchDependency(n, f, v)
            if resolved:
                f2 = operationFlag(f, operation)
            for pkg in rpms:
                if pkg in resolved: # ignore deps resolved also by itself
                    continue
                i = relations[pkg]
                for pre in resolved:
                    # prefer hard requirements, do not overwrite with soft req
                    if f2 or pre not in i.pre:
                        i.pre[pre] = f2
                        relations[pre].post[pkg] = 1
        return relations

    def genOperations(self, order):
        """Return a list of (operation, RpmPackage) tuples from ordered list of
        RpmPackage's order."""
        operations = []
        for r in order:
            if r in self.erases:
                operations.append((OP_ERASE, r))
            else:
                if self.updates and r in self.updates:
                    op = OP_UPDATE
                else:
                    op = OP_INSTALL
                operations.append((op, r))
                if self.obsoletes and r in self.obsoletes:
                    operations.extend(self._genEraseOps(self.obsoletes[r]))
                if self.updates and r in self.updates:
                    operations.extend(self._genEraseOps(self.updates[r]))
        return operations

    def order(self):
        order = []
        if self.installs:
            relations = self.genRelations(self.installs, OP_INSTALL)
            order2 = relations.genOrder()
            if order2 == None:
                return None
            order.extend(order2)
        if self.erases:
            relations = self.genRelations(self.erases, OP_ERASE)
            order2 = relations.genOrder()
            if order2 == None:
                return None
            order2.reverse()
            order.extend(order2)
        return self.genOperations(order)


def selectNewestRpm(rpms, arch_hash, verbose):
    """Select one package out of rpms that has the highest version
    number."""
    newest = rpms[0]
    newestarch = arch_hash.get(newest.getArch(), 999)
    for rpm in rpms[1:]:
        rpmarch = arch_hash.get(rpm.getArch(), 999)
        if (rpmarch < newestarch or
            (rpmarch == newestarch and pkgCompare(newest, rpm) < 0)):
            if verbose > 4:
                print "select", rpm.getFilename(), "over", newest.getFilename()
            newest = rpm
            newestarch = rpmarch
        else:
            if verbose > 4:
                print "select", newest.getFilename(), "over", \
                    rpm.getFilename()
    return newest

def getPkgsNewest(rpms, arch=None, arch_hash={}, # pylint: disable-msg=W0102
    verbose=0, exactarch=1, nosrc=0):
    # Add all rpms by name,arch into a hash.
    h = {}
    for rpm in rpms:
        if rpm.issrc:
            if nosrc:
                if verbose > 5:
                    print "Removed .src.rpm:", rpm.getFilename()
                continue
            rarch = "src"
        else:
            rarch = rpm["arch"]
            if not exactarch:
                rarch = buildarchtranslate.get(rarch, rarch)
        h.setdefault( (rpm["name"], rarch) , []).append(rpm)
    # For each arch select one newest rpm.
    pkgs = []
    for r in h.itervalues():
        pkgs.append(selectNewestRpm(r, arch_hash, verbose))
    if arch:
        # Add all rpms into a hash by their name.
        h = {}
        for rpm in pkgs:
            if rpm.issrc:
                if verbose > 5:
                    print "Removed .src.rpm:", rpm.getFilename()
                continue
            # Remove all rpms not suitable for this arch.
            if arch_hash.get(rpm["arch"]) == None:
                if verbose > 4:
                    print "Removed due to incompatibel arch:", \
                        rpm.getFilename()
                continue
            h.setdefault(rpm["name"], []).append(rpm)
        # By name find the newest rpm and then decide if a noarch
        # rpm is the newest (and all others are deleted) or if an
        # arch-dependent rpm is newest (and all noarchs are removed).
        for rpms in h.itervalues():
            # set verbose to 0 as this is actually not selecting rpms:
            newest = selectNewestRpm(rpms, arch_hash, 0)
            if newest["arch"] == "noarch":
                for r in rpms:
                    if r != newest:
                        pkgs.remove(r)
                        if verbose > 4:
                            print "Removed older rpm:", r.getFilename()
            else:
                for r in rpms:
                    if r["arch"] == "noarch":
                        pkgs.remove(r)
                        if verbose > 4:
                            print "Removed older rpm:", r.getFilename()
    return pkgs

def findRpms(dirname, uselstat=None, verbose=0):
    s = os.stat
    if uselstat:
        s = os.lstat
    dirs = [dirname]
    files = []
    while dirs:
        d = dirs.pop()
        for f in os.listdir(d):
            path = "%s/%s" % (d, f)
            st = s(path)
            if S_ISREG(st.st_mode) and f[-4:] == ".rpm":
                files.append(path)
            elif S_ISDIR(st.st_mode):
                dirs.append(path)
            else:
                if verbose > 2:
                    print "ignoring non-rpm", path
    return files


class RpmInfo:

    def __init__(self, pkg):
        if isinstance(pkg, ListType):
            (self.filename, self.name, self.origepoch, self.version,
                self.release, self.arch, self.sigdatasize, self.hdrdatasize,
                self.pkgsize, self.sha1header) = pkg[:10]
            self.sigdatasize = int(self.sigdatasize)
            self.hdrdatasize = int(self.hdrdatasize)
            self.pkgsize = int(self.pkgsize)
            # python-only
            self.deps = [ (pkg[i], int(pkg[i + 1]), pkg[i + 2]) \
                for i in xrange(10, len(pkg), 3) ]
            # python-only-end
            # pyrex-code
            #self.deps = []
            #for i in xrange(10, len(pkg), 3):
            #    self.deps.append((pkg[i], int(pkg[i + 1]), pkg[i + 2]))
            # pyrex-code-end
        else: # if isinstance(pkg, ReadRpm):
            self.filename = pkg.filename
            self.name = pkg["name"]
            self.origepoch = pkg.getEpoch("")
            self.version = pkg["version"]
            self.release = pkg["release"]
            self.arch = pkg.getArch()
            self.sigdatasize = pkg.sigdatasize
            self.hdrdatasize = pkg.hdrdatasize
            size_in_sig = pkg.sig.getOne("size_in_sig")
            if size_in_sig != None:
                self.pkgsize = 96 + pkg.sigdatasize + size_in_sig
            elif not isUrl(self.filename):
                self.pkgsize = os.stat(self.filename).st_size
            else:
                raise ValueError, "pkg has no size_in_sig"
            self.sha1header = pkg.sig.get("sha1header", "")
            self.deps = pkg.getObsoletes()
        self.epoch = self.origepoch
        if self.epoch == "":
            self.epoch = "0"

    def getCSV(self):
        ret = [self.filename, self.name, self.epoch, self.version,
            self.release, self.arch, str(self.sigdatasize),
            str(self.hdrdatasize), str(self.pkgsize), self.sha1header]
        for (n, f, v) in self.deps:
            ret.extend([n, str(f), v])
        return ret


class RpmCSV:

    def __init__(self, data=None):
        self.pkglist = []
        if isinstance(data, basestring):
            self.pkglist = self.readCSV(data)

    def readCSV(self, filename):
        lines = open(filename, "r").readlines()
        csv = []
        crc = lines.pop()
        if not crc.startswith("# crc: ") or not crc[-1] == "\n":
            #print "crc not correct"
            return None
        crc = int(crc[7:-1])
        crcval = zlib.crc32("")
        for l in lines:
            crcval = zlib.crc32(l, crcval)
            if l[-1:] == "\n":
                l = l[:-1]
            entry = l.split(",")
            if len(entry) < 10:
                #print "csv: not enough entries"
                return None
            csv.append(RpmInfo(entry))
        if crcval != crc:
            #print "csv: crc did not match"
            return None
        return csv

    def addPkg(self, pkg):
        self.pkglist.append(RpmInfo(pkg))

    def writeCSV(self, filename, check=1):
        # python-only
        csv = [ pkg.getCSV() for pkg in self.pkglist ]
        # python-only-end
        # pyrex-code
        #csv = []
        #for pkg in self.pkglist:
        #    csv.append(pkg.getCSV())
        # pyrex-code-end
        # Check if any value contains a wrong character.
        if check:
            for l in csv:
                for item in l:
                    if "," in item:
                        return None
        # Write new CSV file with crc checksum.
        (fd, tmp) = mkstemp_file(pathdirname(filename))
        crcval = zlib.crc32("")
        for l in csv:
            data = ",".join(l) + "\n"
            crcval = zlib.crc32(data, crcval)
            os.write(fd, data)
        os.write(fd, "# crc: " + str(crcval) + "\n")
        os.close(fd)
        os.rename(tmp, filename)
        return 1

def checkCSV():
    pkgs = findRpms("/home/mirror/fedora/development/i386/Fedora/RPMS")
    pkgs = readRpm(pkgs, rpmsigtag, rpmtag)
    csv = RpmCSV()
    for p in pkgs:
        csv.addPkg(p)
    if csv.writeCSV("/tmp/csv") == None:
        print "Cannot write csv file."
    csv2 = RpmCSV("/tmp/csv")
    if csv2.pkglist == None:
        print "Cannot read/parse csv file."
        return
    csv2.writeCSV("/tmp/csv2")


def cacheLocal(urls, filename, subdir, verbose, checksum=None,
    checksumtype=None, nofilename=0):
    import urlgrabber
    try:
        from M2Crypto.SSL.Checker import WrongHost
    except ImportError:
        WrongHost = None

    for url in urls:
        if not url:
            continue
        url = Uri2Filename(url).rstrip("/")
        if nofilename == 0:
            url += filename
        if verbose > 4:
            print "cacheLocal: looking at url:", url
        if not url.startswith("http://") and not url.startswith("ftp://"):
            return url
        (dirname, basename) = pathsplit(filename)
        localdir = cachedir + subdir + dirname
        makeDirs(localdir)
        localfile = "%s/%s" % (localdir, basename)
        if checksum and getChecksum(localfile, checksumtype) == checksum:
            return localfile
        if verbose > 5:
            print "cacheLocal: localfile:", localfile
        try:
            f = urlgrabber.urlgrab(url, localfile,
                timeout=float(urloptions["timeout"]),
                retry=int(urloptions["retries"]),
                keepalive=int(urloptions["keepalive"]),
                proxies=urloptions["proxies"],
                http_headers=urloptions["http_headers"])
        except (urlgrabber.grabber.URLGrabError, WrongHost), e:
            if verbose > 4:
                print "cacheLocal: error: e:", e
            # urlgrab fails with invalid range for already completely transfered
            # files, pretty strange to me to be honest... :)
            if type(e) == ListType and e[0] == 9:
                if checksum and getChecksum(localfile, checksumtype) \
                    != checksum:
                    continue
                return localfile
            continue
        if verbose > 5:
            print "cacheLocal: return:", f
        if checksum and getChecksum(f, checksumtype) != checksum:
            continue
        return f
    return None

def buildPkgRefDict(pkgs):
    """Take a list of packages and return a dict that contains all the possible
       naming conventions for them: name, name.arch, name-version-release.arch,
       name-version, name-version-release, epoch:name-version-release."""
    pkgdict = {}
    for pkg in pkgs:
        (n, e, v, r, a) = (pkg["name"], pkg.getEpoch(), pkg["version"],
            pkg["release"], pkg.getArch())
        na = "%s.%s" % (n, a)
        nv = "%s-%s" % (n, v)
        nvr = "%s-%s" % (nv, r)
        nvra = "%s.%s" % (nvr, a)
        envra = "%s:%s" % (e, nvra)
        for item in (n, na, nv, nvr, nvra, envra):
            pkgdict.setdefault(item, []).append(pkg)
    return pkgdict

__fnmatchre__ = re.compile(".*[\*\[\]\{\}\?].*")
def parsePackages(pkgs, requests):
    """Matches up the user request versus a pkg list. For installs/updates
       available pkgs should be the 'others list' for removes it should be
       the installed list of pkgs."""
    matched = []
    if requests:
        pkgdict = buildPkgRefDict(pkgs)
        for request in requests:
            if request in pkgdict:
                matched.extend(pkgdict[request])
            elif __fnmatchre__.match(request):
                import fnmatch
                regex = re.compile(fnmatch.translate(request))
                for item in pkgdict.iterkeys():
                    if regex.match(item):
                        matched.extend(pkgdict[item])
    return matched

def escape(s):
    """Return escaped string converted to UTF-8. Return None if the string is
       empty, so the newChild method does not add text node."""
    if not s:
        return None
    s = s.replace("&", "&amp;")
    if isinstance(s, unicode):
        return s
    try:
        x = unicode(s, "ascii")
        return s
    except UnicodeError:
        encodings = ("utf-8", "iso-8859-1", "iso-8859-15", "iso-8859-2")
        for enc in encodings:
            try:
                x = unicode(s, enc)
            except UnicodeError:
                pass
            else:
                if x.encode(enc) == s:
                    return x.encode("utf-8")
    newstring = ""
    for char in s:
        if ord(char) > 127:
            newstring = newstring + "?"
        else:
            newstring = newstring + char
    return re.sub("\n$", "", newstring)

flagmap = {
    None: None,
    "EQ": RPMSENSE_EQUAL,
    "LT": RPMSENSE_LESS,
    "GT": RPMSENSE_GREATER,
    "LE": RPMSENSE_EQUAL | RPMSENSE_LESS,
    "GE": RPMSENSE_EQUAL | RPMSENSE_GREATER,
    "": 0,
    RPMSENSE_EQUAL: "EQ",
    RPMSENSE_LESS: "LT",
    RPMSENSE_GREATER: "GT",
    RPMSENSE_EQUAL | RPMSENSE_LESS: "LE",
    RPMSENSE_EQUAL | RPMSENSE_GREATER: "GE"
}
# Files included in primary.xml.
filerc = re.compile("^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$")
dirrc = re.compile("^(.*bin/.*|/etc/.*)$")

def utf8String(string):
    """hands back a unicoded string"""
    if string == None:
        return ""
    if isinstance(string, unicode):
        return string
    try:
        x = unicode(string, "ascii")
        return string
    except UnicodeError:
        for enc in ("utf-8", "iso-8859-1", "iso-8859-15", "iso-8859-2"):
            try:
                x = unicode(string, enc)
            except UnicodeError:
                pass
            else:
                if x.encode(enc) == string:
                    return x.encode("utf-8")
    newstring = ""
    for char in string:
        if ord(char) > 127:
            newstring += "?"
        else:
            newstring += char
    return newstring


def open_fh(filename):
    if filename[-3:] == ".gz":
        #return gzip.open(filename, "r")
        return PyGZIP(filename, None, None, None)
    return open(filename, "r")

def read_repodata(elem):
    p = {}
    p["type"] = elem.attrib.get("type")
    for child in elem:
        if child.tag == "{http://linux.duke.edu/metadata/repo}location":
            p["location"] = child.attrib.get("href")
            p["base"] = child.attrib.get("base")
        elif child.tag == "{http://linux.duke.edu/metadata/repo}checksum":
            p["checksum"] = child.text
            p["checksum_type"] = child.attrib.get("type")
        elif child.tag == "{http://linux.duke.edu/metadata/repo}open-checksum":
            p["openchecksum"] = child.text
            p["openchecksum_type"] = child.attrib.get("type")
        elif child.tag == "{http://linux.duke.edu/metadata/repo}timestamp":
            p["timestamp"] = child.text
    return p

def read_repomd(filename):
    fh = open(filename, "r")
    if not fh:
        return None
    o = {}
    for (_, elem) in iterparse(fh).__iter__():
        if elem.tag == "{http://linux.duke.edu/metadata/repo}data":
            p = read_repodata(elem)
            o[p["type"]] = p
            elem.clear()
    return o

def _bn(qn):
    return qn[qn.find("}") + 1:]

def _prefixprops(elem, prefix):
    prefix += "_"
    ret = {}
    for (key, value) in elem.attrib.iteritems():
        ret[prefix + _bn(key)] = value
    return ret

def read_primary(filename, verbose=5):
    fh = open_fh(filename)
    if not fh:
        return None
    ret = {}
    p = {}
    files = {}
    prco = {}
    for (_, elem) in iterparse(fh).__iter__():
        name = _bn(elem.tag)
        if name in ("name", "arch", "summary", "description", "url",
                "packager"):
            p[name] = elem.text
        elif name == "version": # epoch, ver, rel
            p.update(elem.attrib)
        elif name in ("time", "size"):
            # time: file, build.  size: package, installed, archive.
            p.update(_prefixprops(elem, name))
        elif name in ("checksum", "location"):
            p.update(_prefixprops(elem, name))
            p[name + "_value"] = elem.text
        elif name == "metadata":
            pass
        elif name == "package":
            p["file"] = files
            ret[p["name"] + p["ver"] + "-" + p["rel"]] = p
            p = {}
            files = {}
        elif name == "entry":
            pass
        elif name == "format":
            pass
        elif name == "file":
            files[elem.text] = elem.get("type", "file")
        elif name in ("license", "vendor", "group", "buildhost", "sourcerpm"):
            p[name] = elem.text
        elif name in ("provides", "requires", "conflicts", "obsoletes"):
            prco[name] = [ c2.attrib for c2 in elem ]
        elif name == "header-range":
            p.update(_prefixprops(elem, "rpm_header"))
        elif verbose > 4:
            print "new primary tag:", name
        #elem.clear()
    return ret

def testRepo():
    release = "/home/mirror/fedora/development/i386/os"
    time1 = time.clock()
    for _ in xrange(1000):
        read_repomd(release + "/repodata/repomd.xml")
    print time.clock() - time1, "milisec to read one repomd"
    print read_repomd(release + "/repodata/repomd.xml")
    time1 = time.clock()
    for _ in xrange(5):
        read_primary(release + "/repodata/primary.xml.gz")
    print (time.clock() - time1) / 5.0, "sec to read primary"
    print read_primary(release + "/repodata/primary.xml.gz")


def getProps(reader):
    Namef = reader.Name
    Valuef = reader.Value
    MoveToNextAttributef = reader.MoveToNextAttribute
    props = {}
    while MoveToNextAttributef():
        props[Namef()] = Valuef()
    return props

class RpmRepo:

    def __init__(self, filenames, excludes, verbose, reponame="default",
        readsrc=0, fast=1):
        self.filenames = filenames
        self.filename = None
        self.excludes = excludes.split(" \t,;")
        self.verbose = verbose
        self.reponame = reponame
        self.readsrc = readsrc
        self.filelist_imported = 0
        self.checksum = "sha" # "sha" or "md5"
        self.pretty = 1
        self.pkglist = {}
        self.groupfile = None
        self.fast = fast
        self.repomd = None

    def read(self, onlyrepomd=0, readgroupfile=0):
        for filename in self.filenames:
            if not filename or filename[:1] == "#":
                continue
            if self.verbose > 2:
                print "Reading yum repository %s." % filename
            self.filename = filename
            repomd = cacheLocal([filename], "/repodata/repomd.xml",
                self.reponame + "/repo", self.verbose)
            if not repomd:
                continue
            reader = libxml2.newTextReaderFilename(repomd)
            if reader == None:
                continue
            self.repomd = self.__parseRepomd(reader)
            if not self.repomd:
                continue
            if onlyrepomd:
                return 1
            repoprimary = self.repomd.get("primary", {})
            pchecksum = repoprimary.get("checksum", "no")
            pchecksumtype = repoprimary.get("checksum_type", "md5")
            primary = cacheLocal([filename], "/repodata/primary.xml.gz",
                self.reponame + "/repo", self.verbose, pchecksum,
                pchecksumtype)
            if not primary:
                continue
            reader = libxml2.newTextReaderFilename(primary)
            if reader == None:
                continue
            self.__parsePrimary(reader)
            self.__removeExcluded()
            repogroupfile = self.repomd.get("group", {})
            groupfile = repogroupfile.get("location")
            if readgroupfile and groupfile:
                gchecksum = repogroupfile.get("checksum", "no")
                gchecksumtype = repogroupfile.get("checksum_type", "md5")
                groupfile = cacheLocal([filename], "/" + groupfile,
                    self.reponame + "/repo", self.verbose, gchecksum,
                    gchecksumtype)
                if not groupfile:
                    continue
                self.groupfile = groupfile
                # Now parse the groupfile?
            return 1
        return 0

    def importFilelist(self):
        if self.filelist_imported:
            return 1
        if self.verbose > 2:
            print "Reading full filelist from %s." % self.filename
        repofilelists = self.repomd.get("filelists", {})
        fchecksum = repofilelists.get("checksum", "no")
        fchecksumtype = repofilelists.get("checksum_type", "md5")
        filelists = cacheLocal([self.filename], "/repodata/filelists.xml.gz",
            self.reponame + "/repo", self.verbose, fchecksum, fchecksumtype)
        if not filelists:
            return 0
        reader = libxml2.newTextReaderFilename(filelists)
        if reader == None:
            return 0
        self.__parseFilelist(reader)
        self.filelist_imported = 1
        return 1

    def createRepo(self, baseurl, ignoresymlinks, groupfile):
        filename = Uri2Filename(self.filenames[0]).rstrip("/")
        if self.verbose >= 2:
            print "Creating yum metadata repository for dir %s:" % filename
        rt = {}
        for i in ("name", "epoch", "version", "release", "arch",
            "requirename"):
            value = rpmtag[i]
            rt[i] = value
            rt[value[0]] = value
        filenames = findRpms(filename, ignoresymlinks)
        filenames.sort()
        if self.verbose >= 2:
            print "Reading %d .rpm files:" % len(filenames)
            printhash = PrintHash(len(filenames), 60)
        i = 0
        while i < len(filenames):
            if self.verbose >= 2:
                printhash.nextObject()
            path = filenames[i]
            pkg = ReadRpm(path)
            if pkg.readHeader({}, rt):
                print "Cannot read %s.\n" % path
                continue
            pkg.closeFd()
            if self.excludes and self.__isExcluded(pkg):
                filenames.pop(i)
                continue
            i += 1
        if self.verbose >= 2:
            printhash.nextObject(finish=1)
            print "Writing repo data for %d .rpm files:" % len(filenames)
            printhash = PrintHash(len(filenames), 60)
        numpkg = len(filenames)
        repodir = filename + "/repodata"
        makeDirs(repodir)
        (origpfd, pfdtmp) = mkstemp_file(repodir, special=1)
        pfd = GzipFile(fileobj=origpfd, mode="wb")
        if not pfd:
            return 0
        firstlinexml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        pfd.write(firstlinexml)
        pfd.write("<metadata xmlns=\"http://linux.duke.edu/metadata/common\"" \
            " xmlns:rpm=\"http://linux.duke.edu/metadata/rpm\" " \
            "packages=\"%d\">\n" % numpkg)
        (origffd, ffdtmp) = mkstemp_file(repodir, special=1)
        ffd = GzipFile(fileobj=origffd, mode="wb")
        if not ffd:
            return 0
        ffd.write(firstlinexml)
        ffd.write("<filelists xmlns=\"http://linux.duke.edu/metadata/" \
            "filelists\" packages=\"%d\">\n" % numpkg)
        (origofd, ofdtmp) = mkstemp_file(repodir, special=1)
        ofd = GzipFile(fileobj=origofd, mode="wb")
        if not ofd:
            return 0
        ofd.write(firstlinexml)
        ofd.write("<otherdata xmlns=\"http://linux.duke.edu/metadata/other\"" \
            " packages=\"%s\">\n" % numpkg)

        pdoc = libxml2.newDoc("1.0")
        proot = pdoc.newChild(None, "metadata", None)
        basens = proot.newNs("http://linux.duke.edu/metadata/common", None)
        formatns = proot.newNs("http://linux.duke.edu/metadata/rpm", "rpm")
        proot.setNs(basens)

        fdoc = libxml2.newDoc("1.0")
        froot = fdoc.newChild(None, "filelists", None)
        filesns = froot.newNs("http://linux.duke.edu/metadata/filelists", None)
        froot.setNs(filesns)

        odoc = libxml2.newDoc("1.0")
        oroot = odoc.newChild(None, "otherdata", None)
        otherns = oroot.newNs("http://linux.duke.edu/metadata/other", None)
        oroot.setNs(otherns)

        for path in filenames:
            if self.verbose >= 2:
                printhash.nextObject()
            pkg = ReadRpm(path)
            if pkg.readHeader(rpmsigtag, rpmtag):
                print "Cannot read %s.\n" % path
                continue
            pkg["yumlocation"] = path[len(filename) + 1:]
            pkg["yumchecksum"] = getChecksum(pkg.filename, self.checksum)
            self.__writePrimary(pfd, proot, pkg, formatns)
            self.__writeFilelists(ffd, froot, pkg)
            self.__writeOther(ofd, oroot, pkg)
        pfd.write("</metadata>\n")
        ffd.write("</filelists>\n")
        ofd.write("</otherdata>\n")
        # python-only
        del pfd, ffd, ofd
        # python-only-end
        origpfd.close()
        origffd.close()
        origofd.close()

        repodoc = libxml2.newDoc("1.0")
        reporoot = repodoc.newChild(None, "repomd", None)
        repons = reporoot.newNs("http://linux.duke.edu/metadata/repo", None)
        reporoot.setNs(repons)
        workfiles = [(ofdtmp, 1, "other"), (ffdtmp, 1, "filelists"),
            (pfdtmp, 1, "primary")]
        ngroupfile = repodir + "/" + groupfile
        if os.path.exists(ngroupfile):
            workfiles.append((ngroupfile, 0, "group"))
        for (ffile, gzfile, ftype) in workfiles:
            if gzfile:
                zfo = PyGZIP(ffile, None, None, None)
                uncsum = getChecksum(zfo, self.checksum)
            timestamp = os.stat(ffile).st_mtime
            csum = getChecksum(ffile, self.checksum)
            data = reporoot.newChild(None, "data", None)
            data.newProp("type", ftype)
            location = data.newChild(None, "location", None)
            if baseurl != None:
                location.newProp("xml:base", baseurl)
            if gzfile:
                location.newProp("href", "repodata/" + ftype + ".xml.gz")
            else:
                location.newProp("href", "repodata/" + groupfile)
            checksum = data.newChild(None, "checksum", csum)
            checksum.newProp("type", self.checksum)
            timestamp = data.newChild(None, "timestamp", str(timestamp))
            if gzfile:
                unchecksum = data.newChild(None, "open-checksum", uncsum)
                unchecksum.newProp("type", self.checksum)
        os.rename(pfdtmp, repodir + "/primary.xml.gz")
        os.rename(ffdtmp, repodir + "/filelists.xml.gz")
        os.rename(ofdtmp, repodir + "/other.xml.gz")
        repodoc.saveFormatFileEnc(repodir + "/repomd.xml", "UTF-8", 1)
        if self.verbose >= 2:
            printhash.nextObject(finish=1)
        return 1

    def __parseRepomd(self, reader):
        """Parse repomd.xml for sha1 checks of the files. Returns a hash of
        the form: name -> {location, checksum, timestamp, open-checksum}."""
        rethash = {}
        # Make local variables for heavy used functions to speed up this loop
        Readf = reader.Read
        NodeTypef = reader.NodeType
        Namef = reader.Name
        tmphash = {}
        fname = None
        if Readf() != 1 or NodeTypef() != TYPE_ELEMENT or Namef() != "repomd":
            return rethash
        while Readf() == 1:
            ntype = NodeTypef()
            if ntype == TYPE_END_ELEMENT:
                if Namef() == "repomd":
                    break
                continue
            if ntype != TYPE_ELEMENT:
                continue
            name = Namef()
            if name == "data":
                props = getProps(reader)
                fname = props.get("type")
                if not fname:
                    break
                tmphash = {}
                rethash[fname] = tmphash
            elif name == "location":
                props = getProps(reader)
                loc = props.get("href")
                if loc:
                    tmphash["location"] = loc
            elif name == "checksum" or name == "open-checksum":
                props = getProps(reader)
                ptype = props.get("type")
                if ptype not in ("sha", "md5"):
                    print "Unsupported checksum type %s in repomd.xml for" \
                        " file %s" % (ptype, fname)
                    continue
                tmphash[name + "_type"] = ptype
                if Readf() != 1:
                    break
                tmphash[name] = reader.Value()
            elif name == "timestamp":
                if Readf() != 1:
                    break
                tmphash["timestamp"] = reader.Value()
            elif name == "database_version":
                if Readf() != 1:
                    break
                tmphash["database_version"] = reader.Value()
            elif self.verbose > 4:
                print "new repomd entry: %s" % name
        return rethash

    def __parsePrimary(self, reader):
        Readf = reader.Read
        NodeTypef = reader.NodeType
        Namef = reader.Name
        while Readf() == 1:
            if NodeTypef() == TYPE_ELEMENT and Namef() == "package":
                props = getProps(reader)
                if props.get("type") == "rpm":
                    pkg = self.__parsePackage(reader)
                    if self.readsrc or pkg["arch"] != "src":
                        self.pkglist[pkg.getNEVRA0()] = pkg

    def delDebuginfo(self):
        for (nevra, pkg) in self.pkglist.iteritems():
            # or should we search for "-debuginfo" only?
            if (pkg["name"].endswith("-debuginfo") or
                pkg["name"] == "glibc-debuginfo-common"):
                del self.pkglist[nevra]

    def __removeExcluded(self):
        for pkg in parsePackages(self.pkglist.values(), self.excludes):
            nevra = pkg.getNEVRA0()
            if nevra in self.pkglist:
                del self.pkglist[nevra]

    def __isExcluded(self, pkg):
        return len(parsePackages([pkg, ], self.excludes)) != 0

    def __writeVersion(self, pkg_node, pkg):
        tnode = pkg_node.newChild(None, "version", None)
        tnode.newProp("epoch", pkg.getEpoch())
        tnode.newProp("ver", pkg["version"])
        tnode.newProp("rel", pkg["release"])

    def __writePrimary(self, fd, parent, pkg, formatns):
        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp("type", "rpm")
        pkg_node.newChild(None, "name", pkg["name"])
        pkg_node.newChild(None, "arch", pkg.getArch())
        self.__writeVersion(pkg_node, pkg)
        tnode = pkg_node.newChild(None, "checksum", pkg["yumchecksum"])
        tnode.newProp("type", self.checksum)
        tnode.newProp("pkgid", "YES")
        pkg_node.newChild(None, "summary", escape(pkg["summary"][0]))
        pkg_node.newChild(None, "description", escape(pkg["description"][0]))
        pkg_node.newChild(None, "packager", escape(pkg["packager"]))
        pkg_node.newChild(None, "url", escape(pkg["url"]))
        tnode = pkg_node.newChild(None, "time", None)
        st = os.stat(pkg.filename)
        tnode.newProp("file", str(st.st_mtime))
        tnode.newProp("build", str(pkg["buildtime"][0]))
        tnode = pkg_node.newChild(None, "size", None)
        # st.st_size == 96 + pkg.sigdatasize + pkg.sig.getOne("size_in_sig")
        tnode.newProp("package", str(st.st_size))
        tnode.newProp("installed", str(pkg["size"][0]))
        archivesize = pkg.hdr.getOne("archivesize")
        if archivesize == None:
            archivesize = pkg.sig.getOne("payloadsize")
        tnode.newProp("archive", str(archivesize))
        tnode = pkg_node.newChild(None, "location", None)
        tnode.newProp("href", pkg["yumlocation"])
        fnode = pkg_node.newChild(None, "format", None)
        self.__generateFormat(fnode, pkg, formatns)
        output = pkg_node.serialize("UTF-8", self.pretty)
        fd.write(output + "\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()

    def __writePkgInfo(self, parent, pkg):
        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp("pkgid", pkg["yumchecksum"])
        pkg_node.newProp("name", pkg["name"])
        pkg_node.newProp("arch", pkg.getArch())
        self.__writeVersion(pkg_node, pkg)
        return pkg_node

    def __writeFilelists(self, fd, parent, pkg):
        pkg_node = self.__writePkgInfo(parent, pkg)
        self.__generateFilelist(pkg_node, pkg, 0)
        output = pkg_node.serialize("UTF-8", self.pretty)
        fd.write(output + "\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()

    def __writeOther(self, fd, parent, pkg):
        pkg_node = self.__writePkgInfo(parent, pkg)
        if pkg["changelogname"] != None:
            for (name, ctime, text) in zip(pkg["changelogname"],
                pkg["changelogtime"], pkg["changelogtext"]):
                clog = pkg_node.newChild(None, "changelog", None)
                clog.addContent(utf8String(text))
                clog.newProp("author", utf8String(name))
                clog.newProp("date", str(ctime))
        output = pkg_node.serialize("UTF-8", self.pretty)
        fd.write(output + "\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()

    def __parsePackage(self, reader):
        Readf = reader.Read
        NodeTypef = reader.NodeType
        Namef = reader.Name
        pkg = ReadRpm("repopkg")
        pkg.sig = HdrIndex()
        pkg.hdr = HdrIndex()
        pkg.setHdr()
        pkg.sig["size_in_sig"] = [0, ]
        while Readf() == 1:
            ntype = NodeTypef()
            if ntype == TYPE_END_ELEMENT:
                if Namef() == "package":
                    break
                continue
            if ntype != TYPE_ELEMENT:
                continue
            name = Namef()
            if name == "name":
                Readf()
                pkg["name"] = reader.Value()
            elif name == "arch":
                Readf()
                pkg["arch"] = reader.Value()
                if pkg["arch"] == "src":
                    pkg.issrc = 1
                else:
                    pkg["sourcerpm"] = ""
            elif name == "version":
                props = getProps(reader)
                pkg["version"] = props["ver"]
                pkg["release"] = props["rel"]
                pkg["epoch"] = [int(props["epoch"]), ]
            elif name == "location":
                props = getProps(reader)
                pkg.filename = self.filename + "/" + props["href"]
            elif name == "format":
                self.__parseFormat(reader, pkg)
            elif self.fast == 0:
                if name == "checksum":
                    props = getProps(reader)
                    if props["type"] == "md5":
                        Readf()
                        pkg.sig["md5"] = reader.Value()
                    elif props["type"] == "sha":
                        Readf()
                        pkg.sig["sha1header"] = reader.Value()
                    elif self.verbose > 4:
                        print "unknown checksum type"
                elif name == "size":
                    props = getProps(reader)
                    pkg.sig["size_in_sig"][0] += int(props.get("package", "0"))
                elif self.verbose > 4 and name not in ("summary",
                    "description", "packager", "url", "time"):
                    print "new package entry: %s" % name
        return pkg

    def __parseFilelist(self, reader):
        # Make local variables for heavy used functions to speed up this loop.
        Readf = reader.Read
        NodeTypef = reader.NodeType
        Namef = reader.Name
        Valuef = reader.Value
        filelist = []
        while Readf() == 1:
            if NodeTypef() != TYPE_ELEMENT or Namef() != "package":
                continue
            props = getProps(reader)
            pname = props.get("name", "no-name")
            arch = props.get("arch", "no-arch")
            (epoch, version, release) = ("", "", "")
            while Readf() == 1:
                ntype = NodeTypef()
                if ntype == TYPE_ELEMENT:
                    name = Namef()
                    if name == "file":
                        Readf()
                        filelist.append(Valuef())
                    elif name == "version":
                        props = getProps(reader)
                        epoch   = props["epoch"]
                        version = props["ver"]
                        release = props["rel"]
                    elif self.verbose > 4:
                        print "new filelist: %s" % name
                elif ntype == TYPE_END_ELEMENT:
                    if Namef() == "package":
                        break
                    continue
        nevra = "%s-%s:%s-%s.%s" % (pname, epoch, version, release, arch)
        if nevra in self.pkglist:
            pkg = self.pkglist[nevra]
            pkg["oldfilenames"] = filelist
            #(pkg["basenames"], pkg["dirindexes"], pkg["dirnames"]) = \
            #    genBasenames(filelist)

    def __generateFormat(self, node, pkg, formatns):
        node.newChild(formatns, "license", escape(pkg["license"]))
        node.newChild(formatns, "vendor", escape(pkg["vendor"]))
        node.newChild(formatns, "group", escape(pkg["group"][0]))
        node.newChild(formatns, "buildhost", escape(pkg["buildhost"]))
        node.newChild(formatns, "sourcerpm", escape(pkg["sourcerpm"]))
        tnode = node.newChild(formatns, "header-range", None)
        start = 96 + pkg.sigdatasize
        end = start + pkg.hdrdatasize
        tnode.newProp("start", str(start))
        tnode.newProp("end", str(end))
        provides = pkg.getProvides()
        if len(provides) > 0:
            self.__generateDeps(node, "provides", provides, formatns)
        conflicts = pkg.getConflicts()
        if len(conflicts) > 0:
            self.__generateDeps(node, "conflicts", conflicts, formatns)
        obsoletes = pkg.getObsoletes()
        if len(obsoletes) > 0:
            self.__generateDeps(node, "obsoletes", obsoletes, formatns)
        requires = pkg.getRequires()
        if len(requires) > 0:
            self.__generateDeps(node, "requires", requires, formatns)
        self.__generateFilelist(node, pkg)

    def __generateDeps(self, node, name, deps, formatns):
        dnode = node.newChild(formatns, name, None)
        deps = self.__filterDuplicateDeps(deps)
        for dep in deps:
            enode = dnode.newChild(formatns, "entry", None)
            enode.newProp("name", dep[0])
            if dep[1] != "":
                if (dep[1] & RPMSENSE_SENSEMASK) != 0:
                    enode.newProp("flags", flagmap[dep[1] & RPMSENSE_SENSEMASK])
            if dep[2] != "":
                (e, v, r) = evrSplit(dep[2])
                enode.newProp("epoch", e)
                enode.newProp("ver", v)
                if r != "":
                    enode.newProp("rel", r)
            if dep[1] != "" and name == "requires":
                #if isLegacyPreReq(dep[1]) or isInstallPreReq(dep[1]):
                if (dep[1] & RPMSENSE_PREREQ) != 0:
                    enode.newProp("pre", "1")

    def __generateFilelist(self, node, pkg, filter2=1):
        files = pkg.getFilenames()
        fileflags = pkg["fileflags"]
        filemodes = pkg["filemodes"]
        if files == None or fileflags == None or filemodes == None:
            return
        (writefile, writedir, writeghost) = ([], [], [])
        for (fname, mode, flag) in zip(files, filemodes, fileflags):
            if S_ISDIR(mode):
                if not filter2 or dirrc.match(fname):
                    writedir.append(fname)
            elif not filter2 or filerc.match(fname):
                if flag & RPMFILE_GHOST:
                    writeghost.append(fname)
                else:
                    writefile.append(fname)
        writefile.sort()
        for f in writefile:
            tnode = node.newChild(None, "file", escape(f))
        writedir.sort()
        for f in writedir:
            tnode = node.newChild(None, "file", escape(f))
            tnode.newProp("type", "dir")
        writeghost.sort()
        for f in writeghost:
            tnode = node.newChild(None, "file", escape(f))
            tnode.newProp("type", "ghost")

    def __parseFormat(self, reader, pkg):
        filelist = []
        while reader.Read() == 1:
            ntype = reader.NodeType()
            if ntype == TYPE_END_ELEMENT:
                if reader.Name() == "format":
                    break
                continue
            if ntype != TYPE_ELEMENT:
                continue
            name = reader.Name()
            if name == "rpm:header-range":
                props = getProps(reader)
                header_start = int(props.get("start", "0"))
                header_end = int(props.get("end", "0"))
                pkg.sig["size_in_sig"][0] -= header_start
                pkg["rpm:header-range:end"] = header_end
            elif self.fast == 0:
                if name == "rpm:sourcerpm":
                    reader.Read()
                    pkg["sourcerpm"] = reader.Value()
                elif name == "rpm:provides":
                    (pkg["providename"], pkg["provideflags"],
                        pkg["provideversion"]) = self.__parseDeps(reader, name)
                elif name == "rpm:requires":
                    (pkg["requirename"], pkg["requireflags"],
                        pkg["requireversion"]) = self.__parseDeps(reader, name)
                elif name == "rpm:obsoletes":
                    (pkg["obsoletename"], pkg["obsoleteflags"],
                        pkg["obsoleteversion"]) = self.__parseDeps(reader, name)
                elif name == "rpm:conflicts":
                    (pkg["conflictname"], pkg["conflictflags"],
                        pkg["conflictversion"]) = self.__parseDeps(reader, name)
                elif name == "file":
                    reader.Read()
                    filelist.append(reader.Value())
                elif self.verbose > 4 and name not in ("rpm:vendor",
                    "rpm:buildhost", "rpm:group", "rpm:license"):
                    print "new repo entry: %s" % name
        pkg["oldfilenames"] = filelist
        #(pkg["basenames"], pkg["dirindexes"], pkg["dirnames"]) = \
        #    genBasenames(filelist)

    def __filterDuplicateDeps(self, deps):
        fdeps = []
        for (name, flags, version) in deps:
            flags &= RPMSENSE_SENSEMASK | RPMSENSE_PREREQ
            if (name, flags, version) not in fdeps:
                fdeps.append((name, flags, version))
        fdeps.sort()
        return fdeps

    def __parseDeps(self, reader, ename):
        Readf = reader.Read
        NodeTypef = reader.NodeType
        Namef = reader.Name
        plist = ([], [], [])
        while Readf() == 1:
            ntype = NodeTypef()
            if ntype == TYPE_END_ELEMENT:
                if Namef() == ename:
                    break
                continue
            if ntype != TYPE_ELEMENT:
                continue
            if Namef() == "rpm:entry":
                props = getProps(reader)
                name  = props["name"]
                flags = flagmap[props.get("flags", "")]
                if "pre" in props:
                    flags |= RPMSENSE_PREREQ
                epoch = ""
                if "epoch" in props:
                    epoch = props["epoch"] + ":"
                ver = props.get("ver", "")
                rel = ""
                if "rel" in props:
                    rel = "-" + props["rel"]
                plist[0].append(name)
                plist[1].append(flags)
                plist[2].append("%s%s%s" % (epoch, ver, rel))
        return plist


def parseBoolean(s):
    lower = s.lower()
    if lower in ("yes", "true", "1", "on"):
        return 1
    return 0

class RpmCompsXML:

    def __init__(self, filename):
        self.filename = filename
        self.grouphash = {}
        self.grouphierarchyhash = {}

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def __str__(self):
        return str(self.grouphash)

    def read(self, filename):
        doc = libxml2.parseFile(filename)
        if doc == None:
            return 0
        root = doc.getRootElement()
        if root == None:
            return 0
        node = root.children
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "group" or node.name == "category":
                ret = self.__parseGroup(node.children)
                if not ret:
                    return 0
            elif node.name == "grouphierarchy":
                # We don't need grouphierarchies, so don't parse them ;)
                #ret = self.__parseGroupHierarchy(node.children)
                #if not ret:
                #    return 0
                ret = 1
            else:
                self.printErr("Unknown entry in comps.xml: %s" % node.name)
                return 0
            node = node.next
        return 0

    def getPackageNames(self, group):
        ret = self.__getPackageNames(group, ("mandatory", "default"))
        ret2 = []
        for r in ret:
            ret2.append(r[0])
            ret2.extend(r[1])
        return ret2

    def getOptionalPackageNames(self, group):
        return self.__getPackageNames(group, ("optional",))

    def getDefaultPackageNames(self, group):
        return self.__getPackageNames(group, ("default",))

    def getMandatoryPackageNames(self, group):
        return self.__getPackageNames(group, ("mandatory",))

    def __getPackageNames(self, group, typelist):
        ret = []
        if not self.grouphash.has_key(group):
            return ret
        if self.grouphash[group].has_key("packagelist"):
            pkglist = self.grouphash[group]["packagelist"]
            for pkgname in pkglist:
                for t in typelist:
                    if pkglist[pkgname][0] == t:
                        ret.append((pkgname, pkglist[pkgname][1]))
        if self.grouphash[group].has_key("grouplist"):
            grplist = self.grouphash[group]["grouplist"]
            for grpname in grplist["groupreqs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
            for grpname in grplist["metapkgs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
        # Sort and duplicate removal
        ret.sort()
        for i in xrange(len(ret) - 2, -1, -1):
            if ret[i + 1] == ret[i]:
                ret.pop(i + 1)
        return ret

    def __parseGroup(self, node):
        group = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "name":
                lang = node.prop("lang")
                if lang:
                    group["name:" + lang] = node.content
                else:
                    group["name"] = node.content
            elif node.name == "id":
                group["id"] = node.content
            elif node.name == "description":
                lang = node.prop("lang")
                if lang:
                    group["description:" + lang] = node.content
                else:
                    group["description"] = node.content
            elif node.name == "default":
                group["default"] = parseBoolean(node.content)
            elif node.name == "langonly":
                group["langonly"] = node.content
            elif node.name == "packagelist":
                group["packagelist"] = self.__parsePackageList(node.children)
            elif node.name == "grouplist":
                group["grouplist"] = self.__parseGroupList(node.children)
            node = node.next
        self.grouphash[group["id"]] = group
        return 1

    def __parsePackageList(self, node):
        plist = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "packagereq":
                ptype = node.prop("type")
                if ptype == None:
                    ptype = "default"
                requires = node.prop("requires")
                if requires != None:
                    requires = requires.split()
                else:
                    requires = []
                plist[node.content] = (ptype, requires)
            node = node.next
        return plist

    def __parseGroupList(self, node):
        glist = {}
        glist["groupreqs"] = []
        glist["metapkgs"] = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "groupreq" or node.name == "groupid":
                glist["groupreqs"].append(node.content)
            elif node.name == "metapkg":
                gtype = node.prop("type")
                if gtype == None:
                    gtype = "default"
                glist["metapkgs"][node.content] = gtype
            node = node.next
        return glist



def getVars(releasever, arch, basearch):
    replacevars = {}
    replacevars["$releasever"] = releasever
    replacevars["$RELEASEVER"] = releasever
    replacevars["$arch"] = arch
    replacevars["$ARCH"] = arch
    replacevars["$basearch"] = basearch
    replacevars["$BASEARCH"] = basearch
    for i in xrange(10):
        key = "YUM%d" % i
        value = os.environ.get(key)
        if value != None:
            replacevars[key.lower()] = value
            replacevars[key] = value
    return replacevars

def replaceVars(line, data):
    for (key, value) in data.iteritems():
        line = line.replace(key, value)
    return line


MainVarnames = ("cachedir", "keepcache", "reposdir", "debuglevel",
        "errorlevel", "logfile", "gpgcheck", "assumeyes", "alwaysprompt",
        "tolerant", "exclude", "exactarch", "installonlypkgs",
        "kernelpkgnames", "showdupesfromrepos", "obsoletes",
        "overwrite_groups", "enable_group_conditionals", "installroot",
        "rss-filename", "distroverpkg",
        "diskspacecheck", "tsflags", "recent", "retries", "keepalive",
        "timeout", "http_caching", "throttle", "bandwidth", "commands",
        "proxy", "proxy_username", "proxy_password", "pkgpolicy",
        "plugins", "pluginpath", "pluginconfpath", "metadata_expire")
RepoVarnames = ("name", "baseurl", "mirrorlist", "enabled", "gpgcheck",
        "gpgkey", "exclude", "includepkgs", "enablegroups", "failovermethod",
        "keepalive", "timeout", "http_caching", "retries", "throttle",
        "bandwidth", "metadata_expire", "proxy", "proxy_username",
        "proxy_password")

def YumConf(verbose, buildroot="", filename="/etc/yum.conf",
    reposdirs=[]): # pylint: disable-msg=W0102
    import glob
    data = {}
    ret = YumConf2(filename, verbose, data)
    if ret != None:
        raise ValueError, "could not read line %d in %s" % (ret, filename)
    k = data.get("main", {}).get("reposdir")
    if k != None:
        reposdirs = k.split(" \t,;")
    for reposdir in reposdirs:
        for filename in glob.glob(buildroot + reposdir + "/*.repo"):
            ret = YumConf2(filename, verbose, data)
            if ret != None:
                raise ValueError, "could not read line %d in %s" % (ret,
                    filename)
    return data

def YumConf2(filename, verbose, data):
    lines = []
    if os.path.isfile(filename) and os.access(filename, os.R_OK):
        if verbose > 2:
            print "Reading in config file %s." % filename
        lines = open(filename, "r").readlines()
    stanza = "main"
    prevcommand = None
    for linenum in xrange(len(lines)):
        line = lines[linenum].rstrip("\n\r")
        if line[:1] == "[" and line.find("]") != -1:
            stanza = line[1:line.find("]")]
            prevcommand = None
        elif prevcommand and line[:1] in " \t":
            # continuation line
            line = line.strip()
            if line and line[:1] not in "#;":
                data[stanza][prevcommand].append(line)
        else:
            line = line.strip()
            if line[:1] in "#;" or not line:
                pass # comment line
            elif line.find("=") != -1:
                (key, value) = line.split("=", 1)
                (key, value) = (key.strip(), value.strip())
                if stanza == "main":
                    if key not in MainVarnames:
                        return linenum + 1 # unknown key value
                elif key not in RepoVarnames:
                    return linenum + 1 # unknown key value
                prevcommand = None
                if key in ("baseurl", "mirrorlist"):
                    value = [value]
                    prevcommand = key
                data.setdefault(stanza, {})[key] = value
            else:
                return linenum + 1 # not parsable line
    return None

def readYumConf(configfiles, reposdirs, verbose, buildroot, rpmdbpath,
    distroverpkg, releasever):
    yumconfs = []
    for c in configfiles:
        yumconfs.append(YumConf(verbose, buildroot, c, reposdirs))
    if yumconfs and yumconfs[0].get("main", {}).get("distroverpkg") != None:
        distroverpkg = yumconfs[0].get("main", {}).get("distroverpkg")
        distroverpkg = distroverpkg.split(",")
    if yumconfs and not releasever:
        releasever = readReleaseVer(distroverpkg, buildroot, rpmdbpath)
    return (yumconfs, distroverpkg, releasever)


def readMirrorlist(mirrorlist, replacevars, key, verbose):
    baseurls = []
    for mlist in mirrorlist:
        mlist = replaceVars(mlist, replacevars)
        if verbose > 2:
            print "Getting mirrorlist from %s." % mlist
        fname = cacheLocal([mlist], "mirrorlist", key,
            verbose, nofilename=1)
        if not fname:
            continue
        for l in open(fname).readlines():
            l = l.strip()
            l = l.replace("$ARCH", "$basearch")
            if l and l[0] != "#":
                baseurls.append(l)
    return baseurls

def readRepos(yumconfs, releasever, arch, readdebug,
    readsrc, verbose, readgroupfile=0, fast=1):
    global urloptions # pylint: disable-msg=W0603
    basearch = buildarchtranslate.get(arch, arch)
    repos = []
    for yumconf in yumconfs:
        for key in yumconf.iterkeys():
            if key == "main":
                continue
            sec = yumconf[key]
            if sec.get("enabled") == "0":
                continue
            urloptions = setOptions(yumconf, key)
            baseurls = sec.get("baseurl", [])
            replacevars = getVars(releasever, arch, basearch)
            excludes = yumconf.get("main", {}).get("exclude", "")
            excludes += " " + sec.get("exclude", "")
            excludes = replaceVars(excludes, replacevars)
            # If we have mirrorlist grab it, read it and add the extended
            # lines to our baseurls, just like yum does.
            if "mirrorlist" in sec:
                mirrorlist = sec["mirrorlist"]
                baseurls.extend(readMirrorlist(mirrorlist, replacevars, key,
                    verbose))
            if not baseurls:
                print "%s:" % key, "No url for this section in conf file."
                urloptions = setOptions()
                return None
            for i in xrange(len(baseurls)):
                baseurls[i] = replaceVars(baseurls[i], replacevars)
            repo = RpmRepo(baseurls, excludes, verbose, key, readsrc, fast)
            if repo.read(readgroupfile=readgroupfile) == 0:
                print "Cannot read repo %s." % key
                urloptions = setOptions()
                return None
            if not readdebug:
                repo.delDebuginfo()
            repos.append(repo)
    urloptions = setOptions()
    return repos


def testMirrors(verbose, args):
    # We are per default more verbose:
    verbose += 3
    urloptions["timeout"] = "20.0"
    if args:
        # python-only
        args = [ (a, "5", "i686", "i386") for a in args ]
        # python-only-end
        # pyrex-code
        #args2 = []
        #for a in args:
        #    args2.append((a, "5", "i686", "i386"))
        #args = args2
        # pyrex-code-end
    else:
        ml = "http://fedora.redhat.com/Download/mirrors/"
        args = [
            # FC-releases
            (ml + "fedora-core-$releasever", "4", "i686", "i386"),
            (ml + "fedora-core-$releasever", "5", "i686", "i386"),
            (ml + "fedora-core-debug-$releasever", "5", "i686", "i386"),
            (ml + "fedora-core-source-$releasever", "5", "i686", "i386"),
            (ml + "fedora-core-$releasever", "6", "i686", "i386"),
            (ml + "fedora-core-debug-$releasever", "6", "i686", "i386"),
            (ml + "fedora-core-source-$releasever", "6", "i686", "i386"),
            (ml + "fedora-core-rawhide", "7", "i686", "i386"),
            (ml + "fedora-core-rawhide-debug", "7", "i686", "i386"),
            (ml + "fedora-core-rawhide-source", "7", "i686", "i386"),
            # FC-updates
            (ml + "updates-released-fc$releasever", "4", "i686", "i386"),
            (ml + "updates-released-fc$releasever", "5", "i686", "i386"),
            (ml + "updates-released-debug-fc$releasever", "5", "i686", "i386"),
            (ml + "updates-released-source-fc$releasever", "5", "i686","i386"),
            (ml + "updates-released-fc$releasever", "6", "i686", "i386"),
            (ml + "updates-released-debug-fc$releasever", "6", "i686", "i386"),
            (ml + "updates-released-source-fc$releasever", "6", "i686","i386"),
            # FC-updates-testing
            (ml + "updates-testing-fc$releasever", "4", "i686", "i386"),
            (ml + "updates-testing-fc$releasever", "5", "i686", "i386"),
            (ml + "updates-testing-debug-fc$releasever", "5", "i686", "i386"),
            (ml + "updates-testing-source-fc$releasever", "5", "i686", "i386"),
            (ml + "updates-testing-fc$releasever", "6", "i686", "i386"),
            (ml + "updates-testing-debug-fc$releasever", "6", "i686", "i386"),
            (ml + "updates-testing-source-fc$releasever", "6", "i686", "i386"),
            # Fedora Extras
            (ml + "fedora-extras-$releasever", "4", "i686", "i386"),
            (ml + "fedora-extras-$releasever", "5", "i686", "i386"),
            (ml + "fedora-extras-debug-$releasever", "5", "i686", "i386"),
            (ml + "fedora-extras-source-$releasever", "5", "i686", "i386"),
            (ml + "fedora-extras-$releasever", "6", "i686", "i386"),
            (ml + "fedora-extras-debug-$releasever", "6", "i686", "i386"),
            (ml + "fedora-extras-source-$releasever", "6", "i686", "i386"),
            (ml + "fedora-extras-devel", "7", "i686", "i386"),
        ]
    for (mirrorlist, releasever, arch, basearch) in args:
        print "---------------------------------------"
        replacevars = getVars(releasever, arch, basearch)
        m = readMirrorlist([mirrorlist], replacevars, "testmirrors", verbose)
        #print m
        if verbose > 2:
            for reponame in m:
                reponame = replaceVars(reponame, replacevars)
                repo = RpmRepo([reponame], "", verbose, "testmirrors", 1, 1)
                if repo.read(1) == 0:
                    print "failed"
                else:
                    try:
                        print time.strftime("%Y/%m/%d", \
                         time.gmtime(int(repo.repomd["primary"]["timestamp"])))
                    except:
                        print "FAILED"


def writeFile(filename, data, mode=None):
    (fd, tmpfile) = mkstemp_file(pathdirname(filename), special=1)
    fd.write("".join(data))
    if mode != None:
        os.chmod(tmpfile, mode & 07777)
    os.rename(tmpfile, filename)


rootdir = "/home/devel/test"
hgfiles = rootdir + "/filecache"
grepodir = rootdir + "/git-data"
srepodir = rootdir + "/unpacked"
mirror = "/var/www/html/mirror/"
if not os.path.isdir(mirror):
    mirror = "/home/mirror/"
fedora = mirror + "fedora/"
rhelupdates = mirror + "updates-rhel/"
srpm_repos = [
    # Fedora Core
    #("Fedora Core development", "FC-development",
    # [fedora + "development/SRPMS"], None),
    #("Fedora Core 4", "FC4",
    # [fedora + "4/SRPMS", fedora + "updates/4/SRPMS",
    #  fedora + "updates/testing/4/SRPMS"], None),
    #("Fedora Core 3", "FC3",
    # [fedora + "3/SRPMS", fedora + "updates/3/SRPMS",
    #  fedora + "updates/testing/3/SRPMS"], None),
    #("Fedora Core 2", "FC2",
    # [fedora + "2/SRPMS", fedora + "updates/2/SRPMS",
    #  fedora + "updates/testing/2/SRPMS"], None),
    #("fedora Core 1", "FC1",
    # [fedora + "1/SRPMS", fedora + "updates/1/SRPMS",
    #  fedora + "updates/testing/1/SRPMS"], None),
    # Red Hat Enterprise Linux
    ("Red Hat Enterprise Linux 4", "RHEL4",
     [mirror + "rhel/4/en/os/i386/SRPMS", rhelupdates + "4"], None),
    ("Red Hat Enterprise Linux 3", "RHEL3",
     [mirror + "rhel/3/en/os/i386/SRPMS", rhelupdates + "3"], None),
    ("Red Hat Enterprise Linux 2.1", "RHEL2.1",
     [mirror + "rhel/2.1AS/en/os/i386/SRPMS", rhelupdates + "2.1"], None),
]

def getChangeLogFromRpm(pkg, oldpkg):
    """Try to list the changelog data from pkg which is newer if compared
    to oldpkg."""
    # This only works if an old pkg is available to compare against:
    if not oldpkg or not oldpkg["changelogtime"]:
        return (-1, None)
    # See if the end of the changelog data is the same, then we just
    # list the newer entries:
    oldlength = len(oldpkg["changelogtime"])
    if (pkg["changelogtime"][- oldlength:] == oldpkg["changelogtime"] and
        pkg["changelogname"][- oldlength:] == oldpkg["changelogname"] and
        pkg["changelogtext"][- oldlength:] == oldpkg["changelogtext"]):
        return (len(pkg["changelogtime"]) - oldlength, None)
    # Return the time of the first changelog entry in oldpkg:
    return (-1, oldpkg["changelogtime"][0])

def cmpNoMD5(a, b):
    """Ignore leading md5sum to sort the "sources" file."""
    return cmp(a[33:], b[33:])

def extractSrpm(pkg, pkgdir, filecache, repodir, oldpkg):
    pkgname = pkg["name"]
    files = pkg.getFilenames()
    i = pkg.getSpecfile(files)
    specfile = files[i]
    fullspecfile = "%s/%s" % (pkgdir, specfile)

    (changelognum, changelogtime) = getChangeLogFromRpm(pkg, oldpkg)
    if os.path.exists(fullspecfile): # os.access(fullspecfile, os.R_OK)
        checksum = getChecksum(fullspecfile)
        # same spec file in repo and in rpm: nothing to do
        if checksum == pkg["filemd5s"][i]:
            return
        # If we don't have the previous package anymore, but there is still
        # a specfile, read the time of the last changelog entry.
        if changelognum == -1 and changelogtime == None:
            l = open(fullspecfile, "r").readlines()
            while l:
                if l[0] == "%changelog\n":
                    l.pop(0)
                    break
                l.pop(0)
            if l:
                l = l[0].split()
            if l and l[0] == "*" and len(l) >= 5:
                try:
                    import calendar
                    changelogtime = time.strptime(" ".join(l[1:5]),
                        "%a %b %d %Y")
                    changelogtime = calendar.timegm(changelogtime)
                except:
                    pass
    os.system('rm -rf "%s"' % pkgdir)
    makeDirs(pkgdir)
    extractRpm(pkg, pkgdir + "/")
    for f in os.listdir(pkgdir):
        if f not in files and f not in ("Makefile", "sources"):
            fsrc = pkgdir + "/" + f
            os.unlink(fsrc)
            os.system("cd %s/.. && GIT_DIR=%s git-update-index "
                "--remove %s/%s" % (pkgdir, repodir, pkgname, f))
    if "sources" in files or "Makefile" in files:
        raise ValueError, \
            "src.rpm contains sources/Makefile: %s" % pkg.filename
    EXTRACT_SOURCE_FOR = ["MAKEDEV", "anaconda", "anaconda-help",
        "anaconda-product", "basesystem", "booty", "chkconfig",
        "device-mapper", "dmraid", "firstboot", "glibc-kernheaders", "hwdata",
        "initscripts", "kudzu", "mkinitrd",
        "pam_krb5", "passwd", "redhat-config-kickstart",
        "redhat-config-netboot", "redhat-config-network",
        "redhat-config-securitylevel", "redhat-logos", "redhat-release",
        "rhn-applet", "rhnlib", "rhpl",
        "sysklogd", "system-config-printer", "system-config-securitylevel",
        "tux", "udev"]
    if repodir.endswith("/RHEL2.1.git"):
        EXTRACT_SOURCE_FOR.remove("redhat-config-network")
    sources = []
    if filecache:
        for i in xrange(len(files)):
            f = files[i]
            if not S_ISREG(pkg["filemodes"][i]) or not isBinary(f):
                continue
            fsrc = pkgdir + "/" + f
            # should we use sha instead of md5:
            #md5data = getChecksum(fsrc, "sha")
            md5data = pkg["filemd5s"][i]
            fdir = "%s/%s" % (filecache, md5data[0:2])
            fname = "%s/%s.bin" % (fdir, md5data)
            if not os.path.exists(fname):
                makeDirs(fdir)
                doLnOrCopy(fsrc, fname)
            if pkg["name"] in EXTRACT_SOURCE_FOR:
                if fsrc.find(".tar") >= 0:
                    tempdir = "%s/e.tar" % pkgdir
                    os.mkdir(tempdir)
                    dirname = explodeFile(fsrc, tempdir, "0")
                    os.rename(dirname, "%s/tar" % pkgdir)
                    os.rmdir(tempdir)
            os.unlink(fsrc)
            sources.append("%s %s\n" % (md5data, f))
        sources.sort(cmpNoMD5)
    writeFile(pkgdir + "/sources", sources)
    writeFile(pkgdir + "/Makefile", [
        "include ../pyrpm/Makefile.srpm\n",
        "NAME:=%s\nSPECFILE:=%s\n" % (pkg["name"], specfile)])
    os.environ["GIT_DIR"] = repodir
    os.system("cd %s/.. && { find %s -type f -print | xargs git-update-index "
        "-q --add --refresh; }" % (pkgdir, pkgname))
    os.system('cd %s/.. && { for file in $(git-ls-files); do [ ! -f "$file" ]'
        ' &&  git-update-index --remove "$file"; done; }' % pkgdir)
    del os.environ["GIT_DIR"]
    # Add changelog text:
    (fd, tmpfile) = mkstemp_file(tmpdir, special=1)
    fd.write("update to %s" % pkg.getNVR())
    if oldpkg:
        fd.write(" (from %s-%s)" % (oldpkg["version"], oldpkg["release"]))
    if changelognum != -1 or changelogtime != None:
        fd.write("\n" + pkg.getChangeLog(changelognum, changelogtime))
    fd.write("\n")
    fd.close()
    # python-only
    del fd
    # python-only-end
    changelog = "-F " + tmpfile
    # Add a user name and email:
    user = "cvs@devel.redhat.com"
    email = user
    if pkg["changelogname"]:
        user = pkg["changelogname"][0]
        if user.rfind("> ") != -1:
            user = user[:user.rfind("> ") + 1]
        email = user
        if email.find("<") != -1:
            email = email[email.find("<") + 1:email.rfind(">") + 1]
        if user.rfind(" <") != -1:
            user = user[:user.rfind(" <")]
    # XXX if we monitor trees, we could change the checkin time to
    # first day of release of the rpm package instead of rpm buildtime
    buildtime = str(pkg.hdr.getOne("buildtime"))
    os.system("cd " + repodir + " && GIT_AUTHOR_NAME=\"" + user + \
        "\" GIT_AUTHOR_EMAIL=\"" + email + "\" GIT_AUTHOR_DATE=" + \
        buildtime + " GIT_COMMITTER_NAME=\"" + user + \
        "\" GIT_COMMITTER_EMAIL=\"" + email + "\" GIT_COMMITTER_DATE=" + \
        buildtime + " GIT_DIR=" + repodir + " git commit " + changelog)
    if tmpfile != None:
        os.unlink(tmpfile)

def cmpByTime(a, b):
    return cmp(a["buildtime"][0], b["buildtime"][0])

def createMercurial(verbose):
    if not os.path.isdir(grepodir) or not os.path.isdir(hgfiles):
        print "Error: Paths for mercurial not setup. " + grepodir \
            + " " + hgfiles
        return
    # Create and initialize repos if still missing.
    for (repodescr, reponame, dirs, filecache) in srpm_repos:
        repodir = grepodir + "/" + reponame + ".git"
        unpackdir = srepodir + "/" + reponame
        if not dirs or not os.path.isdir(dirs[0]):
            continue
        if verbose > 2:
            print repodescr
        if os.path.isdir(repodir):
            firsttime = 0
        else:
            firsttime = 1
            makeDirs(repodir)
            os.system("cd %s && { GIT_DIR=%s git init-db; }" % \
                (repodir, repodir))
            writeFile(repodir + "/description", [repodescr + "\n"])
        if not filecache:
            filecache = hgfiles + "/" + reponame
        makeDirs(unpackdir)
        makeDirs(filecache)
        pkgs = []
        for d in dirs:
            pkgs.extend(findRpms(d))
        pkgs = readRpm(pkgs, rpmsigtag, rpmtag)
        if firsttime:
            pkgs.sort(cmpByTime)
        else:
            pkgs = getPkgsNewest(pkgs)
        oldpkgs = {}
        for pkg in pkgs:
            pkgname = pkg["name"]
            pkgdir = unpackdir + "/" + pkgname
            extractSrpm(pkg, pkgdir, filecache, repodir, oldpkgs.get(pkgname))
            oldpkgs[pkgname] = pkg
        os.system("cd %s && { GIT_DIR=%s git repack -d; GIT_DIR=%s git "
            "prune-packed; }" % (unpackdir, repodir, repodir))


def checkDeps(rpms, checkfileconflicts, runorderer, verbose=0):
    # Calling .sort() below does take a little/tiny bit of time, but has the
    # advantage of a deterministic order as well as having errors output in
    # sorted order, so they are easier to read.
    # Add all packages in.
    if verbose > 3:
        time1 = time.clock()
    resolver = RpmResolver(rpms, checkfileconflicts)
    if verbose > 3:
        time2 = time.clock()
        print "- Needed", time2 - time1, "sec for RpmResolver()."
        time1 = time.clock()
    # Check for obsoletes.
    deps = resolver.obsoletes_list.keys()
    deps.sort()
    for (name, flag, version) in deps:
        orpms = resolver.obsoletes_list[(name, flag, version)]
        for pkg in resolver.searchDependency(name, flag, version):
            for rpm in orpms:
                if rpm.getNEVR0() == pkg.getNEVR0():
                    continue
                if rpm["name"] == name or not pkg in resolver.rpms:
                    continue
                print "Warning:", pkg.getFilename(), "is obsoleted by", \
                    rpm.getFilename()
                resolver.removePkg(pkg)
    # Check all conflicts.
    conflicts = []
    deps = resolver.conflicts_list.keys()
    deps.sort()
    for (name, flag, version) in deps:
        orpms = resolver.conflicts_list[(name, flag, version)]
        for pkg in resolver.searchDependency(name, flag, version):
            for rpm in orpms:
                if rpm.getNEVR0() == pkg.getNEVR0():
                    continue
                print "Warning:", rpm.getFilename(), \
                    "contains a conflict with", pkg.getFilename()
                conflicts.append((rpm, pkg))
                conflicts.append((pkg, rpm))
    # Check all requires.
    deps = resolver.requires_list.keys()
    deps.sort()
    for (name, flag, version) in deps:
        if name[:7] == "rpmlib(":
            continue
        if not resolver.searchDependency(name, flag, version):
            for rpm in resolver.requires_list[(name, flag, version)]:
                print "Warning:", rpm.getFilename(), \
                    "did not find a package for:", \
                    depString(name, flag, version)
    if verbose > 3:
        time2 = time.clock()
        print "- Needed", time2 - time1, "sec for conflicts/requires/obsoletes."
        time1 = time.clock()
    # Check for fileconflicts.
    if checkfileconflicts:
        dirnames = resolver.filenames_list.path.keys()
        dirnames.sort()
        for dirname in dirnames:
            pathdirname2 = resolver.filenames_list.path[dirname]
            basenames = pathdirname2.keys()
            basenames.sort()
            for basename in basenames:
                s = pathdirname2[basename]
                if len(s) < 2:
                    continue
                # We could also only check with the next entry and then
                # report one errror for a filename with all rpms listed.
                for j in xrange(len(s) - 1):
                    (rpm1, i1) = s[j]
                    filemodesi1 = rpm1["filemodes"][i1]
                    filemd5si1 = rpm1["filemd5s"][i1]
                    filecolorsi1 = None
                    if rpm1["filecolors"]:
                        filecolorsi1 = rpm1["filecolors"][i1]
                    for k in xrange(j + 1, len(s)):
                        (rpm2, i2) = s[k]
                        filemodesi2 = rpm2["filemodes"][i2]
                        # No fileconflict if mode/md5sum/user/group match.
                        if (filemd5si1 == rpm2["filemd5s"][i2] and
                            filemodesi1 == filemodesi2
                            and rpm1["fileusername"][i1] ==
                                rpm2["fileusername"][i2]
                            and rpm1["filegroupname"][i1] ==
                                rpm2["filegroupname"][i2]):
                            continue
                        # No fileconflict for multilib elf32/elf64 files.
                        if filecolorsi1 and rpm2["filecolors"]:
                            filecolorsi2 = rpm2["filecolors"][i2]
                            if filecolorsi2 and filecolorsi1 != filecolorsi2:
                                continue
                        # Mention which fileconflicts also have a real
                        # Conflicts: dependency within the packages:
                        kn = ""
                        if (rpm1, rpm2) in conflicts:
                            kn = "(known)"
                        print "fileconflict for", dirname + basename, "in", \
                            rpm1.getFilename(), "and", rpm2.getFilename(), kn
        if verbose > 3:
            time2 = time.clock()
            print "- Needed", time2 - time1, "sec for fileconflicts."
            time1 = time.clock()
    # Order rpms on how they get installed.
    if runorderer:
        orderer = RpmOrderer(resolver.rpms, {}, {}, [], resolver)
        operations = orderer.order()
        if operations == None:
            raise
        if verbose > 3:
            time2 = time.clock()
            print "- Needed", time2 - time1, "sec for rpm ordering."
            time1 = time.clock()
        #print operations


def checkRepo(rpms):
    """Check if all src.rpms are included and does each -devel rpm have
    a corresponding normal rpm of the same arch."""
    f = {}
    h = {}
    srcrpms = {}
    for rpm in rpms:
        h[(rpm["name"], rpm.getArch())] = 1
        if rpm.issrc:
            srcrpms[rpm.getFilename()] = 0
            f.setdefault(rpm["name"], []).append(rpm)
    for rpm in rpms:
        if rpm.issrc:
            continue
        if rpm["name"].endswith("-devel"):
            if not h.get((rpm["name"][:-6], rpm.getArch())):
                print rpm.getFilename(), "only has a -devel subrpm"
        if srcrpms.get(rpm["sourcerpm"]) == None:
            print rpm.getFilename(), "does not have a src.rpm", rpm["sourcerpm"]
        else:
            srcrpms[rpm["sourcerpm"]] += 1
    for (rpm, value) in srcrpms.iteritems():
        if value == 0:
            print rpm, "only has a src.rpm"
    for (name, rpms) in f.iteritems():
        if len(rpms) > 1:
            print name, "has more than one src.rpm with the same name"


def verifyStructure(verbose, packages, phash, tag, useidx=1):
    # Verify that all data is also present in /var/lib/rpm/Packages.
    for (tid, mytag) in phash.iteritems():
        if tid not in packages:
            print "Error %s: Package id %s doesn't exist" % (tag, tid)
            if verbose > 2:
                print tag, mytag
            continue
        if tag == "dirindexes" and packages[tid]["dirindexes2"] != None:
            pkgtag = packages[tid]["dirindexes2"]
        elif tag == "dirnames" and packages[tid]["dirnames2"] != None:
            pkgtag = packages[tid]["dirnames2"]
        elif tag == "basenames" and packages[tid]["basenames2"] != None:
            pkgtag = packages[tid]["basenames2"]
        else:
            pkgtag = packages[tid][tag]
        for (idx, mytagidx) in mytag.iteritems():
            if useidx:
                try:
                    val = pkgtag[idx]
                except IndexError:
                    print "Error %s: index %s is not in package" % (tag, idx)
                    if verbose > 2:
                        print mytagidx
            else:
                if idx != 0:
                    print "Error %s: index %s out of range" % (tag, idx)
                val = pkgtag
            if mytagidx != val:
                print "Error %s: %s != %s in package %s" % (tag, mytagidx,
                    val, packages[tid].getFilename())
    # Go through /var/lib/rpm/Packages and check if data is correctly
    # copied over to the other files.
    for (tid, pkg) in packages.iteritems():
        if tag == "dirindexes" and pkg["dirindexes2"] != None:
            refhash = pkg["dirindexes2"]
        elif tag == "dirnames" and pkg["dirnames2"] != None:
            refhash = pkg["dirnames2"]
        elif tag == "basenames" and pkg["basenames2"] != None:
            refhash = pkg["basenames2"]
        else:
            refhash = pkg[tag]
        if not refhash:
            continue
        phashtid = None
        if tid in phash:
            phashtid = phash[tid]
        if not useidx:
            # Single entry with data:
            if phashtid != None and refhash != phashtid[0]:
                print "wrong data in packages for", pkg["name"], tid, tag
            elif phashtid == None:
                print "no data in packages for", pkg["name"], tid, tag
                if verbose > 2:
                    print "refhash:", refhash
            continue
        tnamehash = {}
        for idx in xrange(len(refhash)):
            key = refhash[idx]
            # Only one group entry is copied over.
            if tag == "group" and idx > 0:
                continue
            # requirename only stored if not InstallPreReq
            if tag == "requirename":
                if isInstallPreReq(pkg["requireflags"][idx]):
                    continue
            # only include filemd5s for regular files (and ignore
            # files with size 0 as broken kernels can generate then
            # rpm packages with missing md5sum files for size==0).
            if tag == "filemd5s" and (not S_ISREG(pkg["filemodes"][idx]) or
                (key == "" and pkg["filesizes"][idx] == 0)):
                continue
            # We only need to store triggernames once per package.
            if tag == "triggername":
                if key in tnamehash:
                    continue
                tnamehash[key] = 1
            # Real check for the actual data:
            try:
                if phashtid[idx] != key:
                    print "wrong data"
            except IndexError:
                print "Error %s: index %s is not in package %s" % (tag,
                    idx, tid)
                if verbose > 2:
                    print key, phashtid

def readPackages(buildroot, rpmdbpath, verbose, keepdata=1, hdrtags=None):
    import bsddb
    if hdrtags == None:
        hdrtags = rpmdbtag
    packages = {}
    pkgdata = {}
    keyring = None #openpgp.PGPKeyRing()
    maxtid = 0
    # Read the db4/hash file to determine byte order / endianness
    # as well as maybe host order:
    swapendian = ""
    data = open(buildroot + rpmdbpath + "Packages", "rb").read(16)
    if len(data) == 16:
        if unpack("=I", data[12:16])[0] == 0x00061561:
            if verbose > 4:
                print "Checking rpmdb with same endian order."
        else:
            if pack("=H", 0xdead) == "\xde\xad":
                swapendian = "<"
                if verbose:
                    print "Big-endian machine reading little-endian rpmdb."
            else:
                swapendian = ">"
                if verbose:
                    print "Little-endian machine reading big-endian rpmdb."
    db = bsddb.hashopen(buildroot + rpmdbpath + "Packages", "r")
    try:
        (tid, data) = db.first()
    except:
        return (packages, keyring, maxtid, pkgdata, swapendian)
    while 1:
        tid = unpack("%sI" % swapendian, tid)[0]
        if tid == 0:
            maxtid = unpack("%sI" % swapendian, data)[0]
        else:
            fd = StringIO(data)
            pkg = ReadRpm("rpmdb", fd=fd)
            pkg.readHeader(None, hdrtags, keepdata, 1)
            if pkg["name"] == "gpg-pubkey":
                #for k in openpgp.parsePGPKeys(pkg["description"]):
                #    keyring.addKey(k)
                pkg["group"] = (pkg["group"],)
            packages[tid] = pkg
            if keepdata:
                pkgdata[tid] = data
        try:
            (tid, data) = db.next()
        except:
            break
    return (packages, keyring, maxtid, pkgdata, swapendian)

def readDb(swapendian, filename, dbtype="hash", dotid=None):
    import bsddb
    if dbtype == "hash":
        db = bsddb.hashopen(filename, "r")
    else:
        db = bsddb.btopen(filename, "r")
    rethash = {}
    try:
        (k, v) = db.first()
    except:
        return rethash
    while 1:
        if dotid:
            k = unpack("%sI" % swapendian, k)[0]
        if k == "\x00":
            k = ""
        for i in xrange(0, len(v), 8):
            (tid, idx) = unpack("%s2I" % swapendian, v[i:i + 8])
            rethash.setdefault(tid, {})
            if idx in rethash[tid]:
                print "ignoring duplicate idx: %s %d %d" % (k, tid, idx)
                continue
            rethash[tid][idx] = k
        try:
            (k, v) = db.next()
        except:
            break
    return rethash

def diffFmt(fmt1, fmt2, fmt3, fmt4):
    print "diff between rpmdb header and new header:"
    if fmt1 != fmt2:
        print "fmt1/fmt2 differ"
    if len(fmt1) != len(fmt2):
        print "length: fmt1:", len(fmt1), "fmt2:", len(fmt2)
    # So this does not output additional entries beyond min():
    l = min(len(fmt1), len(fmt2))
    for i in xrange(0, l, 16):
        (tag1, ttype1, offset1, count1) = unpack("!4I", fmt1[i:i + 16])
        (tag2, ttype2, offset2, count2) = unpack("!4I", fmt2[i:i + 16])
        if tag1 != tag2 or ttype1 != ttype2 or offset1 != offset2 or \
            count1 != count2:
            print "tag:", tag1, tag2, i
            if ttype1 != ttype2:
                print "type:", ttype1, ttype2
            if offset1 != offset2:
                print "offset:", offset1, offset2
            if count1 != count2:
                print "count:", count1, count2
    if fmt3 != fmt4:
        print "fmt3/fmt4 differ"
    if len(fmt3) != len(fmt4):
        print "length: fmt3:", len(fmt3), "fmt4:", len(fmt4)

def writeRpmdb(pkg):
    rpmversion = pkg["rpmversion"]
    if rpmversion and rpmversion[:3] not in ("4.0", "3.0", "2.2"):
        install_keys["archivesize"] = 1
    region = "immutable"
    if pkg["immutable"] == None:
        region = "immutable1"
        install_keys["providename"] = 1
        install_keys["provideflags"] = 1
        install_keys["provideversion"] = 1
        install_keys["dirindexes"] = 1
        install_keys["dirnames"] = 1
        install_keys["basenames"] = 1
    (indexNo, storeSize, fmt, fmt2) = writeHeader(pkg, pkg.hdr.hash, rpmdbtag,
        region, {}, 1, pkg.rpmgroup)
    if rpmversion and rpmversion[:3] not in ("4.0", "3.0", "2.2"):
        del install_keys["archivesize"]
    if pkg["immutable"] == None:
        del install_keys["providename"]
        del install_keys["provideflags"]
        del install_keys["provideversion"]
        del install_keys["dirindexes"]
        del install_keys["dirnames"]
        del install_keys["basenames"]
    return (indexNo, storeSize, fmt, fmt2)

def readRpmdb(rpmdbpath, distroverpkg, releasever, configfiles, buildroot,
    arch, archlist, specifyarch, verbose, checkfileconflicts, reposdirs):
    from binascii import b2a_hex
    (yumconfs, distroverpkg, releasever) = readYumConf(configfiles, reposdirs,
        verbose, buildroot, rpmdbpath, distroverpkg, releasever)
    # Read rpmdb:
    if verbose:
        print "Reading rpmdb, this can take some time..."
        print "Reading %sPackages..." % rpmdbpath
        if verbose > 2:
            time1 = time.clock()
    (packages, keyring, maxtid, pkgdata, swapendian) = readPackages(buildroot,
        rpmdbpath, verbose)
    if verbose:
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to read Packages", \
                "(%d rpm packages)." % len(packages.keys())
        print "Reading the other files in %s..." % rpmdbpath
        if verbose > 2:
            time1 = time.clock()
    # Read other rpmdb files:
    if verbose and sys.version_info < (2, 3):
        print "If you use python-2.2 you can get the harmless output:", \
            "'Python bsddb: close errno 13 in dealloc'."
    basenames = readDb(swapendian, rpmdbpath + "Basenames")
    conflictname = readDb(swapendian, rpmdbpath + "Conflictname")
    dirnames = readDb(swapendian, rpmdbpath + "Dirnames", "bt")
    filemd5s = readDb(swapendian, rpmdbpath + "Filemd5s")
    group = readDb(swapendian, rpmdbpath + "Group")
    installtid = readDb(swapendian, rpmdbpath + "Installtid", "bt", 1)
    name = readDb(swapendian, rpmdbpath + "Name")
    providename = readDb(swapendian, rpmdbpath + "Providename")
    provideversion = readDb(swapendian, rpmdbpath + "Provideversion", "bt")
    # We make "Pubkeys" optional since also pyrpmrebuilddb does not write
    # it again:
    if not os.access(rpmdbpath + "Pubkeys", os.R_OK):
        if verbose:
            print "Did not any Pubkey db file."
    else:
        #pubkeys =
        readDb(swapendian, rpmdbpath + "Pubkeys")
    requirename = readDb(swapendian, rpmdbpath + "Requirename")
    requireversion = readDb(swapendian, rpmdbpath + "Requireversion", "bt")
    sha1header = readDb(swapendian, rpmdbpath + "Sha1header")
    sigmd5 = readDb(swapendian, rpmdbpath + "Sigmd5")
    triggername = readDb(swapendian, rpmdbpath + "Triggername")
    if verbose:
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to read the other files."
        print "Checking data integrity..."
        if verbose > 2:
            time1 = time.clock()
    # Checking data integrity of the rpmdb:
    for tid in packages.iterkeys():
        if tid > maxtid:
            print "wrong tid:", tid
    verifyStructure(verbose, packages, basenames, "basenames")
    verifyStructure(verbose, packages, conflictname, "conflictname")
    verifyStructure(verbose, packages, dirnames, "dirnames")
    for x in filemd5s.itervalues():
        for y in x.iterkeys():
            x[y] = b2a_hex(x[y])
    verifyStructure(verbose, packages, filemd5s, "filemd5s")
    verifyStructure(verbose, packages, group, "group")
    verifyStructure(verbose, packages, installtid, "installtid")
    verifyStructure(verbose, packages, name, "name", 0)
    verifyStructure(verbose, packages, providename, "providename")
    verifyStructure(verbose, packages, provideversion, "provideversion")
    #verifyStructure(verbose, packages, pubkeys, "pubkeys")
    verifyStructure(verbose, packages, requirename, "requirename")
    verifyStructure(verbose, packages, requireversion, "requireversion")
    verifyStructure(verbose, packages, sha1header, "install_sha1header", 0)
    verifyStructure(verbose, packages, sigmd5, "install_md5", 0)
    verifyStructure(verbose, packages, triggername, "triggername")
    arch_hash = setMachineDistance(arch, archlist)
    checkdupes = {}
    checkevr = {}
    # Find out "arch" and set "checkdupes".
    for pkg in packages.itervalues():
        if (not specifyarch and rpmdbpath != "/var/lib/rpm/" and
            pkg["name"] in kernelpkgs):
            # This would apply if we e.g. go from i686 -> x86_64, but
            # would also go from i686 -> s390 if such a kernel would
            # accidentally be installed. Good enough for the normal case.
            if arch_hash.get(pkg["arch"]) == None:
                arch = pkg["arch"]
                arch_hash = setMachineDistance(arch)
                print "Change 'arch' setting to be:", arch
        # XXX This only checks the name, not the "Provides:":
        if (yumconfs and pkg["name"] in distroverpkg and
            pkg["version"] != releasever):
            print "releasever could also be", pkg["version"], "instead of", \
                releasever
        if not pkg.isInstallonly():
            checkdupes.setdefault("%s.%s" % (pkg["name"], pkg["arch"]),
                []).append(pkg)
            checkevr.setdefault("%s" % pkg["name"], []).append(pkg)
    # Check "arch" and dupes:
    for pkg in packages.itervalues():
        if (pkg["name"] != "gpg-pubkey" and
            arch_hash.get(pkg["arch"]) == None):
            print "Warning: did not expect package with this arch: %s" % \
                pkg.getFilename()
        if (pkg["arch"] != "noarch" and
            "%s.noarch" % pkg["name"] in checkdupes):
            print "Warning: noarch and arch-dependent package installed:", \
                pkg.getFilename()
    for (pkg, value) in checkdupes.iteritems():
        if len(value) > 1:
            print "Warning: more than one package installed for %s." % pkg
    for (pkg, value) in checkevr.iteritems():
        if len(value) <= 1:
            continue
        p = value[0]
        evr = (p["epoch"], p["version"], p["release"])
        for q in value[1:]:
            if evr != (q["epoch"], q["version"], q["release"]):
                print p.getFilename(), "has different epoch/version/release", \
                    " than", q.getFilename()
    # Read in repositories to compare packages:
    if verbose > 2 and configfiles:
        time3 = time.clock()
    repos = readRepos(yumconfs, releasever, arch, 1, 0, verbose)
    if repos == None:
        return 1
    if verbose > 2 and configfiles:
        print "Needed", time.clock() - time3, "seconds to read the repos."
    for (tid, pkg) in packages.iteritems():
        if pkg["name"] == "gpg-pubkey":
            continue
        rpmversion = pkg["rpmversion"]
        # Check if we could write the rpmdb data again.
        (indexNo, storeSize, fmt, fmt2) = writeRpmdb(pkg)
        lead = pack("!2I", indexNo, storeSize)
        data = "".join([lead, fmt, fmt2])
        if len(data) % 4 != 0:
            print "rpmdb header is not aligned to 4"
        if data != pkgdata[tid]:
            print "writeRpmdb() would not write the same rpmdb data for", \
                pkg["name"], "(rpm-%s)" % rpmversion
            if verbose >= 3:
                diffFmt(pkg.hdrdata[3], fmt, pkg.hdrdata[4], fmt2)
        # Try to just copy the immutable region to verify the sha1.
        immutable = pkg.getImmutableRegion()
        if immutable:
            (indexNo, storeSize, fmt, fmt2) = immutable
        else:
            # If we cannot use the immutable region, try to write our own
            # header again.
            pkg.sig = HdrIndex()
            if pkg["archivesize"] != None:
                pkg.sig["payloadsize"] = pkg["archivesize"]
                if rpmversion and rpmversion[:3] not in ("4.0", "3.0", "2.2"):
                    del pkg["archivesize"]
            region = "immutable"
            if pkg["immutable1"] != None:
                region = "immutable1"
            (indexNo, storeSize, fmt, fmt2) = writeHeader(None, pkg.hdr.hash,
                rpmdbtag, region, install_keys, 0, pkg.rpmgroup)
        found = 0
        nevra = pkg.getNEVRA0()
        for r in repos:
            if nevra in r.pkglist:
                repopkg = r.pkglist[nevra]
                headerend = None
                if repopkg["rpm:header-range:end"]:
                    headerend = repopkg["rpm:header-range:end"]
                rpm = ReadRpm(repopkg.filename)
                if rpm.readHeader(rpmsigtag, rpmtag, 1, headerend=headerend):
                    print "Cannot read %s.\n" % repopkg.filename
                    continue
                rpm.closeFd()
                if rpm.hdrdata[3] != fmt or rpm.hdrdata[4] != fmt2:
                    print "Rpm %s in repo does not match." % repopkg.filename
                    continue
                found = 1
                # Use the rpm header to write again a rpmdb entry and compare
                # that again to the currently existing rpmdb header.
                # We should try to write some of these ourselves:
                for s in ("installtime", "filestates", "instprefixes",
                    "installcolor", "installtid"):
                    if pkg[s] != None:
                        rpm[s] = pkg[s]
                #rpm["installcolor"] = (getInstallColor(arch),)
                rpm.genRpmdbHeader()
                (_, _, fmta, fmta2) = writeRpmdb(rpm)
                if pkg.hdrdata[3] != fmta or pkg.hdrdata[4] != fmta2:
                    if verbose > 2:
                        print "Could not write a new rpmdb for %s." \
                            % repopkg.filename
                    if verbose >= 4:
                        diffFmt(pkg.hdrdata[3], fmta, pkg.hdrdata[4], fmta2)
                    continue
                break
        if found == 0 and configfiles:
            print "Warning: package not found in the repositories:", nevra
        # Verify the sha1 crc of the normal header data. (Signature
        # data does not have an extra crc.)
        sha1header = pkg["install_sha1header"]
        if sha1header == None:
            if verbose:
                print "Warning: package", pkg.getFilename(), \
                    "does not have a sha1 checksum."
            continue
        lead = pack("!8s2I", "\x8e\xad\xe8\x01\x00\x00\x00\x00",
            indexNo, storeSize)
        ctx = sha.new()
        ctx.update(lead)
        ctx.update(fmt)
        ctx.update(fmt2)
        if ctx.hexdigest() != sha1header:
            print pkg.getFilename(), \
                "bad sha1: %s / %s" % (sha1header, ctx.hexdigest())
    checkDeps(packages.values(), checkfileconflicts, 0)
    if verbose:
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to check the rpmdb data."
        print "Done with checkrpmdb."
    return None

def checkSrpms(ignoresymlinks):
    directories = [
        "/var/www/html/mirror/updates-rhel/2.1",
        "/var/www/html/mirror/updates-rhel/3",
        "/var/www/html/mirror/updates-rhel/4",
        "/mnt/hdb4/data/cAos/3.5/updates/SRPMS",
        "/home/mirror/centos/3.6/updates/SRPMS",
        "/mnt/hdb4/data/cAos/4.1/os/SRPMS",
        "/mnt/hdb4/data/cAos/4.1/updates/SRPMS",
        "/home/mirror/centos/4.2/os/SRPMS",
        "/home/mirror/centos/4.2/updates/SRPMS",
        "/home/mirror/scientific/SRPMS/vendor/errata",
        "/home/mirror/scientific/SRPMS/vendor/original",
        "/home/mirror/scientific/SRPMS"]
    for d in directories:
        if not os.path.isdir(d):
            continue
        rpms = findRpms(d, ignoresymlinks)
        rpms = readRpm(rpms, rpmsigtag, rpmtag)
        h = {}
        for rpm in rpms:
            h.setdefault(rpm["name"], []).append(rpm)
        for v in h.itervalues():
            v.sort(pkgCompare)
            for i in xrange(len(v) - 1):
                if (v[i].hdr.getOne("buildtime") >
                    v[i + 1].hdr.getOne("buildtime")):
                    print "buildtime inversion:", v[i].filename, \
                        v[i + 1].filename
    directories.append("/var/www/html/mirror/rhn/SRPMS")
    rpms = []
    for d in directories:
        if os.path.isdir(d):
            rpms.extend(findRpms(d, ignoresymlinks))
    rpms = readRpm(rpms, rpmsigtag, rpmtag)
    h = {}
    for rpm in rpms:
        h.setdefault(rpm["name"], []).append(rpm)
    for v in h.itervalues():
        v.sort(pkgCompare)
        i = 0
        while i < len(v) - 1:
            if pkgCompare(v[i], v[i + 1]) == 0:
                if not sameSrcRpm(v[i], v[i + 1]):
                    print "duplicate rpms:", v[i].filename, v[i + 1].filename
                v.remove(v[i])
            else:
                i += 1

def cmpA(h1, h2):
    return cmp(h1[0], h2[0])

def checkArch(path, ignoresymlinks):
    print "Mark the arch where a src.rpm would not get built:\n"
    arch = ["i386", "x86_64", "ia64", "ppc", "s390", "s390x"]
    rpms = findRpms(path, ignoresymlinks)
    rpms = readRpm(rpms, rpmsigtag, rpmtag)
    # Only look at the newest src.rpms.
    h = {}
    for rpm in rpms:
        h.setdefault(rpm["name"], []).append(rpm)
    rpmnames = h.keys()
    rpmnames.sort()
    for r in rpmnames:
        h[r] = [selectNewestRpm(h[r], {}, 0)]
    # Print table of archs to look at.
    for i in xrange(len(arch) + 2):
        s = ""
        for a in arch:
            if len(a) > i:
                s = "%s%s " % (s, a[i])
            else:
                s = s + "  "
        print "%29s  %s" % ("", s)
    showrpms = []
    for rp in rpmnames:
        srpm = h[rp][0]
        builds = {}
        showit = 0
        n = 1
        nn = 0
        for a in arch:
            if srpm.buildOnArch(a):
                builds[a] = 1
                nn += n
            else:
                builds[a] = 0
                showit = 1
            n = n + n
        if showit:
            showrpms.append((nn, builds, srpm))
    showrpms.sort(cmpA)
    for (_, builds, srpm) in showrpms:
        s = ""
        for a in arch:
            if builds[a] == 1:
                s = "%s  " % s
            else:
                s = "%sx " % s
        print "%29s  %s" % (srpm["name"], s)

def checkSymlinks(repo):
    """Check for dangling symlinks."""
    allfiles = {}
    goodlinks = {}
    dangling = []
    # collect all files
    for rpm in repo:
        for f in rpm.filenames:
            allfiles[f] = None
    for rpm in repo:
        if not rpm.filenames:
            continue
        for (f, mode, link) in zip(rpm.filenames, rpm["filemodes"],
            rpm["filelinktos"]):
            if not S_ISLNK(mode):
                continue
            if link[:1] != "/":
                link = "%s/%s" % (pathdirname(f), link)
            link = os.path.normpath(link)
            if link in allfiles:
                goodlinks[f] = link
                continue
            dangling.append((rpm["name"], f, link))
    # resolve possible dangling links
    for (name, f, link) in dangling:
        if resolveLink(goodlinks, link) not in allfiles:
            print "%s has dangling symlink from %s to %s" % (name, f, link)

def resolveLink(goodlinks, link):
    """Resolve link to file, use information stored in
       dictionary of goodlinks"""
    path = []
    # process all path elements
    for elem in link.split(os.sep):
        path.append(elem)
        tmppath = os.path.join(os.sep, *path)
        # If it's a link, replace already processed path:
        if tmppath in goodlinks:
            path = goodlinks[tmppath].split(os.sep)
    return os.path.join(os.sep, *path)

def checkDirs(repo):
    # collect all directories
    for rpm in repo:
        if not rpm.filenames:
            continue
        for f in rpm.filenames:
            # check if startup scripts are in wrong directory
            if f.startswith("/etc/init.d/") and not opensuse:
                print "init.d:", rpm.filename, f
            # output any package having debug stuff included
            if (not rpm["name"].endswith("-debuginfo") and
                f.startswith("/usr/lib/debug")):
                print "debug stuff in normal package:", rpm.filename, f

def checkProvides(repo):
    provides = {}
    requires = {}
    for rpm in repo:
        for r in rpm.getRequires():
            requires.setdefault(r[0], []).append(rpm.getFilename())
        if not rpm.issrc:
            for p in rpm.getProvides():
                provides.setdefault(p, []).append(rpm)
    if provides.keys():
        print "Duplicate provides:"
    for (p, value) in provides.iteritems():
        # only look at duplicate keys
        if len(value) <= 1:
            continue
        # if no require can match this, ignore duplicates
        if p[0] not in requires:
            continue
        x = []
        for rpm in value:
            #x.append(rpm.getFilename())
            if rpm["name"] not in x:
                x.append(rpm["name"])
        if len(x) <= 1:
            continue
        print p, x

def checkScripts(repo):
    comment = re.compile("^\s*#")
    for rpm in repo:
        for s in ("postin", "postun", "prein", "preun", "verifyscript"):
            data = rpm[s]
            if data == None:
                continue
            if data.find("RPM") != -1:
                for line in data.split("\n"):
                    if line.find("RPM") == -1 or comment.match(line):
                        continue
                    # ignore RPM_INSTALL_PREFIX and "rpm --import"
                    if (line.find("RPM_INSTALL_PREFIX") != -1 or
                        line.find("rpm --import") != -1):
                        continue
                    print rpm.filename, "contains \"RPM\" as string"
                    break
            if data.find("%") != -1:
                for line in data.split("\n"):
                    if line.find("%") == -1 or comment.match(line):
                        continue
                    # ignore ${var%extension} constructs
                    if re.compile(".*\${.+%.+}").match(line):
                        continue
                    # ignore "rpm --query --queryformat" and "rpm --eval"
                    if (line.find("rpm --query --queryformat") != -1 or
                        line.find("rpm --eval") != -1):
                        continue
                    # ignore "find -printf" (cyrus-imapd):
                    #if line.find("-printf") != -1:
                    #    continue
                    # ignore `date +string`
                    if re.compile(".*date \'?\\+").match(line):
                        continue
                    # openSuSE "kmp" rpms
                    if line.find("set --") != -1:
                        continue
                    if line.find("printf") != -1:
                        continue
                    print rpm.filename, "contains \"%\""
                    break

def Python2Pyrex():
    delete = 0
    pyrexcode = 0
    for line in sys.stdin.readlines():
        l = line.strip()
        if delete:
            if l == "# python-only-end":
                delete = 0
        elif l == "# python-only":
            delete = 1
        elif l == "# pyrex-code":
            pyrexcode = 1
        elif l == "# pyrex-code-end":
            pyrexcode = 0
        elif pyrexcode:
            while line[0] and line[0] == " ":
                sys.stdout.write(line[0])
                line = line[1:]
            sys.stdout.write(line[1:])
        elif l.find(" " + "+= ") != -1:
            x = line.find(" " + "+= ")
            sys.stdout.write(line[:x])
            y = line[:x].strip()
            sys.stdout.write(" = " + y + " + (")
            sys.stdout.write(line[x + 4:-1] + ")\n")
        elif l.find(" " + "-= ") != -1:
            x = line.find(" " + "-= ")
            sys.stdout.write(line[:x])
            y = line[:x].strip()
            sys.stdout.write(" = " + y + " - (")
            sys.stdout.write(line[x + 4:-1] + ")\n")
        elif l.find(" " + "|= ") != -1:
            x = line.find(" " + "|= ")
            sys.stdout.write(line[:x])
            y = line[:x].strip()
            sys.stdout.write(" = " + y + " | (")
            sys.stdout.write(line[x + 4:-1] + ")\n")
        elif l.find(" " + "&= ") != -1:
            x = line.find(" " + "&= ")
            sys.stdout.write(line[:x])
            y = line[:x].strip()
            sys.stdout.write(" = " + y + " & (")
            sys.stdout.write(line[x + 4:-1] + ")\n")
        else:
            sys.stdout.write(line)


def usage():
    prog = sys.argv[0]
    print
    print prog, "- Version:", __version__, "-",  __doc__
    print
    print "To check your rpm database:"
    print prog, "[--verbose|-v|--quiet|-q] [--rpmdbpath=/var/lib/rpm/] " \
        + "--checkrpmdb"
    print "Further opotions:"
    print "    [--enablerepos]: read in /etc/yum.conf and /etc/yum.repos.d/"
    print "    [--fileconflicts]: check rpmdb for fileconflicts"
    print "    [-c /etc/yum.conf] [--releasever 4]"
    print
    print "Verify and sanity check rpm packages:"
    print prog, "[--strict] [--nopayload] [--nodigest] \\"
    print "    /mirror/fedora/development/i386/Fedora/RPMS"
    print "find /mirror/ -name \"*.rpm\" -type f -print0 2>/dev/null \\"
    print "    | xargs -0", prog, "[--nodigest] [--nopayload]"
    print "locate '*.rpm' | xargs", prog, "[--nodigest] [--nopayload]"
    print "Options for this are:"
    print "    [--strict]: add additional checks for the Fedora Core" \
        + " development tree"
    print "    [--nodigest]: do not verify sha1/md5sum for header+payload"
    print "    [--nopayload]: do not read in the compressed cpio" \
        + " filedata (payload)"
    print "    [-c /etc/yum.conf]: experimental option to read repositories"
    print "    [--releasever 4]: set releasever for reading yum.conf files"
    print
    print "Diff two src.rpm packages:"
    print prog, "[--explode] --diff 1.src.rpm 2.src.rpm"
    print
    print "Extract src.rpm or normal rpm packages:"
    print prog, "[--buildroot=/chroot] --extract *.rpm"
    print
    print "Check src packages on which arch they would be excluded:"
    print prog, "--checkarch /mirror/fedora/development/SRPMS"
    print

def main():
    import getopt
    global cachedir, opensuse # pylint: disable-msg=W0603
    if len(sys.argv) <= 1:
        usage()
        return 0
    (_, _, kernelversion, _, arch) = os.uname()
    archlist = None
    owner = None
    if os.geteuid() == 0:
        owner = 1
    homedir = os.environ.get("HOME", "")
    if homedir and not owner:
        cachedir = homedir + "/.pyrpm/cache/"
    if not os.path.isdir(cachedir):
        print "Created the directory %s to cache files locally." % cachedir
        makeDirs(cachedir)
    verbose = 2
    ignoresymlinks = 0
    configfiles = []
    distroverpkg = ("fedora-release", "redhat-release")
    #assumeyes = 0
    repo = []
    strict = 0
    nodigest = 0
    payload = 1
    wait = 0
    verify = 1
    small = 0
    explode = 0
    diff = 0
    treediff = 0
    extract = 0
    excludes = ""
    checksrpms = 0
    rpmdbpath = "/var/lib/rpm/"
    withdb = 0
    reposdirs = []
    checkarch = 0
    checkfileconflicts = 0
    runorderer = 0
    specifyarch = 0
    buildroot = ""
    checkrpmdb = 0
    checkoldkernel = 0
    numkeepkernels = 3
    checkdeps = 0
    completerepo = 0
    baseurl = None
    createrepo = 0
    groupfile = "comps.xml"
    mercurial = 0
    pyrex = 0
    releasever = ""
    updaterpms = 0
    exactarch = 1
    testmirrors = 0
    try:
        (opts, args) = getopt.getopt(sys.argv[1:], "c:hqvy?",
            ["help", "verbose", "quiet", "arch=", "archlist=", "releasever=",
            "distroverpkg", "strict", "ignoresymlinks",
            "digest", "nodigest", "payload", "nopayload",
            "wait", "noverify", "small", "explode", "diff", "treediff",
            "extract",
            "excludes=", "nofileconflicts", "fileconflicts", "runorderer",
            "updaterpms", "reposdir=", "disablereposdir", "enablerepos",
            "checksrpms", "checkarch", "rpmdbpath=", "dbpath=", "withdb",
            "cachedir=", "checkrpmdb", "checkoldkernel", "numkeepkernels=",
            "checkdeps", "completerepo", "buildroot=", "installroot=",
            "root=", "version", "baseurl=", "createrepo", "groupfile=",
            "mercurial", "pyrex", "testmirrors", "opensuse"])
    except getopt.GetoptError, msg:
        print "Error:", msg
        return 1
    for (opt, val) in opts:
        if opt in ("-?", "-h", "--help"):
            usage()
            return 0
        elif opt in ("-v", "--verbose"):
            verbose += 1
        elif opt in ("-q", "--quiet"):
            verbose = 0
        elif opt == "--ignoresymlinks":
            ignoresymlinks = 1
        elif opt == "-c":
            configfiles.append(val)
        elif opt == "--arch":
            arch = val
            specifyarch = 1
        elif opt == "--archlist":
            archlist = val.split(",")
            arch = archlist[0]
            archlist = archlist[1:]
            specifyarch = 1
        elif opt == "--releasever":
            releasever = val
        elif opt == "--distroverpkg":
            distroverpkg = val.split(",")
        elif opt == "-y":
            #assumeyes = 1
            pass
        elif opt == "--strict":
            strict = 1
        elif opt == "--digest":
            nodigest = 0
        elif opt == "--nodigest":
            nodigest = 1
        elif opt == "--payload":
            payload = 1
        elif opt == "--nopayload":
            payload = 0
        elif opt == "--nofileconflicts":
            checkfileconflicts = 0
        elif opt == "--fileconflicts":
            checkfileconflicts = 1
        elif opt == "--runorderer":
            runorderer = 1
        elif opt == "--updaterpms":
            updaterpms = 1
        elif opt == "--wait":
            wait = 1
        elif opt == "--noverify":
            verify = 0
        elif opt == "--small":
            small = 1
        elif opt == "--explode":
            explode = 1
        elif opt == "--diff":
            diff = 1
        elif opt == "--treediff":
            treediff = 1
        elif opt == "--extract":
            extract = 1
        elif opt == "--excludes":
            excludes += " " + val
        elif opt == "--checksrpms":
            checksrpms = 1
        elif opt == "--checkarch":
            checkarch = 1
        elif opt in ("--rpmdbpath", "--dbpath"):
            rpmdbpath = val
            if rpmdbpath[-1:] != "/":
                rpmdbpath += "/"
        elif opt == "--withdb":
            withdb = 1
        elif opt == "--cachedir":
            cachedir = val
            if cachedir[-1:] != "/":
                cachedir += "/"
        elif opt == "--checkrpmdb":
            checkrpmdb = 1
        elif opt == "--checkoldkernel":
            checkoldkernel = 1
        elif opt == "--numkeepkernels":
            numkeepkernels = int(val)
        elif opt == "--checkdeps":
            checkdeps = 1
        elif opt == "--completerepo":
            completerepo = 1
        elif opt in ("--buildroot", "--installroot", "--root"):
            #if val[:1] != "/":
            #    print "buildroot should start with a /"
            #    return 1
            buildroot = os.path.abspath(val)
        elif opt == "--version":
            print sys.argv[0], "version:", __version__
            return 0
        elif opt == "--baseurl":
            baseurl = val
        elif opt == "--reposdir":
            if val not in reposdirs:
                reposdirs.append(val.split(" \t,;"))
        elif opt == "--disablereposdir":
            reposdirs = []
        elif opt == "--enablerepos":
            configfiles.append("/etc/yum.conf")
            reposdirs.extend(["/etc/yum.repos.d", "/etc/yum/repos.d"])
        elif opt == "--createrepo":
            createrepo = 1
        elif opt == "--groupfile":
            groupfile = val
        elif opt == "--mercurial":
            mercurial = 1
        elif opt == "--pyrex":
            pyrex = 1
        elif opt == "--testmirrors":
            testmirrors = 1
        elif opt == "--opensuse":
            opensuse = 1
    # Select of what we want todo here:
    if diff:
        diff = diffTwoSrpms(args[0], args[1], explode)
        if diff != "":
            print diff
    elif treediff:
        print TreeDiff(args[0], args[1])
    elif extract:
        db = None
        if withdb:
            db = RpmDB(buildroot, rpmdbpath)
        for a in args:
            extractRpm(a, buildroot, owner, db)
    elif checksrpms:
        checkSrpms(ignoresymlinks)
    elif checkarch:
        checkArch(args[0], ignoresymlinks)
    elif checkrpmdb:
        if readRpmdb(rpmdbpath, distroverpkg, releasever, configfiles,
            buildroot, arch, archlist, specifyarch, verbose,
            checkfileconflicts, reposdirs):
            return 1
    elif checkoldkernel:
        mykernelpkgs = kernelpkgs[:]
        for i in kernelpkgs:
            mykernelpkgs.append(i + "-devel")
        ver = kernelversion
        for s in ("bigmem", "enterprise", "smp", "hugemem", "PAE",
            "guest", "hypervisor", "xen0", "xenU", "xen"):
            if ver.endswith(s):
                ver = ver[:-len(s)]
        # also remove all lower case letters at the end now?
        try:
            (v, r) = ver.split("-", 1)
        except ValueError:
            print "Failed to read version and release of the", \
                "currently running kernel."
            (v, r) = (None, None)
        (packages, keyring, maxtid, pkgdata, swapendian) = \
            readPackages(buildroot, rpmdbpath, verbose, 0, importanttags)
        kernels = []
        for pkg in packages.itervalues():
            if pkg["name"] in mykernelpkgs:
                kernels.append(pkg)
        kernels.sort(pkgCompare)
        kernels.reverse()
        (vr, removekern) = ([], [])
        for pkg in kernels:
            if (pkg["version"], pkg["release"]) not in vr:
                vr.append( (pkg["version"], pkg["release"]) )
            if (len(vr) > numkeepkernels and
                (v, r) != (pkg["version"], pkg["release"])):
                removekern.append(pkg)
        if verbose > 2:
            print "You have the following kernels installed:"
            for pkg in kernels:
                print pkg.getFilename()
            print "The following older kernels should be removed:"
        for pkg in removekern:
            print pkg.getFilename2()
    elif createrepo:
        for a in args:
            if not os.path.isdir(a):
                print "Createrepo needs a directory name:", a
                break
            repo = RpmRepo([a], excludes, verbose)
            repo.createRepo(baseurl, ignoresymlinks, groupfile)
    elif mercurial:
        createMercurial(verbose)
    elif pyrex:
        Python2Pyrex()
    elif testmirrors:
        testMirrors(verbose, args)
    elif updaterpms:
        # If no config file specified, default to /etc/yum.conf and also
        # the default directories for additional yum repos.
        if not configfiles:
            configfiles.append("/etc/yum.conf")
        if not reposdirs:
            reposdirs = ["/etc/yum.repos.d", "/etc/yum/repos.d"]
        (yumconfs, distroverpkg, releasever) = readYumConf(configfiles,
            reposdirs, verbose, buildroot, rpmdbpath, distroverpkg,
            releasever)
        if yumconfs and yumconfs[0].get("main", {}).get("exactarch") != None:
            exactarch = int(yumconfs[0].get("main", {}).get("exactarch"))

        # Read all packages in rpmdb.
        if verbose > 2:
            time1 = time.clock()
        if verbose > 1:
            print "Reading the rpmdb in %s." % rpmdbpath
        (packages, keyring, maxtid, pkgdata, swapendian) = \
            readPackages(buildroot, rpmdbpath, verbose, 0, importanttags)
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to read the rpmdb", \
                "(%d rpm packages)." % len(packages.keys())

        # Read all repositories.
        if verbose > 2:
            time1 = time.clock()
        repos = readRepos(yumconfs, releasever, arch, 1, 0, verbose, fast=0)
        if repos == None:
            return 1
        if verbose > 2:
            time2 = time.clock()
            numrpms = 0
            for r in repos:
                numrpms += len(r.pkglist.keys())
            print "Needed", time2 - time1, "seconds to read the repos", \
                "(%d rpm packages)." % numrpms

        # For timing purposes also read filelists:
        if verbose > 2:
            time1 = time.clock()
        for repo in repos:
            repo.importFilelist()
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "secs to read the repo filelists."

        # Sort repo packages to only keep the newest.
        if verbose > 2:
            time1 = time.clock()
        pkglist = []
        for r in repos:
            pkglist.extend(r.pkglist.values())
        arch_hash = setMachineDistance(arch, archlist)
        pkglist = getPkgsNewest(pkglist, arch, arch_hash, verbose, 1)
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to sort the repos."

        # XXX: Here we should also look at Obsoletes:

        # Select rpms to update:
        if verbose > 2:
            time1 = time.clock()
        h = {}
        # Read all packages from rpmdb, then add all newer packages
        # from the repositories. This oder makes sure rpmdb packages
        # are selected over their same versions in the repos.
        for rpm in packages.itervalues():
            if rpm["name"] == "gpg-pubkey":
                continue
            rarch = rpm["arch"]
            if not exactarch:
                rarch = buildarchtranslate.get(rarch, rarch)
            h.setdefault( (rpm["name"], rarch) , []).append(rpm)
        for rpm in pkglist:
            rarch = rpm["arch"]
            if not exactarch:
                rarch = buildarchtranslate.get(rarch, rarch)
            key = (rpm["name"], rarch)
            if key in h:
                h[key].append(rpm)
        # Now select which rpms to install/erase:
        installrpms = []
        eraserpms = []
        for r in h.itervalues():
            if r[0].isInstallonly():
                # XXX check if there is a newer "kernel" around
                continue
            newest = selectNewestRpm(r, arch_hash, verbose)
            if newest == r[0]:
                continue
            eraserpms.append(r[0])
            installrpms.append(newest)
        # Check noarch constraints.
        #if None:
        #  for rpms in h.itervalues():
        #    newest = selectNewestRpm(rpms, arch_hash, verbose)
        #    if newest["arch"] == "noarch":
        #        for r in rpms:
        #            if r != newest:
        #                pkgs.remove(r)
        #    else:
        #        for r in rpms:
        #            if r["arch"] == "noarch":
        #                pkgs.remove(r)
        #installrpms = getPkgsNewest(rtree.getPkgs(), arch, arch_hash,
        #    verbose, 0)
        #checkDeps(installrpms, checkfileconflicts, runorderer)
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to check for updates."
        if verbose > 1:
            if not installrpms:
                print "No package updates found."
            for rpm in installrpms:
                print "Updating to %s." % rpm.getFilename()
    else:
        keepdata = 1
        hdrtags = rpmtag
        if verify == 0 and nodigest == 1:
            keepdata = 0
            if small:
                hdrtags = importanttags
        if configfiles and verbose > 2:
            time1 = time.clock()
        (yumconfs, distroverpkg, releasever) = readYumConf(configfiles,
            reposdirs, verbose, buildroot, rpmdbpath, distroverpkg,
            releasever)
        repos = readRepos(yumconfs, releasever, arch, 0, 1, verbose)
        if configfiles and verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to read the repos."
        if repos == None:
            return 1
        headerend = {}
        for r in repos:
            for p in r.pkglist.itervalues():
                args.append(p.filename)
                if p["rpm:header-range:end"]:
                    headerend[p.filename] = p["rpm:header-range:end"]
        time1 = time.clock()
        checkarchs = []
        for a in args:
            a = Uri2Filename(a)
            b = [a]
            if not a.endswith(".rpm") and not isUrl(a) and os.path.isdir(a):
                b = findRpms(a, ignoresymlinks)
            for a in b:
                #print a
                rpm = verifyRpm(a, verify, strict, payload, nodigest, hdrtags,
                    keepdata, headerend.get(a))
                if rpm == None:
                    continue
                #f = rpm["filenames"]
                #if f:
                #    print rpm.getFilename()
                #    print f
                if checkdeps or completerepo or strict or wait:
                    if (rpm["name"] in kernelpkgs and not rpm.issrc and
                        rpm["arch"] not in checkarchs):
                        checkarchs.append(rpm["arch"])
                    repo.append(rpm)
                # python-only
                del rpm
                # python-only-end
        if verbose > 2:
            time2 = time.clock()
            print "Needed", time2 - time1, "seconds to read", len(repo), \
                "rpm packages."
        if strict:
            for rpm in repo:
                rpm.filenames = rpm.getFilenames()
            checkDirs(repo)
            if not opensuse:
                checkSymlinks(repo)
            checkScripts(repo)
        if strict or checkdeps:
            if specifyarch:
                checkarchs = [arch, ]
            if checkarchs:
                for arch in checkarchs:
                    time1 = time.clock()
                    print "Check as if kernel has the", \
                        "architecture \"%s\" now:" % arch
                    arch_hash = setMachineDistance(arch, archlist)
                    installrpms = getPkgsNewest(repo, arch, arch_hash,
                        verbose, 0, 1)
                    if strict:
                        checkProvides(installrpms)
                    checkDeps(installrpms, checkfileconflicts, runorderer,
                        verbose)
                    time2 = time.clock()
                    print "Needed", time2 - time1, "sec to check this tree."
            else:
                print "No arch defined to check, are kernels missing?"
        if completerepo:
            checkRepo(repo)

    if wait:
        print "Ready."
        time.sleep(30)
    return 0

def run_main(mymain):
    dohotshot = 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--hotshot":
        dohotshot = 1
        sys.argv.pop(1)
    if dohotshot:
        import hotshot, hotshot.stats
        htfilename = mkstemp_file(tmpdir)[1]
        prof = hotshot.Profile(htfilename)
        prof.runcall(mymain)
        prof.close()
        # python-only
        del prof
        # python-only-end
        print "Starting profil statistics. This takes some time..."
        s = hotshot.stats.load(htfilename)
        s.strip_dirs()
        s.sort_stats("time").print_stats(100)
        s.sort_stats("cumulative").print_stats(100)
        s.sort_stats("calls").print_stats(100)
        os.unlink(htfilename)
    else:
        ret = mymain()
        if ret != None:
            sys.exit(ret)

if __name__ == "__main__":
    #checkCSV()
    run_main(main)

# vim:ts=4:sw=4:showmatch:expandtab
