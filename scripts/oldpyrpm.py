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
# Copyright 2004, 2005 Red Hat, Inc.
#
# Author: Paul Nasrat, Florian La Roche, Phil Knirsch
#

#
# Read .rpm packages from python. Implemented completely in python without
# using the rpmlib C library. Extensive checks have been added and this
# script can be used to check the binary packages for unusual format/content.
#
# Possible options:
# "--strict" should only be used for the Fedora Core development tree
# "--nodigest" to skip sha1/md5sum check for header+payload
# "--nopayload" to not read in the compressed filedata (payload)
#
# Example usage:
# find /mirror/ -name "*.rpm" -type f -print0 2>/dev/null \
#         | xargs -0 ./oldpyrpm.py [--nodigest --nopayload]
# locate '*.rpm' | xargs ./oldpyrpm.py [--nodigest --nopayload]
# ./oldpyrpm.py --strict [--nodigest --nopayload] \
#         /mirror/fedora/development/i386/Fedora/RPMS/*.rpm
#
# Other usages:
# - Check your rpmdb for consistency (works as non-root readonly):
#   ./oldpyrpm.py [--verbose|-v|--quiet|-q] \
#                 [--rpmdbpath=/var/lib/rpm/] --checkrpmdb
#   The check of the rpmdb database is read-only and can be done
#   as normal user (non-root). Apart from the OpenGPG keys in
#   "Pubkeys", all data is stored in "Packages" and then also
#   copied over into other db4 files. "--checkrpmdb" is doing a
#   check between data in "Packages" and the other files, then
#   it checks if our own write routine would come up writing the
#   same data again and it tries to verify the sha1 crc of the
#   normal header data (the signature header cannot be checked).
#   Increasing the verbose level also prints content data, specifying
#   "--quiet" will skip informational messages.
#

#
# TODO:
# - check install_badsha1_2 if available
# - allow a --rebuilddb into a new directory and a diff between two rpmdb
# - check OpenGPG signatures
# - allow src.rpm selection based on OpenGPG signature. Prefer GPG signed.
# - Bring extractCpio and verifyCpio closer together again.
# - i386 rpm extraction on ia64? (This is stored like relocated rpms in
#   duplicated file tags.)
# - Better error handling in PyGZIP.
# - streaming read for cpio files (not high prio item)
# - use setPerms() in doLnOrCopy()
# - Change "strict" and "verify" into "debug" and have one integer specify
#   debug and output levels. (Maybe also "nodigest" can move in?)
# - limit: does not support all RHL5.x and earlier rpms if verify is enabled
# - Whats the difference between "cookie" and "buildhost" + "buildtime".
# - evrSplit(): 'epoch = ""' would make a distinction between missing
#   and "0" epoch (push this change into createrepo)
# things to be noted, probably not getting fixed:
# - PyGZIP is way faster than existing gzip routines, but still 2 times
#   slower than a C version. Can further improvements be made?
#   The C part should offer a class which supports read().
# - Why is bsddb so slow? (Why is reading rpmdb so slow?) Can we make
#   small and faster python bindings for bsddb? Nothing found for this.
# - We use S_ISREG(fileflag) to check for regular files before looking
#   at filemd5s, but filemd5s is only set for regular files, so this
#   might be optimized a bit. (That code is in no performance critical
#   path, so could also stay as is.) Also note that some kernels have
#   bugs to not mmap() files with size 0 and then rpm is writing wrong
#   filemd5s for those.
# - The error case for "--checkrpmdb" might not be too good. E.g. duplicate
#   entries are moaned about, but then also not verified by adding them
#   to the hash, so analysing the error case might still involve adding
#   further custom checks.
# - Python is bad at handling lots of small data and is getting rather
#   slow. At some point it may make sense to write again a librpm type
#   thing to have a core part in C and testing/outer decisions in python.
#   Due to the large data rpm is handling this is kind of tricky.
# things that look even less important to implement:
# - add support for drpm (delta rpm) payloadformat
# - check for #% in spec files: grep "#.*%" *.spec (too many hits until now)
# - add streaming support to bzip2 compressed payload
# - lua scripting support
# possible changes for /bin/rpm:
# - Do not generate filecontexts tags if they are empty, maybe not at all.
# - "rhnplatform" could go away if it is not required.
# - Can hardlinks go into a new rpm tag? (does not gain much)
# - Can requires for the same rpm be deleted from the rpm tag header?
#   Would this disturb any other existing dep solver?
# - Improve perl autogenerated "Provides:"
#

import sys
if sys.version_info < (2, 2):
    sys.exit("error: Python 2.2 or later required")
import os, os.path, md5, sha, pwd, grp, zlib, errno
from struct import pack, unpack

if sys.version_info < (2, 3):
    from types import StringType
    basestring = StringType

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
            letters = [choose(c) for dummy in "123456"]
            return self.normcase("".join(letters))

    _name_sequence = None

    def _get_candidate_names():
        """Common setup sequence for all user-callable interfaces."""
        global _name_sequence
        if _name_sequence == None:
            _name_sequence = _RandomNameSequence()
        return _name_sequence
else:
    from tempfile import _get_candidate_names, TMP_MAX

# optimized routines instead of:
#from stat import S_ISREG, S_ISLNK, S_ISDIR, S_ISFIFO, S_ISCHR, \
#   S_ISBLK, S_ISSOCK
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

openflags = os.O_RDWR | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOINHERIT"):
    openflags |= os.O_NOINHERIT
if hasattr(os, "O_NOFOLLOW"):
    openflags |= os.O_NOFOLLOW

def mkstemp_file(dirname, pre):
    names = _get_candidate_names()
    for _ in xrange(TMP_MAX):
        name = names.next()
        filename = "%s/%s.%s" % (dirname, pre, name)
        try:
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

def mkstemp_dir(dirname, pre):
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

# Use this filename prefix for all temp files to be able
# to search them and delete them again if they are left
# over from killed processes.
tmpprefix = "..pyrpm"

def doLnOrCopy(src, dst):
    dstdir = os.path.dirname(dst)
    tmp = mkstemp_link(dstdir, tmpprefix, src)
    if tmp == None:
        # no hardlink possible, copy the data into a new file
        (fd, tmp) = mkstemp_file(dstdir, tmpprefix)
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

def getMD5(fpath):
    fd = open(fpath, "r")
    ctx = md5.new()
    while 1:
        data = fd.read(16384)
        if not data:
            break
        ctx.update(data)
    return ctx.hexdigest()


# Optimized routines that use zlib to extract data, since
# "import gzip" doesn't give good data handling (old code
# can still easily be enabled to compare performance):

(FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT) = (1, 2, 4, 8, 16)
class PyGZIP:
    def __init__(self, fd, datasize, filename):
        self.fd = fd
        self.filename = filename
        self.length = 0 # length of all decompressed data
        self.length2 = datasize
        self.enddata = "" # remember last 8 bytes for crc/length check
        self.pos = 0
        self.data = ""
        if self.fd.read(3) != "\037\213\010":
            print "Not a gzipped file"
            sys.exit(0)
        # flag (1 byte), modification time (4 bytes), extra flags (1), OS (1)
        data = doRead(self.fd, 7)
        flag = ord(data[0])
        if flag & FEXTRA:
            # Read & discard the extra field, if present
            xlen = ord(self.fd.read(1))
            xlen += 256 * ord(self.fd.read(1))
            doRead(self.fd, xlen)
        if flag & FNAME:
            # Read and discard a nul-terminated string containing the filename
            while self.fd.read(1) != "\000":
                pass
        if flag & FCOMMENT:
            # Read and discard a nul-terminated string containing a comment
            while self.fd.read(1) != "\000":
                pass
        if flag & FHCRC:
            doRead(self.fd, 2)      # Read & discard the 16-bit header CRC
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
            data = self.fd.read(32768)
            if len(data) >= 8:
                self.enddata = data[-8:]
            else:
                self.enddata = self.enddata[-len(data):] + data
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

    def __del__(self):
        data = self.fd.read(8)
        if len(data) >= 8:
            self.enddata = data[-8:]
        else:
            self.enddata = self.enddata[-len(data):] + data
        (crc32, isize) = unpack("<iI", self.enddata)
        if crc32 != self.crcval:
            print self.filename, "CRC check failed:", crc32, self.crcval
        if isize != self.length:
            print self.filename, "Incorrect length of data produced:", isize, self.length
        if isize != self.length2 and self.length2 != None:
            print self.filename, "Incorrect length of data produced:", self.length2


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
RPMSENSE_SCRIPT_PRE = ((1 << 9) | RPMSENSE_PREREQ)      # %pre dependency
RPMSENSE_SCRIPT_POST = ((1 << 10)|RPMSENSE_PREREQ)      # %post dependency
RPMSENSE_SCRIPT_PREUN = ((1 << 11)|RPMSENSE_PREREQ)     # %preun dependency
RPMSENSE_SCRIPT_POSTUN = ((1 << 12)|RPMSENSE_PREREQ)    # %postun dependency
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


RPMSENSE_TRIGGER = (RPMSENSE_TRIGGERIN | RPMSENSE_TRIGGERUN \
    | RPMSENSE_TRIGGERPOSTUN)

