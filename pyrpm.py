#!/usr/bin/python
#!/usr/bin/python2.2
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
# Copyright 2004 Red Hat, Inc.
#
# Author: Paul Nasrat, Florian La Roche
#

import struct, rpmconstants, cpio, os.path, re, sys, getopt, gzip, cStringIO

# in verify mode only allow newer rpm packages
strict = 1

# optional keys in the sig header
sigkeys = [
#   rpmconstants.RPMSIGTAG_PGP,
#   rpmconstants.RPMTAG_BADSHA1_2,
    rpmconstants.RPMTAG_DSAHEADER,
    rpmconstants.RPMSIGTAG_GPG
]
# required keys in the sig header
reqsig = [
    rpmconstants.HEADER_SIGNATURES,
    rpmconstants.RPMSIGTAG_PAYLOADSIZE,
    rpmconstants.RPMSIGTAG_SIZE,
    rpmconstants.RPMTAG_SHA1HEADER,
    rpmconstants.RPMSIGTAG_MD5
]

# rpm tag types
#RPM_NULL = 0
RPM_CHAR = 1
RPM_INT8 = 2
RPM_INT16 = 3
RPM_INT32 = 4
RPM_INT64 = 5 # currently unused
RPM_STRING = 6
RPM_BIN = 7
RPM_STRING_ARRAY = 8
RPM_I18NSTRING = 9

