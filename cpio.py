"Read and write CPIO files. ASCII support only at this time."

import struct

def is_cpio(file):
    """See if file is a CPIO file by checking the magic number."""
    try:
        fpin = open(file, "rb")
        (magic,) = struct.unpack("6s", fpin.read(6))
        fpin.close()
        if magic == "070701" or magic == "070702":
            return True                 # file has correct magic number
    except IOError:
        pass
    return False

class CPIOFile:
    """ Class with methods to open, read, write, close, list CPIO files.

    c = CPIOFile(file, mode="r")

    file: Either the path to the file, or a file-like object.
          If it is a path, the file will be opened and closed by CPIOFile.
    mode: The mode can be either read "r", write "w" or append "a".
    """

    def __init__(self, file, mode="r"):
        """Open the ZIP file with mode read "r", write "w" or append "a"."""
        self.filelist = []      # List of CPIO Header dicts
        self.mode = mode[0]     # we don't support rw

        # Check if we were passed a file-like object
        if isinstance(file, basestring):
            self._filePassed = 0
            self.filename = file
            # Always open in binary mode
            modeDict = {'r' : 'rb', 'w': 'wb', 'a' : 'r+b'}
            self.fp = open(file, modeDict[mode])
        else:
            self._filePassed = 1
            self.fp = file
            self.filename = getattr(file, 'name', None)

        if self.mode == 'r':
            pass
        elif self.mode == 'w':
            pass
        elif self.mode == 'a':
            pass
        else:
            if not self._filePassed:
                self.fp.close()
                self.fp = None
            raise RuntimeError, 'Mode must be "r", "w" or "a"'

    def _read_cpio_headers(self):
        CPIO_HEADER_LEN = 110

        while 1:
            cpio_headers = {}
            (magic, inode, mode, uid, gid, 
            nlink, mtime, filesize, devMajor, 
            devMinor, rdevMajor, rdevMinor, namesize, checksum) = \
            struct.unpack("6s8s8s8s8s8s8s8s8s8s8s8s8s8s", self.fp.read(CPIO_HEADER_LEN))
            cpio_headers['magic'] = magic
            cpio_headers['inode'] = inode
            cpio_headers['mode'] = oct(int(mode,16))
            cpio_headers['uid'] = int(uid,16)
            cpio_headers['gid'] = int(gid, 16)
            cpio_headers['nlink'] = int(nlink,16)
            cpio_headers['mtime'] = int(mtime,16)
            cpio_headers['filesize'] = int(filesize,16)
            cpio_headers['devMajor'] = int(devMajor,16)
            cpio_headers['rdevMajor'] = int(rdevMajor,16)
            cpio_headers['devMinor'] = int(devMinor,16)
            cpio_headers['rdevMinor'] = int(rdevMinor,16)
            cpio_headers['namesize'] = int(namesize,16)
            cpio_headers['checksum'] = checksum

            if cpio_headers["magic"] == "070701" or cpio_headers["magic"] == "070702":
                pass
            else:
                raise IOError, "Bad magic reading CPIO headers %s" % magic

            # Read filename
            size = cpio_headers['namesize']
            cpio_headers["filename"] = self.fp.read(size).rstrip("\x00")
            fsize = CPIO_HEADER_LEN + size
            # Padding
            pad = ( 4 - ( fsize % 4 )) % 4
            self.fp.seek(pad,1)
            cpio_headers["offset"] = self.fp.tell()

            # Detect if we're at the end of the archive
            if cpio_headers["filename"] == "TRAILER!!!":
                break

            # Contents
            filesize = cpio_headers['filesize']
            pad = ( 4 - ( filesize %4 )) % 4 
            self.fp.seek(filesize,1)
            self.fp.seek(pad,1)
            self.filelist.append(cpio_headers)

    def namelist(self):
        """Return a list of file names in the archive."""
        l = []
        for data in self.filelist:
            l.append(data["filename"])
        return l

    def read(self):
        """Return file bytes."""
        if self.mode not in ("r", "a"):
            raise RuntimeError, 'read() requires mode "r" or "a"'
        if not self.fp:
            raise RuntimeError, \
                  "Attempt to read ZIP archive that was already closed"
        self._read_cpio_headers()

    def write(self):
# XXX: TODO implement write support
        if self.mode not in ("w", "a"):
            raise IOError("write() on read-only CPIOFile")
        pass

    def __del__(self):
        """Call the "close()" method in case the user forgot."""
        self.close()

    def close(self):
        """Close the file, and for mode "w" and "a" write the ending
        records."""
        if self.fp is None:
            return
        if self.mode in ("w", "a"):             # write ending records
            pass
        if not self._filePassed:
            self.fp.close()
        self.fp = None


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        c = CPIOFile(f)
        try:
            c.read()
        except IOError, e:
            print "error reading cpio: %s" % e
        print c.filelist
