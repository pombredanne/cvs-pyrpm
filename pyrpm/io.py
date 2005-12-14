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


import fcntl, bsddb, libxml2, os, os.path, sys, struct, time
import zlib, gzip, sha, md5, string, stat, openpgp, re, sqlite
(pack, unpack) = (struct.pack, struct.unpack)
from binascii import b2a_hex, a2b_hex
from types import TupleType
try:
    import urlgrabber
except:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module. Only check scripts available."

from base import *
import functions
import package


def _uriToFilename(uri):
    """Convert a file:/ URI or a local path to a local path."""

    if not uri.startswith("file:/"):
        filename = uri
    else:
        filename = uri[5:]
        if len(filename) > 1 and filename[1] == "/":
            idx = filename[2:].find("/")
            if idx != -1:
                filename = filename[idx+2:]
    return filename


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
                self.enddata = self.enddata[-8+len(data):] + data
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
                    crc32 = unpack("<i", self.enddata[0:4]) # le signed int
                    isize = unpack("<I", self.enddata[4:8]) # le unsigned int
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
    def __init__(self, config, source, hdronly=None):
        RpmIO.__init__(self, config, source)
        self.fd = None
        self.cpio = None
        self.hdronly = hdronly # Don't return payload from read()
        self.issrc = 0  # 0:binary rpm 1:source rpm
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
            # Correct the 'filemtimes' tag to be a signed integer
            if v[0] == 1034:    # 1034 == filemtimes tag
                MAXINT = 1L << 31
                for i in xrange(len(v[1])):
                    if v[1][i] >= MAXINT:
                        v[1][i] -= (MAXINT+MAXINT)
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
        lead = pack("!4s2c2h66s2h16x", RPM_HEADER_LEAD_MAGIC, '\x03', '\x00', 0, 1, pkg.getNEVR()[0:66], rpm_lead_arch[pkg["arch"]], 5)
        (sigindex, sigdata) = self.__generateSig(pkg["signature"])
        (headerindex, headerdata) = self._generateHeader(pkg, 1, [257, 261, 262, 264, 265, 267, 269, 1008, 1029, 1046, 1099, 1127, 1128])
        self._write(lead)
        self._write(sigindex)
        self._write(sigdata)
        self._write(headerindex)
        self._write(headerdata)
        return 1

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
        self.issrc = (leaddata[7] == "\01")
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

        index = unpack("!4I", indexdata[idx*16:(idx+1)*16])
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.__parseTag(index, storedata):
                self.config.printError("%s: tag %d included twice" % (self.source, tag))
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
        return (tag, self.hdr[tag])

    def __readIndex(self, pad, issig=None):
        """Read and verify header index and data.

        self.fd should already be open.  Return (number of tags, tag data size,
        header header, index data, data area, total header size).  Discard data
        to enforce alignment at least pad.  Raise ValueError on invalid data,
        IOError."""

        data = functions.readExact(self.fd, 16)
        (magic, indexNo, storeSize) = unpack("!8s2I", data)
        if magic != RPM_HEADER_INDEX_MAGIC or indexNo < 1:
            raise ValueError, "bad index magic"
        fmt = functions.readExact(self.fd, 16 * indexNo)
        fmt2 = functions.readExact(self.fd, storeSize)
        if pad != 1:
            functions.readExact(self.fd, (pad - (storeSize % pad)) % pad)
        return (indexNo, storeSize, data, fmt, fmt2, 16 + len(fmt) + len(fmt2))

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

        def outputHeader(self, header, align, skip_tags, install_keys=[257,
            261, 262, 264, 265, 267, 269, 1008, 1029, 1046, 1099, 1127, 1128]):
            """Return (index data, data area) representing header
            (tag name => tag value), with data area end aligned to align.

            Completely skip integer tags in skip_tags, defer tags in
            install_keys after the other tags."""

            keys = self.tagnames.keys()
            keys.sort()
            # 1st pass: Output sorted non install only tags
            for tag in keys:
                if tag in skip_tags:
                    continue
                # We'll handle the region header at the end...
                if tag == self.region:
                    continue
                # Skip keys only appearing in /var/lib/rpm/Packages
                if tag in install_keys:
                    continue
                key = self.tagnames[tag]
                # Skip keys we don't have
                if header.has_key(key):
                    self.__appendTag(tag, header[key])
            # Add region header.
            key = self.tagnames[self.region]
            if header.has_key(key):
                self.__appendTag(self.region, header[key])
            else:
                regiondata = self.__createRegionData()
                self.__appendTag(self.region, regiondata)
            # 2nd pass: Ouput install only tags.
            for tag in install_keys:
                if tag in skip_tags:
                    continue
                # Skip tags we don't have
                if not self.tagnames.has_key(tag):
                    continue
                key = self.tagnames[tag]
                # Skip keys we don't have
                if header.has_key(key):
                    self.__appendTag(tag, header[key])
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

        def __createRegionData(self):
            """Return region tag data for current index list."""

            tag = self.region
            type = RPM_BIN
            offset = -(len(self.indexlist) * 16) - 16
            count = 16
            return pack("!2IiI", tag, type, offset, count)

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
                        data += pack("%ds" % (len(value[i]) + isstring),
                            value[i])
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
                    index = pack("!4I", tag, ttype, offset, count) + index
                else:
                    index += pack("!4I", tag, ttype, offset, count)
            align = (pad - (len(self.store) % pad)) % pad
            index = RPM_HEADER_INDEX_MAGIC + pack("!2I", len(self.indexlist),
                len(self.store) + align) + index
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
        return h.outputHeader(header, 8, [], [])

    def _generateHeader(self, header, padding=1, skip_tags=[]):
        """Return (index data, data area) representing signature header
        (tag name => tag value).

        Completely skip integer tags in skip_tags.  Align data area end to
        padding."""

        # Old rpms have the provide stored in the additional headers after
        # the header image tag.
        # Also those rpms already had the archivesize in the normal header
        # as well, so we need to put 
        if header.has_key("rpmversion"):
            if   header["rpmversion"].startswith("3."):
                # In rpm 3.x there was only the oldfilenames tag, but rpm
                # stores the basenames/dirnames/dirindexes as additional tags
                # to the /var/lib/rpm/Packages header as well, so we need to
                # generate them.
                header.generateFileNames()
                # For rpm 3.x we need to add a self provide to the provides,
                # those were missing back in the old days. Only add it though
                # if it isn't already there.
                found_selfprovide = 0
                if header["providename"]:
                    for i in xrange(len(header["providename"])):
                        if header["providename"][i] != header["name"]:
                            continue
                        if (header["provideflags"][i] & RPMSENSE_EQUAL) != \
                           RPMSENSE_EQUAL:
                            continue
                        if header["provideversion"][i] == header.getVR():
                            found_selfprovide = 1
                if not found_selfprovide:
                    header.setdefault("providename", [])
                    header["providename"] = list(header["providename"])
                    header["providename"].append(header["name"])
                    header.setdefault("provideflags", [])
                    header["provideflags"] = list(header["provideflags"])
                    header["provideflags"].append(RPMSENSE_EQUAL)
                    header.setdefault("provideversion", [])
                    header["provideversion"] = list(header["provideversion"])
                    header["provideversion"].append(header.getVR())
                install_keys=[257, 261, 262, 264, 265, 267, 269, 1008, 1029, 1047, 1099, 1112, 1113, 1116, 1117, 1118, 1127, 1128]
                h = self.__GeneratedHeader(rpmtag, rpmtagname, 61)
                return h.outputHeader(header, padding, skip_tags, install_keys)
            elif header["rpmversion"].startswith("4.0."):
                install_keys=[257, 261, 262, 264, 265, 267, 269, 1008, 1029, 1099, 1127, 1128]
                h = self.__GeneratedHeader(rpmtag, rpmtagname, 63)
                return h.outputHeader(header, padding, skip_tags, install_keys)
        h = self.__GeneratedHeader(rpmtag, rpmtagname, 63)
        return h.outputHeader(header, padding, skip_tags)