# limit: does not support all RHL5.x and earlier rpms if verify is enabled
class ReadRpm:
    # self.filename == filename
    # self.fd == filedescriptor
    # self.verify == enable/disable more data checking

    def __init__(self, filename, verify=None):
        self.filename = filename
        self.fd = None
        self.verify = verify

    def raiseErr(self, err):
        raise ValueError, "%s: %s" % (self.filename, err)

    def openFd(self, offset=None):
        if not self.fd:
            try:
                self.fd = open(self.filename, "ro")
            except:
                self.raiseErr("could not open file")
            if offset:
                self.fd.seek(offset, 1)

    def closeFd(self):
        if self.fd:
            self.fd.close()
            self.fd = None

    def parseLead(self, leaddata):
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            struct.unpack("!4scchh66shh16x", leaddata)
        failed = None
        if self.verify:
            if (major != '\x03' and major != '\x04') or minor != '\x00' or \
                sigtype != 5 or rpmtype not in (0, 1):
                failed = 1
            if osnum not in (1, 255, 256):
                failed = 1
            name = name.rstrip('\x00')
            if os.path.basename(self.filename)[:len(name)] != name:
                failed = 1
        if failed:
            print major, minor, rpmtype, arch, name, osnum, sigtype
            self.raiseErr("wrong data in rpm lead")
        return (magic, major, minor, rpmtype, arch, name, osnum, sigtype)

    def verifyTag(self, index, fmt):
        (tag, ttype, offset, count) = index
        if count == 0:
            self.raiseErr("zero length tag")
        if ttype < 1 or ttype > 9:
            self.raiseErr("unknown rpmtype %d" % ttype)
        if ttype == RPM_INT32:
            count = count * 4
        elif ttype == RPM_STRING_ARRAY or \
            ttype == RPM_I18NSTRING:
            size = 0
            for i in xrange(0, count):
                end = fmt.index('\x00', offset) + 1
                size += end - offset
                offset = end
            count = size
        elif ttype == RPM_STRING:
            if count != 1:
                self.raiseErr("tag string count wrong")
            count = fmt.index('\x00', offset) - offset + 1
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

    def verifyIndex(self, fmt, fmt2, indexNo, storeSize):
        checkSize = 0
        for i in xrange(0, indexNo * 16, 16):
            index = struct.unpack("!iiii", fmt[i:i + 16])
            ttype = index[1]
            # alignment for some types of data
            if ttype == RPM_INT16:
                checkSize += (2 - (checkSize % 2)) % 2
            elif ttype == RPM_INT32:
                checkSize += (4 - (checkSize % 4)) % 4
            elif ttype == RPM_INT64:
                checkSize += (8 - (checkSize % 8)) % 8
            checkSize += self.verifyTag(index, fmt2)
        if checkSize != storeSize:
            self.raiseErr("storeSize/checkSize is %d/%d" % (storeSize,
                checkSize))

    def readIndex(self, pad):
        data = self.fd.read(16)
        (magic, indexNo, storeSize) = struct.unpack("!8sii", data)
        if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
            self.raiseErr("bad index magic")
        fmt = self.fd.read(16 * indexNo)
        fmt2 = self.fd.read(storeSize + (pad - (storeSize % pad)) % pad)
        if self.verify:
            self.verifyIndex(fmt, fmt2, indexNo, storeSize)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + len(fmt2))

    def parseTag(self, index, fmt):
        (tag, ttype, offset, count) = index
        if ttype == RPM_INT32:
            data = struct.unpack("!%dI" % count, fmt[offset:offset + count * 4])
        elif ttype == RPM_STRING_ARRAY or \
            ttype == RPM_I18NSTRING:
            data = []
            for i in xrange(0, count):
                end = fmt.index('\x00', offset)
                data.append(fmt[offset:end])
                offset = end + 1
        elif ttype == RPM_STRING:
            data = fmt[offset:fmt.index('\x00', offset)]
        elif ttype == RPM_CHAR:
            data = struct.unpack("!%dc" % count, fmt[offset:offset + count])
        elif ttype == RPM_INT8:
            data = struct.unpack("!%dB" % count, fmt[offset:offset + count])
        elif ttype == RPM_INT16:
            data = struct.unpack("!%dH" % count, fmt[offset:offset + count * 2])
        elif ttype == RPM_INT64:
            data = struct.unpack("!%dQ" % count, fmt[offset:offset + count * 8])
        elif ttype == RPM_BIN:
            data = fmt[offset:offset + count]
        else:
            raise ValueError, "unknown tag header"
        return data

    def parseIndex(self, indexNo, fmt, fmt2, tags=None):
        hdr = {}
        for i in xrange(0, indexNo * 16, 16):
            index = struct.unpack("!iiii", fmt[i:i + 16])
            tag = index[0]
            if tags and tag not in tags:
                continue
            # ignore duplicate entries as long as they are identical
            if hdr.has_key(tag) and hdr[tag] != self.parseTag(index, fmt2):
                print "%s included tag %d twice" % (self.filename, tag)
            else:
                hdr[tag] = self.parseTag(index, fmt2)
        return hdr

    def verifyHeader(self):
        if not strict:
            return
        for i in self.sig.keys():
            if i not in sigkeys and i not in reqsig:
                self.raiseErr("new item in sigindex: %d" % i)
        for i in reqsig:
            if i not in self.sig.keys():
                self.raiseErr("key not present in sig: %d" % i)
        self.cpiosize = self.sig[rpmconstants.RPMSIGTAG_PAYLOADSIZE][0]
        # header + payload size
        self.payloadsize = self.sig[rpmconstants.RPMSIGTAG_SIZE][0] \
            - self.hdrdata[5]
        # XXX: what data is in here?
        identifysig = self.sig[rpmconstants.HEADER_SIGNATURES]
        sha1 = self.sig[rpmconstants.RPMTAG_SHA1HEADER] # header
        md5sum = self.sig[rpmconstants.RPMSIGTAG_MD5] # header + payload
        if self.sig.has_key(rpmconstants.RPMTAG_DSAHEADER):
            dsa = self.sig[rpmconstants.RPMTAG_DSAHEADER] # header
            gpg = self.sig[rpmconstants.RPMSIGTAG_GPG] # header + payload

    def parseHeader(self, tags=None, parsesig=None):
        if self.verify or parsesig:
            (sigindexNo, sigstoreSize, sigdata, sigfmt, sigfmt2, size) = \
                self.sigdata
            self.sig = self.parseIndex(sigindexNo, sigfmt, sigfmt2)
        (hdrindexNo, hdrstoreSize, hdrdata, hdrfmt, hdrfmt2, size) = \
            self.hdrdata
        self.hdr = self.parseIndex(hdrindexNo, hdrfmt, hdrfmt2, tags)
        if self.verify:
            self.verifyHeader()

    def readHeader(self, parse=1, tags=None, keepdata=None):
        self.openFd()
        leaddata = self.fd.read(96)
        if leaddata[:4] != '\xed\xab\xee\xdb':
            self.raiseErr("no rpm magic found")
        if self.verify:
            self.parseLead(leaddata)
        self.sigdata = self.readIndex(8)
        self.hdrdata = self.readIndex(1)
        if keepdata:
            self.leaddata = leaddata
        if parse:
            self.parseHeader(tags)

    def readPayload(self, keepdata=None, verbose=None):
        self.openFd(96 + self.sigdata[5] + self.hdrdata[5])
        if None:
            #import zlib
            payload = self.fd.read()
            if strict and self.verify and self.payloadsize != len(payload):
                self.raiseErr("payloadsize")
            if payload[:9] != '\037\213\010\000\000\000\000\000\000':
                self.raiseErr("not gzipped data")
            #cpiodata = zlib.decompress(payload)
            return
        else:
            gz = gzip.GzipFile(fileobj=self.fd)
            cpiodata = gz.read()
            #while 1:
            #    buf = gz.read(4096)
            #    if not buf:
            #        break
        if strict and self.verify and self.cpiosize != len(cpiodata):
            self.raiseErr("cpiosize")
        if None:
            c = cpio.CPIOFile(cStringIO.StringIO(cpiodata))
            try:
                c.read()
            except IOError, e:
                print "Error reading CPIO payload: %s" % e
            if verbose:
                print c.namelist()
        if keepdata:
            self.cpiodata = cpiodata

    def __repr__(self):
        return self.hdr.__repr__()

    def __getitem__(self, key):
        import types
        if isinstance(key, types.IntType):
            return self.hdr[key]
        elif isinstance(key, types.StringType):
            if key[:3] == "RPM":
                return self.hdr[eval("rpmconstants.%s" % key)]
            else:
                # XXX make this a list of supported strings, no eval
                keybyname = eval("rpmconstants.RPMTAG_%s" % key.upper())
                return self.hdr[keybyname]
        return None


