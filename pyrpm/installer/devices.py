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

from config import log
from pyrpm.installer.functions import getId, getName


class Devices:
    def __init__(self):
        self.devices = [ ]
        self.map = { }
        self.reverse_map = { }

    def add(self, device):
        if device in self.devices:
            log.error("Device '%' is already in use.", device)
            return 0
        self.devices.append(device)
        return 1

    def remove(self, device):
        if not device in self.devices:
            log.warning("Device '%s' is not in use.", device)
            return 1
        self.devices.remove(device)
        return 1

    def getNextFree(self, device):
        if len(device) == 3 and device[:2] in [ "hd", "sd" ]:
            raise NotImplementedError, "hdX, sdX not supported, yet."
        dev = device
        while dev in self.devices:
            i = getId(dev) + 1
            dev = "%s%d" % (getName(dev), i)
        return dev

    def mapTo(self, device, mapto):
        if device in self.map:
            raise ValueError, "Device '%s' already in use." % device
        if mapto in self.reverse_map:
            raise ValueError, "Mapto '%s' already in use." % mapto
        self.map[device] = mapto
        self.reverse_map[mapto] = device

    def map(self, device):
        if device in self.map:
            raise ValueError, "Device '%s' not in use." % device
        return self.map[device]

    def reverseMap(self, mapto):
        if mapto in self.reverse_map:
            raise ValueError, "Mapto '%s' not in use." % mapto
        return self.reverse_map[mapto]

# vim:ts=4:sw=4:showmatch:expandtab
