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

#import profile
import rpmconstants, cpio, os.path
import sys, getopt, gzip, cStringIO
from types import StringType, IntType, ListType
from struct import unpack
rpmtag = rpmconstants.rpmtag
rpmsigtag = rpmconstants.rpmsigtag
#import ugid

RPM_CHAR = rpmconstants.RPM_CHAR
RPM_INT8 = rpmconstants.RPM_INT8
RPM_INT16 = rpmconstants.RPM_INT16
RPM_INT32 = rpmconstants.RPM_INT32
RPM_INT64 = rpmconstants.RPM_INT64
RPM_STRING = rpmconstants.RPM_STRING
RPM_BIN = rpmconstants.RPM_BIN
RPM_STRING_ARRAY = rpmconstants.RPM_STRING_ARRAY
RPM_I18NSTRING = rpmconstants.RPM_I18NSTRING


# limit: does not support all RHL5.x and earlier rpms if verify is enabled
class ReadRpm:

    def __init__(self, filename, verify=None, fd=None, hdronly=None, legacy=1):
        self.filename = filename
        self.issrc = 0
        if filename[-8:] == ".src.rpm" or filename[-10:] == ".nosrc.rpm":
            self.issrc = 1
        self.verify = verify # enable/disable more data checking
        self.fd = fd # filedescriptor
        self.hdronly = hdronly # if only the header is present from a hdlist
        # 1 == check if legacy tags are included, 0 allows more old tags
        # 1 is good for Fedora Core development trees
        self.legacy = legacy

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

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
        self.fd = None

    def __repr__(self):
        return self.hdr.__repr__()

    def __getitem__(self, key):
        try:
            if isinstance(key, StringType):
                return self.hdr[rpmtag[key][0]]
            if isinstance(key, IntType):
                return self.hdr[key]
            # trick to also look at the sig header
            if isinstance(key, ListType):
                if isinstance(key[0], StringType):
                    return self.sig[rpmsigtag[key[0]][0]]
                return self.sig[key[0]]
            self.raiseErr("wrong arg")
        except:
            # XXX: try to catch wrong/misspelled keys here?
            return None

    def parseLead(self, leaddata):
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4scchh66shh16x", leaddata)
        failed = None
        if self.verify:
            if major not in ('\x03', '\x04') or minor != '\x00' or \
                sigtype != 5 or rpmtype not in (0, 1):
                failed = 1
            if osnum not in (1, 255, 256):
                failed = 1
            name = name.rstrip('\x00')
            if self.legacy:
              if os.path.basename(self.filename)[:len(name)] != name:
                failed = 1
        if failed:
            print major, minor, rpmtype, arch, name, osnum, sigtype
            self.raiseErr("wrong data in rpm lead")
        return (magic, major, minor, rpmtype, arch, name, osnum, sigtype)

    def verifyTag(self, index, fmt, issig):
        (tag, ttype, offset, count) = index
        if issig:
            if not rpmsigtag.has_key(tag):
                self.printErr("rpmsigtag has no tag %d" % tag)
            else:
                t = rpmsigtag[tag]
                if t[1] != None and t[1] != ttype:
                    self.printErr("sigtag %d has wrong type %d" % (tag, ttype))
                if t[2] != None and t[2] != count:
                    self.printErr("sigtag %d has wrong count %d" % (tag, count))
                if (t[3] & 1) and self.legacy:
                    self.printErr("tag %d is marked legacy" % tag)
                if self.issrc:
                    if (t[3] & 4):
                        self.printErr("tag %d should be for binary rpms" % tag)
                else:
                    if (t[3] & 2):
                        self.printErr("tag %d should be for src rpms" % tag)
        else:
            if not rpmtag.has_key(tag):
                self.printErr("rpmtag has no tag %d" % tag)
            else:
                t = rpmtag[tag]
                if t[1] != None and t[1] != ttype:
                    self.printErr("tag %d has wrong type %d" % (tag, ttype))
                if t[2] != None and t[2] != count:
                    self.printErr("tag %d has wrong count %d" % (tag, count))
                if (t[3] & 1) and self.legacy:
                    self.printErr("tag %d is marked legacy" % tag)
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

    def verifyIndex(self, fmt, fmt2, indexNo, storeSize, issig):
        checkSize = 0
        for i in xrange(0, indexNo * 16, 16):
            index = unpack("!iiii", fmt[i:i + 16])
            ttype = index[1]
            # alignment for some types of data
            if ttype == RPM_INT16:
                checkSize += (2 - (checkSize % 2)) % 2
            elif ttype == RPM_INT32:
                checkSize += (4 - (checkSize % 4)) % 4
            elif ttype == RPM_INT64:
                checkSize += (8 - (checkSize % 8)) % 8
            checkSize += self.verifyTag(index, fmt2, issig)
        if checkSize != storeSize:
            # XXX: add a check for very old rpm versions here, seems this
            # is triggered for a few RHL5.x rpm packages
            self.printErr("storeSize/checkSize is %d/%d" % (storeSize,
                checkSize))

    def readIndex(self, pad, issig=None):
        data = self.fd.read(16)
        if not len(data):
            return None
        (magic, indexNo, storeSize) = unpack("!8sii", data)
        if magic != "\x8e\xad\xe8\x01\x00\x00\x00\x00" or indexNo < 1:
            self.raiseErr("bad index magic")
        fmt = self.fd.read(16 * indexNo)
        fmt2 = self.fd.read(storeSize)
        padfmt = ""
        if pad != 1:
            padfmt = self.fd.read((pad - (storeSize % pad)) % pad)
        if self.verify:
            self.verifyIndex(fmt, fmt2, indexNo, storeSize, issig)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + \
            len(fmt2) + len(padfmt))

    def parseTag(self, index, fmt):
        (tag, ttype, offset, count) = index
        if ttype == RPM_INT32:
            return unpack("!%dI" % count, fmt[offset:offset + count * 4])
        elif ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
            data = []
            for i in xrange(0, count):
                end = fmt.index('\x00', offset)
                data.append(fmt[offset:end])
                offset = end + 1
            return data
        elif ttype == RPM_STRING:
            return fmt[offset:fmt.index('\x00', offset)]
        elif ttype == RPM_CHAR:
            return unpack("!%dc" % count, fmt[offset:offset + count])
        elif ttype == RPM_INT8:
            return unpack("!%dB" % count, fmt[offset:offset + count])
        elif ttype == RPM_INT16:
            return unpack("!%dH" % count, fmt[offset:offset + count * 2])
        elif ttype == RPM_INT64:
            return unpack("!%dQ" % count, fmt[offset:offset + count * 8])
        elif ttype == RPM_BIN:
            return fmt[offset:offset + count]
        self.raiseErr("unknown tag header")
        return None

    def parseIndex(self, indexNo, fmt, fmt2, tags=None):
        # XXX parseIndex() should be implemented as C function for faster speed
        hdr = {}
        hdrtype = {}
        for i in xrange(0, indexNo * 16, 16):
            index = unpack("!4i", fmt[i:i + 16])
            tag = index[0]
            # support reading only some tags
            if tags and tag not in tags:
                continue
            # ignore duplicate entries as long as they are identical
            if hdr.has_key(tag):
                if hdr[tag] != self.parseTag(index, fmt2):
                    self.printErr("tag %d included twice" % tag)
            else:
                hdr[tag] = self.parseTag(index, fmt2)
                hdrtype[tag] = index[1]
        return (hdr, hdrtype)

    def verifyHeader(self):
        if self.hdronly:
            return
        self.cpiosize = self[["payloadsize"]][0]
        # header + payload size
        self.payloadsize = self[["size_in_sig"]][0] - self.hdrdata[5]
        identifysig = self[["header_signatures"]]
        sha1 = self[["sha1header"]] # header
        md5sum = self[["md5"]] # header + payload
        dsa = self[["dsaheader"]] # header
        gpg = self[["gpg"]] # header + payload

    def parseHeader(self, tags=None, parsesig=None):
        if (self.verify or parsesig) and not self.hdronly:
            (sigindexNo, sigstoreSize, sigdata, sigfmt, sigfmt2, size) = \
                self.sigdata
            (self.sig, self.sigtype) = self.parseIndex(sigindexNo, sigfmt, \
                sigfmt2)
            if self.verify:
                for i in rpmconstants.rpmsigtagrequired:
                    if not self.sig.has_key(i):
                        self.printErr("sig header is missing: %d" % i)
        (hdrindexNo, hdrstoreSize, hdrdata, hdrfmt, hdrfmt2, size) = \
            self.hdrdata
        (self.hdr, self.hdrtype) = self.parseIndex(hdrindexNo, hdrfmt, \
            hdrfmt2, tags)
        
        if self.verify:
            for i in rpmconstants.rpmtagrequired:
                if not self.hdr.has_key(i):
                    self.printErr("hdr is missing: %d" % i)
            self.verifyHeader()

    def readHeader(self, parse=1, tags=None, keepdata=None):
        self.openFd()
        leaddata = self.fd.read(96)
        if leaddata[:4] != '\xed\xab\xee\xdb':
            self.printErr("no rpm magic found")
            return 1
        if self.verify:
            self.parseLead(leaddata)
        self.sigdata = self.readIndex(8, 1)
        self.hdrdata = self.readIndex(1)
        if keepdata:
            self.leaddata = leaddata
        if parse:
            self.parseHeader(tags)
        return None

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
            if self.verify and self.payloadsize != len(payload):
                self.raiseErr("payloadsize")
            if payload[:9] != '\037\213\010\000\000\000\000\000\000':
                self.raiseErr("not gzipped data")
            #cpiodata = zlib.decompress(payload)
            return None
        else:
            gz = gzip.GzipFile(fileobj=self.fd)
            cpiodata = gz.read()
            #while 1:
            #    buf = gz.read(4096)
            #    if not buf:
            #        break
        if self.verify and self.cpiosize != len(cpiodata):
            self.raiseErr("cpiosize")
        if 1:
            c = cpio.CPIOFile(cStringIO.StringIO(cpiodata))
            try:
                c.read()
            except IOError, e:
                print "Error reading CPIO payload: %s" % e
            if verbose:
                print c.namelist()
        self.closeFd()
        if keepdata:
            self.cpiodata = cpiodata
        if self.verify:
            return self.verifyPayload(c.namelist())
        return None

    def verifyPayload(self, cpiofiletree=None):
        hdrfiletree = self.parseFilelist()
        if cpiofiletree == None:
            return 0
        for filename in cpiofiletree.keys():
            cpiostat = cpiofiletree[filename]
            if filename not in hdrfiletree.keys():
                print "Error "+filename+" not in header tags"
                return 1
            hdrstat = hdrfiletree[filename]
            if cpiostat[1] != hdrstat[1]:
                print "Error inode is different for file "+filename
                print cpiostat[1]+" != "+hdrstat[1]
                return 1
            if cpiostat[2] != hdrstat[2]:
                print "Error mode is different for file "+filename
                print cpiostat[2]+" != "+hdrstat[2]
                return 1
