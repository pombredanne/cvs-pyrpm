#
# Copyright (C) 2005 Red Hat, Inc.
# Copyright (C) 2005 Harald Hoyer <harald@redhat.com>
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

__version__ = "0.42"
__doc__ = """Read and manage RPM packages."""

import os, locale, sys

_files = map(lambda v: v[:-3], filter(lambda v: v[-3:] == ".py" and \
                                      v != "__init__.py" and \
                                      v[0] != '.', \
                                      os.listdir(__path__[0])))

locale.setlocale(locale.LC_ALL, "C")
_files.sort()
locale.setlocale(locale.LC_ALL, "")

# not tested at all, just a guess
if sys.version_info < (2, 3):
    sys.exit("error: Python 2.3 or later required")

for _i in _files:
    _cmd = "from %s import *" % _i
    exec _cmd

del _i
del _files
del _cmd

# vim:ts=4:sw=4:showmatch:expandtab
