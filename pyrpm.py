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
rpmtag = rpmconstants.rpmtag

def getPadSize(size, pad):
    """Return padding size if data of size "size" is padded to "pad"
    alignment. Pad is 1 for no padding or e.g. 8."""
    return (pad - (size % pad)) % pad

def getTag(tag):
    """Find the integer tag."""
    import types
    if isinstance(tag, types.IntType):
        return tag
    elif isinstance(tag, types.StringType):
        if tag[:3] == "RPM":
            return eval("rpmconstants.%s" % tag)
        else:
            if rpmtag.has_key(tag):
                return rpmtag[tag]
            return eval("rpmconstants.RPMTAG_%s" % tag.upper())
    return None

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

# optional keys in the sig header
sigkeys = [rpmtag["dsaheader"], rpmtag["gpg"]]
# optional keys for the non-strict case
sigkeys2 = [rpmtag["pgp"], rpmtag["badsha1_2"]]
# required keys in the sig header for the strict case
reqsig = [rpmtag["header_signatures"], rpmtag["payloadsize"],
    rpmtag["size_in_sig"], rpmtag["sha1header"], rpmtag["md5"]]

#   tag                      type        how many, required, strict
ssigkeys = {
    # all required tags for the strict case
    rpmtag["header_signatures"]:(RPM_BIN,None, 1, 1),
    rpmtag["payloadsize"]:  (RPM_INT32,  1,    1, 1),
    rpmtag["size_in_sig"]:  (RPM_INT32,  1,    1, 1),
    rpmtag["sha1header"]:   (RPM_BIN,    None, 1, 1),
    rpmtag["md5"]:          (RPM_BIN,    None, 1, 1),
    # optional tags
    rpmtag["dsaheader"]:    (RPM_BIN,    None, 0, 1),
    rpmtag["gpg"]:          (RPM_BIN,    None, 0, 1),
    # older rpm packages only
    rpmtag["pgp"]:          (RPM_BIN,    None, 0, 0),
    rpmtag["badsha1_2"]:    (RPM_BIN,    None, 0, 0)
}