# XXX: Need to convert hdr username and groupname to uid and gid
#            if cpiostat[3] != hdrstat[3]:
#                print "Error uid is different for file "+filename
#                print cpiostat[3]+" != "+hdrstat[3]
#                return 1
#            if cpiostat[4] != hdrstat[4]:
#                print "Error gid is different for file "+filename
#                print cpiostat[4]+" != "+hdrstat[4]
#                return 1
# XXX: Leave that alone. Nlink is for hardlinks, not in rpm headers...
#            if hdrstat[5] != "" and cpiostat[5] != hdrstat[5]:
#                print "Error nlinks is different for file "+filename
#                print str(cpiostat[5])+" != "+hdrstat[5]
#                return 1
            if cpiostat[6] != hdrstat[6]:
                print "Error filesize is different for file "+filename
                print cpiostat[6]+" != "+hdrstat[6]
                return 1
# XXX: Starting from entry 7 no entries are usable anymore, so leave them...
        return 0

    def getScript(self, s, p):
        script = self[s]
        prog = self[p]
        if script == None and prog == None:
            return (None, None)
        if self.verify:
            if script and prog == None:
                self.raiseErr("no prog")
            if self.legacy:
              if prog not in ("/bin/sh", "/sbin/ldconfig", "/usr/bin/fc-cache",
                "/usr/sbin/glibc_post_upgrade", "/usr/sbin/libgcc_post_upgrade",
                "/usr/sbin/glibc_post_upgrade.i386",
                "/usr/sbin/glibc_post_upgrade.i686",
                "/usr/sbin/build-locale-archive",
                "/usr/bin/scrollkeeper-update"):
                self.raiseErr("unknown prog: %s" % prog)
        return (script, prog)

    def getNVR(self):
        return "%s-%s-%s" % (self["name"], self["version"], self["release"])

    def getNA(self):
        return "%s.%s" % (self["name"], self["arch"])

    def getFilename(self):
        return "%s-%s-%s.%s.rpm" % (self["name"], self["version"],
            self["release"], self["arch"])

    def getDeps(self, name, flags, version):
        n = self[name]
        if not n:
            return None
        f = self[flags]
        v = self[version]
        if f == None or v == None or len(n) != len(f) or len(f) != len(v):
            if f != None or v != None:
                self.raiseErr("wrong length of deps")
        deps = []
        for i in xrange(0, len(n)):
            if f != None:
                deps.append( (n[i], f[i], v[i]) )
            else:
                deps.append( (n[i], None, None) )
        return deps

    def getProvides(self):
        return self.getDeps("providename", "provideflags", "provideversion")

    def getRequires(self):
        return self.getDeps("requirename", "requireflags", "requireversion")

    def getObsoletes(self):
        return self.getDeps("obsoletename", "obsoleteflags", "obsoleteversion")

    def getConflicts(self):
        return self.getDeps("conflictname", "conflictflags", "conflictversion")

    def getTriggers(self):
        return self.getDeps("triggername", "triggerflags", "triggerversion")

    def buildFileNames(self):
        """Returns (dir, filename, linksto, flags)."""
        if self["dirnames"] == None or self["dirindexes"] == None:
            return []
        dirnames = [ self["dirnames"][index] 
                     for index in self["dirindexes"]
                   ]
        return zip (dirnames, self["basenames"], self["fileflags"],
                    self["fileinodes"], self["filemodes"],
                    self["fileusername"], self["filegroupname"],
                    self["filelinktos"], self["filemtimes"],
                    self["filesizes"], self["filedevices"],
                    self["filerdevs"], self["filelangs"],
                    self["filemd5s"]
                )

    def parseFilelist(self):
        fl = {}
        for perm in self.buildFileNames():
            fl[perm[0] + perm[1]] = perm[2:]
        return fl


