#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
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


import types, bsddb, libxml2, urlgrabber.grabber, zlib, gzip
from struct import pack, unpack

from functions import *
import package


FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT = 1, 2, 4, 8, 16
class PyGZIP:
    def __init__(self, fd):
        self.fd = fd
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")
        self.length = 0
        self.buffer = []
        self.bufferlen = 0
        self.pos = 0
        self.enddata = ""
        self.header_read = 0

    def __readHeader(self):
        magic = self.fd.read(2)
        if magic != '\037\213':
            printError("Not a gzipped file")
            v1 = unpack("!H", magic)
            print oct(v1[0])
            sys.exit(0)
        if ord(self.fd.read(1)) != 8:
            printError("Unknown compression method")
            sys.exit(0)
        flag = ord(self.fd.read(1))
        self.fd.read(4+1+1) # Discard modification time, extra flags, OS byte
        if flag & FEXTRA:
            # Read & discard the extra field, if present
            xlen=ord(self.fd.read(1))
            xlen=xlen+256*ord(self.fd.read(1))
            self.fd.read(xlen)
        if flag & FNAME:
            # Read and discard a null-terminated string containing the filename
            while (1):
                s=self.fd.read(1)
                if s=='\000':
                    break
        if flag & FCOMMENT:
            # Read and discard a null-terminated string containing a comment
            while (1):
                s=self.fd.read(1)
                if s=='\000':
                    break
        if flag & FHCRC:
            self.fd.read(2)      # Read & discard the 16-bit header CRC
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")
        self.header_read = 1

    def read(self, bytes=None):
        if not self.header_read:
            self.__readHeader()
        data = ""
        size = 2048
        while bytes == None or self.bufferlen <  bytes:
            if len(data) >= 8:
                self.enddata = data[-8:]
            else:
                self.enddata = self.enddata[:8-len(data)] + data
            size = bytes - self.bufferlen
            if size > 65536:
                size = 32768
            elif size > 32768:
                size = 16384
            elif size > 16384:
                size = 8192
            elif size > 8192:
                size = 4096
            elif size > 4096:
                size = 2048
            else:
                size = 1024
            data = self.fd.read(size)
            if data == "":
            # We've read to the end of the file, so we have to rewind in order
            # to reread the 8 bytes containing the CRC and the file size.  The
            # decompressor is smart and knows when to stop, so feeding it
            # extra data is harmless.
                crc32 = unpack("!I", self.enddata[0:4])
                isize = unpack("!I", self.enddata[4:8])
                if crc32 != self.crcval:
                    printError("CRC check failed.")
                if isize != self.length:
                    printError("Incorrect length of data produced")
                break
            decompdata = self.decompobj.decompress(data)
            decomplen = len(decompdata)
            self.buffer.append(decompdata)
            self.bufferlen += decomplen
            self.length += decomplen
            self.crcval = zlib.crc32(decompdata, self.crcval)
        if bytes == None or self.bufferlen <  bytes:
            decompdata = self.decompobj.flush()
            decomplen = len(decompdata)
            self.buffer.append(decompdata)
            self.bufferlen += decomplen
            self.length = self.length + decomplen
            self.crcval = zlib.crc32(decompdata, self.crcval)
        if bytes == None:
            bytes = self.length
        retdata = ""
        while bytes > 0:
            decompdata = self.buffer[0]
            decomplen = len(decompdata)
            if bytes+self.pos <= decomplen:
                tmpdata = decompdata[self.pos:bytes+self.pos]
                retdata += tmpdata
                #self.buffer[0] = decompdata[bytes:]
                self.bufferlen -= bytes
                self.pos += bytes
                break
            decomplen -= self.pos
            bytes -= decomplen
            self.bufferlen -= decomplen
            if self.pos != 0:
                retdata += decompdata[self.pos:]
            else:
                retdata += decompdata
            self.pos = 0
            self.buffer.pop(0)
        return retdata