_ALL_REQUIRES_MASK  = (RPMSENSE_INTERP | RPMSENSE_SCRIPT_PRE \
    | RPMSENSE_SCRIPT_POST | RPMSENSE_SCRIPT_PREUN | RPMSENSE_SCRIPT_POSTUN \
    | RPMSENSE_SCRIPT_VERIFY | RPMSENSE_FIND_REQUIRES | RPMSENSE_SCRIPT_PREP \
    | RPMSENSE_SCRIPT_BUILD | RPMSENSE_SCRIPT_INSTALL | RPMSENSE_SCRIPT_CLEAN \
    | RPMSENSE_RPMLIB | RPMSENSE_KEYRING)

def _notpre(x):
    return (x & ~RPMSENSE_PREREQ)

_INSTALL_ONLY_MASK = _notpre(RPMSENSE_SCRIPT_PRE | RPMSENSE_SCRIPT_POST \
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
    # triggers
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
    "group": [1016, RPM_GROUP, None, 0], # comps.xml is used now
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
    "archivesize": [1046, RPM_INT32, 1, 1]
}
# Add a reverse mapping for all tags plus the name again.
for v in rpmtag.keys():
    rpmtag[v].append(v)
for v in rpmtag.values():
    rpmtag[v[0]] = v
    if len(v) != 5:
        raise ValueError, "rpmtag has wrong entries"
del v

# Additional tags which can be in the rpmdb /var/lib/rpm/Packages.
rpmdbtag = {
    "origdirindexes": [1119, RPM_INT32, None, 1],
    "origdirnames": [1121, RPM_STRING_ARRAY, None, 1],
    "origbasenames": [1120, RPM_STRING_ARRAY, None, 1],
    "install_size_in_sig": [257, RPM_INT32, 1, 0],
    "install_md5": [261, RPM_BIN, 16, 0],
    "install_unknownchecksum": [262, RPM_BIN, None, 0],
    "install_dsaheader": [267, RPM_BIN, 16, 0],
    "install_sha1header": [269, RPM_STRING, None, 0],
    "installtime": [1008, RPM_INT32, 1, 8],
    "filestates": [1029, RPM_CHAR, None, 0],
    "instprefixes": [1099, RPM_STRING_ARRAY, None, 0],
    "installcolor": [1127, RPM_INT32, None, 0],
    "installtid": [1128, RPM_INT32, None, 0],
    "install_badsha1_1": [264, RPM_STRING, None, 1],
    "install_badsha1_2": [265, RPM_STRING, None, 1],
    "immutable1": [61, RPM_BIN, 16, 1]
}
# List of special rpmdb tags, like also visible above.
install_keys = {}
for v in rpmdbtag.keys():
    install_keys[v] = 1
    rpmdbtag[v].append(v)
for v in rpmdbtag.values():
    rpmdbtag[v[0]] = v
    if len(v) != 5:
        raise ValueError, "rpmdbtag has wrong entries"
for v in rpmtag.keys():
    rpmdbtag[v] = rpmtag[v]
del v
# These entries have the same ID as entries already in the list
# to store duplicate tags that get written to the rpmdb for
# relocated packages or ia64 compat packages (i386 on ia64).
rpmdbtag["dirindexes2"] = [1116, RPM_INT32, None, 0, "dirindexes2"]
rpmdbtag["dirnames2"] = [1118, RPM_STRING_ARRAY, None, 0, "dirnames2"]
rpmdbtag["basenames2"] = [1117, RPM_STRING_ARRAY, None, 0, "basenames2"]
install_keys["dirindexes2"] = 1
install_keys["dirnames2"] = 1
install_keys["basenames2"] = 1

# Required tags in a header.
rpmtagrequired = ("name", "version", "release", "arch", "rpmversion")

importanttags = {"name":1, "epoch":1, "version":1, "release":1,
    "arch":1, "payloadcompressor":1, "payloadformat":1,
    "providename":1, "provideflags":1, "provideversion":1,
    "requirename":1, "requireflags":1, "requireversion":1,
    "obsoletename":1, "obsoleteflags":1, "obsoleteversion":1,
    "conflictname":1, "conflictflags":1, "conflictversion":1,
    "triggername":1, "triggerflags":1, "triggerversion":1,
    "triggerscripts":1, "triggerscriptprog":1, "triggerindex":1,
    "prein":1, "preinprog":1, "postin":1, "postinprog":1,
    "preun":1, "preunprog":1, "postun":1, "postunprog":1,
    "verifyscript":1, "verifyscriptprog":1,
    "oldfilenames":1, "dirindexes":1, "dirnames":1, "basenames":1,
    "fileusername":1, "filegroupname":1, "filemodes":1,
    "filemtimes":1, "filedevices":1, "fileinodes":1, "filesizes":1,
    "filemd5s":1, "filerdevs":1, "filelinktos":1, "fileflags":1}


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
    "badsha1_2": [265, RPM_STRING, None, 1]
}
# Add a reverse mapping for all tags plus the name again.
for v in rpmsigtag.keys():
    rpmsigtag[v].append(v)
for v in rpmsigtag.values():
    rpmsigtag[v[0]] = v
    if len(v) != 5:
        raise ValueError, "rpmsigtag has wrong entries"
del v

# Required tags in a signature header.
rpmsigtagrequired = ("md5",)


# check arch names against this list
possible_archs = {"noarch":1, "i386":1, "i486":1, "i586":1, "i686":1,
    "athlon":1, "pentium3":1, "pentium4":1, "x86_64":1, "ia32e":1, "ia64":1,
    "alpha":1, "alphaev6":1, "axp":1, "sparc":1, "sparc64":1,
    "s390":1, "s390x":1,
    "ppc":1, "ppc64":1, "ppc64iseries":1, "ppc64pseries":1, "ppcpseries":1,
    "ppciseries":1, "ppcmac":1, "ppc8260":1, "m68k":1,
    "arm":1, "armv4l":1, "mips":1, "mipseb":1, "mipsel":1, "hppa":1, "sh":1 }

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
    "/usr/sbin/libgcc_post_upgrade": 1 }


def writeHeader(tags, taghash, region, skip_tags, useinstall, rpmgroup):
    """Use the data "tags" and change it into a rpmtag header."""
    (offset, store, stags1, stags2, stags3) = (0, [], [], [], [])
    # Sort by number and also first normal tags, then install_keys tags
    # and at the end the region tag.
    for tagname in tags.keys():
        tagnum = taghash[tagname][0]
        if tagname == region:
            stags3.append((tagnum, tagname))
        elif skip_tags and skip_tags.has_key(tagname):
            pass
        elif useinstall and install_keys.has_key(tagname):
            stags2.append((tagnum, tagname))
        else:
            stags1.append((tagnum, tagname))
    stags1.sort()
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
            data = "".join( [ "%s\x00" % value[i] for i in xrange(count) ] )
        elif ttype == RPM_BIN:
            data = value
        elif ttype == RPM_INT16:
            data = pack("!%dH" % count, *value)
            pad = (2 - (offset % 2)) % 2
        elif ttype == RPM_INT8 or ttype == RPM_CHAR:
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
        if tagname == region:
            indexdata.insert(0, index)
        else:
            indexdata.append(index)
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
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z") \
        or (c >= "0" and c <= "9")

# compare two strings, rpm/lib/rpmver.c:rpmvercmp()
def stringCompare(str1, str2):
    """ Loop through each version segment (alpha or numeric) of
        str1 and str2 and compare them. """
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
        if _xisdigit(str1[j1]):
            while j1 < lenstr1 and _xisdigit(str1[j1]): j1 += 1
            while j2 < lenstr2 and _xisdigit(str2[j2]): j2 += 1
            isnum = 1
        else:
            while j1 < lenstr1 and _xisalpha(str1[j1]): j1 += 1
            while j2 < lenstr2 and _xisalpha(str2[j2]): j2 += 1
            isnum = 0
        # check if we already hit the end
        if j1 == i1: return -1
        if j2 == i2:
            if isnum: return 1
            return -1
        if isnum:
            # ignore leading "0" for numbers (1.01 == 1.000001)
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


# EVR compare: uses stringCompare to compare epoch/version/release
def labelCompare(e1, e2):
    # remove comparison of the release string if one of them is missing
    if e2[2] == "":
        e1 = (e1[0], e1[1], "")
    elif e1[2] == "":
        e2 = (e2[0], e2[1], "")
    r = stringCompare(e1[0], e2[0])
    if r == 0:
        r = stringCompare(e1[1], e2[1])
        if r == 0:
            r = stringCompare(e1[2], e2[2])
    return r


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

def isUrl(filename):
    if filename.startswith("http://") or \
       filename.startswith("ftp://") or \
       filename.startswith("file://"):
        return 1
    return 0


def parseFile(filename, requested):
    rethash = {}
    for l in open(filename, "r").readlines():
        tmp = l.split(":")
        if requested.has_key(tmp[0]):
            rethash[tmp[0]] = int(tmp[2])
    return rethash

class UGid:
    """Store a list of user- and groupnames and transform them in uids/gids."""

    def __init__(self, names=None):
        self.ugid = {}
        if names:
            for name in names:
                #if not self.ugid.has_key(name):
                #    self.ugid[name] = name
                self.ugid.setdefault(name, name)

    def transform(self, buildroot):
        pass

