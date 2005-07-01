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


import fcntl, bsddb, libxml2, os, os.path, time
import zlib, gzip, sha, md5, string, stat, openpgp, re
from struct import pack, unpack
from binascii import b2a_hex, a2b_hex

from base import *
import functions
import package

FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT = 1, 2, 4, 8, 16
class PyGZIP:
    def __init__(self, config, fd):
        self.config = config
        self.fd = fd
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")
        self.length = 0                 # Length of data read so far
        self.buffer = []                # List of data blocks
        self.bufferlen = 0
        self.pos = 0               # Offset of next data to read from buffer[0]
        self.enddata = ""
        self.header_read = 0

    def __readHeader(self):
        """Read gzip header.

        Raise IOError."""
        
        magic = self.fd.read(2)
        if magic != '\037\213':
            raise IOError("Not a gzipped file")
        if ord(functions.readExact(self.fd, 1)) != 8:
            raise IOError("Unknown compression method")
        flag = ord(functions.readExact(self.fd, 1)) 
        # Discard modification time, extra flags, OS byte
        functions.readExact(self.fd, 4+1+1) 
        if flag & FEXTRA:
            # Read & discard the extra field, if present
            (xlen,) = unpack("<H", functions.readExact(self.fd, 2))
            functions.readExact(self.fd, xlen)
        if flag & FNAME:
            # Read and discard a nul-terminated string containing the filename
            while (1):
                s=self.fd.read(1)
                if s=='\000':
                    break
                if not s:
                    raise IOError, "Unexpected EOF"
        if flag & FCOMMENT:
            # Read and discard a nul-terminated string containing a comment
            while (1):
                s=self.fd.read(1)
                if s=='\000':
                    break
                if not s:
                    raise IOError, "Unexpected EOF"
        if flag & FHCRC:
            functions.readExact(self.fd, 2)      # Read & discard the 16-bit header CRC
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")
        self.header_read = 1

    def read(self, bytes=None):
        """Decompress up to bytes bytes from input.

        Raise IOError."""

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
            # We've read to the end of the file, so we have to take the last 8
            # bytes from the buffer containing the CRC and the file size.  The
            # decompressor is smart and knows when to stop, so feeding it
            # extra data is harmless.
            	try:
                    crc32 = unpack("!I", self.enddata[0:4])
                    isize = unpack("!I", self.enddata[4:8])
                except struct.error:
                    raise IOError, "Unexpected EOF"
                if crc32 != self.crcval:
                    raise IOError, "CRC check failed."
                if isize != self.length:
                    raise IOError, "Incorrect length of data produced"
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
    def __init__(self, config, fd):
        self.config = config
        self.fd = fd                    # filedescriptor
        self.lastfilesize = 0           # Length of "current" file data
        self.readsize = 0       # Number of bytes read from "current" file data

    def getNextEntry(self):
        """Read next header and contents, return (file name, file data length),
        or (None, None) at EOF.

        Metadata is discarded.  Raise IOError."""
        
        self.readsize = 0
        # Do padding if necessary for nexty entry
        functions.readExact(self.fd, (4 - (self.lastfilesize % 4)) % 4)
        # The cpio header contains 8 byte hex numbers with the following
        # content: magic, inode, mode, uid, gid, nlink, mtime, filesize,
        # devMajor, devMinor, rdevMajor, rdevMinor, namesize, checksum.
        data = functions.readExact(self.fd, 110)
        # CPIO ASCII hex, expanded device numbers (070702 with CRC)
        if data[0:6] not in ["070701", "070702"]:
            raise IOError, "Bad magic reading CPIO headers %s" % data[0:6]
        # Read filename and padding.
        filenamesize = int(data[94:102], 16)
        filename = functions.readExact(self.fd, filenamesize).rstrip("\x00")
        functions.readExact(self.fd, (4 - ((110 + filenamesize) % 4)) % 4)
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
        self.lastfilesize = int(data[54:62], 16)
        return (filename, self.lastfilesize)

    def read(self, size):
        """Return up to size bytes of file data.

        Raise IOError."""
        
        if size > self.lastfilesize - self.readsize:
            size = self.lastfilesize - self.readsize
        self.readsize += size
        return functions.readExact(self.fd, size)

    def skipToNextFile(self):
        """Skip current file data.

        Raise IOError."""
        
        size = self.lastfilesize - self.readsize
        data = "1"
        while size > 0 and data:
            data = self.read(min(size, 65536))
            size -= len(data)
        if size > 0:
            raise IOError, "Unexpected EOF from CPIO archive"

class RpmIO:
    """'Virtual' IO Class for RPM packages and data"""
    def __init__(self, config, source):
        self.config = config
        self.source = source

    def open(self, mode="r"):
        """Open self.source using the specified mode.

        Raise IOError."""

        raise NotImplementedError

    def read(self, skip=None):
        """Read next "entry" from package.

        Return
        - (tag name, tag value)
        - (filename, CPIOFile, length)
        - ("magic", RPM_HEADER_LEAD_MAGIC): lead
        - ("-", (pos or None if unknown, length)): before sigs/header/payload
        - ("EOF", 0, 0): after payload
        Raise ValueError on invalid data, IOError."""

        raise NotImplementedError

    def write(self, pkg):
        """Write a RpmPackage header (without payload!) to self.source.

        Raise IOError, NotImplementedError."""
        
        raise NotImplementedError

    def close(self):
        """Close all open files used for reading self.source.

        Raise IOError."""

        pass

    def getRpmFileSize(self):
        """Return number of bytes of .rpm file representing this package
        or None if not known."""

        return None

    def updateDigestFromRange(self, digest, start, len):
        """Update digest with data from position start, until EOF or only
        len bytes.

        Raise NotImplementedError, IOError."""

        raise NotImplementedError

    def updateDigestFromRegion(self, digest, region, header_pos):
        """Update digest with data from immutable region in header at
        header_pos (= (start, len)).

        Raise ValueError on invalid header or region == None,
        NotImplementedError, IOError."""

        raise NotImplementedError

