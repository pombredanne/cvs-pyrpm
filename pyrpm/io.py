#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche
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


import fcntl, os, sys, struct, zlib
(pack, unpack) = (struct.pack, struct.unpack)

try:
    import urlgrabber
except ImportError:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module. Only check scripts available."

from base import *
import functions
from pyrpm.logger import log

FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT = 1, 2, 4, 8, 16
class PyGZIP:
    def __init__(self, fd):
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
            size = (bytes or 65536) - self.bufferlen
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
                    crc32 = unpack("<I", self.enddata[0:4])[0] #le signed int
                    isize = unpack("<I", self.enddata[4:8])[0] #le unsigned int
                except struct.error:
                    raise IOError, "Unexpected EOF"
                if crc32 != self.crcval:
                    raise IOError, "CRC check failed"
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
    def __init__(self, fd):
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
        if filename[:2] == "./":
            filename = filename[1:]
        if filename[:1] != "/":
            filename = "%s%s" % ("/", filename)
        if filename[-1:] == "/" and len(filename) > 1:
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
    def __init__(self, source):
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
    def __init__(self, source, hdronly=None):
        RpmIO.__init__(self, source)
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
                cpiofd = PyGZIP(self.fd)
                self.cpio = CPIOFile(cpiofd)
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
                log.errorLn("%s: tag %d included twice", self.source, tag)
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
        return (tag, self.hdr[tag])

    def getIndexData(self, idx, indexdata):
        return unpack("!4I", indexdata[idx*16:(idx+1)*16])

    def getHeaderByIndexData(self, index, storedata):
        tag = index[0]
        # ignore duplicate entries as long as they are identical
        if self.hdr.has_key(tag):
            if self.hdr[tag] != self.__parseTag(index, storedata):
                log.errorLn("%s: tag %d included twice", self.source, tag)
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
        return self.hdr[tag]

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

            offset = -(len(self.indexlist) * 16) - 16
            # tag, type, offset, count
            return pack("!2IiI", self.region, RPM_BIN, offset, 16)

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
    def __init__(self, source, hdronly=None):
        RpmStreamIO.__init__(self, source, hdronly)

    def __openFile(self, mode="r"):
        """Open self.source, mark it close-on-exec.

        Return the opened file.  Raise IOError."""

        fd = open(functions._uriToFilename(self.source), mode)
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
            log.warningLn("%s: Unsigned tags %s",
                          self.source, [rpmtagname[i] for i in unsignedTags])
        # In practice region data starts at offset 0, but the original design
        # was proposing concatenated regions etc; where would the data region
        # start in that case? Lowest offset in region perhaps?
        functions.updateDigestFromFile(digest, fd, offset + 16)

class RpmFtpIO(RpmStreamIO):
    def __init__(self, source, hdronly=None):
        RpmStreamIO.__init__(self, source, hdronly)

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
    def __init__(self, source, hdronly=None):
        RpmStreamIO.__init__(self, source, hdronly)

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


def getRpmIOFactory(source, hdronly=None):
    """Get a RpmIO implementation for package "URI" source.

    Don't return payload from read() if hdronly.
    Default to file:/ if no scheme is provided."""

    if   source[:5] == 'ftp:/':
        return RpmFtpIO(source, hdronly)
    elif source[:6] == 'file:/':
        return RpmFileIO(source, hdronly)
    elif source[:6] == 'http:/':
        return RpmHttpIO(source, hdronly)
#    elif source[:6] == 'pydb:/':
#        return RpmFileIO(source[6:], hdronly)
    else:
        return RpmFileIO(source, hdronly)
    return None


# vim:ts=4:sw=4:showmatch:expandtab