class RFile:
    def __init__(self, name, mode, uid, gid, time, flag, md5sum=None, \
        size=None, rdev=None, symlink=None):
        self.name = name
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.time = time
        self.flag = flag
        if md5sum != None: # regular file
            self.md5sum = md5sum
            self.size = size
        if rdev: # block/char device
            self.rdev = rdev
        if symlink: # symlink
            self.symlink = symlink

class RDir:
    def __init__(self, name, mode, uid, gid, time, flag):
        self.name = name
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.time = time
        self.flag = flag
        self.files = {}

    def addFile(self, file):
        name = file.name
        if self.files.has_key(name):
            raise ValueError, "dir %s already contains file %s" % (self.name,
                name)
        self.files[name] = file

class RDep:
    def __init__(self, name, flags, epoch, version, release):
        self.name = name
        self.flags = flags
        self.epoch = epoch
        self.version = version
        self.release = release

class RRpm:
    def __init__(self, dep, arch, provides, requires, conflicts, obsoletes,
        uids, gids):
        self.dep = dep # name, flags, EVR
        self.arch = arch
        self.provides = provides
        self.requires = requires
        self.conflicts = conflicts
        self.obsoletes = obsoletes
        # scripts: pre post preun postun verify trigger
        self.uids = uids
        self.gids = gids

def verifyRpm(filename):
    """Read in a complete rpm and verify its integrity."""
    rpm = ReadRpm(filename, 1)
    rpm.readHeader()
    #rpm.readPayload()
    return rpm

def uncompressRpm(filename):
    """Read in a complete rpm and uncompress its payload."""
    rpm = ReadRpm(filename)
    rpm.readHeader(0, None, 1)
    rpm.closeFd()
    rpm.readPayload(1)
    (sigindexNo, sigstoreSize, sigdata, sigfmt, sigfmt2, ssize) = rpm.sigdata
    (hdrindexNo, hdrstoreSize, hdrdata, hdrfmt, hdrfmt2, hsize) = rpm.hdrdata
    open(os.path.basename(filename), "w").write(rpm.leaddata +
        sigdata + sigfmt + sigfmt2 + hdrdata + hdrfmt + hdrfmt2 + rpm.cpiodata)

def showHelp():
    print "pyrpm [options] /path/to/foo.rpm"
    print
    print "options:"
    print "--help this message"
    print "--queryformat [queryformat] specifying a format to print the query as"
    print "                   see python String Formatting Operations for details"
    print

def queryFormatUnescape(s):
    # Hack to emulate %{name} but not %%{name} and expand escapes
    rpmre = re.compile(r'([^%])%\{(\w+)\}')
    s = re.sub(rpmre, r'\1%(\2)s', s)
    s = s.replace("\\n","\n")
    s = s.replace("\\t","\t")
    s = s.replace('\\"', '\"')
    s = s.replace('\\v','\v')
    s = s.replace('\\r','\r')
    return s

def main(args):
    queryformat="%(name)s-%(version)s-%(release)s\n"
    try:
        opts, args = getopt.getopt(args, "hq", ["help", "queryformat="])
    except getopt.error, e:
        print "Error parsing command list arguments: %s" % e
        showHelp()
        sys.exit(1)

    for (opt, val) in opts:
        if opt in ["-h", "--help"]:
            showHelp()
            sys.exit(1)
        if opt in ['-c', "--queryformat"]:
            queryformat = val 

    if not args:
        print "Error no packages to query"
        showHelp()
        sys.exit(1)

    queryformat = queryFormatUnescape(queryformat)

    for a in args:
        rpm = verifyRpm(a)
        sys.stdout.write(queryformat % rpm)

if __name__ == "__main__":
    for a in sys.argv[1:]:
        if os.path.basename(a) == "reiserfs-utils-3.x.0f-1.src.rpm":
            continue
        rpm = verifyRpm(a)
    #main(sys.argv[1:])

# vim:ts=4:sw=4:showmatch:expandtab