class RpmStreamIO(RpmIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmIO.__init__(self, config, source)
        self.fd = None
        self.cpio = None
        self.verify = verify            # Verify lead and index entries
        self.strict = strict # Report legacy tags and packags not named %name
        self.hdronly = hdronly          # Don't return payload from read()
        self.issrc = 0
        self.where = 0  # 0:lead 1:separator 2:sig 3:header 4:files
        self.idx = 0 # Current index
        self.hdr = {}

    def open(self, mode="r"):
        """Open self.source using the specified mode, set self.fd to non-None.

        Raise IOError."""

        raise NotImplementedError

    def close(self):
        if self.cpio:
            self.cpio = None

    def read(self, skip=None):
        """RpmIO.read(), if (skip) on first call, skip to the delimiter before
        payload."""

        if self.fd == None:
            self.open()
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
            # FIXME: unknown tags?
            return (rpmsigtagname[v[0]], v[1])
        # Read/parse hdr
        if self.where == 3:
            # Shall we skip header parsing?
            # Last index of hdr? Switch to data files archive
            if self.idx >= self.hdrdata[0] or skip:
                pos = self._tell()
                self.hdrdata = None
                self.hdr = {}
                cpiofd = PyGZIP(self.config, self.fd)
                self.cpio = CPIOFile(self.config, cpiofd)
                self.where = 4
                # Nobody cares about gzipped payload length so far
                return ("-", (pos, None))
            v = self.getHeaderByIndex(self.idx, self.hdrdata[3], self.hdrdata[4])
            self.idx += 1
            # FIXME: unknown tags?
            return (rpmtagname[v[0]], v[1])
        # Read/parse data files archive
        if self.where == 4 and not self.hdronly and self.cpio != None:
            self.cpio.skipToNextFile()
            (filename, filesize) = self.cpio.getNextEntry()
            if filename != None:
                return (filename, self.cpio, filesize)
        return  ("EOF", 0, 0)

    def write(self, pkg):
        if self.fd == None:
            self.open("w+")
        lead = pack("!4scchh66shh16x", RPM_HEADER_LEAD_MAGIC, '\x04', '\x00', 0, 1, pkg.getNEVR()[0:66], rpm_lead_arch[pkg["arch"]], 5)
        (sigindex, sigdata) = self.__generateSig(pkg["signature"])
        (headerindex, headerdata) = self._generateHeader(pkg)
        self._write(lead)
        self._write(sigindex)
        self._write(sigdata)
        self._write(headerindex)
        self._write(headerdata)
        return 1

    def _read(self, nbytes=None):
        """Read up to nbytes data from self.fd.

        Raise IOError."""

        if self.fd == None:
            self.open()
        return self.fd.read(nbytes)

    def _write(self, data):
        """Open self.source for writing if it is not open, write data to it.

        Raise IOError."""
        
        if self.fd == None:
            self.open("w+")
        return self.fd.write(data)

    def _tell(self):
        """Return current file position or None if file is not seekable."""

        try:
            return self.fd.tell()
        except IOError:
            return None

    def __readLead(self):
        """Read lead.

        self.fd should already be open.  Raise ValueError on invalid data,
        IOError."""
        
        leaddata = functions.readExact(self.fd, 96)
        if leaddata[:4] != RPM_HEADER_LEAD_MAGIC:
            raise ValueError, "no rpm magic found"
        if self.verify:
            self.__verifyLead(leaddata)
        return ("magic", leaddata[:4])

    def __readSig(self):
        """Read signature header.

        self.fd should already be open.  Raise ValueError on invalid data,
        IOError."""

        self.hdr = {}
        self.hdrdata = self.__readIndex(8, 1)

    def __readHdr(self):
        """Read main header.
        
        self.fd should already be open.  Raise ValueError on invalid data,
        IOError."""

        self.hdr = {}
        self.hdrdata = self.__readIndex(1)

    def getHeaderByIndex(self, idx, indexdata, storedata):
        """Parse value of tag idx.

        Return (tag number, tag data).  Raise ValueError on invalid data."""

        index = unpack("!4i", indexdata[idx*16:(idx+1)*16])
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.__parseTag(index, storedata):
                self.config.printError("%s: tag %d included twice" % (self.source, tag))
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
        return (tag, self.hdr[tag])

    def __verifyLead(self, leaddata):
        """Verify RPM lead leaddata.

        Raise ValueError on invalid data."""
        
        (magic, major, minor, rpmtype, arch, name, osnum, sigtype) = \
            unpack("!4scchh66shh16x", leaddata)
        if major not in ('\x03', '\x04') or minor != '\x00' or \
            sigtype != 5 or rpmtype not in (0, 1):
            raise ValueError, "Unsupported RPM file format"
        if osnum not in (1, 255, 256):
            raise ValueError, "Package operating system doesn't match"
        name = name.rstrip('\x00')
        if self.strict:
            if os.path.basename(self.source)[:len(name)] != name:
                raise ValueError, "File name doesn't match package name"

    def __readIndex(self, pad, issig=None):
        """Read and verify header index and data.

        self.fd should already be open.  Return (number of tags, tag data size,
        header header, index data, data area, total header size).  Discard data
        to enforce alignment at least pad.  Raise ValueError on invalid data,
        IOError."""

        data = functions.readExact(self.fd, 16)
        (magic, indexNo, storeSize) = unpack("!8sii", data)
        if magic != RPM_HEADER_INDEX_MAGIC or indexNo < 1:
            raise ValueError, "bad index magic"
        fmt = functions.readExact(self.fd, 16 * indexNo)
        fmt2 = functions.readExact(self.fd, storeSize)
        if pad != 1:
            functions.readExact(self.fd, (pad - (storeSize % pad)) % pad)
        if self.verify:
            self.__verifyIndex(fmt, fmt2, indexNo, storeSize, issig)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + len(fmt2))

    def __verifyIndex(self, fmt, fmt2, indexNo, storeSize, issig):
        """Verify header with index fmt (with indexNo entries), data area fmt
        (of size storeSize).

        Return tag data length.  Raise ValueError on invalid data."""
        
        checkSize = 0
        for i in xrange(0, indexNo * 16, 16):
            index = unpack("!iiii", fmt[i:i + 16])
            ttype = index[1]
            # FIXME: this doesn't actually check alignment
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
            raise ValueError, \
                  "storeSize/checkSize is %d/%d" % (storeSize, checkSize)

    def __verifyTag(self, index, fmt, issig):
        """Verify a tag with index entry index in data area fmt.

        Raise ValueError on invalid data; only print error messages on
        suspicious, but non-fatal errors."""
        
        (tag, ttype, offset, count) = index
        if issig:
            if not rpmsigtag.has_key(tag):
                raise ValueError, "rpmsigtag has no tag %d" % tag
            t = rpmsigtag[tag]
            if t[1] != None and t[1] != ttype:
                raise ValueError, "sigtag %d has wrong type %d" % (tag, ttype)
        else:
            if not rpmtag.has_key(tag):
                raise ValueError, "rpmtag has no tag %d" % tag
            t = rpmtag[tag]
            if t[1] != None and t[1] != ttype:
                if t[1] == RPM_ARGSTRING and (ttype == RPM_STRING or
                                              ttype == RPM_STRING_ARRAY):
                    pass    # special exception case for RPMTAG_GROUP (1016)
                elif t[0] == 1016 and \
                         ttype == RPM_STRING: # XXX hardcoded exception
                    pass
                else:
                    raise ValueError, "tag %d has wrong type %d" % (tag, ttype)
        if t[2] != None and t[2] != count:
            raise ValueError, "tag %d has wrong count %d" % (tag, count)
        if (t[3] & 1) and self.strict:
            self.config.printError("%s: tag %d is marked legacy"
                                   % (self.source, tag))
        if self.issrc:
            if (t[3] & 4):
                self.config.printError("%s: tag %d should be for binary rpms"
                                       % (self.source, tag))
        else:
            if (t[3] & 2):
                self.config.printError("%s: tag %d should be for src rpms"
                                       % (self.source, tag))
        if count == 0:
            raise ValueError, "zero length tag"
        if ttype < 1 or ttype > 9:
            raise ValueError, "unknown rpmtype %d" % ttype
        if ttype == RPM_INT32:
            count = count * 4
        elif ttype == RPM_STRING_ARRAY or \
            ttype == RPM_I18NSTRING:
            size = 0
            for _ in xrange(0, count):
                end = fmt.index('\x00', offset) + 1
                size += end - offset
                offset = end
            count = size
        elif ttype == RPM_STRING:
            if count != 1:
                raise ValueError, "tag string count wrong"
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
            raise ValueError, "unknown tag header"
        return count

    def __parseTag(self, index, fmt):
        """Parse value of tag with index from data in fmt.

        Return tag value.  Raise ValueError on invalid data."""
        
        (tag, ttype, offset, count) = index
        try:
            if ttype == RPM_INT32:
                return unpack("!%dI" % count, fmt[offset:offset + count * 4])
            elif ttype == RPM_STRING_ARRAY or ttype == RPM_I18NSTRING:
                data = []
                for _ in xrange(0, count):
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
            raise ValueError, "unknown tag type: %d" % ttype
        except struct.error:
            raise ValueError, "Invalid header data"

    class __GeneratedHeader:
        """A helper for header generation."""
        
        def __init__(self, taghash, tagnames, region):
            """Initialize for creating a header with region tag region.

            taghash is base.rpmsigtag or base.rpmtag, tagnames is the
            corresponding tag name hash."""
            
            self.taghash = taghash
            self.tagnames = tagnames
            self.region = region
            self.store = ""
            self.offset = 0
            self.indexlist = []

        def outputHeader(self, header, align, skip_tags):
            """Return (index data, data area) representing signature header
            (tag name => tag value), with data area end aligned to align"""

            install_keys = [257, 261, 262, 264, 265, 267, 269, 1008, 1029, 1046, 1099, 1127, 1128]
            keys = self.tagnames.keys()
            keys.sort()
            # 1st pass: Output sorted non install only tags
            for tag in keys:
                if tag in skip_tags:
                    continue
                # We'll handled the region header at the end...
                if tag == self.region:
                    continue
                # Skip keys only appearing in /var/lib/rpm/Packages
                if tag in install_keys:
                    continue
                key = self.tagnames[tag]
                # Skip keys we don't have
                if not header.has_key(key):
                    continue
                self.__appendTag(tag, header[key])
            # 2nd pass: Ouput install only tags
            for tag in install_keys:
                if tag in skip_tags:
                    continue
                # Skip tags we don't have
                if not self.tagnames.has_key(tag):
                    continue
                key = self.tagnames[tag]
                # Skip keys we don't have
                if not header.has_key(key):
                    continue
                self.__appendTag(tag, header[key])
            # Handle region header if we have it at the end.
            key = self.tagnames[self.region]
            if header.has_key(key):
                self.__appendTag(self.region, header[key])
            (index, pad) = self.__generateIndex(align)
            return (index, self.store+pad)

        def __appendTag(self, tag, value):
            """Append tag (tag = value)"""

            ttype = self.taghash[tag][1]
            # Convert back the RPM_ARGSTRING to RPM_STRING
            if ttype == RPM_ARGSTRING:
                ttype = RPM_STRING
            (count, data) = self.__generateTag(ttype, value)
            pad = self.__alignTag(ttype)
            self.offset += len(pad)
            self.indexlist.append((tag, ttype, self.offset, count))
            self.store += pad + data
            self.offset += len(data)
            
        def __generateTag(self, ttype, value):
            """Return (tag data, tag count for index header) for value of
            ttype."""
            
            # Decide if we have to write out a list or a single element
            if isinstance(value, (tuple, list)):
                count = len(value)
            else:
                count = 0
            # Normally we don't have strings. And strings always need to be
            # '\x0' terminated.
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
                raise NotImplemented, "unknown tag header"
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

        def __generateIndex(self, pad):
            """Return (header tags, padding after data area) with data area end
            aligned to pad."""
        
            index = ""
            for (tag, ttype, offset, count) in self.indexlist:
                # Make sure the region tag is the first one in the index
                # despite being the last in the store
                if tag == self.region:
                    index = pack("!iiii", tag, ttype, offset, count) + index
                else:
                    index += pack("!iiii", tag, ttype, offset, count)
            align = (pad - (len(self.store) % pad)) % pad
            index = RPM_HEADER_INDEX_MAGIC +\
                    pack("!ii", len(self.indexlist), len(self.store)+align) + index
            return (index, '\x00' * align)

        def __alignTag(self, ttype):
            """Return alignment data for aligning for ttype from offset
            self.offset."""

            if ttype == RPM_INT16:
                align = (2 - (self.offset % 2)) % 2
            elif ttype == RPM_INT32:
                align = (4 - (self.offset % 4)) % 4
            elif ttype == RPM_INT64:
                align = (8 - (self.offset % 8)) % 8
            else:
                align = 0
            return '\x00' * align

    def __generateSig(self, header):
        """Return (index data, data area) representing signature header
        (tag name => tag value)"""

        h = self.__GeneratedHeader(rpmsigtag, rpmsigtagname, 62)
        return h.outputHeader(header, 8, [])

    def _generateHeader(self, header, padding=1, skip_tags=[]):
        """Return (index data, data area) representing signature header
        (tag name => tag value)"""

        h = self.__GeneratedHeader(rpmtag, rpmtagname, 63)
        return h.outputHeader(header, padding, skip_tags)