class Uid(UGid):
    def transform(self, buildroot):
        # "uid=0" if no /etc/passwd exists at all.
        if not os.path.isfile(buildroot + "/etc/passwd"):
            for uid in self.ugid.keys():
                self.ugid[uid] = 0
                if uid != "root":
                    print "warning: user %s not found, using uid 0" % uid
            return
        # Parse /etc/passwd if glibc is not yet installed.
        if buildroot or not os.path.isfile(buildroot + "/sbin/ldconfig"):
            uidhash = parseFile(buildroot + "/etc/passwd", self.ugid)
            for uid in self.ugid.keys():
                if uidhash.has_key(uid):
                    self.ugid[uid] = uidhash[uid]
                else:
                    print "warning: user %s not found, using uid 0" % uid
                    self.ugid[uid] = 0
            return
        # Normal lookup of users via glibc.
        for uid in self.ugid.keys():
            if uid == "root":
                self.ugid[uid] = 0
            else:
                try:
                    self.ugid[uid] = pwd.getpwnam(uid)[2]
                except:
                    print "warning: user %s not found, using uid 0" % uid
                    self.ugid[uid] = 0

class Gid(UGid):
    def transform(self, buildroot):
        # "gid=0" if no /etc/group exists at all.
        if not os.path.isfile(buildroot + "/etc/group"):
            for gid in self.ugid.keys():
                self.ugid[gid] = 0
                if gid != "root":
                    print "warning: group %s not found, using gid 0" % gid
            return
        # Parse /etc/group if glibc is not yet installed.
        if buildroot or not os.path.isfile(buildroot + "/sbin/ldconfig"):
            gidhash = parseFile(buildroot + "/etc/group", self.ugid)
            for gid in self.ugid.keys():
                if gidhash.has_key(gid):
                    self.ugid[gid] = gidhash[gid]
                else:
                    print "warning: group %s not found, using gid 0" % gid
                    self.ugid[gid] = 0
            return
        # Normal lookup of users via glibc.
        for gid in self.ugid.keys():
            if gid == "root":
                self.ugid[gid] = 0
            else:
                try:
                    self.ugid[gid] = grp.getgrnam(gid)[2]
                except:
                    print "warning: group %s not found, using gid 0" % gid
                    self.ugid[gid] = 0


class CPIO:
    """Read a cpio archive."""

    def __init__(self, fd, issrc, size=None):
        self.fd = fd
        self.issrc = issrc
        self.size = size

    def printErr(self, err):
        print "%s: %s" % ("cpio-header", err)

    def __readDataPad(self, size, pad=0):
        data = doRead(self.fd, size)
        pad = (4 - ((size + pad) % 4)) % 4
        doRead(self.fd, pad)
        if self.size != None:
            self.size -= size + pad
        return data

    def readCpio(self, func, filenamehash, devinode, filenames, extract):
        while 1:
            # (magic, inode, mode, uid, gid, nlink, mtime, filesize,
            # devMajor, devMinor, rdevMajor, rdevMinor, namesize, checksum)
            data = doRead(self.fd, 110)
            if self.size != None:
                self.size -= 110
            # CPIO ASCII hex, expanded device numbers (070702 with CRC)
            if data[0:6] not in ("070701", "070702"):
                raise IOError, "Bad magic reading CPIO headers %s" % data[0:6]
            namesize = int(data[94:102], 16)
            filename = self.__readDataPad(namesize, 110).rstrip("\x00")
            if filename == "TRAILER!!!":
                if self.size != None and self.size != 0:
                    self.printErr("failed cpiosize check")
                return 1
            if filename[:2] == "./":
                filename = filename[1:]
            if not self.issrc and not filename.startswith("/"):
                filename = "%s%s" % ("/", filename)
            if len(filename) > 1 and filename[-1] == "/":
                filename = filename[:-1]
            if extract:
                func(filename, int(data[54:62], 16), self.__readDataPad,
                    filenamehash, devinode, filenames)
            else:
                # (name, inode, mode, nlink, mtime, filesize, dev, rdev)
                filedata = (filename, int(data[6:14], 16),
                    long(data[14:22], 16), int(data[38:46], 16),
                    long(data[46:54], 16), int(data[54:62], 16),
                    int(data[62:70], 16) * 256 + int(data[70:78], 16),
                    int(data[78:86], 16) * 256 + int(data[86:94], 16))
                func(filedata, self.__readDataPad, filenamehash, devinode,
                    filenames)
        return None


class HdrIndex:
    def __init__(self):
        self.hash = {}
        self.__len__ = self.hash.__len__
        self.__getitem__ = self.hash.get
        self.__delitem__ = self.hash.__delitem__
        self.__setitem__ = self.hash.__setitem__
        self.__contains__ = self.hash.__contains__
        self.has_key = self.hash.has_key
        self.__repr__ = self.hash.__repr__

    def getOne(self, key):
        value = self[key]
        if value != None:
            return value[0]
        return value

