#
# Copyright (C) 2006 Red Hat, Inc.
# Author: Miloslav Trmac
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

import struct

import functions

_ELFMAG = "\x7F" "ELF"

_ELFCLASS32 = 1
_ELFCLASS64 = 2

_ELFDATA2LSB = 1
_ELFDATA2MSB = 2

_EV_CURRENT = 1

ET_REL = 1                              # Relocatable file
ET_EXEC = 2                             # Executable file
ET_DYN = 3                              # Shared object file
ET_CORE = 4                             # Core file

class _ELFPhdr:
    """An ELF program header."""

    PT_DYNAMIC = 2

    def __init__(self, file):
        """Read a program header from the current position at ELFFile file.

        Raise IOError, ValueError on invalid input."""

        if not file.b64:
            tuple_ = file._readAndUnpack("8I")
        else:
            tuple_ = file._readAndUnpack("2I6Q")
        (self.type, self.offset, self.vaddr, self.paddr, self.filesz,
         self.memsz, self.flags, self.align) = tuple_

    # Number of bytes in one entry, indexed by ELFFile.b64
    entry_size = { False: 32, True: 56 }

class _ELFDynamic:
    """An ELF dynamic section entry."""

    DT_GNU_PRELINKED = 0x6ffffdf5
    DT_GNU_LIBLIST = 0x6ffffef9

    def __init__(self, file):
        """Read a dynamic section entry from the current position at ELFFile
        file.

        Raise IOError, ValueError on invalid input."""

        if not file.b64:
            (self.tag, self.value) = file._readAndUnpack("2I")
        else:
            (self.tag, self.value) = file._readAndUnpack("2Q")

    # Number of bytes in one entry, indexed by ELFFile.b64
    entry_size = { False: 8, True: 16 }

class ELFFile:
    """ELF file.

    Contains only the minimum necessary for file_is_prelinked()."""

    def __init__(self, filename):
        """Open an ELF file filename.

        Raise IOError, ValueError on invalid (or non-ELF) input."""

        self.filename = filename
        self.fd = open(filename)
        (magic, data_size, encoding, version) = \
                struct.unpack("4s3B9x", functions.readExact(self.fd, 16))
        if magic != _ELFMAG:
            raise ValueError, "%s: Not an ELF file" % filename
        if version != _EV_CURRENT:
            raise ValueError, \
                  "%s: Unknown ELF version %s" % (filename, version)
        if data_size == _ELFCLASS32:
            self.b64 = False
        elif data_size == _ELFCLASS64:
            self.b64 = True
        else:
            raise ValueError, \
                  "%s: Unknown data size %s" % (filename, data_size)
        if encoding == _ELFDATA2LSB:
            self.endian_prefix = '<'
        elif encoding == _ELFDATA2MSB:
            self.endian_prefix = '>'
        else:
            raise ValueError, \
                  "%s: Unknown data encoding %s" % (filename, encoding)
        if not self.b64:
            tuple_ = self._readAndUnpack("H10xI10x2H6x")
        else:
            tuple_ = self._readAndUnpack("H14xQ14x2H6x")
        (self.type, ph_offset, ph_size, num_ph) = tuple_
        if ph_size != _ELFPhdr.entry_size[self.b64]:
            raise ValueError, \
                  ("%s: Unhandled program header size %s"
                   % (filename, ph_size))
        self.fd.seek(ph_offset)
        self.phdrs = []
        for _ in xrange(num_ph):
            self.phdrs.append(_ELFPhdr(self))
        self.dynamic = []
        dynamics = [phdr for phdr in self.phdrs
                    if phdr.type == _ELFPhdr.PT_DYNAMIC]
        if dynamics:
            if len(dynamics) > 1:
                raise ValueError, \
                      "%s: More than one dynamic section" % filename
            dynamic = dynamics[0]
            self.fd.seek(dynamic.offset)
            if dynamic.filesz % _ELFDynamic.entry_size[self.b64] != 0:
                raise ValueError, "%s: Invalid dynamic section size" % filename
            for _ in xrange(dynamic.filesz / _ELFDynamic.entry_size[self.b64]):
                self.dynamic.append(_ELFDynamic(self))

    def _readAndUnpack(self, format):
        """Read data from self.fd and extract it as described by format.

        Raise IOError, ValueError on invalid input."""

        format = self.endian_prefix + format
        data = functions.readExact(self.fd, struct.calcsize(format))
        try:
            res = struct.unpack(format, data)
        except struct.error:
            raise ValueError, "%s: Error unpacking data" % self.filename
        return res

    def close(self):
        if self.fd is not None:
            self.fd.close()
            self.fd = None


def file_is_prelinked(filename):
    """Return True if the file named by filename is prelinked."""

    try:
        e = ELFFile(filename)
    except (IOError, ValueError):
        return False
    if e.type not in (ET_EXEC, ET_DYN):
        return False
    for dyn in e.dynamic:
        if dyn.tag in (_ELFDynamic.DT_GNU_PRELINKED,
                       _ELFDynamic.DT_GNU_LIBLIST):
            return True
    return False

# vim:ts=4:sw=4:showmatch:expandtab