class RpmFileIO(RpmStreamIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)
        self.issrc = 0
        if source.endswith(".src.rpm") or source.endswith(".nosrc.rpm"):
            self.issrc = 1

    def __openFile(self, mode="r"):
        """Open self.source, mark it close-on-exec.

        Return the opened file.  Raise IOError."""
        
        if not self.source.startswith("file:/"):
            filename = self.source
        else:
            filename = self.source[5:]
            if filename[1] == "/":
                idx = filename[2:].index("/")
                filename = filename[idx+2:]
        fd = open(filename, mode)
        fcntl.fcntl(fd.fileno(), fcntl.F_SETFD, 1)
        return fd

    def open(self, mode="r"):
        if not self.fd:
            self.fd = self.__openFile(mode)

    def close(self):
        RpmStreamIO.close(self)
        if self.fd:
            self.fd.close()
            self.fd = None

    def __getFdForRange(self, start, length):
        """Open self.source, seek to start and make sure there are at
        least length bytes available if len != 0.

        Return the open file.  Raise IOError."""
        
        fd = self.__openFile()
        fd.seek(0, 2)
        total = fd.tell()
        if length is None:
            length = 0
        if start + length > total:
            raise IOError, "File was truncated"
        fd.seek(start)
        return fd

    def getRpmFileSize(self):
        try:
            fd = self.__getFdForRange(0, None)
        except IOError:
            return None
        return os.fstat(fd.fileno()).st_size

    def updateDigestFromRange(self, digest, start, len):
        fd = self.__getFdForRange(start, len)
        functions.updateDigestFromFile(digest, fd, len)

    def updateDigestFromRegion(self, digest, region, header_pos):
        if region is None or len(region) != 16:
            # What was the digest computed from?
            raise ValueError, "No region"
        (tag, type_, offset, count) = unpack("!4i", region)
        # FIXME: other regions than "immutable"?
        if (tag != 63 or type_ != RPM_BIN or -offset <= 0 or -offset % 16 != 0
            or count != 16):
            raise ValueError, "Invalid region"
        regionIndexEntries = -offset / 16
        if header_pos[0] is None:
            raise NotImplementedError
        fd = self.__getFdForRange(*header_pos)
        data = fd.read(16)
        if len(data) != 16:
            raise ValueError, "Unexpected EOF in header"
        (totalIndexEntries, totalDataSize) = unpack("!8x2i", data)
        data = fd.read(16 * totalIndexEntries)
        if len(data) != 16 * totalIndexEntries:
            raise ValueError, "Unexpected EOF in header"
        unsignedTags = []
        for i in xrange(totalIndexEntries):
            (tag, type_, offset, count) = \
                  unpack("!4i", data[i * 16 : (i + 1) * 16])
            # FIXME: other regions than "immutable"?
            if tag == 63:
                break
            unsignedTags.append(tag)
        else:
            raise ValueError, "%s: immutable tag disappeared" % self.source
        if (type_ != RPM_BIN or count != 16 or
            i + regionIndexEntries > totalIndexEntries):
            raise ValueError, "Invalid region tag"
        digest.update(pack("!2i", regionIndexEntries, offset + 16))
        digest.update(data[i * 16 : (i + regionIndexEntries) * 16])
        for i in xrange(i + regionIndexEntries, totalIndexEntries):
            (tag,) = unpack("!i", data[i * 16 : i * 16 + 4])
            unsignedTags.append(tag)
        if unsignedTags:
            # FIXME: only once per package
            self.config.printWarning(0, "%s: Unsigned tags %s"
                                     % (self.source,
                                        [rpmtagname[i] for i in unsignedTags]))
        # In practice region data starts at offset 0, but the original design
        # was proposing concatenated regions etc; where would the data region
        # start in that case? Lowest offset in region perhaps?
        functions.updateDigestFromFile(digest, fd, offset + 16)