class ReadRpm:
    """Read (Linux) rpm packages."""

    def __init__(self, filename, verify=None, fd=None, strict=None,
                 nodigest=None):
        self.filename = filename
        self.issrc = 0
        self.verify = verify # enable/disable more data checking
        self.fd = fd # filedescriptor
        self.strict = strict
        self.nodigest = nodigest # check md5sum/sha1 digests
        self.buildroot = None # do we have a chroot-like start?
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

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def raiseErr(self, err):
        raise ValueError, "%s: %s" % (self.filename, err)

    def __openFd(self, offset=None):
        if not self.fd:
            if isUrl(self.filename):
                import urlgrabber
                try:
                    self.fd = urlgrabber.urlopen(self.filename)
                #except urlgrabber.grabber.URLGrabError, e:
                #    raise IOError, str(e)
                except urlgrabber.grabber.URLGrabError:
                    self.printErr("could not open file")
                    return 1
            else:
                try:
                    self.fd = open(self.filename, "ro")
                except:
                    self.printErr("could not open file")
                    return 1
            if offset:
                self.fd.seek(offset, 1)
        return None

    def closeFd(self):
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
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4s2B2H66s2H16x", leaddata)
        failed = None
        if major not in (3, 4) or minor != 0 or \
            sigtype != 5 or rpmtype not in (0, 1):
            failed = 1
        # 21 == darwin
        if osnum not in (1, 21, 255, 256):
            failed = 1
        name = name.rstrip("\x00")
        if self.strict:
            if not os.path.basename(self.filename).startswith(name):
                failed = 1
        if failed:
            print major, minor, rpmtype, arch, name, osnum, sigtype
            self.printErr("wrong data in rpm lead")

    def __verifyTag(self, index, fmt, hdrtags):
        (tag, ttype, offset, count) = index
        if not hdrtags.has_key(tag):
            self.printErr("hdrtags has no tag %d" % tag)
        else:
            t = hdrtags[tag]
            if t[1] != None and t[1] != ttype:
                if t[1] == RPM_ARGSTRING and \
                    (ttype == RPM_STRING or ttype == RPM_STRING_ARRAY):
                    pass    # special exception case
                elif t[1] == RPM_GROUP and \
                    (ttype == RPM_STRING or ttype == RPM_I18NSTRING):
                    pass    # exception for RPMTAG_GROUP
                else:
                    self.printErr("tag %d has wrong type %d" % (tag, ttype))
            if t[2] != None and t[2] != count:
                self.printErr("tag %d has wrong count %d" % (tag, count))
            if (t[3] & 1) and self.strict:
                self.printErr("tag %d is old" % tag)
            if self.issrc:
                if (t[3] & 4):
                    self.printErr("tag %d should be for binary rpms" % tag)
            else:
                if (t[3] & 2):
                    self.printErr("tag %d should be for src rpms" % tag)
        if count == 0:
            self.raiseErr("zero length tag")
        if ttype < 1 or ttype > 9:
            self.raiseErr("unknown rpmtype %d" % ttype)
        if ttype == RPM_INT32:
            count = count * 4
        elif ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
            size = 0
            for _ in xrange(count):
                end = fmt.index("\x00", offset) + 1
                size += end - offset
                offset = end
            count = size
        elif ttype == RPM_STRING:
            if count != 1:
                self.raiseErr("tag string count wrong")
            count = fmt.index("\x00", offset) - offset + 1
        elif ttype == RPM_CHAR or ttype == RPM_INT8:
            pass
        elif ttype == RPM_INT16:
            count = count * 2
        elif ttype == RPM_INT64:
            count = count * 8
        elif ttype == RPM_BIN:
            pass
        else:
            self.raiseErr("unknown tag header")
        return count

    def __verifyIndex(self, fmt, fmt2, indexNo, storeSize, hdrtags):
        checkSize = 0
        for i in xrange(0, indexNo * 16, 16):
            index = unpack("!4I", fmt[i:i + 16])
            ttype = index[1]
            # alignment for some types of data
            if ttype == RPM_INT16:
                checkSize += (2 - (checkSize % 2)) % 2
            elif ttype == RPM_INT32:
                checkSize += (4 - (checkSize % 4)) % 4
            elif ttype == RPM_INT64:
                checkSize += (8 - (checkSize % 8)) % 8
            checkSize += self.__verifyTag(index, fmt2, hdrtags)
        if checkSize != storeSize:
            # Seems this is triggered for a few (legacy) RHL5.x rpm packages.
            self.printErr("storeSize/checkSize is %d/%d" % (storeSize,
                checkSize))

    def __readIndex(self, pad, hdrtags, rpmdb=None):
        if rpmdb:
            data = "\x8e\xad\xe8\x01\x00\x00\x00\x00" + doRead(self.fd, 8)
        else:
            data = doRead(self.fd, 16)
        (magic, indexNo, storeSize) = unpack("!8s2I", data)
        if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
            self.raiseErr("bad index magic")
        fmt = doRead(self.fd, 16 * indexNo)
        fmt2 = doRead(self.fd, storeSize)
        padfmt = ""
        if pad != 1:
            padfmt = doRead(self.fd, (pad - (storeSize % pad)) % pad)
        if self.verify:
            self.__verifyIndex(fmt, fmt2, indexNo, storeSize, hdrtags)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + \
            len(fmt2) + len(padfmt))

    def __parseIndex(self, indexNo, fmt, fmt2, dorpmtag):
        hdr = HdrIndex()
        if len(dorpmtag) == 0:
            return hdr
        for i in xrange(0, indexNo * 16, 16):
            (tag, ttype, offset, count) = unpack("!4I", fmt[i:i + 16])
            if not dorpmtag.has_key(tag):
                #print "unknown tag:", (tag, ttype, offset, count), self.filename
                continue
            nametag = dorpmtag[tag][4]
            if ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
                data = []
                for _ in xrange(count):
                    end = fmt2.index("\x00", offset)
                    data.append(fmt2[offset:end])
                    offset = end + 1
            elif ttype == RPM_STRING:
                data = fmt2[offset:fmt2.index("\x00", offset)]
            elif ttype == RPM_INT32:
                # distinguish between signed and unsigned ints
                if dorpmtag[tag][3] & 8:
                    data = unpack("!%di" % count,
                        fmt2[offset:offset + count * 4])
                else:
                    data = unpack("!%dI" % count,
                        fmt2[offset:offset + count * 4])
            elif ttype == RPM_INT8 or ttype == RPM_CHAR:
                data = unpack("!%dB" % count, fmt2[offset:offset + count])
            elif ttype == RPM_INT16:
                data = unpack("!%dH" % count, fmt2[offset:offset + count * 2])
            elif ttype == RPM_INT64:
                data = unpack("!%dQ" % count, fmt2[offset:offset + count * 8])
            elif ttype == RPM_BIN:
                data = fmt2[offset:offset + count]
            else:
                self.raiseErr("unknown tag header")
                data = None
            if nametag == "group":
                self.rpmgroup = ttype
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

    def readHeader(self, sigtags, hdrtags, keepdata=None, rpmdb=None):
        if rpmdb == None:
            if self.__openFd():
                return 1
            leaddata = doRead(self.fd, 96)
            if leaddata[:4] != "\xed\xab\xee\xdb":
                self.printErr("no rpm magic found")
                return 1
            self.issrc = (leaddata[7] == "\x01")
            if self.verify:
                self.__verifyLead(leaddata)
            sigdata = self.__readIndex(8, sigtags)
            self.sigdatasize = sigdata[5]
        hdrdata = self.__readIndex(1, hdrtags, rpmdb)
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
        self.__getitem__ = self.hdr.__getitem__
        self.__delitem__ = self.hdr.__delitem__
        self.__setitem__ = self.hdr.__setitem__
        self.__contains__ = self.hdr.__contains__
        self.has_key = self.hdr.has_key
        self.__repr__ = self.hdr.__repr__
        if self.verify:
            self.__doVerify()
        # hack: Save a tiny bit of memory by compressing the fileusername
        # and filegroupname strings to be only stored once. Evil and maybe
        # this does not make sense at all.
        for i in ("fileusername", "filegroupname"):
            if not self[i]:
                continue
            y = []
            z = {}
            for j in self[i]:
                #if not z.has_key(j):
                #    z[j] = j
                z.setdefault(j, j)
                y.append(z[j])
            self[i] = y
        return None

    def verifyCpio(self, filedata, read_data, filenamehash, devinode, _):
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
            linkto, i) = fileinfo
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
        if isreg and inode != inode2:
            self.printErr("wrong fileinode for %s" % filename)
        if self.strict and mode != mode2:
            self.printErr("wrong filemode for %s" % filename)
        # uid/gid are ignored from cpio
        # device/inode are only set correctly for regular files
        di = devinode.get((dev, inode))
        if di == None:
            pass
            # nlink is only set correctly for hardlinks, so disable this check:
            #if nlink != 1:
            #    self.printErr("wrong number of hardlinks")
        else:
            # Search for "normpath" to read why hardlinks might not
            # be hardlinks, but only double stored files with "/../"
            # stored in their filename. Broken packages out there...
            if self.strict and nlink != len(di):
                self.printErr("wrong number of hardlinks %s, %d / %d" % \
                    (filename, nlink, len(di)))
            # This case also happens e.g. in RHL6.2: procps-2.0.6-5.i386.rpm
            # where nlinks is greater than the number of actual hardlinks.
            #elif nlink > len(di):
            #   self.printErr("wrong number of hardlinks %s, %d / %d" % \
            #       (filename, nlink, len(di)))
        if mtime != mtime2:
            self.printErr("wrong filemtimes for %s" % filename)
        if filesize != self["filesizes"][i] and \
            not (filesize == 0 and nlink > 1):
            self.printErr("wrong filesize for %s" % filename)
        if isreg and dev != dev2:
            self.printErr("wrong filedevice for %s" % filename)
        if self.strict and rdev != rdev2:
            self.printErr("wrong filerdevs for %s" % filename)
        if S_ISLNK(mode):
            if data.rstrip("\x00") != linkto:
                self.printErr("wrong filelinkto for %s" % filename)
        elif isreg:
            if not (filesize == 0 and nlink > 1):
                ctx = md5.new()
                ctx.update(data)
                if ctx.hexdigest() != self["filemd5s"][i]:
                    if self.strict or self["filesizes"][i] != 0:
                        self.printErr("wrong filemd5s for %s: %s, %s" \
                            % (filename, ctx.hexdigest(), \
                            self["filemd5s"][i]))

    def extractCpio(self, filename, datasize, read_data, filenamehash,
            devinode, filenames):
        data = ""
        if datasize:
            data = read_data(datasize)
        fileinfo = filenamehash.get(filename)
        if fileinfo == None:
            self.printErr("cpio file %s not in rpm header" % filename)
            return
        (fn, flag, mode, mtime, dev, inode, user, group, rdev,
            linkto, i) = fileinfo
        del filenamehash[filename]
        uid = gid = None
        if self.owner:
            uid = self.uid.ugid[user]
            gid = self.gid.ugid[group]
        if self.relocated:
            filename = self.__relocatedFile(filename)
        if self.buildroot:
            filename = "%s%s" % (self.buildroot, filename)
        dirname = os.path.dirname(filename)
        makeDirs(dirname)
        if S_ISREG(mode):
            di = devinode.get((dev, inode))
            if di == None or data:
                (fd, tmpfilename) = mkstemp_file(dirname, tmpprefix)
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
                        if self.buildroot:
                            fn2 = "%s%s" % (self.buildroot, fn2)
                        dirname = os.path.dirname(fn2)
                        makeDirs(dirname)
                        tmpfilename = mkstemp_link(dirname, tmpprefix, filename)
                        if tmpfilename == None:
                            (fd, tmpfilename) = mkstemp_file(dirname, tmpprefix)
                            os.write(fd, data)
                            os.close(fd)
                            setPerms(tmpfilename, uid, gid, mode, mtime)
                        os.rename(tmpfilename, fn2)
                    del devinode[(dev, inode)]
        elif S_ISDIR(mode):
            makeDirs(filename)
            setPerms(filename, uid, gid, mode, None)
        elif S_ISLNK(mode):
            #if os.path.islink(filename) \
            #    and os.readlink(filename) == linkto:
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
        basenames = self["basenames"]
        if basenames != None:
            dirnames = self["dirnames"]
            return [ "%s%s" % (dirnames[d], b)
                     for (d, b) in zip(self["dirindexes"], basenames) ]
        else:
            oldfilenames = self["oldfilenames"]
            if oldfilenames != None:
                return oldfilenames
        return []

    def readPayload(self, func, filenames=None, extract=None):
        self.__openFd(96 + self.sigdatasize + self.hdrdatasize)
        devinode = {}     # this will contain possibly hardlinked files
        filenamehash = {} # full filename of all files
        if filenames == None:
            filenames = self.getFilenames()
        if filenames:
            fileinfo = zip(filenames, self["fileflags"], self["filemodes"],
                self["filemtimes"], self["filedevices"], self["fileinodes"],
                self["fileusername"], self["filegroupname"], self["filerdevs"],
                self["filelinktos"], xrange(len(self["fileinodes"])))
            for (fn, flag, mode, mtime, dev, inode, user, group,
                rdev, linkto, i) in fileinfo:
                if flag & (RPMFILE_GHOST | RPMFILE_EXCLUDE):
                    continue
                filenamehash[fn] = fileinfo[i]
                if S_ISREG(mode):
                    #di = (dev, inode)
                    #if not devinode.has_key(di):
                    #    devinode[di] = []
                    #devinode[di].append(i)
                    devinode.setdefault((dev, inode), []).append(i)
        for di in devinode.keys():
            if len(devinode[di]) <= 1:
                del devinode[di]
        # sanity check hardlinks
        if self.verify:
            for hardlinks in devinode.values():
                j = hardlinks[0]
                mode = self["filemodes"][j]
                mtime = self["filemtimes"][j]
                size = self["filesizes"][j]
                fmd5 = self["filemd5s"][j]
                for j in hardlinks[1:]:
                    # dev/inode are already guaranteed to be the same
                    if self["filemodes"][j] != mode:
                        self.raiseErr("modes differ for hardlink")
                    if self["filemtimes"][j] != mtime:
                        self.raiseErr("mtimes differ for hardlink")
                    if self["filesizes"][j] != size:
                        self.raiseErr("sizes differ for hardlink")
                    if self["filemd5s"][j] != fmd5:
                        self.raiseErr("md5s differ for hardlink")
        cpiosize = self.sig.getOne("payloadsize")
        archivesize = self.hdr.getOne("archivesize")
        if archivesize != None:
            if cpiosize == None:
                cpiosize = archivesize
            elif cpiosize != archivesize:
                self.printErr("wrong archive size")
        if self["payloadcompressor"] in [None, "gzip"]:
            fd = PyGZIP(self.fd, cpiosize, self.filename)
            #import gzip
            #fd = gzip.GzipFile(fileobj=self.fd)
        elif self["payloadcompressor"] == "bzip2":
            import bz2, cStringIO
            payload = self.fd.read()
            fd = cStringIO.StringIO(bz2.decompress(payload))
        else:
            self.printErr("unknown payload compression")
            return
        if self["payloadformat"] not in [None, "cpio"]:
            self.printErr("unknown payload format")
            return
        c = CPIO(fd, self.issrc, cpiosize)
        if c.readCpio(func, filenamehash, devinode, filenames, extract) == None:
            self.raiseErr("Error reading CPIO payload")
        for filename in filenamehash.iterkeys():
            self.printErr("file not in cpio: %s" % filename)
        if extract and len(devinode.keys()):
            self.printErr("hardlinked files remain from cpio")
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

    def getNVR(self):
        return "%s-%s-%s" % (self["name"], self["version"], self["release"])

    def getNA(self):
        return "%s.%s" % (self["name"], self["arch"])

    def getEVR(self):
        e = self["epoch"]
        if e != None:
            return "%d:%s-%s" % (e[0], self["version"], self["release"])
        return "%s-%s" % (self["version"], self["release"])

    def getEpoch(self):
        e = self["epoch"]
        if e == None:
            return "0"
        return str(e[0])

    def getArch(self):
        if self.issrc:
            return "src"
        return self["arch"]

    def getFilename(self):
        return "%s-%s-%s.%s.rpm" % (self["name"], self["version"],
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

    def __getDeps(self, name, flags, version):
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
        provs = self.__getDeps("providename", "provideflags", "provideversion")
        if not self.issrc:
            provs.append( (self["name"], RPMSENSE_EQUAL, self.getEVR()) )
        return provs

    def getRequires(self):
        return self.__getDeps("requirename", "requireflags", "requireversion")

    def getObsoletes(self):
        return self.__getDeps("obsoletename", "obsoleteflags",
            "obsoleteversion")

    def getConflicts(self):
        return self.__getDeps("conflictname", "conflictflags",
            "conflictversion")

    def getTriggers(self):
        deps = self.__getDeps("triggername", "triggerflags", "triggerversion")
        index = self["triggerindex"]
        scripts = self["triggerscripts"]
        progs = self["triggerscriptprog"]
        if deps == []:
            if self.verify:
                if index != None or scripts != None or progs != None:
                    self.printErr("wrong triggers still exist")
            return []
        if self.verify and len(scripts) != len(progs):
            self.printErr("wrong triggers")
        if index == None:
            if self.verify and len(deps) != len(scripts):
                self.printErr("wrong triggers")
        else:
            if self.verify and len(deps) != len(index):
                self.printErr("wrong triggers")
            scripts = [ scripts[i] for i in index ]
            progs = [ progs[i] for i in index ]
        return [(n, f, v, progs.pop(0), scripts.pop(0)) for (n, f, v) in deps]

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
        if self["buildarchs"] == [ "noarch" ]:
            return 2
        # otherwise build this rpm normally for this arch
        return 1

    def getChangeLog(self, num=-1):
        """ Return the changlog entry in one string. """
        import time
        ctext = self["changelogtext"]
        if not ctext:
            return ""
        cname = self["changelogname"]
        ctime = self["changelogtime"]
        if num == -1 or num > len(ctext):
            num = len(ctext)
        data = ""
        for i in xrange(num):
            data = data + "* %s %s\n\n%s\n\n" % (time.strftime("%a %b %d %Y",
                time.localtime(ctime[i])), cname[i], ctext[i])
        return data

    def __verifyWriteHeader(self, hdrhash, taghash, region, hdrdata,
        useinstall, rpmgroup):
        (indexNo, storeSize, fmt, fmt2) = writeHeader(hdrhash, taghash, region,
            None, useinstall, rpmgroup)
        if indexNo != hdrdata[0]:
            if taghash == rpmtag:
                print self.getFilename(), self["rpmversion"], "normal header"
            else:
                print self.getFilename(), self["rpmversion"], "sig header"
            print "wrong number of rpmtag values", indexNo, hdrdata[0]
        if storeSize != hdrdata[1]:
            if taghash == rpmtag:
                print self.getFilename(), self["rpmversion"], "normal header"
            else:
                print self.getFilename(), self["rpmversion"], "sig header"
            print "wrong length of data", storeSize, hdrdata[1]
        if fmt != hdrdata[3]:
            if taghash == rpmtag:
                print self.getFilename(), self["rpmversion"], "normal header"
            else:
                print self.getFilename(), self["rpmversion"], "sig header"
            print "wrong fmt data"
            print "fmt length:", len(fmt), len(hdrdata[3])
            for i in xrange(0, indexNo * 16, 16):
                (tag1, ttype1, offset1, count1) = unpack("!4I", fmt[i:i + 16])
                (tag2, ttype2, offset2, count2) = unpack("!4I",
                    hdrdata[3][i:i + 16])
                print "tag(%d):" % i, tag1, tag2
                if tag1 != tag2:
                    print "tag:", tag1, tag2
                if ttype1 != ttype2:
                    print "ttype:", ttype1, ttype2
                print "offset(%d):" % i, offset1, offset2, "(tag: %s)" % tag1
                if offset1 != offset2:
                    print "offset(%d):" % i, offset1, offset2, "(tag: %s)" \
                        % tag1
                if count1 != count2:
                    print "ttype/count:", ttype1, count1, count2
        if fmt2 != hdrdata[4]:
            print "wrong fmt2 data"

    def __doVerify(self):
        self.__verifyWriteHeader(self.hdr.hash, rpmtag,
            "immutable", self.hdrdata, 1, self.rpmgroup)
        if self.strict:
            self.__verifyWriteHeader(self.sig.hash, rpmsigtag,
                "header_signatures", self.sigdata, 0, None)
        # disable the utf-8 test per default:
        if self.strict and None:
            for i in ["summary", "description", "changelogtext"]:
                if self[i] == None:
                    continue
                for j in self[i]:
                    try:
                        j.decode("utf-8")
                    except:
                        self.printErr("not utf-8 in %s" % i)
                        #self.printErr("text: %s" % j)
                        break
        for i in rpmsigtagrequired:
            if not self.sig.has_key(i):
                self.printErr("sig header is missing: %s" % i)
        for i in rpmtagrequired:
            if not self.hdr.has_key(i):
                self.printErr("hdr is missing: %s" % i)
        size_in_sig = self.sig.getOne("size_in_sig")
        if size_in_sig != None:
            rpmsize = os.stat(self.filename)[6]
            if rpmsize != 96 + self.sigdatasize + size_in_sig:
                self.printErr("wrong size in rpm package")
        filenames = self.getFilenames()
        fileflags = self["fileflags"]
        if fileflags:
            for flag in fileflags:
                if flag & RPMFILE_EXCLUDE:
                    self.printErr("exclude flag set in rpm")
        if self.issrc:
            i = self.getSpecfile(filenames)
            if i == None:
                self.printErr("no specfile found in src.rpm")
            else:
                if self.strict and not filenames[i].endswith(".spec"):
                    self.printErr("specfile does not end with .spec")
            if self["sourcerpm"] != None:
                self.printErr("binary rpm does contain sourcerpm tag")
        else:
            if self["sourcerpm"] == None:
                self.printErr("source rpm does not contain sourcerpm tag")
        if self["triggerscripts"] != None:
            if len(self["triggerscripts"]) != len(self["triggerscriptprog"]):
                self.printErr("wrong trigger lengths")
        if "-" in self["version"] or ":" in self["version"]:
            self.printErr("version contains wrong char")
        if ":" in self["release"]:
            self.printErr("version contains wrong char")
        if self.strict:
            if "," in self["version"] or "," in self["release"]:
                self.printErr("version contains wrong char")
        if self["payloadformat"] not in [None, "cpio", "drpm"]:
            self.printErr("wrong payload format %s" % self["payloadformat"])
        if self.strict:
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
            if self["packager"] not in (None, \
                "Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>"):
                self.printErr("unknown packager: %s" % self["packager"])
            if self["vendor"] not in (None, "Red Hat, Inc."):
                self.printErr("unknown vendor: %s" % self["vendor"])
            if self["distribution"] not in (None, "Red Hat Linux",
                "Red Hat FC-3", "Red Hat (FC-3)", "Red Hat (FC-4)",
                "Red Hat (FC-5)",
                "Red Hat (scratch)", "Red Hat (RHEL-3)", "Red Hat (RHEL-4)"):
                self.printErr("unknown distribution: %s" % self["distribution"])
        arch = self["arch"]
        if self["rhnplatform"] not in (None, arch):
            self.printErr("unknown arch for rhnplatform")
        if self.strict:
            if os.path.basename(self.filename) != self.getFilename():
                self.printErr("bad filename: %s" % self.filename)
            if self["platform"] not in (None, "", arch + "-redhat-linux-gnu",
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
                    if not possible_archs.has_key(i):
                        self.printErr("new possible arch %s" % i)
            if self["exclusivearch"] != None:
                for i in self["exclusivearch"]:
                    if not possible_archs.has_key(i):
                        self.printErr("new possible arch %s" % i)
        for (s, p) in (("prein", "preinprog"), ("postin", "postinprog"),
            ("preun", "preunprog"), ("postun", "postunprog"),
            ("verifyscript", "verifyscriptprog")):
            (script, prog) = (self[s], self[p])
            if script != None and prog == None:
                self.printErr("no prog")
            if self.strict:
                if not possible_scripts.has_key(prog):
                    self.printErr("unknown prog: %s" % prog)
                if script == None and prog == "/bin/sh":
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
            provs = self.__getDeps("providename", "provideflags",
                "provideversion")
            mydep = (self["name"], RPMSENSE_EQUAL, self.getEVR())
            ver = self["rpmversion"]
            # AS2.1 still has compat rpms which need this:
            if ver != None and ver[:4] < "4.3." and mydep not in provs:
                provs.append(mydep)
            if mydep not in provs:
                self.printErr("no provides for own rpm package, rpm=%s" % ver)
        self.getTriggers()

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
            if self["dirindexes"] != None or \
                self["dirnames"] != None or \
                self["basenames"] != None:
                self.printErr("new filetag still present")
            if lx != len(self["oldfilenames"]):
                self.printErr("wrong length for tag oldfilenames")
        elif self["dirindexes"]:
            if len(self["dirindexes"]) != lx or len(self["basenames"]) != lx \
                or self["dirnames"] == None:
                self.printErr("wrong length for file* tag")
        filemodes = self["filemodes"]
        filemd5s = self["filemd5s"]
        fileflags = self["fileflags"]
        if filemodes:
            for x in xrange(len(filemodes)):
                if fileflags[x] & (RPMFILE_GHOST | RPMFILE_EXCLUDE):
                    continue
                if S_ISREG(filemodes[x]):
                    if not filemd5s[x]:
                        # There is a kernel bug to not mmap() files with
                        # size 0. That kernel also builds broken rpms.
                        if self.strict or self["filesizes"][x] != 0:
                            self.printErr("missing filemd5sum, %d, %s" % (x,
                                filenames[x]))
                elif filemd5s[x] != "":
                    print filemd5s[x]
                    self.printErr("non-regular file has filemd5sum")
        # Verify region headers have sane data. We do not support more than
        # one region header at this point.
        for (data, regiontag, indexNo) in ((self["immutable"],
            rpmtag["immutable"][0], self.hdrdata[0]),
            (self["immutable1"], rpmdbtag["immutable1"][0], self.hdrdata[0]),
            (self.sig["header_signatures"], rpmsigtag["header_signatures"][0],
            self.sigdata[0])):
            if data == None:
                continue
            (tag, ttype, offset, count) = unpack("!2IiI", data)
            if tag != regiontag:
                self.printErr("region has wrong tag")
            if ttype != RPM_BIN or count != 16:
                self.printErr("region has wrong type/count")
            if -offset % 16 != 0:
                self.printErr("region has wrong offset")
            if -offset / 16 != indexNo:
                self.printErr("region only for partial header")

        if self.nodigest:
            return

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
                self.printErr("wrong md5: %s / %s" % (md5sum, ctx.hexdigest()))


def verifyRpm(filename, verify, strict, payload, nodigest, hdrtags, keepdata):
    """Read in a complete rpm and verify its integrity."""
    rpm = ReadRpm(filename, verify, strict=strict, nodigest=nodigest)
    if rpm.readHeader(rpmsigtag, hdrtags, keepdata):
        return None
    if payload:
        rpm.readPayload(rpm.verifyCpio)
    rpm.closeFd()
    return rpm

def extractRpm(filename, buildroot, owner=None):
    """Extract a rpm into a directory."""
    if isinstance(filename, basestring):
        rpm = ReadRpm(filename)
        if rpm.readHeader(rpmsigtag, rpmtag):
            return None
    else:
        rpm = filename
    rpm.buildroot = buildroot
    if rpm.issrc:
        if not buildroot.endswith("/") and buildroot != "":
            buildroot = buildroot + "/"
    else:
        while buildroot.endswith("/"):
            buildroot = buildroot[:-1]
        if os.geteuid() == 0:
            owner = 1
    rpm.buildroot = buildroot
    rpm.owner = owner
    if owner:
        rpm.uid = Uid(rpm["fileusername"])
        rpm.uid.transform(buildroot)
        rpm.gid = Gid(rpm["filegroupname"])
        rpm.gid.transform(buildroot)
    rpm.readPayload(rpm.extractCpio, extract=1)

def isBinary(filename):
    for i in (".gz", ".tgz", ".taz", ".bz2", ".z", ".Z", ".zip", ".ttf",
        ".db", ".jar"):
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
    #if newdirn.endswith(".EL"):
    #    newdirn = newdirn[:-3]
    #if newdirn.endswith("1.4.1rh"):
    #    newdirn = newdirn[:-7]
    while newdirn[-1] in "-_.0123456789":
        newdirn = newdirn[:-1]
    os.system("cd " + dirname + " && tar x" + explode + "f " + filename \
        + "; for i in * ; do test -d \"$i\" && mv \"$i\" " + newdirn + "; done")

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

    obuildroot = orpm.buildroot = mkstemp_dir("/tmp", tmpprefix) + "/"
    nbuildroot = nrpm.buildroot = mkstemp_dir("/tmp", tmpprefix) + "/"

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
        if orpm["filemd5s"][f] == nrpm["filemd5s"][g] and \
            f != ospec and g != nspec:
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
    ret = ret + getoutput("diff -urN " + obuildroot + " " + nbuildroot \
        + " | " + sed)
    os.system("rm -rf " + obuildroot + " " + nbuildroot)
    return ret

def cmpRpms(one, two):
    evr1 = (one.getEpoch(), one["version"], one["release"])
    evr2 = (two.getEpoch(), two["version"], two["release"])
    return labelCompare(evr1, evr2)

class RpmTree:

    def __init__(self):
        self.h = {}

    def addRpm(self, filename):
        if isinstance(filename, basestring):
            rpm = ReadRpm(filename)
            if rpm.readHeader(rpmsigtag, rpmtag):
                print "Cannot read %s.\n" % filename
                return None
            rpm.closeFd()
        else:
            rpm = filename
        #na = (rpm["name"], rpm.getArch())
        #if not self.h.has_key(na):
        #    self.h[na] = []
        #self.h[na].append(rpm)
        self.h.setdefault( (rpm["name"], rpm.getArch()) , []).append(rpm)
        return rpm

    def addDirectory(self, dirname):
        files = map(lambda v, dirname=dirname: "%s/%s" % (dirname, v),
            os.listdir(dirname))
        for f in files:
            if f.endswith(".rpm"):
                self.addRpm(f)

    def getNames(self):
        rpmnames = self.h.keys()
        rpmnames.sort()
        return rpmnames

    def sortVersions(self):
        for v in self.h.values():
            v.sort(cmpRpms)

    def keepNewest(self):
        for r in self.h.keys():
            v = self.h[r]
            newest = v[0]
            for rpm in v:
                if cmpRpms(newest, rpm) < 0:
                    newest = rpm
            self.h[r] = [newest]

    def sort_unify(self):
        self.sortVersions()
        # Remove identical rpms and print a warning about further rpms
        # who might add new patches without changing version/release.
        for v in self.h.values():
            i = 0
            while i < len(v) - 1:
                if cmpRpms(v[i], v[i + 1]) == 0:
                    if not sameSrcRpm(v[i], v[i + 1]):
                        print "duplicate rpms:", v[i].filename, v[i + 1].filename
                    v.remove(v[i])
                i = i + 1


def verifyStructure(verbose, packages, phash, tag, useidx=1):
    # Verify that all data is also present in /var/lib/rpm/Packages.
    for tid in phash.keys():
        mytag = phash[tid]
        if not packages.has_key(tid):
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
        for idx in mytag.keys():
            if useidx:
                try:
                    val = pkgtag[idx]
                except:
                    print "Error %s: index %s is not in package" % (tag, idx)
                    if verbose > 2:
                        print mytag[idx]
            else:
                if idx != 0:
                    print "Error %s: index %s out of range" % (tag, idx)
                val = pkgtag
            if mytag[idx] != val:
                print "Error %s: %s != %s in package %s" % (tag, mytag[idx],
                    val, packages[tid].getFilename())
    # Go through /var/lib/rpm/Packages and check if data is correctly
    # copied over to the other files.
    for tid in packages.keys():
        pkg = packages[tid]
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
        if phash.has_key(tid):
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
            if tag == "requirename" and \
                isInstallPreReq(pkg["requireflags"][idx]):
                continue
            # only include filemd5s for regular files
            if tag == "filemd5s" and not S_ISREG(pkg["fileflags"][idx]):
            #check could also be: if tag == "filemd5s" and not key:
                continue
            # We only need to store triggernames once per package.
            if tag == "triggername":
                if tnamehash.has_key(key):
                    continue
                tnamehash[key] = 1
            # Real check for the actual data:
            try:
                if phashtid[idx] != key:
                    print "wrong data"
            except:
                print "Error %s: index %s is not in package %s" % (tag,
                    idx, tid)
                if verbose > 2:
                    print key, phashtid

def readPackages(dbpath, verbose):
    import bsddb, cStringIO
    packages = {}
    pkgdata = {}
    keyring = None #openpgp.PGPKeyRing()
    maxtid = 0
    # Read the db4/hash file to determine byte order / endianness
    # as well as maybe host order:
    swapendian = ""
    data = open(dbpath + "Packages", "ro").read(16)
    if len(data) == 16:
        if unpack("=I", data[12:16])[0] == 0x00061561:
            if verbose > 2:
                print "checking rpmdb with same endian order"
        else:
            if pack("=H", 0xdead) == "\xde\xad":
                swapendian = "<"
                if verbose:
                    print "big-endian machine reading little-endian rpmdb"
            else:
                swapendian = ">"
                if verbose:
                    print "little-endian machine reading big-endian rpmdb"
    db = bsddb.hashopen(dbpath + "Packages", "r")
    #for (tid, data) in db.iteritems():
    for tid in db.keys():
        data = db[tid]
        tid = unpack("%sI" % swapendian, tid)[0]
        if tid == 0:
            maxtid = unpack("%sI" % swapendian, data)[0]
            continue
        fd = cStringIO.StringIO(data)
        pkg = ReadRpm("rpmdb", fd=fd)
        pkg.readHeader(None, rpmdbtag, 1, 1)
        if pkg["name"] == "gpg-pubkey":
            #for k in openpgp.parsePGPKeys(pkg["description"]):
            #    keyring.addKey(k)
            pkg["group"] = (pkg["group"],)
        packages[tid] = pkg
        pkgdata[tid] = data
    return (packages, keyring, maxtid, pkgdata, swapendian)

def readDb(swapendian, filename, dbtype="hash", dotid=None):
    import bsddb
    if dbtype == "hash":
        db = bsddb.hashopen(filename, "r")
    else:
        db = bsddb.btopen(filename, "r")
    rethash = {}
    #for (k, v) in db.iteritems():
    for k in db.keys():
        v = db[k]
        if dotid:
            k = unpack("%sI" % swapendian, k)[0]
        if k == "\x00":
            k = ""
        for i in xrange(0, len(v), 8):
            (tid, idx) = unpack("%s2I" % swapendian, v[i:i+8])
            if not rethash.has_key(tid):
                rethash[tid] = {}
            if rethash[tid].has_key(idx):
                print "ignoring duplicate idx: %s %d %d" % (k, tid, idx)
                continue
            rethash[tid][idx] = k
    return rethash

def readRpmdb(dbpath, verbose):
    from binascii import b2a_hex
    if verbose:
        print "Reading rpmdb, this can take some time..."
        print "Reading Packages..."
    (packages, keyring, maxtid, pkgdata, swapendian) = readPackages(dbpath,
        verbose)
    if verbose:
        print "Reading the rest..."
    if verbose and sys.version_info < (2, 3):
        print "If you use python-2.2 you can get the harmless output:", \
            "'Python bsddb: close errno 13 in dealloc'."
    basenames = readDb(swapendian, dbpath + "Basenames")
    conflictname = readDb(swapendian, dbpath + "Conflictname")
    dirnames = readDb(swapendian, dbpath + "Dirnames", "bt")
    filemd5s = readDb(swapendian, dbpath + "Filemd5s")
    group = readDb(swapendian, dbpath + "Group")
    installtid = readDb(swapendian, dbpath + "Installtid", "bt", 1)
    name = readDb(swapendian, dbpath + "Name")
    providename = readDb(swapendian, dbpath + "Providename")
    provideversion = readDb(swapendian, dbpath + "Provideversion", "bt")
    pubkeys = readDb(swapendian, dbpath + "Pubkeys")
    requirename = readDb(swapendian, dbpath + "Requirename")
    requireversion = readDb(swapendian, dbpath + "Requireversion", "bt")
    sha1header = readDb(swapendian, dbpath + "Sha1header")
    sigmd5 = readDb(swapendian, dbpath + "Sigmd5")
    triggername = readDb(swapendian, dbpath + "Triggername")
    if verbose:
        print "Checking data integrity..."
    for tid in packages.keys():
        if tid > maxtid:
            print "wrong tid:", tid
    verifyStructure(verbose, packages, basenames, "basenames")
    verifyStructure(verbose, packages, conflictname, "conflictname")
    verifyStructure(verbose, packages, dirnames, "dirnames")
    for x in filemd5s.values():
        for y in x.keys():
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
    for tid in packages.keys():
        pkg = packages[tid]
        if pkg["name"] == "gpg-pubkey":
            continue
        # Check if we could write the rpmdb data again.
        region = "immutable"
        if pkg["rpmversion"][:3] not in ("4.0", "3.0", "2.2"):
            install_keys["archivesize"] = 1
        if pkg["immutable1"] != None:
            region = "immutable1"
            install_keys["providename"] = 1
            install_keys["provideflags"] = 1
            install_keys["provideversion"] = 1
            install_keys["dirindexes"] = 1
            install_keys["dirnames"] = 1
            install_keys["basenames"] = 1
        (indexNo, storeSize, fmt, fmt2) = writeHeader(pkg.hdr.hash, rpmdbtag,
            region, None, 1, pkg.rpmgroup)
        if pkg["rpmversion"][:3] not in ("4.0", "3.0", "2.2"):
            del install_keys["archivesize"]
        if pkg["immutable1"] != None:
            del install_keys["providename"]
            del install_keys["provideflags"]
            del install_keys["provideversion"]
            del install_keys["dirindexes"]
            del install_keys["dirnames"]
            del install_keys["basenames"]
        lead = pack("!2I", indexNo, storeSize)
        data = "".join([lead, fmt, fmt2])
        if len(data) % 4 != 0:
            print "rpmdb header is not aligned to 4"
        if data != pkgdata[tid]:
            print pkg["name"], "wrong pkgdata", len(data), len(pkgdata[tid]), pkg["rpmversion"]
            if fmt != pkg.hdrdata[3]:
                print "wrong fmt"
            if fmt2 != pkg.hdrdata[4]:
                print "wrong fmt2", len(fmt2), len(pkg.hdrdata[4])
            for i in xrange(0, indexNo * 16, 16):
                (tag1, ttype1, offset1, count1) = unpack("!4I", fmt[i:i + 16])
                (tag2, ttype2, offset2, count2) = unpack("!4I",
                    pkg.hdrdata[3][i:i + 16])
                if tag1 != tag2 or ttype1 != ttype2 or count1 != count2:
                    print "tag:", tag1, tag2, i
                if offset1 != offset2:
                    print "offset:", offset1, offset2, "tag=", tag1
        # Verify the sha1 crc of the normal header data. (Signature data left out.)
        pkg.sig = HdrIndex()
        if pkg["archivesize"] != None:
            pkg.sig["payloadsize"] = pkg["archivesize"]
            if pkg["rpmversion"][:3] not in ("4.0", "3.0", "2.2"):
                del pkg["archivesize"]
        sha1header = pkg["install_sha1header"]
        install_badsha1_2 = pkg["install_badsha1_2"]
        if sha1header == None: # and install_badsha1_2 == None:
            print "warning: package", pkg.getFilename(), "does not have a sha1 header"
            continue
        (indexNo, storeSize, fmt, fmt2) = writeHeader(pkg.hdr.hash, rpmdbtag,
            region, install_keys, 0, pkg.rpmgroup)
        lead = pack("!8s2I", "\x8e\xad\xe8\x01\x00\x00\x00\x00",
            indexNo, storeSize)
        if sha1header == None:
            sha1header = install_badsha1_2
            #lead = convert(lead)
            #fmt = convert(fmt)
            #fmt2 = convert(fmt2)
        ctx = sha.new()
        ctx.update(lead)
        ctx.update(fmt)
        ctx.update(fmt2)
        if ctx.hexdigest() != sha1header:
            print pkg.getFilename(), \
                "bad sha1: %s / %s" % (sha1header, ctx.hexdigest())
    if verbose:
        print "Done."

def sameSrcRpm(a, b):
    # Packages with the same md5sum for the payload are the same.
    amd5sum = a.sig["md5"]
    if amd5sum != None and amd5sum == b.sig["md5"]:
        return 1
    # Check if all regular files are the same in both packages.
    amd5s = []
    for (md5, name, mode) in zip(a["filemd5s"], a.getFilenames(),
        a["filemodes"]):
        if S_ISREG(mode):
            amd5s.append((md5, name))
    amd5s.sort()
    bmd5s = []
    for (md5, name, mode) in zip(b["filemd5s"], b.getFilenames(),
        b["filemodes"]):
        if S_ISREG(mode):
            bmd5s.append((md5, name))
    bmd5s.sort()
    return amd5s == bmd5s

def checkSrpms():
    directories = [
        "/var/www/html/mirror/updates-rhel/2.1",
        "/var/www/html/mirror/updates-rhel/3",
        "/var/www/html/mirror/updates-rhel/4",
        "/mnt/hdb4/data/cAos/3.5/updates/SRPMS",
        "/mnt/hdb4/data/cAos/4.1/os/SRPMS",
        "/mnt/hdb4/data/cAos/4.1/updates/SRPMS"]
    for d in directories:
        if not os.path.isdir(d):
            continue
        r = RpmTree()
        r.addDirectory(d)
        r.sort_unify()
        for v in r.h.values():
            for i in xrange(len(v) - 1):
                if v[i].hdr.getOne("buildtime") > \
                    v[i + 1].hdr.getOne("buildtime"):
                    print "buildtime inversion:", v[i].filename, \
                        v[i + 1].filename
    directories.append("/var/www/html/mirror/rhn/SRPMS")
    r = RpmTree()
    for d in directories:
        if os.path.isdir(d):
            r.addDirectory(d)
    r.sort_unify()
    for rp in r.getNames():
        v = r.h[rp]
        print "%s:" % v[0]["name"]
        for s in v:
            print "\t%s" % s.getFilename()

def cmpA(h1, h2):
    return cmp(h1[0], h2[0])

def checkArch(path):
    print "Mark the arch where a src.rpm would not get built:\n"
    arch = ["i386", "x86_64", "ia64", "ppc", "s390", "s390x"]
    r = RpmTree()
    r.addDirectory(path)
    r.keepNewest() # Only look at the newest src.rpms.
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
    for rp in r.getNames():
        srpm = r.h[rp][0]
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
    for (dummy, builds, srpm) in showrpms:
        s = ""
        for a in arch:
            if builds[a] == 1:
                s = "%s  " % s
            else:
                s = "%sx " % s
        print "%29s  %s" % (srpm["name"], s)


def checkSymlinks(repo):
    """Check if any two dirs in a repository differ in user/group/mode."""
    allfiles = {}
    # collect all directories
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
            if not link.startswith("/"):
                link = "%s/%s" % (os.path.dirname(f), link)
            link = os.path.normpath(link)
            if allfiles.has_key(link):
                continue
            print "%s has dangling symlink from %s to %s" \
                % (rpm["name"], f, link)

def checkDirs(repo):
    """Check if any two dirs in a repository differ in user/group/mode."""
    dirs = {}
    # collect all directories
    for rpm in repo:
        if not rpm.filenames:
            continue
        for (f, mode, user, group) in zip(rpm.filenames, rpm["filemodes"],
            rpm["fileusername"], rpm["filegroupname"]):
            # check if startup scripts are in wrong directory
            if f.startswith("/etc/init.d/"):
                print "init.d:", rpm.filename, f
            # output any package having debug stuff included
            if not rpm["name"].endswith("-debuginfo") and \
                f.startswith("/usr/lib/debug"):
                print "debug stuff in normal package:", rpm.filename, f
            # collect all directories into "dirs"
            if not S_ISDIR(mode):
                continue
            dirs.setdefault(f, []).append( (f, user, group, mode,
                rpm.filename) )
    # check if all dirs have same user/group/mode
    for d in dirs.values():
        if len(d) < 2:
            continue
        (user, group, mode) = (d[0][1], d[0][2], d[0][3])
        for i in xrange(1, len(d)):
            if d[i][1] != user or d[i][2] != group or d[i][3] != mode:
                print "dir check failed for ", d
                break

dupes = [ ("glibc", "i386"),
          ("nptl-devel", "i386"),
          ("openssl", "i386"),
          ("kernel", "i586"),
          ("kernel-smp", "i686"),
          ("kernel-smp-devel", "i686"),
          ("kernel-xen0", "i686"),
          ("kernel-xenU", "i686"),
          ("kernel-devel", "i586") ]
def checkProvides(repo, checkrequires=1):
    provides = {}
    requires = {}
    for rpm in repo:
        req = rpm.getRequires()
        for r in req:
            if not requires.has_key(r[0]):
                requires[r[0]] = []
            requires[r[0]].append(rpm.getFilename())
    for rpm in repo:
        if (rpm["name"], rpm["arch"]) in dupes:
            continue
        for p in rpm.getProvides():
            if not provides.has_key(p):
                provides[p] = []
            provides[p].append(rpm)
    print "Duplicate provides:"
    for p in provides.keys():
        # only look at duplicate keys
        if len(provides[p]) <= 1:
            continue
        # if no require can match this, ignore duplicates
        if checkrequires and not requires.has_key(p[0]):
            continue
        x = []
        for rpm in provides[p]:
            #x.append(rpm.getFilename())
            if rpm["name"] not in x:
                x.append(rpm["name"])
        if len(x) <= 1:
            continue
        print p, x


# split EVR string in epoch, version and release
def evrSplit(evr):
    epoch = "0"
    i = evr.find(":")
    if i != -1:
        epoch = evr[:i]
    j = evr.find("-", i + 1)
    if j != -1:
        return (epoch, evr[i + 1:j], evr[j + 1:])
    return (epoch, evr[i + 1:], "")


def usage():
    prog = sys.argv[0]
    print "To check your rpm database:"
    print prog, "[--verbose|-v|--quiet|-q] [--rpmdbpath=/var/lib/rpm/] " \
        + "--checkrpmdb"
    print
    print "Check a directory with rpm packages:"
    print prog, "[--strict] [--nopayload] [--nodigest] " \
        + "/mirror/fedora/development/i386/Fedora/RPMS"
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
    if len(sys.argv) <= 1:
        usage()
        sys.exit(0)
    verbose = 2
    repo = []
    strict = 0
    nodigest = 0
    payload = 1
    wait = 0
    verify = 1
    small = 0
    explode = 0
    diff = 0
    extract = 0
    checksrpms = 0
    rpmdbpath = "/var/lib/rpm/"
    checkarch = 0
    buildroot = ""
    checkrpmdb = 0
    (opts, args) = getopt.getopt(sys.argv[1:], "hqv?",
        ["help", "verbose", "quiet", "strict", "digest", "nodigest", "payload",
         "nopayload",
         "wait", "noverify", "small", "explode", "diff", "extract",
         "checksrpms", "checkarch", "rpmdbpath=",
         "checkrpmdb", "buildroot="])
    for (opt, val) in opts:
        if opt in ("-?", "-h", "--help"):
            usage()
            sys.exit(0)
        elif opt in ("-v", "--verbose"):
            verbose += 1
        elif opt in ("-q", "--quiet"):
            verbose = 0
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
        elif opt == "--extract":
            extract = 1
        elif opt == "--checksrpms":
            checksrpms = 1
        elif opt == "--checkarch":
            checkarch = 1
        elif opt == "--rpmdbpath":
            rpmdbpath = val
            if rpmdbpath[-1:] != "/":
                rpmdbpath += "/"
        elif opt == "--checkrpmdb":
            checkrpmdb = 1
        elif opt == "--buildroot":
            #if not val.startswith("/"):
            #    print "buildroot should start with a /"
            #    return
            buildroot = os.path.abspath(val)
    if diff:
        diff = diffTwoSrpms(args[0], args[1], explode)
        if diff != "":
            print diff
        return
    if extract:
        for a in args:
            extractRpm(a, buildroot)
        return
    if checksrpms:
        checkSrpms()
        return
    if checkarch:
        checkArch(args[0])
        return
    if checkrpmdb:
        readRpmdb(rpmdbpath, verbose)
        return
    keepdata = 1
    hdrtags = rpmtag
    if verify == 0 and nodigest == 1:
        keepdata = 0
        if small:
            for i in importanttags.keys():
                value = rpmtag[i]
                importanttags[i] = value
                importanttags[value[0]] = value
            hdrtags = importanttags
    #for _ in xrange(50):
    for a in args:
        b = [a]
        if not a.endswith(".rpm") and not isUrl(a) and os.path.isdir(a):
            b = []
            for c in os.listdir(a):
                fn = "%s/%s" % (a, c)
                if c.endswith(".rpm"): # and os.path.isfile(fn):
                    b.append(fn)
        for a in b:
            rpm = verifyRpm(a, verify, strict, payload, nodigest, hdrtags,
                keepdata)
            if rpm == None:
                continue
            #f = rpm["requirename"]
            #if f:
            #    print rpm.getFilename()
            #    print f
            if strict or wait:
                repo.append(rpm)
            del rpm
    if strict:
        for rpm in repo:
            rpm.filenames = rpm.getFilenames()
        checkDirs(repo)
        checkSymlinks(repo)
        checkProvides(repo, checkrequires=1)
    if wait:
        import time
        print "ready"
        time.sleep(30)

if __name__ == "__main__":
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
        s = hotshot.stats.load(htfilename)
        s.strip_dirs().sort_stats("time").print_stats(100)
        s.strip_dirs().sort_stats("cumulative").print_stats(100)
        os.unlink(htfilename)
    else:
        main()

# vim:ts=4:sw=4:showmatch:expandtab