# limit: does not support all RHL5.x and earlier rpms if verify is enabled
class ReadRpm:

    def __init__(self, filename, verify=None, fd=None, hdronly=None):
        self.filename = filename
        self.fd = fd # filedescriptor
        self.verify = verify # enable/disable more data checking
        self.hdronly = hdronly # if only the header is present from a hdlist
        self.strict = 1 # XXX find some way to switch back to non-strict mode
        # for older rpm packages

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

    def getOneNumber(self, tag, sig=0):
        try:
            if sig:
                num = self.sig[tag]
            else:
                num = self.hdr[tag]
        except:
            return None
        if len(num) != 1:
            print num, len(num)
            raise ValueError, "bad length %d" % len(num)
        return num[0]

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
        if not len(data):
            return None
        (magic, indexNo, storeSize) = struct.unpack("!8sii", data)
        if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
            self.raiseErr("bad index magic")
        fmt = self.fd.read(16 * indexNo)
        fmt2 = self.fd.read(storeSize + getPadSize(storeSize, pad))
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
        # XXX: parseIndex() seems to consume lots of CPU, analyse why
        hdr = {}
        hdrtype = {}
        for i in xrange(0, indexNo * 16, 16):
            index = struct.unpack("!iiii", fmt[i:i + 16])
            tag = index[0]
            if tags and tag not in tags:
                continue
            # ignore duplicate entries as long as they are identical
            if self.strict == 0 and hdr.has_key(tag):
                if hdr[tag] != self.parseTag(index, fmt2):
                    print "%s included tag %d twice" % (self.filename, tag)
            else:
                hdr[tag] = self.parseTag(index, fmt2)
                hdrtype[tag] = index[1]
        return (hdr, hdrtype)

    def addTag(self, tag, data, type, hdr=1):
        # XXX: this should also get implemented as setitem(tag, data, type, hdr)
        if hdr:
            self.hdr[tag] = data
            self.hdrtype[tag] = type
        else:
            self.sig[tag] = data
            self.sigtype[tag] = type

    def newIndex(self, hdr, pad): # XXX not finished yet
        indexNo = len(hdr)
        storeSize = 0
        data = ""
        fmt = ""
        fmt2 = ""
        size = 0
        return (indexNo, storeSize, data, fmt, fmt2, size)

    def writeIndex(self):
        pass # XXX

    def verifyHeader(self):
        if self.hdronly:
            return
        for i in self.sig.keys():
            if i not in sigkeys and i not in reqsig and \
                (not self.strict or i not in sigkeys2):
                self.raiseErr("new item in sigindex: %d" % i)
        if not self.strict:
            return
        for i in reqsig:
            if i not in self.sig.keys():
                self.raiseErr("key not present in sig: %d" % i)
        self.cpiosize = self.getOneNumber("payloadsize", 1)
        # header + payload size
        self.payloadsize = self.getOneNumber(getTag("size_in_sig"), 1) \
            - self.hdrdata[5]
        # XXX: what data is in here?
        identifysig = self.sig[rpmtag["header_signatures"]]
        sha1 = self.sig[rpmtag["sha1header"]] # header
        md5sum = self.sig[rpmtag["md5"]] # header + payload
        if self.sig.has_key(rpmtag["dsaheader"]):
            dsa = self.sig[rpmtag["dsaheader"]] # header
            gpg = self.sig[rpmtag["gpg"]] # header + payload

    def parseHeader(self, tags=None, parsesig=None):
        if (self.verify or parsesig) and not self.hdronly:
            (sigindexNo, sigstoreSize, sigdata, sigfmt, sigfmt2, size) = \
                self.sigdata
            (self.sig, self.sigtype) = self.parseIndex(sigindexNo, sigfmt, \
                sigfmt2)
        (hdrindexNo, hdrstoreSize, hdrdata, hdrfmt, hdrfmt2, size) = \
            self.hdrdata
        (self.hdr, self.hdrtype) = self.parseIndex(hdrindexNo, hdrfmt, \
            hdrfmt2, tags)
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

    def readHdlist(self, parse=1, tags=None):
        self.hdrdata = self.readIndex(1)
        if not self.hdrdata:
            return None
        if parse:
            self.parseHeader(tags)
        return 1

    def readPayload(self, keepdata=None, verbose=None):
        self.openFd(96 + self.sigdata[5] + self.hdrdata[5])
        if None:
            #import zlib
            payload = self.fd.read()
            if self.strict and self.verify and self.payloadsize != len(payload):
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
        if self.strict and self.verify and self.cpiosize != len(cpiodata):
            self.raiseErr("cpiosize")
        if 1:
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
        return self.hdr[getTag(key)]

    def getItem(self, tag):
        try:
            return self[tag]
        except:
            return None

    def getScript(self, s, p):
        script = self.getItem(s)
        prog = self.getItem(p)
        if script and not prog:
            self.raiseErr("no prog")
        if script == None and prog == None:
            return (None, None)
        if prog not in ("/bin/sh", "/sbin/ldconfig", "/usr/bin/fc-cache",
            "/usr/sbin/glibc_post_upgrade", "/usr/sbin/libgcc_post_upgrade",
            "/usr/sbin/build-locale-archive", "/usr/bin/scrollkeeper-update"):
            self.raiseErr("unknown prog: %s" % prog)
        return (script, prog)

    def getNVR(self):
        return "%s-%s-%s" % (self["name"], self["version"], self["release"])

    def getNA(self):
        return "%s-%s" % (self["name"], self["arch"])

    def getFilename(self):
        return "%s-%s-%s.%s.rpm" % (self["name"], self["version"],
            self["release"], self["arch"])

    def getDeps(self, name, flags, version):
        n = self.getItem(name)
        if not n:
            return []
        f = self.hdr[flags]
        v = self.hdr[version]
        deps = []
        for i in xrange(0, len(n)):
            deps.append( (n[i], f[i], v[i]) )
        return deps

    def getProvides(self):
        return self.getDeps(rpmconstants.RPMTAG_PROVIDENAME,
            rpmconstants.RPMTAG_PROVIDEFLAGS,
            rpmconstants.RPMTAG_PROVIDEVERSION)

    def getRequires(self):
        return self.getDeps(rpmconstants.RPMTAG_REQUIRENAME,
            rpmconstants.RPMTAG_REQUIREFLAGS,
            rpmconstants.RPMTAG_REQUIREVERSION)

    def getObsoletes(self):
        return self.getDeps(rpmconstants.RPMTAG_OBSOLETENAME,
            rpmconstants.RPMTAG_OBSOLETEFLAGS,
            rpmconstants.RPMTAG_OBSOLETEVERSION)

    def getConflicts(self):
        return self.getDeps(rpmconstants.RPMTAG_CONFLICTNAME,
            rpmconstants.RPMTAG_CONFLICTFLAGS,
            rpmconstants.RPMTAG_CONFLICTVERSION)

    def getTriggers(self):
        return self.getDeps(rpmconstants.RPMTAG_TRIGGERNAME,
            rpmconstants.RPMTAG_TRIGGERFLAGS,
            rpmconstants.RPMTAG_TRIGGERVERSION)


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
    def __init__(self, name, flags, evr):
        self.name = name
        self.flags = flags
        self.evr = evr