class CPIOFile:
    """ Read ASCII CPIO files. """
    def __init__(self, fd):
        self.fd = fd                    # filedescriptor

    def getNextEntry(self):
        # The cpio header contains 8 byte hex numbers with the following
        # content: magic, inode, mode, uid, gid, nlink, mtime, filesize,
        # devMajor, devMinor, rdevMajor, rdevMinor, namesize, checksum.
        data = self.fd.read(110)

        # CPIO ASCII hex, expanded device numbers (070702 with CRC)
        if data[0:6] not in ["070701", "070702"]:
            raise IOError, "Bad magic reading CPIO headers %s" % data[0:6]

        # Read filename and padding.
        filenamesize = int(data[94:102], 16)
        filename = self.fd.read(filenamesize).rstrip("\x00")
        self.fd.read((4 - ((110 + filenamesize) % 4)) % 4)
        if filename == "TRAILER!!!": # end of archive detection
            return (None, None)
        # Adjust filename, so that it matches the way the rpm header has
        # filenames stored. This code used to be:
        # 'filename = "/" + os.path.normpath("./" + filename)'
        if filename.startswith("./"):
            filename = filename[1:]
        if not filename.startswith("/"):
            filename = "%s%s" % ("/", filename)
        if filename.endswith("/") and len(filename) > 1:
            filename = filename[:-1]

        # Read file contents.
        filesize = int(data[54:62], 16)
        filerawdata = self.fd.read(filesize)
        self.fd.read((4 - (filesize % 4)) % 4)

        return (filename, filerawdata)


class RpmIO:
    """'Virtual' IO Class for RPM packages and data"""
    def __init__(self, source):
        self.source = source

    def open(self, mode="r"):
        return 0

    def read(self, skip=None):
        return 0

    def write(self, pkg):
        return 0

    def close(self):
        return 0