class RRpm:
    def __init__(self, rpm):
        self.filename = rpm.filename
        self.name = rpm["name"]
        self.version = rpm["version"]
        self.release = rpm["release"]
        self.epoch = rpm["epoch"]
        if self.epoch:
            self.epoch = self.epoch[0]
            evr = str(self.epoch) + ":" + self.version + "-" + self.release
        else:
            evr = self.version + "-" + self.release
        self.dep = (self.name, rpmconstants.RPMSENSE_EQUAL, evr)
        self.arch = rpm["arch"]

        #self.hdrfiletree = rpm.parseFilelist()
        #self.filetree = rpm.buildFileNames()
        self.basenames = rpm["basenames"]
        self.dirnames = rpm["dirnames"]

        self.provides = rpm.getProvides()
        self.requires = rpm.getRequires()
        self.obsoletes = rpm.getObsoletes()
        self.conflicts = rpm.getConflicts()

        (self.pre, self.preprog) = rpm.getScript("prein", "preinprog")
        (self.post, self.postprog) = rpm.getScript("postin", "postinprog")
        (self.preun, self.preunprog) = rpm.getScript("preun", "preunprog")
        (self.postun, self.postunprog) = rpm.getScript("postun", "postunprog")
        (self.verify, self.verifyprog) = rpm.getScript("verifyscript",
            "verifyscriptprog")

        self.triggers = rpm.getTriggers()
        self.triggerindex = rpm["triggerindex"]
        self.trigger = rpm["triggerscripts"]
        self.triggerprog = rpm["triggerscriptprog"]
        if self.trigger != None:
            if len(self.trigger) != len(self.triggerprog):
                raise ValueError, "wrong trigger lengths"
        # legacy:
        self.triggerin = rpm["triggerin"]
        self.triggerun = rpm["triggerun"]
        self.triggerpostun = rpm["triggerpostun"]

        #self.uids = uids
        #self.gids = gids

        if "-" in self.version:
            self.printErr("version contains wrong char")
        if rpm["payloadformat"] not in [None, "cpio"]:
            self.printErr("wrong payload format")
        if rpm["payloadcompressor"] not in [None, "gzip"]:
            self.printErr("no gzip compressor: %s" % rpm["payloadcompressor"])
        if rpm.legacy:
          if rpm["payloadflags"] not in ["9"]:
            self.printErr("no payload flags: %s" % rpm["payloadflags"])
        if rpm["os"] not in ["Linux", "linux"]:
            self.printErr("bad os: %s" % rpm["os"])
        if rpm.legacy:
          if rpm["packager"] not in (None, \
            "Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>"):
            self.printErr("unknown packager: %s" % rpm["packager"])
          if rpm["vendor"] not in (None, "Red Hat, Inc."):
            self.printErr("unknown vendor: %s" % rpm["vendor"])
          if rpm["distribution"] not in (None, "Red Hat Linux", "Red Hat FC-3",
            "Red Hat (FC-3)", "Red Hat (RHEL-3)", "Red Hat (FC-4)"):
            self.printErr("unknown distribution: %s" % rpm["distribution"])
        if rpm["rhnplatform"] not in (None, self.arch):
            self.printErr("unknown arch for rhnplatform")
        if rpm["platform"] not in (None, self.arch + "-redhat-linux-gnu",
            self.arch + "-redhat-linux", "--target=${target_platform}",
            self.arch + "-unknown-linux",
            "--target=${TARGET_PLATFORM}", "--target=$TARGET_PLATFORM", ""):
            self.printErr("unknown arch %s" % rpm["platform"])
        if rpm["exclusiveos"] not in (None, ['Linux'], ['linux']):
            self.printErr("unknown os %s" % rpm["exclusiveos"])
        if rpm.legacy:
          if rpm["buildarchs"] not in (None, ['noarch']):
            self.printErr("bad buildarch: %s" % rpm["buildarchs"])
        if rpm["excludearch"] != None:
            for i in rpm["excludearch"]:
                if i not in rpmconstants.possible_archs:
                    self.printErr("new possible arch %s" % i)
        if rpm["exclusivearch"] != None:
            for i in rpm["exclusivearch"]:
                if i not in rpmconstants.possible_archs:
                    self.printErr("new possible arch %s" % i)

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)


