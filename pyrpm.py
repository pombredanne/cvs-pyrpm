#!/usr/bin/python2.2
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
# Copyright 2004 Red Hat, Inc.
#

import struct
import rpmconstants
import cpio
import os.path
import re
import sys
import getopt
#import zlib
import gzip
import cStringIO

def parseLead(leaddata, fname=None, verify=1):
    """ Takes a python file object at the start of an RPM file and
        reads the lead. """
    (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
        struct.unpack("!4scchh66shh16x", leaddata)
    failed = None
    if magic != '\xed\xab\xee\xdb':
        failed = 1
    if verify:
        if (major != '\x03' and major != '\x04') or minor != '\x00' or \
            sigtype != 5 or rpmtype not in (0, 1):
            failed = 1
        if osnum not in (1, 255, 256):
            failed = 1
        name = name.rstrip('\x00')
        if fname and os.path.basename(fname)[:len(name)] != name:
            failed = 1
    if failed:
        print major, minor, rpmtype, arch, name, osnum, sigtype
        raise ValueError, "%s has wrong data in rpm lead" % fname
    return (magic, major, minor, rpmtype, arch, name, osnum, sigtype)

def verifyTag(index, fmt):
    (tag, ttype, offset, count) = index
    if count == 0:
        raise ValueError, "zero length tag"
    if ttype < 1 or ttype > 9:
        raise ValueError, "unknown rpmtype %d" % ttype
    if ttype == rpmconstants.RPM_INT32:
        count = count * 4
    elif ttype == rpmconstants.RPM_STRING_ARRAY or \
        ttype == rpmconstants.RPM_I18NSTRING:
        size = 0
        for i in xrange(0, count):
            end = fmt.index('\x00', offset) + 1
            size += end - offset
            offset = end
        count = size
    elif ttype == rpmconstants.RPM_STRING:
        if count != 1:
            raise ValueError, "tag string count wrong"
        count = fmt.index('\x00', offset) - offset + 1
    elif ttype == rpmconstants.RPM_CHAR or ttype == rpmconstants.RPM_INT8:
        pass
    elif ttype == rpmconstants.RPM_INT16:
        count = count * 2
    elif ttype == rpmconstants.RPM_INT64:
        count = count * 8
    elif ttype == rpmconstants.RPM_BIN:
        pass
    else:
        raise ValueError, "unknown tag header"
    return count

def verifyIndex(fmt, fmt2, indexNo, storeSize):
    checkSize = 0
    for i in xrange(0, indexNo * 16, 16):
        index = struct.unpack("!iiii", fmt[i:i + 16])
        ttype = index[1]
        # alignment for some types of data
        if ttype == rpmconstants.RPM_INT16:
            checkSize += (2 - (checkSize % 2)) % 2
        elif ttype == rpmconstants.RPM_INT32:
            checkSize += (4 - (checkSize % 4)) % 4
        elif ttype == rpmconstants.RPM_INT64:
            checkSize += (8 - (checkSize % 8)) % 8
        checkSize += verifyTag(index, fmt2)
    if checkSize != storeSize:
       raise ValueError, "storeSize/checkSize is %d/%d" % (storeSize, checkSize)

def readTag(index, fmt):
    (tag, ttype, offset, count) = index
    if ttype == rpmconstants.RPM_INT32:
        data = struct.unpack("!%dI" % count, fmt[offset:offset + count * 4])
    elif ttype == rpmconstants.RPM_STRING_ARRAY or \
        ttype == rpmconstants.RPM_I18NSTRING:
        data = []
        for i in xrange(0, count):
            end = fmt.index('\x00', offset)
            data.append(fmt[offset:end])
            offset = end + 1
    elif ttype == rpmconstants.RPM_STRING:
        data = fmt[offset:fmt.index('\x00', offset)]
    elif ttype == rpmconstants.RPM_CHAR:
        data = struct.unpack("!%dc" % count, fmt[offset:offset + count])
    elif ttype == rpmconstants.RPM_INT8:
        data = struct.unpack("!%dB" % count, fmt[offset:offset + count])
    elif ttype == rpmconstants.RPM_INT16:
        data = struct.unpack("!%dH" % count, fmt[offset:offset + count * 2])
    elif ttype == rpmconstants.RPM_INT64:
        data = struct.unpack("!%dQ" % count, fmt[offset:offset + count * 8])
    elif ttype == rpmconstants.RPM_BIN:
        data = fmt[offset:offset + count]
    else:
        raise ValueError, "unknown tag header"
    return data

def readIndex(filename, f, pad, verify=0, skip=0, tags=None):
    data = f.read(16)
    (magic, indexNo, storeSize) = struct.unpack("!8sii", data)
    if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
        raise ValueError, "bad magic"
    fmt = f.read(16 * indexNo)
    fmt2 = f.read(storeSize + (pad - (storeSize % pad)) % pad)
    if skip:
        return None
    if verify:
        verifyIndex(fmt, fmt2, indexNo, storeSize)
    hdr = {}
    for i in xrange(0, indexNo * 16, 16):
        index = struct.unpack("!iiii", fmt[i:i + 16])
        tag = index[0]
        if tags and tag not in tags:
            continue
        if hdr.has_key(tag):
            if hdr[tag] != readTag(index, fmt2):
                print "%s included tag %d twice" % (filename, tag)
        else:
            hdr[tag] = readTag(index, fmt2)
    return (hdr, len(fmt) + len(fmt2), data + fmt + fmt2)

sigkeys = [
    rpmconstants.RPMSIGTAG_SIZE,
    rpmconstants.HEADER_SIGNATURES,
    rpmconstants.RPMSIGTAG_PAYLOADSIZE,
    rpmconstants.RPMTAG_SHA1HEADER,
    rpmconstants.RPMSIGTAG_MD5,
    rpmconstants.RPMTAG_DSAHEADER,
    rpmconstants.RPMSIGTAG_GPG
]
reqsig = [
    rpmconstants.HEADER_SIGNATURES,
    rpmconstants.RPMSIGTAG_PAYLOADSIZE,
    rpmconstants.RPMTAG_SHA1HEADER,
    rpmconstants.RPMSIGTAG_MD5
]

def verifyHeader(sigindex, hdr, hdrsize, payloadsize, cpiosize):
    for i in sigindex.keys():
        if i not in sigkeys:
            raise ValueError, "new item in sigindex: %d" % i
    for i in reqsig:
        if i not in sigindex.keys():
            print "rpm has broken header:", hdr[rpmconstants.RPMTAG_NAME]
            #raise ValueError, "key not present in sig: %d" % i
            return
    size = sigindex[rpmconstants.RPMSIGTAG_SIZE][0] # header + payload
    #if size != hdrsize + payloadsize + 16:
    #    print size, hdrsize, payloadsize, hdrsize+payloadsize
    #    raise ValueError, "size"
    identifysig = sigindex[rpmconstants.HEADER_SIGNATURES] # what data is in here?
    # uncompressed payload
    if cpiosize != sigindex[rpmconstants.RPMSIGTAG_PAYLOADSIZE][0]:
        print cpiosize, sigindex[rpmconstants.RPMSIGTAG_PAYLOADSIZE]
        raise ValueError, "cpio size"
    sha1 = sigindex[rpmconstants.RPMTAG_SHA1HEADER] # header
    md5sum = sigindex[rpmconstants.RPMSIGTAG_MD5] # header + payload
    if sigindex.has_key(rpmconstants.RPMTAG_DSAHEADER):
        dsa = sigindex[rpmconstants.RPMTAG_DSAHEADER] # header
        gpg = sigindex[rpmconstants.RPMSIGTAG_GPG] # header + payload

def parseHeader(f, filename, verify=0, tags=None):
    leaddata = f.read(96)
    lead = parseLead(leaddata, filename, verify)
    skip = 0
    (sigindex, dummy, sigdata) = readIndex(filename, f, 8, verify, skip, tags)
    (hdr, hdrsize, hdrdata) = readIndex(filename, f, 1, verify, skip, tags)
    #payload = f.read()
    #if payload[:9] != '\037\213\010\000\000\000\000\000\000':
    #    raise ValueError, "nnot gzipped data"
    #cpiodata = zlib.decompress(payload)
    payload = ""
    gz = gzip.GzipFile(fileobj=f)
    cpiodata = gz.read()
    c = cpio.CPIOFile(cStringIO.StringIO(cpiodata))
    try:
        c.read()
    except IOError, e:
        print "Error reading CPIO payload: %s" % e
    print c.namelist()
        
    #while 1:
    #    buf = gz.read(4096)
    #    if not buf:
    #        break
    if verify:
        verifyHeader(sigindex, hdr, hdrsize, len(payload), len(cpiodata))
    return (lead, sigindex, hdr)

class RpmHeader:
    def __init__(self, name, verify=1, tags=None):
        self.readHeader(name, verify, tags)

    def readHeader(self, filename, verify=1, tags=None):
        try:
            fd = open(filename, "ro")
        except:
            print "could not open file: %s" % filename
            return
        (self.lead, self.sigindex, self.hdr) = parseHeader(fd, filename,
            verify, tags)
        fd.close()

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
        rpm = RpmHeader(a)
        sys.stdout.write(queryformat % rpm)

if __name__ == "__main__":
    #for a in sys.argv[1:]:
    #    rpm = RpmHeader(a)
    main(sys.argv[1:])

# vim:ts=4:sw=4:showmatch:expandtab
