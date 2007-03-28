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


import fcntl, os, sys, struct, zlib, time
import __builtin__
(pack, unpack) = (struct.pack, struct.unpack)

try:
    import urlgrabber
except ImportError:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module. Only check scripts available."

from base import *
import functions
from pyrpm.logger import log


# based on Andrew Kuchling's minigzip.py distributed with the zlib module
FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT = 1, 2, 4, 8, 16
READ, WRITE = 1, 2

def LOWU32(i):
    """Return the low-order 32 bits of an int, as a non-negative int."""
    return i & 0xFFFFFFFFL

def write32(output, value):
    output.write(pack("<l", value))

def write32u(output, value):
    # The L format writes the bit pattern correctly whether signed
    # or unsigned.
    output.write(pack("<L", value))

class PaddedFile:
    """readonly file object that prepends string the content of f"""
    def __init__(self, string, f):
        self._string = string
        self._length = len(string)
        self._file = f
        self._read = 0

    def read(self, size):
        if self._read is None:
            return self._file.read(size)
        if self._read + size <= self._length:
            read = self._read
            self._read += size
            return self._string[read:self._read]
        else:
            read = self._read
            self._read = None
            return self._string[read:] + \
                   self._file.read(size-self._length+read)

    def unused(self):
        if self._read is None:
            return ''
        return self._string[self._read:]
        