class RpmStreamIO(RpmIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmIO.__init__(self, source)
        self.fd = None
        self.cpio = None
        self.verify = verify
        self.strict = strict
        self.hdronly = hdronly
        self.issrc = 0
        self.where = 0  # 0:lead 1:separator 2:sig 3:header 4:files
        self.idx = 0 # Current index
        self.hdr = {}
        self.hdrtype = {}

    def open(self, mode="r"):
        return 0

    def close(self):
        if self.cpio:
            self.cpio = None
        return 1

    def read(self, skip=None):
        if self.fd == None:
            self.open()
        if self.fd == None:
            return (None, None)
        if skip:
            self.__readLead()
            self.__readSig()
            self.__readHdr()
            self.where=3
        # Read/check leadata
        if self.where == 0:
            self.where = 1
            return self.__readLead()
        # Separator
        if self.where == 1:
            pos = self._tell()
            self.__readSig()
            self.where = 2
            return ("-", (pos, self.hdrdata[5]))
        # Read/parse signature
        if self.where == 2:
            # Last index of sig? Switch to from sig to hdr
            if self.idx >= self.hdrdata[0]:
                pos = self._tell()
                self.__readHdr()
                self.idx = 0
                self.where = 3
                return ("-", (pos, self.hdrdata[5]))
            v = self.getHeaderByIndex(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            return (rpmsigtagname[v[0]], v[1])
        # Read/parse hdr
        if self.where == 3:
            # Shall we skip header parsing?
            # Last index of hdr? Switch to data files archive
            if self.idx >= self.hdrdata[0] or skip:
                pos = self._tell()
                self.hdrdata = None
                self.hdr = {}
                self.hdrtype = {}
#                cpiofd = gzip.GzipFile(fileobj=self.fd)
                cpiofd = PyGZIP(self.fd)
                self.cpio = CPIOFile(cpiofd)
                self.where = 4
                # Nobody cares about gzipped payload length so far
                return ("-", (pos, None))
            v =  self.getHeaderByIndex(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            return (rpmtagname[v[0]], v[1])
        # Read/parse data files archive
        if self.where == 4 and not self.hdronly:
            (filename, filerawdata) = self.cpio.getNextEntry()
            if filename != None:
                return (filename, filerawdata)
        return  ("EOF", "")

    def write(self, pkg):
        if self.fd == None:
            self.open("w+")
        if self.fd == None:
            return 0
        lead = pack("!4scchh66shh16x", RPM_HEADER_LEAD_MAGIC, '\x04', '\x00', 0, 1, pkg.getNEVR()[0:66], rpm_lead_arch[pkg["arch"]], 5)
        (sigindex, sigdata) = self.__generateSig(pkg["signature"])
        (headerindex, headerdata) = self.__generateHeader(pkg)
        self._write(lead)
        self._write(sigindex)
        self._write(sigdata)
        self._write(headerindex)
        self._write(headerdata)
        return 1

    def _read(self, nbytes=None):
        if self.fd == None:
            self.open()
        if self.fd == None:
            return None
        return self.fd.read(nbytes)

    def _write(self, data):
        if self.fd == None:
            self.open("w+")
        if self.fd == None:
            return 0
        return self.fd.write(data)

    def _tell(self):
        try:
            return self.fd.tell()
        except IOError:
            return None

    def __readLead(self):
        leaddata = self._read(96)
        if leaddata[:4] != RPM_HEADER_LEAD_MAGIC:
            printError("%s: no rpm magic found" % self.source)
            return (None, None)
        if self.verify and not self.__verifyLead(leaddata):
            return (None, None)
        return ("magic", leaddata[:4])

    def __readSig(self):
        self.hdr = {}
        self.hdrtype = {}
        self.hdrdata = self.__readIndex(8, 1)

    def __readHdr(self):
        self.hdr = {}
        self.hdrtype = {}
        self.hdrdata = self.__readIndex(1)

    def getHeaderByIndex(self, idx, indexdata, storedata):
        index = unpack("!4i", indexdata[idx*16:(idx+1)*16])
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.__parseTag(index, storedata):
                printError("%s: tag %d included twice" % (self.source, tag))
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
            self.hdrtype[tag] = index[1]
        return (tag, self.hdr[tag])

    def __verifyLead(self, leaddata):
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4scchh66shh16x", leaddata)
        ret = 1
        if major not in ('\x03', '\x04') or minor != '\x00' or \
            sigtype != 5 or rpmtype not in (0, 1):
            ret = 0
        if osnum not in (1, 255, 256):
            ret = 0
        name = name.rstrip('\x00')
        if self.strict:
            if os.path.basename(self.source)[:len(name)] != name:
                ret = 0
        if not ret:
            printError("%s: wrong data in rpm lead" % self.source)
        return ret

    def __readIndex(self, pad, issig=None):
        data = self._read(16)
        if not len(data):
            return None
        (magic, indexNo, storeSize) = unpack("!8sii", data)
        if magic != RPM_HEADER_INDEX_MAGIC or indexNo < 1:
            raiseFatal("%s: bad index magic" % self.source)
        fmt = self._read(16 * indexNo)
        fmt2 = self._read(storeSize)
        if pad != 1:
            self._read((pad - (storeSize % pad)) % pad)
        if self.verify:
            self.__verifyIndex(fmt, fmt2, indexNo, storeSize, issig)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + len(fmt2))

    def __verifyIndex(self, fmt, fmt2, indexNo, storeSize, issig):
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
            checkSize += self.__verifyTag(index, fmt2, issig)
        if checkSize != storeSize:
            # XXX: add a check for very old rpm versions here, seems this
            # is triggered for a few RHL5.x rpm packages
            printError("%s: storeSize/checkSize is %d/%d" % (self.source, storeSize, checkSize))

    def __verifyTag(self, index, fmt, issig):
        (tag, ttype, offset, count) = index
        if issig:
            if not rpmsigtag.has_key(tag):
                printError("%s: rpmsigtag has no tag %d" % (self.source, tag))
            else:
                t = rpmsigtag[tag]
                if t[1] != None and t[1] != ttype:
                    printError("%s: sigtag %d has wrong type %d" % (self.source, tag, ttype))
                if t[2] != None and t[2] != count:
                    printError("%s: sigtag %d has wrong count %d" % (self.source, tag, count))
                if (t[3] & 1) and self.strict:
                    printError("%s: tag %d is marked legacy" % (self.source, tag))
                if self.issrc:
                    if (t[3] & 4):
                        printError("%s: tag %d should be for binary rpms" % (self.source, tag))
                else:
                    if (t[3] & 2):
                        printError("%s: tag %d should be for src rpms" % (self.source, tag))
        else:
            if not rpmtag.has_key(tag):
                printError("%s: rpmtag has no tag %d" % (self.source, tag))
            else:
                t = rpmtag[tag]
                if t[1] != None and t[1] != ttype:
                    if t[1] == RPM_ARGSTRING and (ttype == RPM_STRING or \
                        ttype == RPM_STRING_ARRAY):
                        pass    # special exception case for RPMTAG_GROUP (1016)
                    elif t[0] == 1016 and \
                        ttype == RPM_STRING: # XXX hardcoded exception
                        pass
                    else:
                        printError("%s: tag %d has wrong type %d" % (self.source, tag, ttype))
                if t[2] != None and t[2] != count:
                    printError("%s: tag %d has wrong count %d" % (self.source, tag, count))
                if (t[3] & 1) and self.strict:
                    printError("%s: tag %d is marked legacy" % (self.source, tag))
                if self.issrc:
                    if (t[3] & 4):
                        printError("%s: tag %d should be for binary rpms" % (self.source, tag))
                else:
                    if (t[3] & 2):
                        printError("%s: tag %d should be for src rpms" % (self.source, tag))
        if count == 0:
            raiseFatal("%s: zero length tag" % self.source)
        if ttype < 1 or ttype > 9:
            raiseFatal("%s: unknown rpmtype %d" % (self.source, ttype))
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
                raiseFatal("%s: tag string count wrong" % self.source)
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
            raiseFatal("%s: unknown tag header" % self.source)
        return count

    def __parseTag(self, index, fmt):
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
        raiseFatal("%s: unknown tag type: %d" % (self.source, ttype))
        return None

    def __generateTag(self, ttype, value):
        # Decided if we have to write out a list or a single element
        if isinstance(value, types.TupleType) or isinstance(value, types.ListType):
            count = len(value)
        else:
            count = 0
        # Normally we don't have strings. And strings always need to be '\x0'
        # terminated.
        isstring = 0
        if ttype == RPM_STRING or \
           ttype == RPM_STRING_ARRAY or\
           ttype == RPM_I18NSTRING:
            format = "s"
            isstring = 1
        elif ttype == RPM_BIN:
            format = "s"
        elif ttype == RPM_CHAR:
            format = "!c"
        elif ttype == RPM_INT8:
            format = "!B"
        elif ttype == RPM_INT16:
            format = "!H"
        elif ttype == RPM_INT32:
            format = "!I"
        elif ttype == RPM_INT64:
            format = "!Q"
        else:
            raiseFatal("%s: unknown tag header" % self.source)
        if count == 0:
            if format == "s":
                data = pack("%ds" % (len(value)+isstring), value)
            else:
                data = pack(format, value)
        else:
            data = ""
            for i in xrange(0,count):
                if format == "s":
                    data += pack("%ds" % (len(value[i])+isstring), value[i])
                else:
                    data += pack(format, value[i])
        # Fix counter. If it was a list, keep the counter.
        # If it was a single element, use 1 or if it is a RPM_BIN type the
        # length of the binary data.
        if count == 0:
            if ttype == RPM_BIN:
                count = len(value)
            else:
                count = 1
        return (count, data)

    def __generateIndex(self, indexlist, store, pad):
        index = RPM_HEADER_INDEX_MAGIC
        index += pack("!ii", len(indexlist), len(store))
        (tag, ttype, offset, count) = indexlist.pop()
        index += pack("!iiii", tag, ttype, offset, count)
        for (tag, ttype, offset, count) in indexlist:
            index += pack("!iiii", tag, ttype, offset, count)
        align = (pad - (len(store) % pad)) % pad
        return (index, pack("%ds" % align, '\x00'))

    def __alignTag(self, ttype, offset):
        if ttype == RPM_INT16:
            align = (2 - (offset % 2)) % 2
        elif ttype == RPM_INT32:
            align = (4 - (offset % 4)) % 4
        elif ttype == RPM_INT64:
            align = (8 - (offset % 8)) % 8
        else:
            align = 0
        return pack("%ds" % align, '\x00')

    def __generateSig(self, header):
        store = ""
        offset = 0
        indexlist = []
        keys = rpmsigtag.keys()
        keys.sort()
        for tag in keys:
            if not isinstance(tag, types.IntType):
                continue
            # We need to handle tag 62 at the very end...
            if tag == 62:
                continue
            key = rpmsigtagname[tag]
            # Skip keys we don't have
            if not header.has_key(key):
                continue
            value = header[key]
            ttype = rpmsigtag[tag][1]
            # Convert back the RPM_ARGSTRING to RPM_STRING
            if ttype == RPM_ARGSTRING:
                ttype = RPM_STRING
            (count, data) = self.__generateTag(ttype, value)
            pad = self.__alignTag(ttype, offset)
            offset += len(pad)
            indexlist.append((tag, ttype, offset, count))
            store += pad + data
            offset += len(data)
        # Handle tag 62 if we have it.
        tag = 62
        key = rpmsigtagname[tag]
        if header.has_key(key):
            value = header[key]
            ttype = rpmsigtag[tag][1]
            # Convert back the RPM_ARGSTRING to RPM_STRING
            if ttype == RPM_ARGSTRING:
                ttype = RPM_STRING
            (count, data) = self.__generateTag(ttype, value)
            pad = self.__alignTag(ttype, offset)
            offset += len(pad)
            indexlist.append((tag, ttype, offset, count))
            store += pad + data
            offset += len(data)
        (index, pad) = self.__generateIndex(indexlist, store, 8)
        return (index, store+pad)

    def __generateHeader(self, header):
        store = ""
        indexlist = []
        offset = 0
        keys = rpmtag.keys()
        keys.sort()
        for tag in keys:
            if not isinstance(tag, types.IntType):
                continue
            # We need to handle tag 63 at the very end...
            if tag == 63:
                continue
            key = rpmtagname[tag]
            if not header.has_key(key):
                continue
            value = header[key]
            ttype = rpmtag[tag][1]
            # Convert back the RPM_ARGSTRING to RPM_STRING
            if ttype == RPM_ARGSTRING:
                ttype = RPM_STRING
            (count, data) = self.__generateTag(ttype, value)
            pad = self.__alignTag(ttype, offset)
            offset += len(pad)
            indexlist.append((tag, ttype, offset, count))
            store += pad + data
            offset += len(data)
        # Handle tag 63 if we have it.
        tag = 63
        key = rpmtagname[tag]
        if header.has_key(key):
            value = header[key]
            ttype = rpmtag[tag][1]
            # Convert back the RPM_ARGSTRING to RPM_STRING
            if ttype == RPM_ARGSTRING:
                ttype = RPM_STRING
            (count, data) = self.__generateTag(ttype, value)
            pad = self.__alignTag(ttype, offset)
            offset += len(pad)
            indexlist.append((tag, ttype, offset, count))
            store += pad + data
            offset += len(data)
        (index, pad) = self.__generateIndex(indexlist, store, 1)
        return (index, store+pad)


class RpmFileIO(RpmStreamIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, source, verify, strict, hdronly)
        self.issrc = 0
        if source.endswith(".src.rpm") or source.endswith(".nosrc.rpm"):
            self.issrc = 1

    def __openFile(self, mode="r"):
        if not self.fd:
            try:
                import fcntl
                self.fd = open(self.source, mode)
                fcntl.fcntl(self.fd.fileno(), fcntl.F_SETFD, 1)
            except:
                raiseFatal("%s: could not open file" % self.source)

    def __closeFile(self):
        if self.fd:
            self.fd.close()
        self.fd = None

    def open(self, mode="r"):
        RpmStreamIO.open(self)
        self.__openFile(mode)
        return 1

    def close(self):
        RpmStreamIO.close(self)
        self.__closeFile()
        return 1


class RpmFtpIO(RpmStreamIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, source, verify, strict, hdronly)

    def open(self, mode="r"):
        RpmStreamIO.open(self)
        urlg = urlgrabber.grabber.URLGrabberFileObject(self.source)
        self.fd  = urlg.fo
        return self.fd != None

    def close(self):
        RpmStreamIO.close(self)
        self.fd.close()
        self.fd = None
        return 1


class RpmHttpIO(RpmStreamIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, source, verify, strict, hdronly)

    def open(self, mode="r"):
        RpmStreamIO.open(self)
        opts = urlgrabber.grabber.URLGrabberOptions()
        self.urlg = urlgrabber.grabber.URLGrabberFileObject(self.source, None, opts)
        self.fd = self.urlg.fo
        return 1

    def close(self):
        RpmStreamIO.close(self)
        self.urlg.close()
        return 1

    def _read(self, nbytes=None):
        return self.urlg.read(nbytes)

    def _write(self, data):
        return 0

    def _tell(self):
        return None


class RpmDBIO(RpmFileIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmFileIO.__init__(self, source, verify, strict, hdronly)


class RpmDB:
    def __init__(self, source):
        self.source = source
        self.filenames = {}
        self.pkglist = {}

    def read(self):
        db = bsddb.hashopen(self.source+"/Packages", "r")
        for key in db.keys():
            rpmio = RpmFileIO("dummy")
            pkg = package.RpmPackage("dummy")
            data = db[key]
            val = unpack("i", key)[0]
            if val != 0:
                (indexNo, storeSize) = unpack("!ii", data[0:8])
                indexdata = data[8:indexNo*16+8]
                storedata = data[indexNo*16+8:]
                pkg["signature"] = {}
                for idx in xrange(0, indexNo):
                    (tag, tagval) = rpmio.getHeaderByIndex(idx, indexdata, storedata)
                    if   tag == 257:
                        pkg["signature"]["size_in_sig"] = tagval
                    elif tag == 261:
                        pkg["signature"]["md5"] = tagval
                    elif tag == 269:
                        pkg["signature"]["sha1header"] =tagval
                    elif rpmtag.has_key(tag):
                        if rpmtagname[tag] == "archivesize":
                            pkg["signature"]["payloadsize"] = tagval
                        else:
                            pkg[rpmtagname[tag]] = tagval
                if not pkg.has_key("arch"):
                    continue
                if pkg["name"].startswith("gpg-pubkey"):
                    continue
                pkg.generateFileNames()
                nevra = pkg.getNEVRA()
                pkg.source = "db:/"+self.source+"/"+nevra
                for filename in pkg["filenames"]:
                    if not self.filenames.has_key(filename):
                        self.filenames[filename] = []
                    self.filenames[filename].append(pkg)
                self.pkglist[nevra] = pkg
                rpmio.hdr = {}
                rpmio.hdrtype = {}
        return 1

    def getPackage(self, name):
        if not self.pkglist:
            if not self.read():
                return None
        if not self.pkglist.has_key(name):
                return None
        return self.pkglist[name]

    def getPkgList(self):
        if not self.pkglist:
            if not self.read():
                return {}
        return self.pkglist

    def isDuplicate(self, file):
        if not self.pkglist:
            if not self.read():
                return 1
        if self.filenames.has_key(file) and len(self.filenames[file]) > 1:
            return 1
        return 0


class RpmPyDBIO(RpmFileIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmFileIO.__init__(self, source, verify, strict, hdronly)


class RpmPyDB:
    def __init__(self, source):
        self.source = source
        self.filenames = {}
        self.pkglist = {}

    def setSource(self, source):
        self.source = source

    def read(self):
        if not self.__mkDBDirs():
            return 0
        namelist = os.listdir(self.source+"/headers")
        for nevra in namelist:
            src = "pydb:/"+self.source+"/headers/"+nevra
            pkg = package.RpmPackage(src)
            pkg.read(tags=("name", "epoch", "version", "release", "arch", "providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "filesizes", "filemodes", "filerdevs", "filemtimes", "filemd5s", "filelinktos", "fileflags", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "dirindexes", "basenames", "dirnames", "preunprog", "preun", "postunprog", "postun", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
            pkg.close()
            for filename in pkg["filenames"]:
                if not self.filenames.has_key(filename):
                    self.filenames[filename] = []
                self.filenames[filename].append(pkg)
            self.pkglist[nevra] = pkg
        return 1

    def write(self):
        if not self.__mkDBDirs():
            return 0
        return 1

    def addPkg(self, pkg, nowrite=None):
        if not self.__mkDBDirs():
            return 0
        nevra = pkg.getNEVRA()
        if not nowrite:
            src = "pydb:/"+self.source+"/headers/"+nevra
            apkg = getRpmIOFactory(src)
            if not apkg.write(pkg):
                return 0
            apkg.close()
        for filename in pkg["filenames"]:
            if not self.filenames.has_key(filename):
                self.filenames[filename] = []
            if pkg in self.filenames[filename]:
                printWarning(2, "%s: File '%s' was already in PyDB for package"\
                    % (nevra, filename))
                self.filenames[filename].remove(pkg)
            self.filenames[filename].append(pkg)
        if not self.write():
            return 0
        self.pkglist[nevra] = pkg
        return 1

    def erasePkg(self, pkg, nowrite=None):
        if not self.__mkDBDirs():
            return 0
        nevra = pkg.getNEVRA()
        if not nowrite:
            headerfile = self.source+"/headers/"+nevra
            try:
                os.unlink(headerfile)
            except:
                printWarning(1, "%s: Package not found in PyDB" % nevra)
        for filename in pkg["filenames"]:
            # Check if the filename is in the filenames list and was referenced
            # by the package we want to remove
            if not self.filenames.has_key(filename) or \
               not pkg in self.filenames[filename]:
                printWarning(1, "%s: File '%s' not found in PyDB during erase"\
                    % (nevra, filename))
                continue
            self.filenames[filename].remove(pkg)
        if not self.write():
            return 0
        del self.pkglist[nevra]
        return 1

    def getPackage(self, name):
        if not self.pkglist:
            if not self.read():
                return None
        if not self.pkglist.has_key(name):
                return None
        return self.pkglist[name]

    def getPkgList(self):
        if not self.pkglist:
            if not self.read():
                return {}
        return self.pkglist

    def isDuplicate(self, file):
        if not self.pkglist:
            if not self.read():
                return 1
        if self.filenames.has_key(file) and len(self.filenames[file]) > 1:
            return 1
        return 0

    def getNumPkgs(self, name):
        if not self.pkglist:
            if not self.read():
                return 0
        count = 0
        for pkg in self.pkglist.values():
            if pkg["name"] == name:
                count += 1
        return count

    def __mkDBDirs(self):
        if not os.path.isdir(self.source):
            try:
                os.makedirs(self.source)
            except:
                printError("%s: Couldn't open PyRPM database" % self.source)
                return 0
        if not os.path.isdir(self.source+"/headers"):
            try:
                os.makedirs(self.source+"/headers")
            except:
                printError("%s: Couldn't open PyRPM headers" % self.source)
                return 0
        return 1


class RpmRepoIO(RpmFileIO):
    def __init__(self, source, verify=None, strict=None, hdronly=None):
        RpmFileIO.__init__(self, source, verify, strict, hdronly)


class RpmCompsXMLIO:
    def __init__(self, source, verify=None):
        self.source = source
        self.grouphash = {}
        self.grouphierarchyhash = {}

    def __str__(self):
        return str(self.grouphash)

    def read(self):
        doc = libxml2.parseFile (self.source)
        if doc == None:
            return 0
        root = doc.getRootElement()
        if root == None:
            return 0
        return self.__parseNode(root.children)

    def write(self):
        pass

    def getPackageNames(self, group):
        ret = []
        if not self.grouphash.has_key(group):
            return ret
        if self.grouphash[group].has_key("packagelist"):
            pkglist = self.grouphash[group]["packagelist"]
            for pkgname in pkglist:
                if pkglist[pkgname][0] == "mandatory" or \
                   pkglist[pkgname][0] == "default":
                    ret.append(pkgname)
                    for req in pkglist[pkgname][1]:
                        ret.append(req)
        if self.grouphash[group].has_key("grouplist"):
            grplist = self.grouphash[group]["grouplist"]
            for grpname in grplist["groupreqs"]:
                ret.extend(self.getPackageNames(grpname))
            for grpname in grplist["metapkgs"]:
                if grplist["metapkgs"][grpname] == "mandatory" or \
                   grplist["metapkgs"][grpname] == "default":
                    ret.extend(self.getPackageNames(grpname))
        # Sort and duplicate removal
        ret.sort()
        for i in xrange(len(ret)-2, -1, -1):
            if ret[i+1] == ret[i]:
                ret.pop(i+1)
        return ret

    def __parseNode(self, node):
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "group":
                ret = self.__parseGroup(node.children)
                if not ret:
                    return 0
            elif node.name == "grouphierarchy":
                ret = self.__parseGroupHierarchy(node.children)
                if not ret:
                    return 0
            else:
                printWarning(1, "Unknown entry in comps.xml: %s" % node.name)
                return 0
            node = node.next

    def __parseGroup(self, node):
        group = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if  node.name == "name":
                lang = node.prop("lang")
                if lang:
                    group["name:"+lang] = node.content
                else:
                    group["name"] = node.content
            elif node.name == "id":
                group["id"] = node.content
            elif node.name == "description":
                lang = node.prop("lang")
                if lang:
                    group["description:"+lang] = node.content
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
            if   node.name == "groupreq":
                glist["groupreqs"].append(node.content)
            elif node.name == "metapkg":
                gtype = node.prop("type")
                if gtype == None:
                    gtype = "default"
                glist["metapkgs"][node.content] = gtype
            node = node.next
        return glist

    def __parseGroupHierarchy(self, node):
        # We don't need grouphierarchies, so don't parse them ;)
        return 1
#        group = {}
#        while node != None:
#            if node.type != "element":
#                node = node.next
#                continue
#            if node.name == "name":
#                lang = node.prop('lang')
#                if lang != None:
#                    group["name:"+lang] = node.content
#                else:
#                    name = totext(node.content)
#            node = node.next


def getRpmIOFactory(source, verify=None, strict=None, hdronly=None):
    if source[:4] == 'db:/':
        return RpmDBIO(source[4:], verify, strict, hdronly)
    elif source[:5] == 'ftp:/':
        return RpmFtpIO(source, verify, strict, hdronly)
    elif source[:6] == 'file:/':
        return RpmFileIO(source[6:], verify, strict, hdronly)
    elif source[:6] == 'http:/':
        return RpmHttpIO(source, verify, strict, hdronly)
    elif source[:6] == 'pydb:/':
        return RpmPyDBIO(source[6:], verify, strict, hdronly)
    elif source[:6] == 'repo:/':
        return RpmRepoIO(source[6:], verify, strict, hdronly)
    else:
        return RpmFileIO(source, verify, strict, hdronly)
    return None

# vim:ts=4:sw=4:showmatch:expandtab