class RpmFileIO(RpmStreamIO):
    def __init__(self, config, source, hdronly=None):
        RpmStreamIO.__init__(self, config, source, hdronly)

    def __openFile(self, mode="r"):
        """Open self.source, mark it close-on-exec.

        Return the opened file.  Raise IOError."""

        fd = open(_uriToFilename(self.source), mode)
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
        (tag, type_, offset, count) = unpack("!2IiI", region)
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
        (totalIndexEntries, totalDataSize) = unpack("!8x2I", data)
        data = fd.read(16 * totalIndexEntries)
        if len(data) != 16 * totalIndexEntries:
            raise ValueError, "Unexpected EOF in header"
        unsignedTags = []
        for i in xrange(totalIndexEntries):
            (tag, type_, offset, count) = \
                  unpack("!4I", data[i * 16 : (i + 1) * 16])
            # FIXME: other regions than "immutable"?
            if tag == 63:
                break
            unsignedTags.append(tag)
        else:
            raise ValueError, "%s: immutable tag disappeared" % self.source
        if (type_ != RPM_BIN or count != 16 or
            i + regionIndexEntries > totalIndexEntries):
            raise ValueError, "Invalid region tag"
        digest.update(pack("!2I", regionIndexEntries, offset + 16))
        digest.update(data[i * 16 : (i + regionIndexEntries) * 16])
        for i in xrange(i + regionIndexEntries, totalIndexEntries):
            (tag,) = unpack("!I", data[i * 16 : i * 16 + 4])
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
    def __init__(self, config, source, hdronly=None):
        RpmStreamIO.__init__(self, config, source, hdronly)

    def open(self, unused_mode="r"):
        try:
            self.fd = urlgrabber.urlopen(self.source)
        except urlgrabber.grabber.URLGrabError, e:
            raise IOError, str(e)

    def close(self):
        RpmStreamIO.close(self)
        self.fd.close()
        self.fd = None


