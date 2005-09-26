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
    """'Virtual' IO Class for RPM packages and data
    Behaves a little like a dictionary and has similar methods like it.
    """

    def __init__(self, config, source):
        self.config = config
        self.source = source

    def open(self, mode="r"):
        """Open self.source using the specified mode.

        Raise IOError."""

        raise NotImplementedError

    def getNextFile(self):
        """Read next file from package.

        Return
        - (filename, CPIOFile, length)
        - ("EOF", 0, 0): End marker for end of data
        Raise ValueError on invalid data, IOError.
        Might not be implemented by various IOs, like databases etc.
        """

        raise NotImplementedError

    def getTag(self, pkg, item):
        """Return the tag of the given package for the given name. The name
        syntax looks like this:
            [S]tagname[,X]
        The optional S specifies if this is a signature tag or normal
        header tag.
        The optional ,X specifies if the 1st occurence of the tag is wanted or
        the Xth one (from 0 to 9).

        Return
        data for the given tag of the given package
        """

        raise NotImplementedError

    def has_key(self, pkg, item):
        """Check if the given key is available or not for the given package"""

        raise NotImplementedError

    def keys(self, pkg):
        """Returns a list of all available keys from this package from this IO
        """

        raise NotImplementedError

    def isSrc(self, pkg):
        """Returns true if the given pkg is a source rpm"""

        raise NotImplementedError

    def write(self, pkg):
        """Write a RpmPackage header (without payload!) to self.source.

        Raise IOError, NotImplementedError."""

        raise NotImplementedError

    def close(self):
        """Close all open files used for reading self.source.

        Raise IOError."""

        raise NotImplementedError

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
        self.verify = verify   # Verify lead and index entries
        self.strict = strict   # Report legacy tags and packages not named %name
        self.hdronly = hdronly # Don't return payload from read()
        self.issrc = 0         # 0:binary rpm 1:source rpm
        self.readidx = 0       # 0: indexes not read 1: indexes read
        self.sigstart = 0      # Start of signature store
        self.siglen = 0        # Length of signature store
        self.hdrstart = 0      # Start of header store
        self.hdrlen = 0        # Length of header store
        self.lead = None       # Lead data
        self.pos = 0           # Current position in stream for CPIO

    def open(self, mode="r"):
        """Open self.source using the specified mode, set self.fd to non-None.

        Raise IOError."""

        raise NotImplementedError

    def getNextFile(self, skip=None):
        """RpmIO.read(), if (skip) on first call, skip to the delimiter before
        payload."""

        if self.fd == None:
            self.open()
        if not self.readidx:
            self.__readHeader()
        if not self.cpio:
            cpiofd = PyGZIP(self.config, self.fd)
            self.cpio = CPIOFile(self.config, cpiofd)
            self.fd.seek(self.hdrstart+self.hdrlen, 0)
        (filename, filesize) = self.cpio.getNextEntry()
        if filename != None:
            return (filename, self.cpio, filesize)
        else:
            return  ("EOF", 0, 0)

    def getTag(self, pkg, item):
        """Get data for a given tag. Format looks like this:
        [S]tagname[,X]

        Optional [S] parameter specifies that this is a signature tag
        Optional [,X] parameter specifies the n-th occurence of a tag. Default 0
        """

        if self.fd == None:
            self.open()
        if not self.readidx:
            self.__readHeader()
        if item[0] == "S":
            offset = self.sigstart
        else:
            offset = self.hdrstart
        # Get the correct extended index for the given item from our indexdata
        index = self.indexdata.getIndex(item)
        if not index:
            return None
        len = index[4] # Get length of data segment
        oldpos = self._tell()
        self.fd.seek(offset+index[2], 0)
        storedata = functions.readExact(self.fd, len)
        data = self.indexdata.parseTag(index, storedata) 
        self.fd.seek(oldpos, 0)
        return data

    def has_key(self, pkg, item):
        if self.fd == None:
            self.open()
        if not self.readidx:
            self.__readHeader()
        return self.indexdata.has_key(item)

    def keys(self, pkg):
        return self.indexdata.keys()

    def isSrc(self, pkg):
        return self.issrc

    def write(self, pkg):
        """Writes the given package to this IO.
        """
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

    def close(self):
        if self.cpio:
            self.cpio = None

    def __readHeader(self):
        self.fd.seek(0, 0)
        self.leaddata = functions.readExact(self.fd, 96)
        if self.leaddata[:4] != RPM_HEADER_LEAD_MAGIC:
            raise ValueError, "no rpm magic found"
        self.issrc = (self.leaddata[7] == "\01")
        self.sigstart = self._tell()
        (indexNo, storeSize, sindex, sstore, slen) = self.__readIndex(8)
        self.sigstart += indexNo*16 + 16
        self.siglen = storeSize
        self.hdrstart = self._tell()
        (indexNo, storeSize, index, store, len) = self.__readIndex(1)
        self.hdrstart += indexNo*16 + 16
        self.hdrlen = storeSize
        self.indexdata = RpmIndexData(self.config, index, self.hdrlen,
                                      sindex, self.siglen)
        self.readidx = 1
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

    def __readIndex(self, pad):
        """Read and verify header index and data.

        self.fd should already be open.  Return (number of tags, tag data size,
        header header, index data, data area, total header size).  Discard data
        to enforce alignment at least pad.  Raise ValueError on invalid data,
        IOError."""

        data = functions.readExact(self.fd, 16)
        (magic, indexNo, storeSize) = unpack("!8s2I", data)
        if magic != RPM_HEADER_INDEX_MAGIC or indexNo < 1:
            raise ValueError, "bad index magic"
        index = functions.readExact(self.fd, 16 * indexNo)
        store = functions.readExact(self.fd, storeSize)
        if pad != 1:
            functions.readExact(self.fd, (pad - (storeSize % pad)) % pad)
        return (indexNo, storeSize, index, store, 16 + len(index) + len(store))

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

        h = self.__GeneratedHeader(rpmtag, rpmtagname, 63)
        return h.outputHeader(header, padding, skip_tags)


class RpmFileIO(RpmStreamIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)

    def __openFile(self, mode="r"):
        """Open self.source, mark it close-on-exec.

        Return the opened file.  Raise IOError."""

        fd = open(functions._uriToFilename(self.source), mode)
        fcntl.fcntl(fd.fileno(), fcntl.F_SETFD, 1)
        return fd

    def open(self, mode="r"):
        if not self.fd:
            self.fd = self.__openFile(mode)
        return self.fd != None

    def close(self):
        RpmStreamIO.close(self)
        if self.fd:
            self.fd.close()
            self.fd = None
        return 1

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
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)

    def open(self, unused_mode="r"):
        try:
            self.fd = urlgrabber.urlopen(self.source)
        except urlgrabber.grabber.URLGrabError, e:
            raise IOError, str(e)
        return 1

    def close(self):
        RpmStreamIO.close(self)
        self.fd.close()
        self.fd = None
        return 1


class RpmHttpIO(RpmStreamIO):
    def __init__(self, config, source, verify=None, strict=None, hdronly=None):
        RpmStreamIO.__init__(self, config, source, verify, strict, hdronly)

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


def getRpmIOFactory(config, source, verify=None, strict=None, hdronly=None):
    """Get a RpmIO implementation for package "URI" source.

    Configure it to verify lead and index entries if verify; report legacy tags
    and packages not named %name if strict; don't return payload from read()
    if hdronly.  Default to file:/ if no scheme is provided."""

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


# vim:ts=4:sw=4:showmatch:expandtab