class RpmFtpIO(RpmStreamIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)

    def open(self, mode="r"):
        import urlgrabber
        try:
            self.fd = urlgrabber.urlopen(self.source)
        except urlgrabber.grabber.URLGrabError, e:
            raise IOError, str(e)

    def close(self):
        RpmStreamIO.close(self)
        self.fd.close()
        self.fd = None


class RpmHttpIO(RpmStreamIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)

    def open(self, mode="r"):
        import urlgrabber
        try:
            self.fd = urlgrabber.urlopen(self.source)
        except urlgrabber.grabber.URLGrabError, e:
            raise IOError, str(e)

    def close(self):
        RpmStreamIO.close(self)
        self.fd.close()
        self.fd = None

    def _write(self, data):
        raise NotImplementedError

    def _tell(self):
        return None

class RpmDatabase:
    def __init__(self, config, source, buildroot=None):
        self.config = config
        self.source = source
        self.buildroot = buildroot
        self.filenames = {}
        self.pkglist = {}
        self.keyring = openpgp.PGPKeyRing()
        self.is_read = 0

    def setSource(self, source):
        self.source = source

    def setBuildroot(self, buildroot):
        self.buildroot = buildroot

    def read(self):
        raiseFatal("RpmDatabase::read() method not implemented")

    def write(self):
        raiseFatal("RpmDatabase::write() method not implemented")

    def addPkg(self, pkg, nowrite=None):
        raiseFatal("RpmDatabase::addPkg() method not implemented")

    def erasePkg(self, pkg, nowrite=None):
        raiseFatal("RpmDatabase::erasePkg() method not implemented")

    def getPackage(self, name):
        if not self.pkglist.has_key(name):
                return None
        return self.pkglist[name]

    def getPkgList(self):
        return self.pkglist.values()

    def isInstalled(self, pkg):
        return pkg in self.pkglist.values()

    def isDuplicate(self, file):
        if self.filenames.has_key(file) and len(self.filenames[file]) > 1:
            return 1
        return 0

    def getNumPkgs(self, name):
        count = 0
        for pkg in self.pkglist.values():
            if pkg["name"] == name:
                count += 1
        return count

    def _getDBPath(self):
        if   self.source[:6] == 'pydb:/':
            tsource = self.source[6:]
        elif self.source[:7] == 'rpmdb:/':
            tsource = self.source[7:]
        else:
            tsource = self.source 
        if self.buildroot != None:
            return self.buildroot + tsource
        else:
            return tsource