def verifyRpm(filename, payload=None):
    """Read in a complete rpm and verify its integrity."""
    rpm = ReadRpm(filename, 1, legacy=1)
    #nochangelog = [rpmconstants.RPMTAG_CHANGELOGTIME,
    #    rpmconstants.RPMTAG_CHANGELOGNAME, rpmconstants.RPMTAG_CHANGELOGTEXT]
    if rpm.readHeader():
        return None
    if payload:
        rpm.readPayload()
    rpm.closeFd()
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
    import re
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

def verifyAllRpms():
    import time
    repo = []
    for a in sys.argv[1:]:
        rpm = verifyRpm(a)
        if rpm != None:
            f = rpm["dirnamesxxx"]
            if f:
                print rpm.getFilename()
                print f
            rrpm = RRpm(rpm)
            repo.append(rrpm)
    print "ready"
    time.sleep(30)

if __name__ == "__main__":
    if None:
        rpms = readHdlist("/home/fedora/i386/Fedora/base/hdlist", 1)
        for rpm in rpms:
            print rpm.getFilename()
        rpms = readHdlist("/home/fedora/i386/Fedora/base/hdlist2", 1)
        sys.exit(0)
    if 1:
        #profile.run("verifyAllRpms()")
        verifyAllRpms()
        sys.exit(0)
    main(sys.argv[1:])

# vim:ts=4:sw=4:showmatch:expandtab
