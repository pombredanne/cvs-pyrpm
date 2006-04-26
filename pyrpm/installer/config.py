#
# Copyright (C) 2005,2006 Red Hat, Inc.
# Author: Thomas Woerner <twoerner@redhat.com>
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

import sys

################################### classes ###################################

class Logger:
    def __init__(self):
        self.fd = None

    def open(self, filename):
        if self.fd:
            return
        self.fd = open(filename, "w")
        sys.stdout = sys.stderr = self

    def write(self, data):
        sys.__stdout__.write(data)
        if not self.fd:
            return
        self.fd.write(data)
        self.fd.flush()

    def close(self):
        if not self.fd:
            return
        self.fd.close()
        self.fd = None
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def flush(self):
        sys.__stdout__.flush()
        if self.fd:
            self.fd.flush()

    def log(self, data):
        if self.fd:
            self.fd.write(data)
        else:
            sys.__stdout__.write(data)

################################## variables ##################################

logger = Logger()
verbose = 0

################################## functions ##################################

def log(data):
    global logger
    logger.log(data)
