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
# Author: Phil Knirsch, Thomas Woerner, Florian LaRoche
#

import rpmconstants, cpio
import os.path, popen2, tempfile, sys, gzip, pwd, grp
from types import StringType, IntType, ListType
from struct import unpack
rpmtag = rpmconstants.rpmtag
rpmsigtag = rpmconstants.rpmsigtag

RPM_CHAR = rpmconstants.RPM_CHAR
RPM_INT8 = rpmconstants.RPM_INT8
RPM_INT16 = rpmconstants.RPM_INT16
RPM_INT32 = rpmconstants.RPM_INT32
RPM_INT64 = rpmconstants.RPM_INT64
RPM_STRING = rpmconstants.RPM_STRING
RPM_BIN = rpmconstants.RPM_BIN
RPM_STRING_ARRAY = rpmconstants.RPM_STRING_ARRAY
RPM_I18NSTRING = rpmconstants.RPM_I18NSTRING
RPM_ARGSTRING = rpmconstants.RPM_ARGSTRING


class RpmError:
    def __init__(self):
        pass

    def printErr(self, err):
        print "%s: %s" % (self.filename, err)

    def raiseErr(self, err):
        raise ValueError, "%s: %s" % (self.filename, err)


class RpmIO(RpmError):
    """'Virtual' IO Class for RPM packages and data"""
    def __init__(self):
        RpmError.__init__(self)

    def open(self):
        return 1

    def read(self):
        return 1

    def write(self):
        return 1

    def close(self):
        return 1