notthere = [rpmconstants.RPMTAG_PREREQ, rpmconstants.RPMTAG_AUTOREQPROV,
    rpmconstants.RPMTAG_AUTOREQ, rpmconstants.RPMTAG_AUTOPROV,
    rpmconstants.RPMTAG_CAPABILITY, rpmconstants.RPMTAG_BUILDCONFLICTS,
    rpmconstants.RPMTAG_BUILDMACROS, rpmconstants.RPMTAG_OLDFILENAMES,
    rpmconstants.RPMTAG_OLDORIGFILENAMES,
    rpmconstants.RPMTAG_ROOT, rpmconstants.RPMTAG_DEFAULTPREFIX,
    rpmconstants.RPMTAG_BUILDROOT, rpmconstants.RPMTAG_INSTALLPREFIX,
    rpmconstants.RPMTAG_EXCLUDEOS, rpmconstants.RPMTAG_DOCDIR,
    rpmconstants.RPMTAG_INSTPREFIXES, rpmconstants.RPMTAG_INSTALLCOLOR,
    rpmconstants.RPMTAG_INSTALLTID, rpmconstants.RPMTAG_REMOVETID,
    rpmconstants.RPMTAG_SHA1RHN,
    rpmconstants.RPMTAG_PATCHESNAME, rpmconstants.RPMTAG_PATCHESFLAGS,
    rpmconstants.RPMTAG_PATCHESVERSION,
    rpmconstants.RPMTAG_CACHECTIME, rpmconstants.RPMTAG_CACHEPKGPATH,
    rpmconstants.RPMTAG_CACHEPKGSIZE, rpmconstants.RPMTAG_CACHEPKGMTIME,
    rpmconstants.RPMTAG_NOSOURCE, rpmconstants.RPMTAG_NOPATCH,
    rpmconstants.RPMTAG_INSTALLTIME]