class RpmHttpIO(RpmStreamIO):
    def __init__(self, config, source, hdronly=None):
        RpmStreamIO.__init__(self, config, source, hdronly)

    def open(self, unused_mode="r"):
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
    """A persistent RPM database storage."""
    # FIXME: doesn't support adding/removing gpg keys

    def __init__(self, config, source, buildroot=None):
        """Create a new RpmDatabase for "URI" source.

        If buildroot is not None, use the database under buildroot."""
        # FIXME: buildroot is a misnomer

        self.config = config
        self.source = source
        self.buildroot = buildroot
        self.filenames = FilenamesList()
        self.pkglist = {}            # nevra => RpmPackage for non-key packages
        self.keyring = openpgp.PGPKeyRing()
        self.is_read = 0                # 1 if the database was already read

    # FIXME: not used
    def setSource(self, source):
        """Set database source to source.

        Does not write/reread the database."""

        self.source = source

    def setBuildroot(self, buildroot):
        """Set database chroot to buildroot."""

        self.buildroot = buildroot

    def open(self):
        """If the database keeps a connection, prepare it."""

        raise NotImplementedError

    def close(self):
        """If the database keeps a connection, close it."""

        raise NotImplementedError

    def read(self):
        """Read the database in memory.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    # FIXME: not used, addPkg/erasePkg write data immediately
    # For now, yes. Maybe someday there will be transcation based databases.
    def write(self):
        """Write the database out.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    def addPkg(self, pkg, nowrite=None):
        """Add RpmPackage pkg to database in memory and persistently if not
        nowrite.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    def _addPkg(self, pkg):
        """Add RpmPackage pkg to self.filenames and self.pkglist"""

        self.filenames.addPkg(pkg)
        self.pkglist[pkg.getNEVRA()] = pkg

    def erasePkg(self, pkg, nowrite=None):
        """Remove RpmPackage pkg from database in memory and persistently if
        not nowrite.

        Return 1 on success, 0 on failure."""

        raise NotImplementedError

    def _erasePkg(self, pkg):
        """Remove RpmPackage pkg from self.filenames and self.pkglist"""

        self.filenames.removePkg(pkg)
        del self.pkglist[pkg.getNEVRA()]

    # FIXME: not used
    def getPackage(self, nevra):
        """Return a RpmPackage with NEVRA nevra, or None if not found."""

        return self.pkglist.get(nevra)

    def getPkgList(self):
        """Return a list of RpmPackages in the database."""

        return self.pkglist.values()

    def isInstalled(self, pkg):
        """Return True if RpmPackage pkg is in the database.

        pkg must be exactly the same object, not only have the same NEVRA."""

        return pkg in self.pkglist.values()

    def isDuplicate(self, dirname, filename=None):
        """Return True if a file is contained in more than one package in the
        database.

        The file can be specified either as a single absolute path ("dirname")
        or as a (dirname, filename) pair."""

        if filename == None:
            (dirname, basename) = os.path.split(dirname)
            if len(dirname) > 0 and dirname[-1] != "/":
                dirname += "/"
        if dirname == "/etc/init.d/" or dirname == "/etc/rc.d/init.d/":
            num = 0
            d = self.filenames.path.get("/etc/rc.d/init.d/")
            if d:
                num = len(d.get(basename, []))
            d = self.filenames.path.get("/etc/init.d/")
            if d:
                num += len(d.get(basename, []))
            return num > 1
        d = self.filenames.path.get(dirname)
        if not d:
            return 0
        return len(d.get(basename, [])) > 1

    def getNumPkgs(self, name):
        """Return number of packages in database with %name name."""

        count = 0
        for pkg in self.pkglist.values():
            if pkg["name"] == name:
                count += 1
        return count

    def _getDBPath(self):
        """Return a physical path to the database."""

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
    """Standard RPM database storage in BSD db."""

    def __init__(self, config, source, buildroot=None):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.zero = pack("I", 0)
        self.dbopen = False
        self.maxid = 0
        # Correctly initialize the tscolor based on the current arch
        self.config.tscolor = self.__getInstallColor()
        self.netsharedpath = self.__getNetSharedPath()

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        # Never fails, attempts to recover as much as possible
        if self.is_read:
            return 1
        self.is_read = 1
        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            return 1
        try:
            db = bsddb.hashopen(os.path.join(dbpath, "Packages"), "r")
        except bsddb.error:
            return 1
        for key in db.keys():
            rpmio = RpmFileIO(self.config, "dummy")
            pkg = package.RpmPackage(self.config, "dummy")
            data = db[key]
            try:
                val = unpack("I", key)[0]
            except struct.error:
                self.config.printError("Invalid key %s in rpmdb" % repr(key))
                continue

            if val == 0:
                self.maxid = unpack("I", data)[0]
                continue

            try:
                (indexNo, storeSize) = unpack("!2I", data[0:8])
            except struct.error:
                self.config.printError("Value for key %s in rpmdb is too short"
                                       % repr(key))
                continue
            if len(data) < indexNo*16 + 8:
                self.config.printError("Value for key %s in rpmdb is too short"
                                       % repr(key))
                continue
            indexdata = data[8:indexNo*16+8]
            storedata = data[indexNo*16+8:]
            pkg["signature"] = {}
            for idx in xrange(0, indexNo):
                try:
                    (tag, tagval) = rpmio.getHeaderByIndex(idx, indexdata,
                                                           storedata)
                except ValueError, e:
                    self.config.printError("Invalid header entry %s in %s: %s"
                                           % (idx, key, e))
                    continue
                if rpmtag.has_key(tag):
                    if rpmtagname[tag] == "archivesize":
                        pkg["signature"]["payloadsize"] = tagval
                    else:
                        pkg[rpmtagname[tag]] = tagval
                if   tag == 257:
                    pkg["signature"]["size_in_sig"] = tagval
                elif tag == 261:
                    pkg["signature"]["md5"] = tagval
                elif tag == 262:
                    pkg["signature"]["gpg"] = tagval
                elif tag == 264:
                    pkg["signature"]["badsha1_1"] = tagval
                elif tag == 265:
                    pkg["signature"]["badsha1_2"] = tagval
                elif tag == 267:
                    pkg["signature"]["dsaheader"] = tagval
                elif tag == 269:
                    pkg["signature"]["sha1header"] = tagval
            if pkg["name"] == "gpg-pubkey":
                continue # FIXME
                try:
                    keys = openpgp.parsePGPKeys(pkg["description"])
                except ValueError, e:
                    self.config.printError("Invalid key package %s: %s"
                                           % (pkg["name"], e))
                    continue
                for k in keys:
                    self.keyring.addKey(k)
                continue
            if not pkg.has_key("arch"): # FIXME: when does this happen?
                continue
            pkg.generateFileNames()
            pkg.source = "rpmdb:/"+os.path.join(dbpath, pkg.getNEVRA())
            try:
                pkg["provides"] = pkg.getProvides()
                pkg["requires"] = pkg.getRequires()
                pkg["obsoletes"] = pkg.getObsoletes()
                pkg["conflicts"] = pkg.getConflicts()
                pkg["triggers"] = pkg.getTriggers()
            except ValueError, e:
                self.config.printError("Error in package %s: %s"
                                       % pkg.getNEVRA(), e)
                continue
            pkg["install_id"] = val
            self._addPkg(pkg)
            pkg.io = None
            pkg.header_read = 1
            rpmio.hdr = {}
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        self._addPkg(pkg)

        if nowrite:
            return 1

        functions.blockSignals()
        try:
            self.__openDB4()

            try:
                self.maxid = unpack("I", self.packages_db[self.zero])[0]
            except:
                pass

            self.maxid += 1
            pkgid = self.maxid

            rpmio = RpmFileIO(self.config, "dummy")
            if pkg["signature"].has_key("size_in_sig"):
                pkg["install_size_in_sig"] = pkg["signature"]["size_in_sig"]
            if pkg["signature"].has_key("gpg"):
                pkg["install_gpg"] = pkg["signature"]["gpg"]
            if pkg["signature"].has_key("md5"):
                pkg["install_md5"] = pkg["signature"]["md5"]
            if pkg["signature"].has_key("sha1header"):
                pkg["install_sha1header"] = pkg["signature"]["sha1header"]
            if pkg["signature"].has_key("dsaheader"):
                pkg["install_dsaheader"] = pkg["signature"]["dsaheader"]
            if pkg["signature"].has_key("payloadsize"):
                pkg["archivesize"] = pkg["signature"]["payloadsize"]
            pkg["installtime"] = int(time.time())
            if pkg.has_key("basenames"):
                pkg["filestates"] = self.__getFileStates(pkg)
            pkg["installcolor"] = [self.config.tscolor,]
            pkg["installtid"] = [self.config.tid,]

            self.__writeDB4(self.basenames_db, "basenames", pkgid, pkg)
            self.__writeDB4(self.conflictname_db, "conflictname", pkgid, pkg)
            self.__writeDB4(self.dirnames_db, "dirnames", pkgid, pkg)
            self.__writeDB4(self.filemd5s_db, "filemd5s", pkgid, pkg, True,
                            a2b_hex)
            self.__writeDB4(self.group_db, "group", pkgid, pkg)
            self.__writeDB4(self.installtid_db, "installtid", pkgid, pkg, True,
                            lambda x:pack("i", x))
            self.__writeDB4(self.name_db, "name", pkgid, pkg, False)
            (headerindex, headerdata) = rpmio._generateHeader(pkg, 4)
            self.packages_db[pack("I", pkgid)] = headerindex[8:]+headerdata
            self.__writeDB4(self.providename_db, "providename", pkgid, pkg)
            self.__writeDB4(self.provideversion_db, "provideversion", pkgid,
                            pkg)
            self.__writeDB4(self.requirename_db, "requirename", pkgid, pkg)
            self.__writeDB4(self.requireversion_db, "requireversion", pkgid,
                            pkg)
            self.__writeDB4(self.sha1header_db, "install_sha1header", pkgid,
                            pkg, False)
            self.__writeDB4(self.sigmd5_db, "install_md5", pkgid, pkg, False)
            self.__writeDB4(self.triggername_db, "triggername", pkgid, pkg)
            self.packages_db[self.zero] = pack("I", self.maxid)
        except bsddb.error:
            functions.unblockSignals()
            self._erasePkg(pkg)
            return 0 # Due to the blocking, this is now virtually atomic
        functions.unblockSignals()
        return 1

    def erasePkg(self, pkg, nowrite=None):
        self._erasePkg(pkg)

        if nowrite:
            return 1

        if not pkg.has_key("install_id"):
            self._addPkg(pkg)
            return 0

        functions.blockSignals()
        try:
            self.__openDB4()

            pkgid = pkg["install_id"]

            self.__removeId(self.basenames_db, "basenames", pkgid, pkg)
            self.__removeId(self.conflictname_db, "conflictname", pkgid, pkg)
            self.__removeId(self.dirnames_db, "dirnames", pkgid, pkg)
            self.__removeId(self.filemd5s_db, "filemd5s", pkgid, pkg, True,
                            a2b_hex)
            self.__removeId(self.group_db, "group", pkgid, pkg)
            self.__removeId(self.installtid_db, "installtid", pkgid, pkg, True,
                            lambda x:pack("i", x))
            self.__removeId(self.name_db, "name", pkgid, pkg, False)
            self.__removeId(self.providename_db, "providename", pkgid, pkg)
            self.__removeId(self.provideversion_db, "provideversion", pkgid,
                            pkg)
            self.__removeId(self.requirename_db, "requirename", pkgid, pkg)
            self.__removeId(self.requireversion_db, "requireversion", pkgid,
                            pkg)
            self.__removeId(self.sha1header_db, "install_sha1header", pkgid,
                            pkg, False)
            self.__removeId(self.sigmd5_db, "install_md5", pkgid, pkg, False)
            self.__removeId(self.triggername_db, "triggername", pkgid, pkg)
            del self.packages_db[pack("I", pkgid)]
        except bsddb.error:
            functions.unblockSignals()
            self._addPkg(pkg)
            return 0 # FIXME: keep trying?
        functions.unblockSignals()
        return 1

    def __openDB4(self):
        """Make sure the database is read, and open all subdatabases.

        Raise bsddb.error."""

        dbpath = self._getDBPath()
        if not os.path.isdir(dbpath):
            os.makedirs(dbpath)

        if not self.is_read:
            self.read() # Never fails

        if self.dbopen:
            return

        # We first need to remove the __db files, otherwise rpm will later
        # be really upset. :)
        for i in xrange(9):
            try:
                os.unlink(os.path.join(dbpath, "__db.00%d" % i))
            except OSError:
                pass
        self.basenames_db      = bsddb.hashopen(os.path.join(dbpath,
                                                             "Basenames"), "c")
        self.conflictname_db   = bsddb.hashopen(os.path.join(dbpath,
                                                             "Conflictname"),
                                                "c")
        self.dirnames_db       = bsddb.btopen(os.path.join(dbpath, "Dirnames"),
                                              "c")
        self.filemd5s_db       = bsddb.hashopen(os.path.join(dbpath,
                                                             "Filemd5s"), "c")
        self.group_db          = bsddb.hashopen(os.path.join(dbpath, "Group"),
                                                "c")
        self.installtid_db     = bsddb.btopen(os.path.join(dbpath,
                                                           "Installtid"), "c")
        self.name_db           = bsddb.hashopen(os.path.join(dbpath, "Name"),
                                                "c")
        self.packages_db       = bsddb.hashopen(os.path.join(dbpath,
                                                             "Packages"), "c")
        self.providename_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Providename"),
                                                "c")
        self.provideversion_db = bsddb.btopen(os.path.join(dbpath,
                                                           "Provideversion"),
                                              "c")
        self.requirename_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Requirename"),
                                                "c")
        self.requireversion_db = bsddb.btopen(os.path.join(dbpath,
                                                           "Requireversion"),
                                              "c")
        self.sha1header_db     = bsddb.hashopen(os.path.join(dbpath,
                                                             "Sha1header"),
                                                "c")
        self.sigmd5_db         = bsddb.hashopen(os.path.join(dbpath, "Sigmd5"),
                                                "c")
        self.triggername_db    = bsddb.hashopen(os.path.join(dbpath,
                                                             "Triggername"),
                                                "c")
        self.dbopen = True

    def __removeId(self, db, tag, pkgid, pkg, useidx=True, func=str):
        """Remove index entries for tag of RpmPackage pkg (with id pkgid) from
        a BSD database db.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        if not pkg.has_key(tag):
            return
        if useidx:
            maxidx = len(pkg[tag])
        else:
            maxidx = 1
        for idx in xrange(maxidx):
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if not db.has_key(key):
                continue
            data = db[key]
            ndata = ""
            rdata = pack("2I", pkgid, idx)
            for i in xrange(0, len(data), 8):
                if not data[i:i+8] == rdata:
                    ndata += data[i:i+8]
            if len(ndata) == 0:
                del db[key]
            else:
                db[key] = ndata

    def __writeDB4(self, db, tag, pkgid, pkg, useidx=True, func=str):
        """Add index entries for tag of RpmPackage pkg (with id pkgid) to a
        BSD database db.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        tnamehash = {}
        if not pkg.has_key(tag):
            return
        for idx in xrange(len(pkg[tag])):
            if tag == "requirename":
                # Skip rpmlib() requirenames...
                #if key.startswith("rpmlib("):
                #    continue
                # Skip install prereqs, just like rpm does...
                if isInstallPreReq(pkg["requireflags"][idx]):
                    continue
            # Skip all files with empty md5 sums
            key = self.__getKey(tag, idx, pkg, useidx, func)
            if tag == "filemd5s" and (key == "" or key == "\x00"):
                continue
            # Equal Triggernames aren't added multiple times for the same pkg
            if tag == "triggername":
                if tnamehash.has_key(key):
                    continue
                else:
                    tnamehash[key] = 1
            if not db.has_key(key):
                db[key] = ""
            db[key] += pack("2I", pkgid, idx)
            if not useidx:
                break

    def __getKey(self, tag, idx, pkg, useidx, func):
        """Convert idx'th (0-based) value of RpmPackage pkg tag to a string
        usable as a database key.

        The tag has a single value if not useidx.  Convert the value using
        func."""

        if useidx:
            key = pkg[tag][idx]
        else:
            key = pkg[tag]
        # Convert empty keys, handle filemd5s a little different
        if key != "":
            key = func(key)
        elif tag != "filemd5s":
            key = "\x00"
        return key

    def __getInstallColor(self):
        """Return the install color for self.config.machine."""

        if self.config.machine == "ia64": # also "0" and "3" have been here
            return 2
        elif self.config.machine in ("ia32e", "amd64", "x86_64", "sparc64",
            "s390x", "powerpc64") or self.config.machine.startswith("ppc"):
            return 3
        return 0

    def __getFileStates(self, pkg):
        """Returns a list of file states for rpmdb. """
        states = []
        for i in xrange(len(pkg["basenames"])):
            if pkg.has_key("filecolors"):
                fcolor = pkg["filecolors"][i]
            else:
                fcolor = 0
            if self.config.tscolor and fcolor and \
               not (self.config.tscolor & fcolor):
                states.append(RPMFILE_STATE_WRONGCOLOR)
                continue
            if pkg["dirnames"][pkg["dirindexes"][i]] in self.netsharedpath:
                states.append(RPMFILE_STATE_NETSHARED)
                continue
            fflags = pkg["fileflags"][i]
            if self.config.excludedocs and (RPMFILE_DOC & fflags):
                states.append(RPMFILE_STATE_NOTINSTALLED)
                continue
            if self.config.excludeconfigs and (RPMFILE_CONFIG & fflags):
                states.append(RPMFILE_STATE_NOTINSTALLED)
                continue
            states.append(RPMFILE_STATE_NORMAL)
            # FIXME: Still missing:
            #  - install_langs (found in /var/lib/rpm/macros) (unimportant)
            #  - Now empty dirs which contained files which weren't installed
        return states

    def __getNetSharedPath(self):
        netpaths = []
        try:
            if self.buildroot:
                fname = br + "/etc/rpm/macros"
            else:
                fname = "/etc/rpm/macros"
            lines = open(fname).readlines()
            inpath = 0
            liststr = ""
            for l in lines:
                if not inpath and not l.startswith("%_netsharedpath"):
                    continue
                l = l[:-1]
                if l.startswith("%_netsharedpath"):
                    inpath = 1
                    l = l.split(None, 1)[1]
                if not l[-1] == "\\":
                    liststr += l
                    break
                liststr += l[:-1]
            return liststr.split(",")
        except:
            return []

class RpmSQLiteDB(RpmDatabase):
    """RPM database storage in an SQLite database."""

    # Tags stored in the Packages table
    pkgnames = ["name", "epoch", "version", "release", "arch", "prein", "preinprog", "postin", "postinprog", "preun", "preunprog", "postun", "postunprog", "verifyscript", "verifyscriptprog", "url", "license", "rpmversion", "sourcerpm", "optflags", "sourcepkgid", "buildtime", "buildhost", "cookie", "size", "distribution", "vendor", "packager", "os", "payloadformat", "payloadcompressor", "payloadflags", "rhnplatform", "platform", "capability", "xpm", "gif", "verifyscript2", "disturl"]
    # Tags stored in separate tables
    tagnames = ["providename", "provideflags", "provideversion", "requirename", "requireflags", "requireversion", "obsoletename", "obsoleteflags", "obsoleteversion", "conflictname", "conflictflags", "conflictversion", "triggername", "triggerflags", "triggerversion", "triggerscripts", "triggerscriptprog", "triggerindex", "i18ntable", "summary", "description", "changelogtime", "changelogname", "changelogtext", "prefixes", "pubkeys", "group", "dirindexes", "dirnames", "basenames", "fileusername", "filegroupname", "filemodes", "filemtimes", "filedevices", "fileinodes", "filesizes", "filemd5s", "filerdevs", "filelinktos", "fileflags", "fileverifyflags", "fileclass", "filelangs", "filecolors", "filedependsx", "filedependsn", "classdict", "dependsdict", "policies", "filecontexts", "oldfilenames"]
    def __init__(self, config, source, buildroot=None):
        RpmDatabase.__init__(self, config, source, buildroot)
        self.cx = None

    def open(self):
        if self.cx:
            return
        dbpath = self._getDBPath()
        self.cx = sqlite.connect(os.path.join(dbpath, "rpmdb.sqlite"),
                                 autocommit=1)

    def close(self):
        if self.cx:
            self.cx.close()
        self.cx = None

    def read(self):
        if self.is_read:
            return 1
        if not self.cx:
            return 0
        self.is_read = 1
        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        cu.execute("select rowid, "+string.join(self.pkgnames, ",")+" from Packages")
        for row in cu.fetchall():
            pkg = package.RpmPackage(self.config, "dummy")
            pkg["install_id"] = row[0]
            for i in xrange(len(self.pkgnames)):
                if row[i+1] != None:
                    if self.pkgnames[i] == "epoch" or \
                       self.pkgnames[i] == "size":
                        pkg[self.pkgnames[i]] = [row[i+1],]
                    else:
                        pkg[self.pkgnames[i]] = row[i+1]
            for tag in self.tagnames:
                self.__readTags(cu, row[0], pkg, tag)
            pkg.generateFileNames()
            try:
                pkg["provides"] = pkg.getProvides()
                pkg["requires"] = pkg.getRequires()
                pkg["obsoletes"] = pkg.getObsoletes()
                pkg["conflicts"] = pkg.getConflicts()
                pkg["triggers"] = pkg.getTriggers()
            except ValueError, e:
                self.config.printError("Error in package %s: %s"
                                       % pkg.getNEVRA(), e)
                continue
            self._addPkg(pkg)
            pkg.io = None
            pkg.header_read = 1
        try:
            cu.execute("commit")
        except:
            return 0
        return 1

    def write(self):
        return 1

    def addPkg(self, pkg, nowrite=None):
        self._addPkg(pkg)

        if nowrite:
            return 1

        if not self.cx:
            self._erasePkg(pkg)
            return 0

        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        namelist = []
        vallist = []
        valstring = ""
        for tag in self.pkgnames:
            if not pkg.has_key(tag):
                continue
            namelist.append(tag)
            if valstring == "":
                valstring = "%s"
            else:
                valstring += ", %s"
            if rpmtag[tag][1] == RPM_BIN:
                vallist.append(b2a_hex(pkg[tag]))
            else:
                if isinstance(pkg[tag], TupleType):
                    vallist.append(str(pkg[tag][0]))
                else:
                    vallist.append(str(pkg[tag]))
        cu.execute("insert into Packages ("+string.join(namelist, ",")+") values ("+valstring+")", vallist)
        rowid = cu.lastrowid
        for tag in self.tagnames:
            if not pkg.has_key(tag):
                continue
            self.__writeTags(cu, rowid, pkg, tag)
        try:
            cu.execute("commit")
        except:
            self._erasePkg(pkg)
            return 0
        return 1

    def erasePkg(self, pkg, nowrite=None):
        self._erasePkg(pkg)

        if nowrite:
            return 1

        if not self.cx:
            self._addPkg(pkg)
            return 0

        self.__initDB()
        cu = self.cx.cursor()
        cu.execute("begin")
        cu.execute("delete from Packages where rowid=%d", (pkg["install_id"],))
        for tag in self.tagnames:
            cu.execute("delete from %s where id=%d", (tag, pkg["install_id"]))
        try:
            cu.execute("commit")
        except:
            self._addPkg(pkg)
            return 0
        return 1

    def __initDB(self):
        """Make sure the necessary tables are defined."""

        cu = self.cx.cursor()
        cu.execute("select tbl_name from sqlite_master where type='table' order by tbl_name")
        tables = [row.tbl_name for row in cu.fetchall()]
        if tables == []:
            cu.execute("""