class RpmStreamIO(RpmIO):
    def __init__(self, verify=None, legacy=None, parsesig=None, hdronly=None, tags=None, ntags=None):
        self.fd = None
        self.verify = verify
        self.legacy = legacy
        self.parsesig = parsesig
        self.hdronly = hdronly
        self.tags = tags
        self.ntags = ntags
        self.issrc = 0
        self.where = 0  # 0:lead 1:separator 2:sig 3:header 4:files
        self.idx = 0 # Current index
        self.hdr = {}
        self.hdrtype = {}

    def open(self):
        return 1

    def close(self):
        return 1

    def read(self):
        if self.fd == None:
            self.open()
        if self.fd == None:
            return (None, None)
        # Read/check leadata
        if self.where == 0:
            self.where = 1
            return self.readLead()
        # Separator
        if self.where == 1:
            self.readSig()
            # Shall we skip signature parsing/reading?
            if (self.verify or self.parsesig) and not self.hdronly:
                self.where = 2
            else:
                self.readHdr()
                self.where = 3
            return ("-", "")
        # Read/parse signature
        if self.where == 2:
            # Last index of sig? Switch to from sig to hdr
            if self.idx >= self.sigdata[0]:
                self.readHdr()
                self.idx = 0
                self.where = 3
                return ("-", "")
            v = self.getNextHeader(self.idx, self.sigdata[3], self.sigdata[4])
            self.idx += 1
            return v
        # Read/parse hdr
        if self.where == 3:
            # Last index of hdr? Switch to data files archive
            if self.idx >= self.hdrdata[0]:
                self.cpiofd = gzip.GzipFile(fileobj=self.fd)
                self.cpio = cpio.CPIOFile(self.cpiofd)
                self.where = 4
                return ("-", "")
            v =  self.getNextHeader(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            return v
        # Read/parse data files archive
        if self.where == 4:
            v = self.cpio.getNextEntry()
            if v[0] != None:
                return v
        return  ("EOF", "", "")

    def readLead(self):
        leaddata = self.fd.read(96)
        if leaddata[:4] != '\xed\xab\xee\xdb':
            self.printErr("no rpm magic found")
            return (None, None)
        if self.verify and self.verifyLead(leaddata):
            return (None, None)
        return ("magic", leaddata[:4])

    def readSig(self):
        self.sigdata = self.readIndex(8, 1)

    def readHdr(self):
        self.hdrdata = self.readIndex(1)

    def getNextHeader(self, idx, indexdata, storedata):
        index = unpack("!4i", indexdata[idx*16:(idx+1)*16])
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.parseTag(index, storedata):
                self.printErr("tag %d included twice" % tag)
        else: 
            self.hdr[tag] = self.parseTag(index, storedata)
            self.hdrtype[tag] = index[1]
        return (rpmconstants.rpmtagname[tag], self.hdr[tag])

    def verifyLead(self, leaddata):
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4scchh66shh16x", leaddata)
        ret = None
        if major not in ('\x03', '\x04') or minor != '\x00' or \
            sigtype != 5 or rpmtype not in (0, 1):
            ret = 1
        if osnum not in (1, 255, 256):
            ret = 1
        name = name.rstrip('\x00')
        if self.legacy:
            if os.path.basename(self.filename)[:len(name)] != name:
                ret = 1
        if ret:
            self.printErr("wrong data in rpm lead")
        return ret

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
                    if t[1] == RPM_ARGSTRING and (ttype == RPM_STRING or \
                        ttype == RPM_STRING_ARRAY):
                        pass    # special exception case
                    elif t[0] == rpmconstants.RPMTAG_GROUP and \
                        ttype == RPM_STRING: # XXX hardcoded exception
                        pass
                    else:
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

    def parseHeader(self, data, sigdata, hdrdata):
        if (self.verify or self.parsesig) and not self.hdronly:
            (sigindexNo, sigstoreSize, sigdata, sigfmt, sigfmt2, size) = \
                sigdata
            (self.sig, self.sigtype) = self.parseIndex(sigindexNo, sigfmt, \
                sigfmt2)
            if self.verify:
                for i in rpmconstants.rpmsigtagrequired:
                    if not self.sig.has_key(i):
                        self.printErr("sig header is missing: %d" % i)
        (hdrindexNo, hdrstoreSize, hdrdata, hdrfmt, hdrfmt2, size) = \
            hdrdata
        (self.hdr, self.hdrtype) = self.parseIndex(hdrindexNo, hdrfmt, \
            hdrfmt2)
        if self.verify:
            for i in rpmconstants.rpmtagrequired:
                if not self.hdr.has_key(i):
                    self.printErr("hdr is missing: %d" % i)
            self.verifyHeader()

    def parseIndex(self, indexNo, fmt, fmt2):
        # XXX parseIndex() should be implemented as C function for faster speed
        hdr = {}
        hdrtype = {}
        for i in xrange(0, indexNo * 16, 16):
            index = unpack("!4i", fmt[i:i + 16])
            tag = index[0]
            # support reading only some tags
            if self.tags and tag not in self.tags:
                continue
            # negative tag list
            if self.ntags and tag in self.ntags:
                continue
            # ignore duplicate entries as long as they are identical
            if hdr.has_key(tag):
                if hdr[tag] != self.parseTag(index, fmt2):
                    self.printErr("tag %d included twice" % tag)
            else: 
                hdr[tag] = self.parseTag(index, fmt2)
                hdrtype[tag] = index[1]
        return (hdr, hdrtype)

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


    def readData(self, data):
        if self.headerlen == 0:
            dummy = {}
            self.readHeader(dummy)
        self.openFile(96 + self.headerlen)
        self.cpiofd = gzip.GzipFile(fileobj=self.fd)
        c = cpio.CPIOFile(self.cpiofd)
        try:
            c.read()
        except IOError, e:
            print "Error reading CPIO payload: %s" % e
        if self.verify:
            return self.verifyPayload(c.namelist())
        return 1

    def write(self, data):
        if self.filename == None:
            return 1
        self.open()
        ret = self.writeHeader(data)
        ret = ret & self.writeData(data)
        self.close()
        return ret

    def writeHeader(self, data):
            return 1

    def writeData(self, data):
            return 1


class RpmFile(RpmStreamIO):
    def __init__(self, filename, verify=None, legacy=None, parsesig=None, hdronly=None, tags=None, ntags=None):
        RpmStreamIO.__init__(self, verify, legacy, parsesig, hdronly, tags, ntags)
        self.filename = filename
        self.fd = None
        self.cpiofd = None
        self.verify = verify
        self.legacy = legacy
        self.parsesig = parsesig
        self.hdronly = hdronly
        self.tags = tags
        self.ntags = ntags
        self.issrc = 0
        self.headerlen = 0
        if filename[-8:] == ".src.rpm" or filename[-10:] == ".nosrc.rpm":
            self.issrc = 1

    def openFile(self, offset=None):
        if not self.fd:
            try:
                self.fd = open(self.filename, "r")
            except:
                self.raiseErr("could not open file")
            if offset:
                self.fd.seek(offset, 1)

    def closeFile(self):
        if self.fd != None:
            self.fd.close()
        self.fd = None

    def open(self):
        self.openFile()

    def close(self):
        self.closeFile()


class RpmDB(RpmIO):
    def __init__(self):
        RpmIO.__init__(self)
        self.source = None

    def read(self, data):
        return 1

    def write(self, data):
        return 1


class RpmRepo(RpmIO):
    def __init__(self):
        RpmIO.__init__(self)
        self.source = None

    def read(self, data):
        return 1

    def write(self, data):
        return 1


class RpmData(RpmError):
    def __init__(self):
        RpmError.__init__(self)
        self.data = {}
        self.hdr = {}
        self.hdrtype = None
        self.sig = {}
        self.sigtype = None
        self.modified = None
        self.cpiodata = None

    def __repr__(self):
        return self.data.__repr__()

    def __getitem__(self, key):
        try:
            return self.data[key]
        except:
            # XXX: try to catch wrong/misspelled keys here?
            return None

    def __setitem__(self, key, value):
        self.modified = 1
        self.data[key] = value
        return self.data[key]

    def verify(self):
        ret = 1
        return ret


class RpmPackage(RpmData):
    def __init__(self):
        RpmData.__init__(self)
        self.clear()

    def clear(self):
        pass

    def read(self, io):
        if io.read(self):
            return 1
        self["provides"] = self.getProvides()
        self["requires"] = self.getRequires()
        self["obsoletes"] = self.getObsoletes()
        self["conflicts"] = self.getConflicts()
        return 0

    def write(self, io):
        return io.write(self)

    def verify(self):
        ret = RpmData.verify(self)
        return ret

    def extractold(self, io, files=None):
        if files == None:
            files = self["filetree"]
        [filename, filedata, filerawdata] = cfile.getNextEntry()
        while filename != None:
            if filename in files:
                cfile.extractCurrentEntry()
            [filename, filedata, filerawdata] = cfile.getNextEntry()
        # Needed for hardlinks... :(
        cfile.postExtract()
        return 0

    def extract(self, io, files=None):
        if files == None:
            files = self["filetree"]
        (filename, filedata, filerawdata) = io.read()
        while filename != None and filename != "EOF" :
            if filename in files:
                idx = files.index(filename)
                print filename, \
                      filedata[7], self["filesizes"][idx], \
                      hex(filedata[8]*256+filedata[9]), hex(int(self["filedevices"][idx])), \
                      oct(filedata[2]), oct(int(self["filemodes"][idx]))
            (filename, filedata, filerawdata) = io.read()
        return 0

    def updateFilestats(self):
        # No files -> No need to do anything.
        if not self["basenames"]:
            return
        # Check every file from the rpm headers and update the filemods
        # according to the info from the rpm headers.
        for i in xrange(len(self["basenames"])):
            fullname = self["dirnames"][self["dirindexes"][i]]+self["basenames"][i]
            if not (os.path.isfile(fullname) or os.path.isdir(fullname)) or os.path.islink(fullname):
                continue
            pw = pwd.getpwnam(self["fileusername"][i])
            if pw != None:
                uid = pw[2]
            else:
                uid = -1
            grp = grp.getgrnam(self["filegroupname"][i])
            if grp != None:
                gid = grp[2]
            else:
                gid = -1
            if uid != -1 and gid != -1:
                os.chown(fullname, uid, gid)
            os.chmod(fullname, (~cpio.CP_IFMT) & self["filemodes"][i])
            os.utime(fullname, (self["filemtimes"][i], self["filemtimes"][i]))

    def readHeader(self, io):
        (key, value) = io.read()
        # Read over lead
        while key != None and key != "-":
            (key, value) = io.read()
        # Read header
        (key, value) = io.read()
        while key != None and key != "-":
            (key, value) = io.read()
            self[key] = value
        self.parseFilelist()

    def parseFilelist(self):
        self["filetree"] = []
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            self["filetree"].append(self["dirnames"][self["dirindexes"][i]] + self["basenames"][i])

    def install(self, io, files=None):
        self.readHeader(io)
        if self["preinprog"] != None:
            runScript(self["preinprog"], self["prein"], "1")
        self.extract(io, self["filetree"])
        self.updateFilestats()
        if self["postinprog"] != None:
            runScript(self["postinprog"], self["postin"], "1")

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


# Collection of class indepedant helper functions
def runScript(prog=None, script=None, arg1=None, arg2=None):
    tmpfilename = tempfile.mktemp(dir="/var/tmp/", prefix="rpm-tmp-")
    fd = open(tmpfilename, "w")
    if script != None:
        fd.write(script)
    fd.close()
    cmd = ""
    cmd = cmd+prog
    if prog != "/sbin/ldconfig":
        cmd = cmd+" "+tmpfilename
        if arg1 != None:
            cmd = cmd+" "+arg1
        if arg2 != None:
            cmd = cmd+" "+arg2
    p = popen2.Popen3(cmd, 1)
    p.tochild.close()
    rout = p.fromchild.read()
    rerr = p.childerr.read()
    p.fromchild.close()
    p.childerr.close()
    ret = p.wait()
    os.unlink(tmpfilename)
    if ret != 0 or rout != "" or rerr != "":
        print "Error in script:"
        print script
        print ret
        print rout
        print rerr
        return 0
    return 1

# vim:ts=4:sw=4:showmatch:expandtab