class RRpm:
    def __init__(self, rpm):
        self.name = rpm[rpmconstants.RPMTAG_NAME]
        self.version = rpm[rpmconstants.RPMTAG_VERSION]
        self.release = rpm[rpmconstants.RPMTAG_RELEASE]
        self.epoch = rpm.getOneNumber(rpmconstants.RPMTAG_EPOCH)
        if self.epoch:
            evr = str(self.epoch) + ":" + self.version + "-" + self.release
        else:
            evr = self.version + "-" + self.release
        self.dep = (self.name, 0, evr) # XXX: 0 is not correct
        self.arch = rpm[rpmconstants.RPMTAG_ARCH]

        self.provides = rpm.getProvides()
        self.requires = rpm.getRequires()
        self.obsoletes = rpm.getObsoletes()
        self.conflicts = rpm.getConflicts()

        (self.pre, self.preprog) = rpm.getScript(rpmconstants.RPMTAG_PREIN,
            rpmconstants.RPMTAG_PREINPROG)
        (self.post, self.postprog) = rpm.getScript(rpmconstants.RPMTAG_POSTIN,
            rpmconstants.RPMTAG_POSTINPROG)
        (self.preun, self.preunprog) = rpm.getScript(rpmconstants.RPMTAG_PREUN,
            rpmconstants.RPMTAG_PREUNPROG)
        (self.postun, self.postunprog) = rpm.getScript( \
            rpmconstants.RPMTAG_POSTUN, rpmconstants.RPMTAG_POSTUNPROG)
        (self.verify, self.verifyprog) = rpm.getScript( \
            rpmconstants.RPMTAG_VERIFYSCRIPT,
            rpmconstants.RPMTAG_VERIFYSCRIPTPROG)

        self.triggers = rpm.getTriggers()
        self.trigger = rpm.getItem(rpmconstants.RPMTAG_TRIGGERSCRIPTS)
        self.triggerprog = rpm.getItem(rpmconstants.RPMTAG_TRIGGERSCRIPTPROG)
        self.triggerindex = rpm.getItem(rpmconstants.RPMTAG_TRIGGERINDEX)
        self.triggerin = rpm.getItem(rpmconstants.RPMTAG_TRIGGERIN)
        self.triggerun = rpm.getItem(rpmconstants.RPMTAG_TRIGGERUN)
        self.triggerpostun = rpm.getItem(rpmconstants.RPMTAG_TRIGGERPOSTUN)

        #self.uids = uids
        #self.gids = gids

        for i in notthere:
            if rpm.getItem(i) != None:
                print "tag %d is still present" % i, rpm.getItem(i)
        if rpm.getItem(rpmconstants.RPMTAG_PAYLOADFORMAT) != "cpio":
            print "no cpio payload"
        if rpm.getItem(rpmconstants.RPMTAG_PAYLOADCOMPRESSOR) != "gzip":
            print "no cpio compressor"
        if rpm.getItem(rpmconstants.RPMTAG_PAYLOADFLAGS) != "9":
            print "no payload flags"
        if rpm.getItem(rpmconstants.RPMTAG_OS) != "linux":
            print "bad os"
        if rpm.getItem(rpmconstants.RPMTAG_PACKAGER) not in ( \
            "Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>"):
            print "unknown packager"
        if rpm.getItem(rpmconstants.RPMTAG_VENDOR) not in ("Red Hat, Inc."):
            print "unknown vendor"
        if rpm.getItem(rpmconstants.RPMTAG_DISTRIBUTION) not in \
            (None, "", "Red Hat Linux", "Red Hat FC-3", "Red Hat (FC-3)",
            "Red Hat (RHEL-3)"):
            print "unknown vendor"
        if rpm.getItem(rpmconstants.RPMTAG_PREFIXES) not in (None, ["/usr"],
            ["/var/named/chroot"], ["/usr/X11R6"], ["/usr/lib/qt-3.3"]):
            print "unknown prefix"
        if rpm.getItem(rpmconstants.RPMTAG_RHNPLATFORM) not in (None,
            self.arch):
            print "unknown arch"
        if rpm.getItem(rpmconstants.RPMTAG_PLATFORM) not in ( \
            None, "i386-redhat-linux-gnu", "i386-redhat-linux",
            "noarch-redhat-linux-gnu", "i686-redhat-linux-gnu",
            "i586-redhat-linux-gnu"):
            print "unknown arch", rpm.getItem(rpmconstants.RPMTAG_PLATFORM)


def verifyRpm(filename, payload=None):
    """Read in a complete rpm and verify its integrity."""
    rpm = ReadRpm(filename, 1)
    rpm.readHeader()
    if payload:
        rpm.readPayload()
    return rpm

def readHdlist(filename, verify=None):
    fd = open(filename, "ro")
    rpms = []
    while 1:
        rpm = ReadRpm(filename, verify, fd, 1)
        if not rpm.readHdlist():
            break
        rpms.append(rpm)
    return rpms

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
    if None:
        rpms = readHdlist("/home/hdlist")
        for rpm in rpms:
            print rpm.getFilename()
        rpms = readHdlist("/home/hdlist2")
        sys.exit(0)
    if None:
        for a in sys.argv[1:]:
            if os.path.basename(a) == "reiserfs-utils-3.x.0f-1.src.rpm":
                continue
            rpm = verifyRpm(a)
            rrpm = RRpm(rpm)
        sys.exit(0)
    main(sys.argv[1:])

# vim:ts=4:sw=4:showmatch:expandtab