class RpmDB(RpmDatabase):
    def __init__(self, config, source, buildroot=None):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.dbopen = False

    def read(self):
        if self.is_read:
            return 1
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            return 1
        try:
            db = bsddb.hashopen(dbpath+"/Packages", "c")
        except:
            return 1
        for key in db.keys():
            rpmio = RpmFileIO(self.config, "dummy")
            pkg = package.RpmPackage(self.config, "dummy")
            data = db[key]
            val = unpack("i", key)[0]
            if val != 0:
                (indexNo, storeSize) = unpack("!ii", data[0:8])
                indexdata = data[8:indexNo*16+8]
                storedata = data[indexNo*16+8:]
                pkg["signature"] = {}
                for idx in xrange(0, indexNo):
                    try:
                        (tag, tagval) = rpmio.getHeaderByIndex(idx, indexdata,
                                                               storedata)
                    except ValueError, e:
                        # FIXME: different handling?
                        config.printError("Invalid header entry %s in %s: %s"
                                          % (idx, key, e))
                        continue
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
                if pkg["name"].startswith("gpg-pubkey"):
                    keys = openpgp.parsePGPKeys(pkg["description"])
                    for k in keys:
                        self.keyring.addKey(k)
                    continue
                if not pkg.has_key("arch"):
                    continue
                pkg.generateFileNames()
                nevra = pkg.getNEVRA()
                pkg.source = "rpmdb:/"+dbpath+"/"+nevra
                for filename in pkg["filenames"]:
                    if not self.filenames.has_key(filename):
                        self.filenames[filename] = []
                    self.filenames[filename].append(pkg)
                self.pkglist[nevra] = pkg
                pkg["provides"] = pkg.getProvides()
                pkg["requires"] = pkg.getRequires() 
                pkg["obsoletes"] = pkg.getObsoletes()
                pkg["conflicts"] = pkg.getConflicts()
                pkg["triggers"] = pkg.getTriggers()
                pkg["install_id"] = val
                pkg.io = rpmio
                pkg.header_read = 1
                rpmio.hdr = {}
        self.is_read = 1
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        nevra = pkg.getNEVRA()
        for filename in pkg["filenames"]:
            if not self.filenames.has_key(filename):
                self.filenames[filename] = []
            if pkg in self.filenames[filename]:
                self.config.printWarning(2, "%s: File '%s' was already in PyDB for package" % (nevra, filename))
                self.filenames[filename].remove(pkg)
            self.filenames[filename].append(pkg)
        self.pkglist[nevra] = pkg 

        if nowrite:
            return 1

        self.__openDB4()

        id = 2
        while id in self.ids:
            id += 1
        self.ids.append(id)

        rpmio = RpmFileIO(self.config, "dummy")
        pkg["install_size_in_sig"] = pkg["signature"]["size_in_sig"]
        pkg["install_md5"] = pkg["signature"]["md5"]
        pkg["install_sha1header"] = pkg["signature"]["sha1header"]
        pkg["installtime"] = int(time.time())
        pkg["filestates"]= ['\x00']
        pkg["archivesize"] = pkg["signature"]["payloadsize"]
        pkg["installcolor"] = [0,]
        pkg["installtid"] = [self.config.tid, ]

        self.__writeDB4(self.basenames_db, "basenames", id, pkg)
        self.__writeDB4(self.conflictname_db, "conflictname", id, pkg)
        self.__writeDB4(self.dirnames_db, "dirnames", id, pkg)
        self.__writeDB4(self.filemd5s_db, "filemd5s", id, pkg, True, lambda x:a2b_hex(x))
        self.__writeDB4(self.group_db, "group", id, pkg)
        self.__writeDB4(self.installtid_db, "installtid", id, pkg, True, lambda x:pack("i", x))
        self.__writeDB4(self.name_db, "name", id, pkg, False)
        (headerindex, headerdata) = rpmio._generateHeader(pkg, 4)
        self.packages_db[pack("i", id)] = headerindex[8:]+headerdata
        self.__writeDB4(self.providename_db, "providename", id, pkg)
        self.__writeDB4(self.provideversion_db, "provideversion", id, pkg)
        self.__writeDB4(self.requirename_db, "requirename", id, pkg)
        self.__writeDB4(self.requireversion_db, "requireversion", id, pkg)
        self.__writeDB4(self.sha1header_db, "install_sha1header", id, pkg)
        self.__writeDB4(self.sigmd5_db, "install_md5", id, pkg)
        self.__writeDB4(self.triggername_db, "triggername", id, pkg)

    def erasePkg(self, pkg, nowrite=None):
        nevra = pkg.getNEVRA()
        for filename in pkg["filenames"]:
            # Check if the filename is in the filenames list and was referenced
            # by the package we want to remove
            if not self.filenames.has_key(filename) or \
               not pkg in self.filenames[filename]:
                self.config.printWarning(1, "%s: File '%s' not found in PyDB during erase"\
                    % (nevra, filename))
                continue
        del self.pkglist[nevra]

        if nowrite:
            return 1

        self.__openDB4()

        if not pkg.has_key("install_id"):
            return 0

        id = pkg["install_id"]

        self.__removeId(self.basenames_db, "basenames", id, pkg)
        self.__removeId(self.conflictname_db, "conflictname", id, pkg)
        self.__removeId(self.dirnames_db, "dirnames", id, pkg)
        self.__removeId(self.filemd5s_db, "filemd5s", id, pkg, True, lambda x:a2b_hex(x))
        self.__removeId(self.group_db, "group", id, pkg)
        self.__removeId(self.installtid_db, "installtid", id, pkg, True, lambda x:pack("i", x))
        self.__removeId(self.name_db, "name", id, pkg, False)
        self.__removeId(self.providename_db, "providename", id, pkg)
        self.__removeId(self.provideversion_db, "provideversion", id, pkg)
        self.__removeId(self.requirename_db, "requirename", id, pkg)
        self.__removeId(self.requireversion_db, "requireversion", id, pkg)
        self.__removeId(self.sha1header_db, "install_sha1header", id, pkg)
        self.__removeId(self.sigmd5_db, "install_md5", id, pkg)
        self.__removeId(self.triggername_db, "triggername", id, pkg)
        del self.packages_db[pack("i", id)]
        self.ids.remove(id)

    def __openDB4(self):
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            os.makedirs(dbpath)

        if not self.is_read:
            self.read()

        if not self.dbopen:
            # We first need to remove the __db files, otherwise rpm will later
            # be really upset. :)
            for i in xrange(9):
                try:
                    os.unlink("%s/__db.00%d" % (dbpath, i))
                except:
                    pass
            self.basenames_db      = bsddb.hashopen(dbpath+"/Basenames", "c")
            self.conflictname_db   = bsddb.hashopen(dbpath+"/Conflictname", "c")
            self.dirnames_db       = bsddb.btopen(dbpath+"/Dirnames", "c")
            self.filemd5s_db       = bsddb.hashopen(dbpath+"/Filemd5s", "c")
            self.group_db          = bsddb.hashopen(dbpath+"/Group", "c")
            self.installtid_db     = bsddb.btopen(dbpath+"/Installtid", "c")
            self.name_db           = bsddb.hashopen(dbpath+"/Name", "c")
            self.packages_db       = bsddb.hashopen(dbpath+"/Packages", "c")
            self.providename_db    = bsddb.hashopen(dbpath+"/Providename", "c")
            self.provideversion_db = bsddb.btopen(dbpath+"/Provideversion", "c")
            self.requirename_db    = bsddb.hashopen(dbpath+"/Requirename", "c")
            self.requireversion_db = bsddb.btopen(dbpath+"/Requireversion", "c")
            self.sha1header_db     = bsddb.hashopen(dbpath+"/Sha1header", "c")
            self.sigmd5_db         = bsddb.hashopen(dbpath+"/Sigmd5", "c")
            self.triggername_db    = bsddb.hashopen(dbpath+"/Triggername", "c")
            self.dbopen            = True
            self.ids               = map(lambda x:unpack("i", x)[0], self.packages_db.keys())

    def __removeId(self, db, tag, id, pkg, useidx=True, func=lambda x:str(x)):
        if not pkg.has_key(tag):
            return
        for idx in xrange(len(pkg[tag])):
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if not db.has_key(key):
                continue
            data = db[key]
            ndata = ""
            for i in xrange(0, len(data), 8):
                if not data[i:i+8] == pack("ii", id, idx):
                    ndata += data[i:i+8]
            db[key] = ndata

    def __writeDB4(self, db, tag, id, pkg, useidx=True, func=lambda x:str(x)):
        if not pkg.has_key(tag):
            return
        for idx in xrange(len(pkg[tag])):
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if tag == "requirename":
                # Skip rpmlib() requirenames...
                if key.startswith("rpmlib("):
                    continue
                # Skip install prereqs, just like rpm does...
                if isInstallPreReq(pkg["requireflags"][idx]):
                    continue
            if not db.has_key(key):
                db[key] = ""
            db[key] += pack("ii", id, idx)
            if not useidx:
                return

    def __getKey(self, tag, idx, pkg, useidx, func):
        if useidx:
            key = pkg[tag][idx]
        else:
            key = pkg[tag]
        # Convert empty keys, handle filemd5s a little different
        if key == "":
            if tag != "filemd5s":
                key = "\x00"
        else:
            key = func(key)
        return key