class PyGZIP:
    """The GzipFile class simulates most of the methods of a file object with
    the exception of the readinto() and truncate() methods.

    """

    myfileobj = None

    def __init__(self, filename=None, mode=None,
                 compresslevel=9, fileobj=None):
        """Constructor for the GzipFile class.

        At least one of fileobj and filename must be given a
        non-trivial value.

        The new class instance is based on fileobj, which can be a regular
        file, a StringIO object, or any other object which simulates a file.
        It defaults to None, in which case filename is opened to provide
        a file object.

        When fileobj is not None, the filename argument is only used to be
        included in the gzip file header, which may includes the original
        filename of the uncompressed file.  It defaults to the filename of
        fileobj, if discernible; otherwise, it defaults to the empty string,
        and in this case the original filename is not included in the header.

        The mode argument can be any of 'r', 'rb', 'a', 'ab', 'w', or 'wb',
        depending on whether the file will be read or written.  The default
        is the mode of fileobj if discernible; otherwise, the default is 'rb'.
        Be aware that only the 'rb', 'ab', and 'wb' values should be used
        for cross-platform portability.

        The compresslevel argument is an integer from 1 to 9 controlling the
        level of compression; 1 is fastest and produces the least compression,
        and 9 is slowest and produces the most compression.  The default is 9.

        """

        # guarantee the file is opened in binary mode on platforms
        # that care about that sort of thing
        if mode and 'b' not in mode:
            mode += 'b'
        if fileobj is None:
            fileobj = self.myfileobj = __builtin__.open(filename, mode or 'rb')
        if filename is None:
            if hasattr(fileobj, 'name'): filename = fileobj.name
            else: filename = ''
        if mode is None:
            if hasattr(fileobj, 'mode'): mode = fileobj.mode
            else: mode = 'rb'

        if mode[0:1] == 'r':
            self.mode = READ
            # Set flag indicating start of a new member
            self._new_member = True

            self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
            self.crcval = zlib.crc32("")
            self.buffer = []   # List of data blocks
            self.bufferlen = 0
            self.pos = 0       # Offset of next data to read from buffer[0]
            
            self.name = filename

        elif mode[0:1] == 'w' or mode[0:1] == 'a':
            self.mode = WRITE
            self._init_write(filename)
            self.compress = zlib.compressobj(compresslevel,
                                             zlib.DEFLATED,
                                             -zlib.MAX_WBITS,
                                             zlib.DEF_MEM_LEVEL,
                                             0)
        else:
            raise IOError, "Mode " + mode + " not supported"

        self.size = 0
        self.fileobj = fileobj
        self.offset = 0

        if self.mode == WRITE:
            self._write_gzip_header()

    @property
    def filename(self):
        import warnings
        warnings.warn("use the name attribute", DeprecationWarning)
        if self.mode == WRITE and self.name[-3:] != ".gz":
            return self.name + ".gz"
        return self.name

    def __repr__(self):
        s = repr(self.fileobj)
        return '<gzip ' + s[1:-1] + ' ' + hex(id(self)) + '>'

    def _init_write(self, filename):
        self.name = filename
        self.crc = zlib.crc32("")
        self.writebuf = []
        self.bufsize = 0

    def _write_gzip_header(self):
        self.fileobj.write('\037\213')             # magic header
        self.fileobj.write('\010')                 # compression method
        fname = self.name
        if fname.endswith(".gz"):
            fname = fname[:-3]
        flags = 0
        if fname:
            flags = FNAME
        self.fileobj.write(chr(flags))
        write32u(self.fileobj, long(time.time()))
        self.fileobj.write('\002')
        self.fileobj.write('\377')
        if fname:
            self.fileobj.write(fname + '\000')

    def _read_gzip_header(self, f):
        magic = f.read(2)
        if magic != '\037\213':
            raise IOError, 'Not a gzipped file'
        method = ord( f.read(1) )
        if method != 8:
            raise IOError, 'Unknown compression method'
        flag = ord( f.read(1) )
        # modtime = f.read(4)
        # extraflag = f.read(1)
        # os = f.read(1)
        f.read(6)

        if flag & FEXTRA:
            # Read & discard the extra field, if present
            xlen = ord(f.read(1))
            xlen = xlen + 256*ord(f.read(1))
            f.read(xlen)
        if flag & FNAME:
            # Read and discard a null-terminated string containing the filename
            while True:
                s = f.read(1)
                if not s or s=='\000':
                    break
        if flag & FCOMMENT:
            # Read and discard a null-terminated string containing a comment
            while True:
                s = f.read(1)
                if not s or s=='\000':
                    break
        if flag & FHCRC:
            f.read(2)     # Read & discard the 16-bit header CRC


    def write(self,data):
        if self.mode != WRITE:
            import errno
            raise IOError(errno.EBADF, "write() on read-only GzipFile object")

        if self.fileobj is None:
            raise ValueError, "write() on closed GzipFile object"
        if len(data) > 0:
            self.size = self.size + len(data)
            self.crc = zlib.crc32(data, self.crc)
            self.fileobj.write( self.compress.compress(data) )
            self.offset += len(data)

    def _read_eof(self):
        if len(self.decompobj.unused_data) < 8:
            unused = self.decompobj.unused_data  + \
                     self.fileobj.read(8-len(self.decompobj.unused_data))
            if len(unused)<8:
                raise IOError, "Unexpected EOF"
        else:
            unused = self.decompobj.unused_data
        crc32 = unpack(
            "<L", unused[0:4])[0] #le signed int
        isize = unpack(
            "<L", unused[4:8])[0] #le unsigned int

        # Do the CRC check with a LOWU32 on the read self.crcval due to the
        # signed/unsigned problem of the zlib crc code.
        if crc32 != LOWU32(self.crcval):
            raise IOError, "CRC check failed"
        if isize != LOWU32(self.size):
            raise IOError, "Incorrect length of data produced"
        if len(unused) > 8:
            f = PaddedFile(unused[8:], self.fileobj)
        else:
            f = self.fileobj
        try:
            self._read_gzip_header(f)
        except IOError:
            return ''
        if len(unused) > 8:
            return f.unused()
        else:
            return ''
        

    def _read(self, readsize):
        data = self.fileobj.read(readsize)

        while True:
            if data == "":
                decompdata = self.decompobj.flush()
            else:
                decompdata = self.decompobj.decompress(data)
            decomplen = len(decompdata)
            self.buffer.append(decompdata)
            self.bufferlen += decomplen
            self.size += decomplen
            self.crcval = zlib.crc32(decompdata, self.crcval)
            if self.decompobj.unused_data:
                data = self._read_eof()
                self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
                self.crcval = zlib.crc32("")
                self.size = 0
                if data:
                    continue
            break
        return data==''

    def read(self, size=-1):
        """Decompress up to bytes bytes from input.

        Raise IOError."""

        if self.mode != READ:
            import errno
            raise IOError(errno.EBADF, "read() on write-only GzipFile object")

        if self._new_member:
            self._read_gzip_header(self.fileobj)
            self._new_member = False

        while size < 0 or self.bufferlen <  size:
            if size < 0:
                readsize = 65536 - self.bufferlen
            else:
                readsize = size - self.bufferlen
                
            if readsize > 65536:
                readsize = 32768
            elif readsize > 32768:
                readsize = 16384
            elif readsize > 16384:
                readsize = 8192
            elif readsize > 8192:
                readsize = 4096
            elif readsize > 4096:
                readsize = 2048
            else:
                readsize = 1024

            eof = self._read(readsize)
            if eof:
                break
        if size < 0:
            size = self.bufferlen
        retdata = ""
        while size > 0 and self.buffer:
            decompdata = self.buffer[0]
            decomplen = len(decompdata)
            if size+self.pos <= decomplen:
                tmpdata = decompdata[self.pos:size+self.pos]
                retdata += tmpdata
                self.bufferlen -= size
                self.pos += size
                break
            decomplen -= self.pos
            size -= decomplen
            self.bufferlen -= decomplen
            if self.pos != 0:
                retdata += decompdata[self.pos:]
            else:
                retdata += decompdata
            self.pos = 0
            self.buffer.pop(0)
        self.offset += len(retdata)
        return retdata

    def close(self):
        if self.mode == WRITE:
            self.fileobj.write(self.compress.flush())
            # The native zlib crc is an unsigned 32-bit integer, but
            # the Python wrapper implicitly casts that to a signed C
            # long.  So, on a 32-bit box self.crc may "look negative",
            # while the same crc on a 64-bit box may "look positive".
            # To avoid irksome warnings from the `struct` module, force
            # it to look positive on all boxes.
            write32u(self.fileobj, LOWU32(self.crc))
            # self.size may exceed 2GB, or even 4GB
            write32u(self.fileobj, LOWU32(self.size))
            self.fileobj = None
        elif self.mode == READ:
            self.fileobj = None
        if self.myfileobj:
            self.myfileobj.close()
            self.myfileobj = None

    def __del__(self):
        try:
            if (self.myfileobj is None and
                self.fileobj is None):
                return
        except AttributeError:
            return
        self.close()

    def flush(self,zlib_mode=zlib.Z_SYNC_FLUSH):
        if self.mode == WRITE:
            # Ensure the compressor's buffer is flushed
            self.fileobj.write(self.compress.flush(zlib_mode))
        self.fileobj.flush()

    def fileno(self):
        """Invoke the underlying file object's fileno() method.

        This will raise AttributeError if the underlying file object
        doesn't support fileno().
        """
        return self.fileobj.fileno()

    def isatty(self):
        return False

    def tell(self):
        return self.offset

    def rewind(self):
        '''Return the uncompressed stream file position indicator to the
        beginning of the file'''
        if self.mode != READ:
            raise IOError("Can't rewind in write mode")
        self.fileobj.seek(0)
        self._new_member = True
        self.decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
        self.crcval = zlib.crc32("")
        self.buffer = []   # List of data blocks
        self.bufferlen = 0
        self.pos = 0       # Offset of next data to read from buffer[0]
        self.offset = 0
        self.size = 0

    def seek(self, offset, whence=0):
        if whence:
            if whence == 1:
                offset = self.offset + offset
            else:
                raise ValueError('Seek from end not supported')
        if self.mode == WRITE:
            if offset < self.offset:
                raise IOError('Negative seek in write mode')
            count = offset - self.offset
            for i in range(count // 1024):
                self.write(1024 * '\0')
            self.write((count % 1024) * '\0')
        elif self.mode == READ:
            if offset < self.offset:
                # for negative seek, rewind and do positive seek
                self.rewind()
            count = offset - self.offset
            for i in range(count // 1024):
                self.read(1024)
            self.read(count % 1024)

    def readline(self, size=-1):
        if self._new_member:
            self._read_gzip_header(self.fileobj)
            self._new_member = False

        scansize = 0
        buffpos = 0
        while True:
            for idx in range(buffpos, len(self.buffer)):
                if idx == 0:
                    scansize -= self.pos
                    pos = self.buffer[idx].find('\n', self.pos)
                else:
                    pos = self.buffer[idx].find('\n')                    
                if pos != -1:
                    if size>=0 and scansize+pos+1>size:
                        return self.read(size)
                    return self.read(scansize+pos+1)
                scansize += len(self.buffer[idx])
                if size>=0 and scansize>size:
                    return self.read(size)
            buffpos = len(self.buffer)
            eof = self._read(1024)
            if eof:
                return self.read(scansize)

    def readlines(self, sizehint=0):
        # Negative numbers result in reading all the lines
        if sizehint <= 0:
            sizehint = sys.maxint
        L = []
        while sizehint > 0:
            line = self.readline()
            if line == "":
                break
            L.append(line)
            sizehint = sizehint - len(line)

        return L

    def writelines(self, L):
        for line in L:
            self.write(line)

    def __iter__(self):
        return self

    def next(self):
        line = self.readline()
        if line:
            return line
        else:
            raise StopIteration


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
        self.hdrdata = self.__readIndex(8)

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
                log.error("%s: tag %d included twice", self.source, tag)
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
                log.error("%s: tag %d included twice", self.source, tag)
        else:
            self.hdr[tag] = self.__parseTag(index, storedata)
        return self.hdr[tag]

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
            log.warning("%s: Unsigned tags %s",
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
