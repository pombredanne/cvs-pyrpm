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
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
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
        return 0

    def read(self):
        return 0

    def write(self):
        return 0

    def close(self):
        return 0


class RpmStreamIO(RpmIO):
    def __init__(self, verify=None, legacy=None, parsesig=None, hdronly=None):
        self.fd = None
        self.verify = verify
        self.legacy = legacy
        self.parsesig = parsesig
        self.hdronly = hdronly
        self.issrc = 0
        self.where = 0  # 0:lead 1:separator 2:sig 3:header 4:files
        self.idx = 0 # Current index
        self.hdr = {}
        self.hdrtype = {}

    def open(self):
        return 0

    def close(self):
        return 0

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
                self.idx = self.hdrdata[0]+1
                self.where = 2
            return ("-", "")
        # Read/parse signature
        if self.where == 2:
            # Last index of sig? Switch to from sig to hdr
            if self.idx >= self.hdrdata[0]:
                self.readHdr()
                self.idx = 0
                self.where = 3
                return ("-", "")
            v = self.getHeaderByIndex(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            return (rpmconstants.rpmsigtagname[v[0]], v[1])
        # Read/parse hdr
        if self.where == 3:
            # Last index of hdr? Switch to data files archive
            if self.idx >= self.hdrdata[0]:
                self.hdrdata = None
                self.hdr = {}
                self.hdrtype = {}
                self.cpiofd = gzip.GzipFile(fileobj=self.fd)
                self.cpio = cpio.CPIOFile(self.cpiofd)
                self.where = 4
                return ("-", "")
            v =  self.getHeaderByIndex(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            return (rpmconstants.rpmtagname[v[0]], v[1])
        # Read/parse data files archive
        if self.where == 4:
            (filename, filedata, filerawdata) = self.cpio.getNextEntry()
            if filename != None:
                return (filename, filerawdata)
        return  ("EOF", "")

    def readLead(self):
        leaddata = self.fd.read(96)
        if leaddata[:4] != '\xed\xab\xee\xdb':
            self.printErr("no rpm magic found")
            return (None, None)
        if self.verify and not self.verifyLead(leaddata):
            return (None, None)
        return ("magic", leaddata[:4])

    def readSig(self):
        self.hdr = {}
        self.hdrtype = {}
        self.hdrdata = self.readIndex(8, 1)

    def readHdr(self):
        self.hdr = {}
        self.hdrtype = {}
        self.hdrdata = self.readIndex(1)

    def getHeaderByIndex(self, idx, indexdata, storedata):
        index = unpack("!4i", indexdata[idx*16:(idx+1)*16])
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.parseTag(index, storedata):
                self.printErr("tag %d included twice" % tag)
        else: 
            self.hdr[tag] = self.parseTag(index, storedata)
            self.hdrtype[tag] = index[1]
        return (tag, self.hdr[tag])

    def verifyLead(self, leaddata):
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4scchh66shh16x", leaddata)
        ret = 1
        if major not in ('\x03', '\x04') or minor != '\x00' or \
            sigtype != 5 or rpmtype not in (0, 1):
            ret = 0
        if osnum not in (1, 255, 256):
            ret = 0
        name = name.rstrip('\x00')
        if self.legacy:
            if os.path.basename(self.filename)[:len(name)] != name:
                ret = 0
        if not ret:
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
        return 0

    def write(self, data):
        if self.filename == None:
            return 0
        self.open()
        ret = self.writeHeader(data)
        ret = ret & self.writeData(data)
        self.close()
        return ret

    def writeHeader(self, data):
            return 0

    def writeData(self, data):
            return 0


class RpmDBIO(RpmIO):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmIO.__init__(self)


class RpmFtpIO(RpmIO):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmIO.__init__(self)


class RpmFileIO(RpmStreamIO):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmStreamIO.__init__(self, verify, legacy, parsesig, hdronly)
        self.filename = source
        self.issrc = 0
        if self.filename[-8:] == ".src.rpm" or self.filename[-10:] == ".nosrc.rpm":
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
        return 1

    def close(self):
        self.closeFile()
        return 1


class RpmHttpIO(RpmIO):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmStreamIO.__init__(self, verify, legacy, parsesig, hdronly)
        self.url = source

    def open(self):
        pass

    def open(self):
        pass


class RpmRepoIO(RpmIO):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmIO.__init__(self)


def getRpmIOFactory(source, verify=None, legacy=None, parsesig=None, hdronly=None):
    if source[:4] == 'db:/':
        return RpmDBIO(source[4:], verify, legacy, parsesig, hdronly)
    if source[:5] == 'ftp:/':
        return RpmFtpIO(source[5:], verify, legacy, parsesig, hdronly)
    if source[:6] == 'file:/':
        return RpmFileIO(source[6:], verify, legacy, parsesig, hdronly)
    if source[:6] == 'http:/':
        return RpmHttpIO(source[6:], verify, legacy, parsesig, hdronly)
    if source[:6] == 'repo:/':
        return RpmRepoIO(source[6:], verify, legacy, parsesig, hdronly)
    return None


class RpmData(RpmError):
    def __init__(self):
        RpmError.__init__(self)
        self.data = {}
        self.modified = None

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
        ret = 0
        return ret


class RpmPackage(RpmData):
    def __init__(self, source, verify=None, legacy=None, parsesig=None, hdronly=None):
        RpmData.__init__(self)
        self.clear()
        self.source = source
        self.verify = verify
        self.legacy = legacy
        self.parsesig = parsesig
        self.hdronly = hdronly

    def clear(self):
        self.io = None
        self.header_read = 0

    def open(self):
        if self.io != None:
            return 1
        self.io = getRpmIOFactory(self.source, self.verify, self.legacy, self.parsesig, self.hdronly)
        if not self.io:
            return 0
        if not self.io.open():
            return 0
        return 1

    def close(self):
        if self.io != None:
            self.io.close()
        self.io = None
        return 1

    def read(self, tags=None, ntags=None):
        if not self.open():
            return 0
        if not self.readHeader(tags, ntags):
            return 0
        self["provides"] = self.getProvides()
        self["requires"] = self.getRequires()
        self["obsoletes"] = self.getObsoletes()
        self["conflicts"] = self.getConflicts()
        self.close()
        return 1

    def write(self):
        if not self.open():
            return 0
        ret = self.io.write(self)
        self.close()
        return ret

    def verify(self):
        ret = RpmData.verify(self)
        return ret

    def install(self, files=None):
        if not self.open():
            return 0
        if not self.readHeader():
            return 0
        if not files:
            files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preinprog"] != None:
            if not runScript(self["preinprog"], self["prein"], "1"):
                return 0
        if not self.extract(files):
            return 0
        if self["postinprog"] != None:
            if not runScript(self["postinprog"], self["postin"], "1"):
                return 0
        return 1

    def remove(self, files=None):
        if not self.open():
            return 0
        if not self.readHeader():
            return 0
        if not files:
            files = self["filenames"]
        # Set umask to 022, especially important for scripts
        os.umask(022)
        if self["preunprog"] != None:
            if not runScript(self["preunprog"], self["preun"], "1"):
                return 0
        # Remove files starting from the end (reverse process to install)
        files.reverse()
        for f in files:
            if os.path.isdir(f):
                try:
                    os.rmdir(f)
                except:
                    print "Error removing dir %s from pkg %s" % (f, self.source)
            else:
                try:
                    os.unlink(f)
                except:
                    print "Error removing file %s from pkg %s" % (f, self.source)
        if self["postunprog"] != None:
            if not runScript(self["postunprog"], self["postun"], "1"):
                return 0

    def readHeader(self, tags=None, ntags=None):
        if self.header_read:
            return 1
        (key, value) = self.io.read()
        # Read over lead
        while key != None and key != "-":
            (key, value) = self.io.read()
        # Read sig
        (key, value) = self.io.read()
        while key != None and key != "-":
            if tags and key in tags:
                self[key] = value
            elif ntags and not key in ntags:
                self[key] = value
            elif not tags and not ntags:
                self[key] = value
            (key, value) = self.io.read()
        # Read header
        (key, value) = self.io.read()
        while key != None and key != "-":
            if tags and key in tags:
                self[key] = value
            elif ntags and not key in ntags:
                self[key] = value
            elif not tags and not ntags:
                self[key] = value
            (key, value) = self.io.read()
        self.generateFileNames()
        self.header_read = 1
        return 1

    def extract(self, files=None):
        if files == None:
            files = self["filenames"]
        # We don't need those lists earlier, so we create them "on-the-fly"
        # before we actually start extracting files.
        self.generateFileInfoList()
        self.generateHardLinkList()
        (filename, filerawdata) = self.io.read()
        while filename != None and filename != "EOF" :
            rfi = self.rfilist[filename]
            if rfi != None:
                if not str(rfi.inode)+":"+str(rfi.dev) in self.hardlinks.keys():
                    if not installFile(rfi, filerawdata):
                        return 0
                else:
                    if len(filerawdata) > 0:
                        if not installFile(rfi, filerawdata):
                            return 0
                        if not self.handleHardlinks(rfi):
                            return 0
            (filename, filerawdata) = self.io.read()
        return self.handleRemainingHardlinks()

    def generateFileNames(self):
        self["filenames"] = []
        if self["dirnames"] == None or self["dirindexes"] == None:
            return
        for i in xrange (len(self["basenames"])):
            filename = self["dirnames"][self["dirindexes"][i]] + self["basenames"][i]
            self["filenames"].append(filename)

    def generateFileInfoList(self):
        self.rfilist = {}
        for filename in self["filenames"]:
            self.rfilist[filename] = self.getRpmFileInfo(filename)

    def generateHardLinkList(self):
        self.hardlinks = {}
        for filename in self.rfilist.keys():
            rfi = self.rfilist[filename]
            key = str(rfi.inode)+":"+str(rfi.dev)
            if key not in self.hardlinks.keys():
                self.hardlinks[key] = []
            self.hardlinks[key].append(rfi)
        for key in self.hardlinks.keys():
            if len(self.hardlinks[key]) == 1:
                del self.hardlinks[key]

    def handleHardlinks(self, rfi):
        key = str(rfi.inode)+":"+str(rfi.dev)
        self.hardlinks[key].remove(rfi)
        for hrfi in self.hardlinks[key]:
            makeDirs(hrfi.filename)
            if not createLink(rfi.filename, hrfi.filename):
                return 0
        del self.hardlinks[key]
        return 1

    def handleRemainingHardlinks(self):
        keys = self.hardlinks.keys()
        for key in keys:
            rfi = self.hardlinks[key][0]
            if not installFile(rfi, ""):
                return 0
            if not self.handleHardlinks(rfi):
                return 0
        return 1

    def getRpmFileInfo(self, filename):
        try:
            i = self["filenames"].index(filename)
        except:
            return None
        rpminode = self["fileinodes"][i]
        rpmmode = self["filemodes"][i]
        if os.path.isfile("/etc/passwd"):
            try:
                pw = pwd.getpwnam(self["fileusername"][i])
            except:
                pw = None
        else:
            pw = None
        if pw != None:
            rpmuid = pw[2]
        else:
            rpmuid = 0      # default to root as uid if not found
        if os.path.isfile("/etc/group"):
            try:
                gr = grp.getgrnam(self["filegroupname"][i])
            except:
                gr = None
        else:
            gr = None
        if gr != None:
            rpmgid = gr[2]
        else:
            rpmgid = 0      # default to root as gid if not found
        rpmmtime = self["filemtimes"][i]
        rpmfilesize = self["filesizes"][i]
        rpmdev = self["filedevices"][i]
        rpmrdev = self["filerdevs"][i]
        rfi = RpmFileInfo(filename, rpminode, rpmmode, rpmuid, rpmgid, rpmmtime, rpmfilesize, rpmdev, rpmrdev)
        return rfi

    def getNEVRA(self):
        if self["epoch"] != None:
            e = str(self["epoch"][0])+":"
        else:
            e = ""
        return "%s-%s%s-%s.%s" % (self["name"], e, self["version"], self["release"], self["arch"])

    def getDeps(self, name, flags, version):
        n = self[name]
        if not n:
            return []
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


class RpmFileInfo:
    def __init__(self, filename, inode, mode, uid, gid, mtime, filesize, dev, rdev):
        self.filename = filename
        self.inode = inode
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.mtime = mtime
        self.filesize = filesize
        self.dev = dev
        self.rdev = rdev


# Collection of class indepedant helper functions
def runScript(prog=None, script=None, arg1=None, arg2=None):
    if prog == None:
        prog = "/bin/sh"
    (fd, tmpfilename) = tempfile.mkstemp(dir="/var/tmp/", prefix="rpm-tmp.")
    if fd == None:
        return 0
    if script != None:
        os.write(fd, script)
    os.close(fd)
    fd = None
    args = [prog]
    if prog != "/sbin/ldconfig":
        args.append(tmpfilename)
        if arg1 != None:
            args.append(arg1)
        if arg2 != None:
            args.append(arg2)
    pid = os.fork()
    if pid != 0:
        (cpid, status) = os.waitpid(pid, 0)
    else:
        os.close(0)
        os.execv(prog, args)
        sys.exit()
    os.unlink(tmpfilename)
    if status != 0:
        print "Error in running script:"
        print prog
        print args
        return 0
    return 1

def installFile(rfi, data):
    filetype = rfi.mode & cpio.CP_IFMT
    if  filetype == cpio.CP_IFREG:
        makeDirs(rfi.filename)
        (fd, tmpfilename) = tempfile.mkstemp(dir=os.path.dirname(rfi.filename), prefix=rfi.filename+".")
        if not fd:
            return 0
        if os.write(fd, data) < 0:
            os.close(fd)
            os.unlink(tmpfilename)
            return 0
        os.close(fd)
        if not setFileMods(tmpfilename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            os.unlink(tmpfilename)
            return 0
        if os.rename(tmpfilename, rfi.filename) != None:
            return 0
    elif filetype == cpio.CP_IFDIR:
        if os.path.isdir(rfi.filename):
            return 1
        os.makedirs(rfi.filename)
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            return 0
    elif filetype == cpio.CP_IFLNK:
        symlinkfile = data.rstrip("\x00")
        if os.path.islink(rfi.filename) and os.readlink(rfi.filename) == symlinkfile:
            return 1
        makeDirs(rfi.filename)
        try:
            os.unlink(rfi.filename)
        except:
            pass
        os.symlink(symlinkfile, rfi.filename)
    elif filetype == cpio.CP_IFIFO:
        makeDirs(rfi.filename)
        if not os.path.exists(rfi.filename) and os.mkfifo(rfi.filename) != None:
            return 0
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            os.unlink(rfi.filename)
            return 0
    elif filetype == cpio.CP_IFCHR or \
         filetype == cpio.CP_IFBLK:
        makeDirs(rfi.filename)
        try:
            os.mknod(rfi.filename, rfi.mode, rfi.rdev)
        except:
            pass
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(rfi.filetype))
    return 1

def setFileMods(filename, uid, gid, mode, mtime):
    if os.chown(filename, uid, gid) != None:
        return 0
    if os.chmod(filename, (~cpio.CP_IFMT) & mode) != None:
        return 0
    if os.utime(filename, (mtime, mtime)) != None:
        return 0
    return 1

def makeDirs(fullname):
    dirname = fullname[:fullname.rfind("/")]
    if not os.path.isdir(dirname):
            os.makedirs(dirname)

def createLink(src, dst):
    try:
        # First try to unlink the defered file
        os.unlink(dst)
    except:
        pass
    # Behave exactly like cpio: If the hardlink fails (because of different
    # partitions), then it has to fail
    if os.link(src, dst) != None:
        return 0
    return 1

# vim:ts=4:sw=4:showmatch:expandtab