create table Packages (
               name text,
               epoch int,
               version text,
               release text,
               arch text,
               prein text,
               preinprog text,
               postin text,
               postinprog text,
               preun text,
               preunprog text,
               postun text,
               postunprog text,
               verifyscript text,
               verifyscriptprog text,
               url text,
               license text,
               rpmversion text,
               sourcerpm text,
               optflags text,
               sourcepkgid text,
               buildtime text,
               buildhost text,
               cookie text,
               size int,
               distribution text,
               vendor text,
               packager text,
               os text,
               payloadformat text,
               payloadcompressor text,
               payloadflags text,
               rhnplatform text,
               platform text,
               capability int,
               xpm text,
               gif text,
               verifyscript2 text,
               disturl text)
""")
            for tag in self.tagnames:
                cu.execute("""
create table %s (
               id int,
               idx int,
               val text,
               primary key(id, idx))
""", tag)

    def __readTags(self, cu, rowid, pkg, tag):
        """Read values of tag with name tag to RpmPackage pkg with ID rowid
        using cu."""

        cu.execute("select val from %s where id=%d order by idx", (tag, rowid))
        for row in cu.fetchall():
            if not pkg.has_key(tag):
                pkg[tag] = []
            if   rpmtag[tag][1] == RPM_BIN:
                pkg[tag].append(a2b_hex(row[0]))
            elif rpmtag[tag][1] == RPM_INT8 or \
                 rpmtag[tag][1] == RPM_INT16 or \
                 rpmtag[tag][1] == RPM_INT32 or \
                 rpmtag[tag][1] == RPM_INT64:
                pkg[tag].append(int(row[0]))
            else:
                pkg[tag].append(row[0])

    def __writeTags(self, cu, rowid, pkg, tag):
        """Write values of tag with name tag from RpmPackage pkg with ID rowid
        using cu."""

        for idx in xrange(len(pkg[tag])):
            if rpmtag[tag][1] == RPM_BIN:
                val = b2a_hex(pkg[tag][idx])
            else:
                val = str(pkg[tag][idx])
            cu.execute("insert into %s (id, idx, val) values (%d, %d, %s)", (tag, rowid, idx, val))


class RpmRepo(RpmDatabase):
    """A (mostly) read-only RPM database storage in repodata XML.

    This is not a full implementation of RpmDatabase: notably the file database
    is not populated at all."""

    # A mapping between strings and RPMSENSE_* comparison flags
    flagmap = { None: None,
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

    def __init__(self, config, source, buildroot=None, excludes="",
                 reponame="default", key_urls=[]):
        """Exclude packages matching whitespace-separated excludes.  Use
        reponame for cache subdirectory name and pkg["yumreponame"].

        Load PGP keys from URLs in key_urls."""

        RpmDatabase.__init__(self, config, source, buildroot)
        self.baseurl = None
        self.excludes = excludes.split()
        self.reponame = reponame
        self.key_urls = key_urls
        self.filelist_imported  = 0
        # Files included in primary.xml
        self._filerc = re.compile('^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$')
        self._dirrc = re.compile('^(.*bin/.*|/etc/.*)$')
        self.filereqs = []      # Filereqs, if available

    def read(self):
        self.is_read = 1 # FIXME: write-only
        for uri in self.source:
            filename = _uriToFilename(uri)
            filename = functions.cacheLocal(os.path.join(filename, "repodata/primary.xml.gz"), self.reponame, 1)
            if not filename:
                continue
            try:
                reader = libxml2.newTextReaderFilename(filename)
            except libxml2.libxmlError:
                continue
            self.baseurl = uri
            self.__parseNode(reader)
            for url in self.key_urls:
                url = _uriToFilename(url)
                filename = functions.cacheLocal(url, self.reponame, 1)
                try:
                    f = file(filename)
                    key_data = f.read()
                    f.close()
                except IOError, e:
                    self.config.printError("Error reading GPG key %s: %s"
                                           % (filename, e))
                    continue
                try:
                    keys = openpgp.parsePGPKeys(key_data)
                except ValueError, e:
                    self.config.printError("Invalid GPG key %s: %s" % (url, e))
                    continue
                for k in keys:
                    self.keyring.addKey(k)
            filename = _uriToFilename(uri)
            filename = functions.cacheLocal(os.path.join(filename, "filereq.xml.gz"), self.reponame, 1)
            # If we can't find the filereq.xml.gz file it doesn't matter
            if not filename:
                return 1
            try:
                reader = libxml2.newTextReaderFilename(filename)
            except libxml2.libxmlError:
                return 1
            self.__parseNode(reader)
        return 0

    def addPkg(self, pkg, unused_nowrite=None):
        # Doesn't know how to write things out, so nowrite is ignored
        if self.__isExcluded(pkg):
            return 0
        self.pkglist[pkg.getNEVRA()] = pkg
        return 1

    def isFilelistImported(self):
        return self.filelist_imported

    def importFilelist(self):
        """Parse filelists.xml.gz if it was not parsed before.

        Return 1 on success, 0 on failure."""

        # We need to have successfully read a repo from one source before we
        # can import it's filelist.
        if not self.baseurl or not self.is_read:
            return 0
        if self.filelist_imported:
            return 1
        filename = _uriToFilename(self.baseurl)
        filename = functions.cacheLocal(os.path.join(filename, "repodata/filelists.xml.gz"),
                              self.reponame, 1)
        if not filename:
            return 0
        try:
            reader = libxml2.newTextReaderFilename(filename)
        except libxml2.libxmlError:
            return 0
        self.__parseNode(reader)
        self.filelist_imported = 1
        return 1

    def createRepo(self):
        """Create repodata metadata for self.source.

        Return 1 on success, 0 on failure.  Assumes self.source is a local file
        system path without schema prefix."""

        self.filerequires = []
        self.config.printInfo(1, "Pass 1: Parsing package headers for file requires.\n")
        self.__readDir(self.source, "")
        filename = _uriToFilename(self.source)
        datapath = os.path.join(filename, "repodata")
        if not os.path.isdir(datapath):
            try:
                os.makedirs(datapath)
            except OSError, e:
                self.config.printError("%s: Couldn't create repodata: %s"
                                       % (filename, e))
                return 0
        try:
            pfd = gzip.GzipFile(os.path.join(datapath, "primary.xml.gz"), "wb")
        except IOError:
            return 0
        try:
            ffd = gzip.GzipFile(os.path.join(datapath, "filelists.xml.gz"),
                                "wb")
        except IOError:
            return 0
        #try:
        #    ofd = gzip.GzipFile(os.path.join(datapath, "other.xml.gz"), "wb")
        #except IOError:
        #    return 0
        pdoc = libxml2.newDoc("1.0")
        proot = pdoc.newChild(None, "metadata", None)
        fdoc = libxml2.newDoc("1.0")
        froot = fdoc.newChild(None, "filelists", None)
        #odoc = libxml2.newDoc("1.0")
        #oroot = odoc.newChild(None, "filelists", None)
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
            try:
                checksum = self.__getChecksum(pkg)
            except (IOError, NotImplementedError), e:
                self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                continue
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

    def _matchesFile(self, fname):
        return fname in self.filereqs or \
               self._filerc.match(fname) or \
               self._dirrc.match(fname)

    def __parseNode(self, reader):
        """Parse <package> tags from libxml2.xmlTextReader reader."""

        while reader.Read() == 1:
            ntype = reader.NodeType()
            name = reader.Name()
            if ntype != libxml2.XML_READER_TYPE_ELEMENT or \
               (name != "package" and name != "filereq"):
                continue
            if name == "filereq":
                if reader.Read() != 1:
                    break
                self.filereqs.append(reader.Value())
                continue
            props = self.__getProps(reader)
            if props.get("type") == "rpm":
                try:
                    pkg = self.__parsePackage(reader)
                except ValueError, e:
                    self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                    continue
                if pkg["arch"] == "src" or self.__isExcluded(pkg):
                    continue
                pkg["yumreponame"] = self.reponame
                self.pkglist[pkg.getNEVRA()] = pkg
            if props.has_key("name"):
                try:
                    arch = props["arch"]
                except KeyError:
                    self.config.printWarning(0,
                                             "%s: missing arch= in <package>"
                                             % pkg.getNEVRA())
                    continue
                try:
                    self.__parseFilelist(reader, props["name"], arch)
                except ValueError, e:
                    self.config.printWarning(0, "%s: %s" % (pkg.getNEVRA(), e))
                    continue

    def __isExcluded(self, pkg):
        """Return True if RpmPackage pkg is excluded by configuration."""

        if not self.config.ignorearch and \
           not functions.archCompat(pkg["arch"], self.config.machine):
            self.config.printWarning(1, "%s: Package excluded because of arch incompatibility" % pkg.getNEVRA())
            return 1
        excludes = functions.findPkgByNames(self.excludes, [pkg])
        return len(excludes) > 0

    def __escape(self, s):
        """Return escaped string converted to UTF-8"""

        if s == None:
            return ''
        s = string.replace(s, "&", "&amp;")
        if isinstance(s, unicode):
            return s
        try:
            x = unicode(s, 'ascii')
            return s
        except UnicodeError:
            encodings = ['utf-8', 'iso-8859-1', 'iso-8859-15', 'iso-8859-2']
            for enc in encodings:
                try:
                    x = unicode(s, enc)
                except UnicodeError:
                    pass
                else:
                    if x.encode(enc) == s:
                        return x.encode('utf-8')
        newstring = ''
        for char in s:
            if ord(char) > 127:
                newstring = newstring + '?'
            else:
                newstring = newstring + char
        return re.sub("\n$", '', newstring) # FIXME: not done in other returns

    def __readDir(self, dir, location):
        """Look for non-excluded *.rpm files under dir and add them to
        self.pkglist.

        dir must be a local file system path.  The remote location prefix
        corresponding to dir is location.  Collect file requires of added
        packages in self.filerequires.  Set pkg["yumlocation"] to the remote
        relative path to the package."""

        tmplist = []
        functions.readDir(dir, tmplist,
                          ("name", "epoch", "version", "release", "arch",
                           "sourcerpm", "requirename", "requireflags",
                           "requireversion"))
        for pkg in tmplist:
            if self.__isExcluded(pkg):
                continue
            for reqname in pkg["requirename"]:
                if reqname[0] == "/":
                    self.filerequires.append(reqname)
            # FIXME: this is done in createRepo too
            # If it is a source rpm change the arch to "src". Only valid
            # for createRepo, never do this anywhere else. ;)
            if pkg.isSourceRPM():
                pkg["arch"] = "src"
            nevra = pkg.getNEVRA()
            self.config.printInfo(2, "Adding %s to repo and checking file requires.\n" % nevra)
            pkg["yumlocation"] = location+pkg.source[len(dir):]
            self.pkglist[nevra] = pkg

    def __writePrimary(self, fd, parent, pkg):
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

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
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

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
        """Return checksum of package source of RpmPackage pkg.

        Raise IOError, NotImplementedError."""

        io = getRpmIOFactory(self.config, pkg.source)
        if self.config.checksum == "md5":
            s = md5.new()
        else:
            s = sha.new()
        io.updateDigestFromRange(s, 0, None)
        return s.hexdigest()

    def __getProps(self, reader):
        """Return a dictionary (name => value) of attributes of current tag
        from libxml2.xmlTextReader reader."""

        props = {}
        while reader.MoveToNextAttribute():
            props[reader.Name()] = reader.Value()
        return props

    def __parsePackage(self, reader):
        """Parse a package from current <package> tag at libxml2.xmlTextReader
        reader.

        Raise ValueError on invalid data."""

        pkg = package.RpmPackage(self.config, "dummy", db = self)
        pkg["signature"] = {}
        pkg["signature"]["size_in_sig"] = [0,]
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "package":
                    break
                continue
            props = self.__getProps(reader)
            if    name == "name":
                if reader.Read() != 1:
                    break
                pkg["name"] = reader.Value()
            elif name == "arch":
                if reader.Read() != 1:
                    break
                pkg["arch"] = reader.Value()
                if pkg["arch"] != "src":
                    pkg["sourcerpm"] = ""
            elif name == "version":
                try:
                    pkg["version"] = props["ver"]
                    pkg["release"] = props["rel"]
                    pkg["epoch"] = [int(props["epoch"]),]
                except KeyError:
                    raise ValueError, "Missing attributes of <version>"
            elif name == "checksum":
                try:
                    type_ = props["type"]
                except KeyError:
                    raise ValueError, "Missing type= in <checksum>"
                if   type_ == "md5":
                    if reader.Read() != 1:
                        break
                    pkg["signature"]["md5"] = reader.Value()
                elif type_ == "sha":
                    if reader.Read() != 1:
                        break
                    pkg["signature"]["sha1header"] = reader.Value()
            elif name == "location":
                try:
                    pkg.source = self.baseurl + "/" + props["href"]
                except KeyError:
                    raise ValueError, "Missing href= in <location>"
            elif name == "size":
                try:
                    pkg["signature"]["size_in_sig"][0] += int(props["package"])
                except KeyError:
                    raise ValueError, "Missing package= in <size>"
            elif name == "format":
                self.__parseFormat(reader, pkg)
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

    def __parseFilelist(self, reader, pname, arch):
        """Parse a file list from current <package name=pname> tag at
        libxml2.xmlTextReader reader for package with arch arch.

        Raise ValueError on invalid data."""

        filelist = []
        version, release, epoch = None, None, None
        while reader.Read() == 1:
            ntype = reader.NodeType()
            if ntype != libxml2.XML_READER_TYPE_ELEMENT and \
               ntype != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if ntype == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "package":
                    break
                continue
            if   name == "version":
                props = self.__getProps(reader)
                version = props.get("ver")
                release = props.get("rel")
                epoch   = props.get("epoch")
            elif name == "file":
                if reader.Read() != 1:
                    break
                filelist.append(reader.Value())
        if version is None or release is None or epoch is None:
            raise ValueError, "Missing version information"
        nevra = "%s-%s:%s-%s.%s" % (pname, epoch, version, release, arch)
        pkg = self.pkglist.get(nevra)
        if pkg:
            # get rid of old dirnames, dirindexes and basenames
            if pkg.has_key("dirnames"):
                del pkg["dirnames"]
            if pkg.has_key("dirindexes"):
                del pkg["dirindexes"]
            if pkg.has_key("basenames"):
                del pkg["basenames"]
            pkg["oldfilenames"] = filelist

    def __generateFormat(self, node, pkg):
        """Add RPM-specific tags under libxml2.xmlNode node for RpmPackage
        pkg."""

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
        """Add RPM-specific dependency info under libxml2.xmlNode node for
        RpmPackage pkg dependencies "name"."""

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

    def __generateFilelist(self, node, pkg, filter=1):
        """Add RPM-specific file list under libxml2.xmlNode node for RpmPackage
        pkg.

        Restrict the output to _dirrc/_filerc or known file requires if
        filter."""

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

    def __parseFormat(self, reader, pkg):
        """Parse data from current <format> tag at libxml2.xmlTextReader reader
        to RpmPackage pkg.

        Raise ValueError on invalid input."""

        pkg["oldfilenames"] = []
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == "format":
                    break
                continue
            elif name == "rpm:sourcerpm":
                if reader.Read() != 1:
                    break
                pkg["sourcerpm"] = reader.Value()
            elif name == "rpm:header-range":
                props = self.__getProps(reader)
                try:
                    header_start = int(props["start"])
                    header_end = int(props["end"])
                except KeyError:
                    raise ValueError, "Missing start= in <rpm:header_range>"
                pkg["signature"]["size_in_sig"][0] -= header_start
                pkg.range_signature = [96, header_start-96]
                pkg.range_header = [header_start, header_end-header_start]
                pkg.range_payload = [header_end, None]
            elif name == "rpm:provides":
                plist = self.__parseDeps(reader, name)
                pkg["providename"], pkg["provideflags"], pkg["provideversion"] = plist
            elif name == "rpm:requires":
                plist = self.__parseDeps(reader, name)
                pkg["requirename"], pkg["requireflags"], pkg["requireversion"] = plist
            elif name == "rpm:obsoletes":
                plist = self.__parseDeps(reader, name)
                pkg["obsoletename"], pkg["obsoleteflags"], pkg["obsoleteversion"] = plist
            elif name == "rpm:conflicts":
                plist = self.__parseDeps(reader, name)
                pkg["conflictname"], pkg["conflictflags"], pkg["conflictversion"] = plist
            elif name == "file":
                if reader.Read() != 1:
                    break
                pkg["oldfilenames"].append(reader.Value())

    def __filterDuplicateDeps(self, deps):
        """Return the list of (name, flags, release) dependencies deps with
        duplicates (when output by __generateDeps ()) removed."""

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

    def __parseDeps(self, reader, ename):
        """Parse a dependency list from currrent tag ename at
        libxml2.xmlTextReader reader.

        Return [namelist, flaglist, versionlist].  Raise ValueError on invalid
        input."""

        plist = [[], [], []]
        while reader.Read() == 1:
            if reader.NodeType() != libxml2.XML_READER_TYPE_ELEMENT and \
               reader.NodeType() != libxml2.XML_READER_TYPE_END_ELEMENT:
                continue
            name = reader.Name()
            if reader.NodeType() == libxml2.XML_READER_TYPE_END_ELEMENT:
                if name == ename:
                    break
                continue
            props = self.__getProps(reader)
            if name == "rpm:entry":
                try:
                    name = props["name"]
                except KeyError:
                    raise ValueError, "Missing name= in <rpm.entry>"
                ver = props.get("ver")
                flags = props.get("flags")
                if props.has_key("pre"):
                    prereq = RPMSENSE_PREREQ
                else:
                    prereq = 0
                if ver == None:
                    plist[0].append(name)
                    plist[1].append(prereq)
                    plist[2].append("")
                    continue
                epoch = props.get("epoch")
                rel = props.get("rel")
                if epoch != None:
                    ver = "%s:%s" % (epoch, ver)
                if rel != None:
                    ver = "%s-%s" % (ver, rel)
                plist[0].append(name)
                try:
                    flags = self.flagmap[flags]
                except KeyError:
                    raise ValueError, "Unknown flags %s" % flags
                plist[1].append(flags + prereq)
                plist[2].append(ver)
        return plist

class RpmCompsXML:
    def __init__(self, config, source):
        """Initialize the parser.

        source is an URL to comps.xml."""

        self.config = config
        self.source = source
        self.grouphash = {}             # group id => { key => value }
        self.grouphierarchyhash = {}    # FIXME: write-only

    def __str__(self):
        return str(self.grouphash)

    def read(self):
        """Open and parse the comps file.

        Return 1 on success, 0 on failure."""

        filename = functions.cacheLocal(_uriToFilename(self.source), "", 1)
        if filename is None:
            return 0
        try:
            doc = libxml2.parseFile (filename)
            root = doc.getRootElement()
        except libxml2.libxmlError:
            return 0
        return self.__parseNode(root.children)

    def getPackageNames(self, group):
        """Return a list of mandatory an default packages from group and its
        dependencies and the dependencies of the packages.

        The list may contain a single package name more than once.  Only the
        first-level package dependencies are returned, not their transitive
        closure."""

        ret = self.__getPackageNames(group, ("mandatory", "default"))
        ret2 = []
        for val in ret:
            ret2.append(val[0])
            ret2.extend(val[1])
        return ret2

    def getOptionalPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        optional packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["optional"])

    def getDefaultPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        default packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["default"])

    def getMandatoryPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        mandatory packagres from group and its dependencies."""

        return self.__getPackageNames(group, ["mandatory"])

    def __getPackageNames(self, group, typelist):
        """Return a sorted list of (package name, [package requirement]) of
        packages from group and its dependencies with selection type in
        typelist."""

        ret = []
        if not self.grouphash.has_key(group):
            return ret
        if self.grouphash[group].has_key("packagelist"):
            pkglist = self.grouphash[group]["packagelist"]
            for (pkgname, value) in pkglist.iteritems():
                if value[0] in typelist:
                    ret.append((pkgname, value[1]))
        if self.grouphash[group].has_key("grouplist"):
            grplist = self.grouphash[group]["grouplist"]
            # FIXME: Stack overflow with loops in group requirements
            for grpname in grplist["groupreqs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
            for grpname in grplist["metapkgs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
        # Sort and duplicate removal
        ret.sort()
        for i in xrange(len(ret)-2, -1, -1):
            if ret[i+1] == ret[i]:
                ret.pop(i+1)
        return ret

    def __parseNode(self, node):
        """Parse libxml2.xmlNode node and its siblings under the root
        element.

        Return 1 on success, 0 on failure.  Handle <group>, <grouphierarchy>,
        warn about other tags."""

        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if node.name == "group" or node.name == "category":
                self.__parseGroup(node.children)
            elif node.name == "grouphierarchy":
                ret = self.__parseGroupHierarchy(node.children)
                if not ret:
                    return 0
            else:
                self.config.printWarning(1, "Unknown entry in comps.xml: %s" % node.name)
                return 0
            node = node.next
        return 1

    def __parseGroup(self, node):
        """Parse libxml2.xmlNode node and its siblings under <group>."""

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

    def __parsePackageList(self, node):
        """Parse libxml2.xmlNode node and its siblings under <packagelist>.

        Return { package => (selection, [requirement]) }."""

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
        """Parse libxml2.xmlNode node and its siblings under <grouplist>.

        Return { "groupgreqs" => [requirement],
        "metapkgs" => { requirement => requirement type } }."""

        glist = {}
        glist["groupreqs"] = []
        glist["metapkgs"] = {}
        while node != None:
            if node.type != "element":
                node = node.next
                continue
            if   node.name == "groupreq" or node.name == "groupid":
                glist["groupreqs"].append(node.content)
            elif node.name == "metapkg":
                gtype = node.prop("type")
                if gtype == None:
                    gtype = "default"
                glist["metapkgs"][node.content] = gtype
            node = node.next
        return glist

    def __parseGroupHierarchy(self, node):
        """"Parse" libxml2.xmlNode node and its siblings under
        <grouphierarchy>.

        Return 1."""

        # We don't need grouphierarchies, so don't parse them ;)
        return 1


def getRpmIOFactory(config, source, hdronly=None):
    """Get a RpmIO implementation for package "URI" source.

    Don't return payload from read() if hdronly.
    Default to file:/ if no scheme is provided."""

    if   source[:5] == 'ftp:/':
        return RpmFtpIO(config, source, hdronly)
    elif source[:6] == 'file:/':
        return RpmFileIO(config, source, hdronly)
    elif source[:6] == 'http:/':
        return RpmHttpIO(config, source, hdronly)
    elif source[:6] == 'pydb:/':
        return RpmFileIO(config, source[6:], hdronly)
    else:
        return RpmFileIO(config, source, hdronly)
    return None


def getRpmDBFactory(config, source, root=None):
    """Get a RpmDatabase implementation for database "URI" source under
    root.

    Default to rpmdb:/ if no scheme is provided."""

    if   source[:7] == 'rpmdb:/':
        return RpmDB(config, source[7:], root)
    elif source[:10] == 'sqlitedb:/':
        return RpmSQLiteDB(config, source[10:], root)
    return RpmDB(config, source, root)


# vim:ts=4:sw=4:showmatch:expandtab