class RpmPyDB(RpmDatabase):
    def __init__(self, config, source, buildroot):
        RpmDatabase.__init__(self, config, source, buildroot)

    def read(self):
        if self.is_read:
            return 1
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath+"/headers"):
            return 1
        namelist = os.listdir(dbpath+"/headers")
        tags = list(self.config.resolvertags)
        tags.extend(("filerdevs", "filemtimes", "filelinktos", "fileusername", "filegroupname", "fileverifyflags", "filedevices", "fileinodes", "preunprog", "preun", "postunprog", "postun", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex"))
        for nevra in namelist:
            src = "pydb:/"+dbpath+"/headers/"+nevra
            pkg = package.RpmPackage(self.config, src)
            try:
                pkg.read(tags=tags)
                pkg.close()
            except (IOError, ValueError), e:
                self.config.printWarning(0, "Invalid header %s in database: %s"
                                         % (nevra, e))
                continue
            for filename in pkg["filenames"]:
                if not self.filenames.has_key(filename):
                    self.filenames[filename] = []
                self.filenames[filename].append(pkg)
            self.pkglist[nevra] = pkg
        if os.path.isdir(dbpath+"/pubkeys"):
            namelist = os.listdir(dbpath+"/pubkeys")
            for name in namelist:
                data = file(dbpath+"/pubkeys/"+name).read()
                for k in openpgp.parsePGPKeys(data):
                    self.keyring.addKey(k)
        self.is_read = 1
        return 1

    def write(self):
        if not self.__mkDBDirs():
            return 0
        return 1

    def addPkg(self, pkg, nowrite=None):
        if not nowrite and not self.__mkDBDirs():
            return 0
        dbpath = self._getDBPath()
        nevra = pkg.getNEVRA()
        if not nowrite:
            src = "pydb:/"+dbpath+"/headers/"+nevra
            apkg = getRpmIOFactory(self.config, src)
            try:
                apkg.write(pkg)
                apkg.close()
            except IOError:
                return 0
        for filename in pkg["filenames"]:
            if not self.filenames.has_key(filename):
                self.filenames[filename] = []
            if pkg in self.filenames[filename]:
                self.config.printWarning(2, "%s: File '%s' was already in PyDB for package" % (nevra, filename))
                self.filenames[filename].remove(pkg)
            self.filenames[filename].append(pkg)
        if not nowrite and not self.write():
            return 0
        self.pkglist[nevra] = pkg
        return 1

    def erasePkg(self, pkg, nowrite=None):
        if not nowrite and not self.__mkDBDirs():
            return 0
        dbpath = self._getDBPath()
        nevra = pkg.getNEVRA()
        if not nowrite:
            headerfile = dbpath+"/headers/"+nevra
            try:
                os.unlink(headerfile)
            except:
                self.config.printWarning(1, "%s: Package not found in PyDB" % nevra)
        for filename in pkg["filenames"]:
            # Check if the filename is in the filenames list and was referenced
            # by the package we want to remove
            if not self.filenames.has_key(filename) or \
               not pkg in self.filenames[filename]:
                self.config.printWarning(1, "%s: File '%s' not found in PyDB during erase"\
                    % (nevra, filename))
                continue
            self.filenames[filename].remove(pkg)
        if not nowrite and not self.write():
            return 0
        del self.pkglist[nevra]
        return 1

    def __mkDBDirs(self):
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath+"/headers"):
            try:
                os.makedirs(dbpath+"/headers")
            except:
                self.config.printError("%s: Couldn't open PyRPM database" % dbpath)
                return 0
        if not os.path.isdir(dbpath+"/pubkeys"):
            try:
                os.makedirs(dbpath+"/pubkeys")
            except IOError:
                pass
        return 1


class RpmRepo(RpmDatabase):
    def __init__(self, config, source, buildroot=None, excludes="", reponame="default"):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.excludes = excludes.split()
        self.reponame = reponame
        self.filelist_imported  = 0
        self.flagmap = { None: None,
                         "EQ": RPMSENSE_EQUAL,
                         "LT": RPMSENSE_LESS,
                         "GT": RPMSENSE_GREATER,
                         "LE": RPMSENSE_EQUAL | RPMSENSE_LESS,
                         "GE": RPMSENSE_EQUAL | RPMSENSE_GREATER,
                         RPMSENSE_EQUAL: "EQ",
                         RPMSENSE_LESS: "LT",
                         RPMSENSE_GREATER: "GT",
                         RPMSENSE_EQUAL | RPMSENSE_LESS: "LE",
                         RPMSENSE_EQUAL | RPMSENSE_GREATER: "GE"}
        # Files included in primary.xml
        self._filerc = re.compile('^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$')
        self._dirrc = re.compile('^(.*bin/.*|/etc/.*)$')

    def read(self):
        if not self.source.startswith("file:/"):
            filename = self.source
        else:
            filename = self.source[5:]
            if filename[1] == "/":
                idx = filename[2:].index("/")
                filename = filename[idx+2:]
        filename = functions.cacheLocal(filename + "/repodata/primary.xml.gz",
                              self.reponame)
        if not filename:
            return 0
        doc = libxml2.parseFile(filename)
        if doc == None:
            return 0
        root = doc.getRootElement()
        if root == None:
            return 0
        return self.__parseNode(root.children)

    def createRepo(self):
        self.filerequires = []
        self.config.printInfo(1, "Pass 1: Parsing package headers for file requires.\n")
        self.__readDir(self.source, "")
        if not self.source.startswith("file:/"):
            filename = self.source
        else:
            filename = self.source[5:]
            if filename[1] == "/":
                idx = filename[2:].index("/")
                filename = filename[idx+2:]
        if not os.path.isdir(filename+"/repodata"):
            try:
                os.makedirs(filename+"/repodata")
            except:
                self.config.printError("%s: Couldn't open PyRPM database" % filename)
                return 0
        pfd = gzip.GzipFile(filename+"/repodata/primary.xml.gz", "wb")
        if not pfd:
            return 0
        ffd = gzip.GzipFile(filename+"/repodata/filelists.xml.gz", "wb")
        if not ffd:
            return 0
        ofd = gzip.GzipFile(filename+"/repodata/other.xml.gz", "wb")
        if not ofd:
            return 0
        pdoc = libxml2.newDoc("1.0")
        proot = pdoc.newChild(None, "metadata", None)
        fdoc = libxml2.newDoc("1.0")
        froot = pdoc.newChild(None, "filelists", None)
        odoc = libxml2.newDoc("1.0")
        oroot = pdoc.newChild(None, "filelists", None)
        self.config.printInfo(1, "Pass 2: Writing repodata information.\n")
        pfd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        pfd.write('<metadata xmlns="http://linux.duke.edu/metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="%d">\n' % len(self.getPkgList()))
        ffd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        ffd.write('<filelists xmlns:rpm="http://linux.duke.edu/filelists" packages="%d">\n' % len(self.getPkgList()))
        for pkg in self.getPkgList():
            self.config.printInfo(2, "Processing complete data of package %s.\n" % pkg.getNEVRA())
            pkg.header_read = 0
            try:
                pkg.open()
                pkg.read()
            except (IOError, ValueError), e:
                self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                continue
            # If it is a source rpm change the arch to "src". Only valid
            # for createRepo, never do this anywhere else. ;)
            if pkg.isSourceRPM():
                pkg["arch"] = "src"
            checksum = self.__getChecksum(pkg)
            pkg["yumchecksum"] = checksum
            self.__writePrimary(pfd, proot, pkg)
            self.__writeFilelists(ffd, froot, pkg)
#            self.__writeOther(ofd, oroot, pkg)
	    try:
                pkg.close()
            except IOError:
                pass # Should not happen when opening for reading anyway
            pkg.clear()
        pfd.write('</metadata>\n')
        ffd.write('</filelists>\n')
        pfd.close()
        ffd.close()
        del self.filerequires
        return 1

    def __escape(self, str):
        """Return escaped string converted to UTF-8"""
        if str == None:
            return ''
        str = string.replace(str, "&", "&amp;")
        if isinstance(str, unicode):
            return str
        try:
            x = unicode(str, 'ascii')
            return str
        except UnicodeError:
            encodings = ['utf-8', 'iso-8859-1', 'iso-8859-15', 'iso-8859-2']
            for enc in encodings:
                try:
                    x = unicode(str, enc)
                except UnicodeError:
                    pass
                else:
                    if x.encode(enc) == str:
                        return x.encode('utf-8')
        newstring = ''
        for char in str:
            if ord(char) > 127:
                newstring = newstring + '?'
            else:
                newstring = newstring + char
        return re.sub("\n$", '', newstring)

    def __readDir(self, dir, location):
        files = os.listdir(dir)
        for f in files:
            if os.path.isdir("%s/%s" % (dir, f)):
                self.__readDir("%s/%s" % (dir, f), "%s%s/" % (location, f))
            elif f.endswith(".rpm"):
                path = dir + "/" + f
                pkg = package.RpmPackage(self.config, path)
                try:
                    pkg.read(tags=("name", "epoch", "version", "release", "arch", "sourcerpm", "requirename", "requireflags", "requireversion"))
                except (IOError, ValueError), e:
                    self.config.printWarning(0, "%s: %s" % (path, e)) 
                    continue
                pkg.close()
                if self.__isExcluded(pkg):
                    continue
                for reqname in pkg["requirename"]:
                    if reqname[0] == "/":
                        self.filerequires.append(reqname)
                # If it is a source rpm change the arch to "src". Only valid
                # for createRepo, never do this anywhere else. ;)
                if pkg.isSourceRPM():
                    pkg["arch"] = "src"
                nevra = pkg.getNEVRA()
                self.config.printInfo(2, "Adding %s to repo and checking file requires.\n" % nevra)
                pkg["yumlocation"] = location+f
                self.pkglist[nevra] = pkg

    def __writePrimary(self, fd, parent, pkg):
        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('type', 'rpm')
        pkg_node.newChild(None, 'name', pkg['name'])
        pkg_node.newChild(None, 'arch', pkg['arch'])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        tnode = pkg_node.newChild(None, 'checksum', pkg["yumchecksum"])
        tnode.newProp('type', self.config.checksum)
        tnode.newProp('pkgid', 'YES')
        pkg_node.newChild(None, 'summary', self.__escape(pkg['summary'][0]))
        pkg_node.newChild(None, 'description', self.__escape(pkg['description'][0]))
        pkg_node.newChild(None, 'packager', self.__escape(pkg['packager']))
        pkg_node.newChild(None, 'url', self.__escape(pkg['url']))
        tnode = pkg_node.newChild(None, 'time', None)
        tnode.newProp('file', str(pkg['buildtime'][0]))
        tnode.newProp('build', str(pkg['buildtime'][0]))
        tnode = pkg_node.newChild(None, 'size', None)
        tnode.newProp('package', str(pkg['signature']['size_in_sig'][0]+pkg.range_signature[0]+pkg.range_signature[1]))
        tnode.newProp('installed', str(pkg['size'][0]))
        tnode.newProp('archive', str(pkg['signature']['payloadsize'][0]))
        tnode = pkg_node.newChild(None, 'location', None)
        tnode.newProp('href', pkg["yumlocation"])
        fnode = pkg_node.newChild(None, 'format', None)
        self.__generateFormat(fnode, pkg)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __writeFilelists(self, fd, parent, pkg):
        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('pkgid', pkg["yumchecksum"])
        pkg_node.newProp('name', pkg["name"])
        pkg_node.newProp('arch', pkg["arch"])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        self.__generateFilelist(pkg_node, pkg, 0)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __getChecksum(self, pkg):
        # FIXME: raise IOError

        io = getRpmIOFactory(self.config, pkg.source)
        data = io._read(65536)
        if self.config.checksum == "md5":
            s = md5.new()
        else:
            s = sha.new()
        while len(data) > 0:
            s.update(data)
            data = io._read(65536)
        return s.hexdigest()

    def __generateFormat(self, node, pkg):
        node.newChild(None, 'rpm:license', self.__escape(pkg['license']))
        node.newChild(None, 'rpm:vendor', self.__escape(pkg['vendor']))
        node.newChild(None, 'rpm:group', self.__escape(pkg['group'][0]))
        node.newChild(None, 'rpm:buildhost', self.__escape(pkg['buildhost']))
        node.newChild(None, 'rpm:sourcerpm', self.__escape(pkg['sourcerpm']))
        tnode = node.newChild(None, 'rpm:header-range', None)
        tnode.newProp('start', str(pkg.range_signature[0] + pkg.range_signature[1]))
        tnode.newProp('end', str(pkg.range_payload[0]))
        if len(pkg["provides"]) > 0:
            self.__generateDeps(node, pkg, "provides")
        if len(pkg["requires"]) > 0:
            self.__generateDeps(node, pkg, "requires")
        if len(pkg["conflicts"]) > 0:
            self.__generateDeps(node, pkg, "conflicts")
        if len(pkg["obsoletes"]) > 0:
            self.__generateDeps(node, pkg, "obsoletes")
        self.__generateFilelist(node, pkg)

    def __generateDeps(self, node, pkg, name):
        dnode = node.newChild(None, 'rpm:%s' % name, None)
        deps = self.__filterDuplicateDeps(pkg[name])
        for dep in deps:
            enode = dnode.newChild(None, 'rpm:entry', None)
            enode.newProp('name', dep[0])
            if dep[1] != "":
                if (dep[1] & RPMSENSE_SENSEMASK) != 0:
                    enode.newProp('flags', self.flagmap[dep[1] & RPMSENSE_SENSEMASK])
                if isLegacyPreReq(dep[1]) or isInstallPreReq(dep[1]):
                    enode.newProp('pre', '1')
            if dep[2] != "":
                e,v,r = functions.evrSplit(dep[2])
                enode.newProp('epoch', e)
                enode.newProp('ver', v)
                if r != "":
                    enode.newProp('rel', r)

    def __filterDuplicateDeps(self, deps):
        fdeps = []
        for name, flags, version in deps:
            duplicate = 0
            for fname, fflags, fversion in fdeps:
                if name != fname or \
                   version != fversion or \
                   (isErasePreReq(flags) or \
                    isInstallPreReq(flags) or \
                    isLegacyPreReq(flags)) != \
                   (isErasePreReq(fflags) or \
                    isInstallPreReq(fflags) or \
                    isLegacyPreReq(fflags)) or \
                   (flags & RPMSENSE_SENSEMASK) != (fflags & RPMSENSE_SENSEMASK):
                    continue
                duplicate = 1
                break
            if not duplicate:
                fdeps.append([name, flags, version])
        return fdeps

    def __generateFilelist(self, node, pkg, filter=1):
        files = pkg['filenames']
        fileflags = pkg['fileflags']
        filemodes = pkg['filemodes']
        if files == None or fileflags == None or filemodes == None:
            return
        for (fname, mode, flag) in zip(files, filemodes, fileflags):
            if stat.S_ISDIR(mode):
                if not filter or \
                   self._dirrc.match(fname) or \
                   fname in self.filerequires:
                    tnode = node.newChild(None, 'file', self.__escape(fname))
                    tnode.newProp('type', 'dir')
            elif not filter or \
                 self._filerc.match(fname) or \
                 fname in self.filerequires:
                tnode = node.newChild(None, 'file', self.__escape(fname))
                if flag & RPMFILE_GHOST:
                    tnode.newProp('type', 'ghost')

    def addPkg(self, pkg, nowrite=None):
        if self.__isExcluded(pkg):
            return 0
        self.pkglist[pkg.getNEVRA()] = pkg
        return 1

    def importFilelist(self):
        if self.filelist_imported:
            return 1
        if not self.source.startswith("file:/"):
            filename = self.source
        else:
            filename = self.source[5:]
            if filename[1] == "/":
                idx = filename[2:].index("/")
                filename = filename[idx+2:]
        filename = functions.cacheLocal(filename + "/repodata/filelists.xml.gz",
                              self.reponame)
        if not filename:
            return 0
        doc = libxml2.parseFile(filename)
        if doc == None:
            return 0
        root = doc.getRootElement()
        if root == None:
            return 0
        self.filelist_imported = 1
        return self.__parseNode(root.children)

    def __parseNode(self, node):
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "package" and node.prop("type") == "rpm":
                pkg = self.__parsePackage(node.children)
                if pkg["arch"] == "src" or self.__isExcluded(pkg):
                    node = node.next
                    continue
                pkg["yumreponame"] = self.reponame
                self.pkglist[pkg.getNEVRA()] = pkg
            if node.name == "package" and node.prop("name") != None:
                self.__parseFilelist(node.children, node.prop("name"), node.prop("arch"))
            node = node.next
        return 1

    def __isExcluded(self, pkg):
        found = 0
        for ex in self.excludes:
            excludes = functions.findPkgByName(ex, [pkg])
            if len(excludes) > 0:
                found = 1
                break
        return found

    def __parsePackage(self, node):
        pkg = package.RpmPackage(self.config, "dummy")
        pkg["signature"] = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if   node.name == "name":
                pkg["name"] = node.content
            elif node.name == "arch":
                pkg["arch"] = node.content
            elif node.name == "version":
                pkg["version"] = node.prop("ver")
                pkg["release"] = node.prop("rel")
                pkg["epoch"] = [int(node.prop("epoch"))]
            elif node.name == "checksum":
                if   node.prop("type") == "md5":
                    pkg["signature"]["md5"] = node.content
                elif node.prop("type") == "sha":
                    pkg["signature"]["sha1header"] = node.content
            elif node.name == "location":
                pkg.source = self.source + "/" + node.prop("href")
            elif node.name == "format":
                self.__parseFormat(node.children, pkg)
            node = node.next
        pkg.header_read = 1
        pkg["provides"] = pkg.getProvides()
        pkg["requires"] = pkg.getRequires()
        pkg["obsoletes"] = pkg.getObsoletes()
        pkg["conflicts"] = pkg.getConflicts()
        pkg["triggers"] = pkg.getTriggers()
        if pkg.has_key("providename"):
            del pkg["providename"]
        if pkg.has_key("provideflags"):
            del pkg["provideflags"]
        if pkg.has_key("provideversion"):
            del pkg["provideversion"]
        if pkg.has_key("requirename"):
            del pkg["requirename"]
        if pkg.has_key("requireflags"):
            del pkg["requireflags"]
        if pkg.has_key("requireversion"):
            del pkg["requireversion"]
        if pkg.has_key("obsoletename"):
            del pkg["obsoletename"]
        if pkg.has_key("obsoleteflags"):
            del pkg["obsoleteflags"]
        if pkg.has_key("obsoleteversion"):
            del pkg["obsoleteversion"]
        if pkg.has_key("conflictname"):
            del pkg["conflictname"]
        if pkg.has_key("conflictflags"):
            del pkg["conflictflags"]
        if pkg.has_key("conflictversion"):
            del pkg["conflictversion"]
        return pkg

    def __parseFormat(self, node, pkg):
        pkg["filenames"] = []
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            elif node.name == "sourcerpm":
                pkg["sourcerpm"] = node.content
            elif node.name == "provides":
                plist = self.__parseDeps(node.children, pkg)
                pkg["providename"], pkg["provideflags"], pkg["provideversion"] = plist
            elif node.name == "requires":
                plist = self.__parseDeps(node.children, pkg)
                pkg["requirename"], pkg["requireflags"], pkg["requireversion"] = plist
            elif node.name == "obsoletes":
                plist = self.__parseDeps(node.children, pkg)
                pkg["obsoletename"], pkg["obsoleteflags"], pkg["obsoleteversion"] = plist
            elif node.name == "conflicts":
                plist = self.__parseDeps(node.children, pkg)
                pkg["conflictname"], pkg["conflictflags"], pkg["conflictversion"] = plist
            elif node.name == "file":
                pkg["filenames"].append(node.content)
            node = node.next

    def __parseDeps(self, node, pkg):
        plist = []
        plist.append([])
        plist.append([])
        plist.append([])
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "entry":
                name = node.prop("name")
                flags = node.prop("flags")
                ver = node.prop("ver")
                if node.prop("pre") == "1":
                    prereq = RPMSENSE_PREREQ
                else:
                    prereq = 0
                if ver == None:
                    plist[0].append(name)
                    plist[1].append(prereq)
                    plist[2].append("")
                    node = node.next
                    continue
                epoch = node.prop("epoch")
                rel = node.prop("rel")
                if epoch != None:
                    ver = "%s:%s" % (epoch, ver)
                if rel != None:
                    ver = "%s-%s" % (ver, rel)
                plist[0].append(name)
                plist[1].append(self.flagmap[flags] + prereq)
                plist[2].append(ver)
            node = node.next
        return plist

    def __parseFilelist(self, node, name, arch):
        filelist = []
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if   node.name == "version":
                version = node.prop("ver")
                release = node.prop("rel")
                epoch = node.prop("epoch")
            elif node.name == "file":
                filelist.append(node.content)
            node = node.next
        nevra = "%s-%s:%s-%s.%s" % (name, epoch, version, release, arch)
        if self.pkglist.has_key(nevra):
            self.pkglist[nevra]["filenames"] = filelist
        return 1

class RpmCompsXML:
    def __init__(self, config, source):
        self.config = config
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
                self.config.printWarning(1, "Unknown entry in comps.xml: %s" % node.name)
                return 0
            node = node.next
        return 0

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
                group["default"] = functions.parseBoolean(node.content)
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


def getRpmIOFactory(config, source, verify=None, strict=None, hdronly=None):
    if   source[:5] == 'ftp:/':
        return RpmFtpIO(config, source, verify, strict, hdronly)
    elif source[:6] == 'file:/':
        return RpmFileIO(config, source, verify, strict, hdronly)
    elif source[:6] == 'http:/':
        return RpmHttpIO(config, source, verify, strict, hdronly)
    elif source[:6] == 'pydb:/':
        return RpmFileIO(config, source[6:], verify, strict, hdronly)
    else:
        return RpmFileIO(config, source, verify, strict, hdronly)
    return None


def getRpmDBFactory(config, source, root=None):
    if   source[:6] == 'pydb:/':
        return RpmPyDB(config, source[6:], root)
    elif source[:7] == 'rpmdb:/':
        return RpmDB(config, source[7:], root)
    return RpmDB(config, source, root)


# vim:ts=4:sw=4:showmatch:expandtab
