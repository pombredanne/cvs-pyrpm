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

import pyrpm.functions as functions
import config

class RAID:
    prog = "LANG=C /sbin/mdadm"
    chunk_size = 64L*1024L

    def __init__(self, name, devices, mapto=None, chroot=None):
        self.name = name
        self.map_to = mapto
        self.chroot = chroot
        if mapto:
            self.device = "/dev/%s" % mapto
        else:
            self.device = "/dev/%s" % name
        self.active = False
        self.level = -1
        self.spares = -1
        self.devices = devices
        self.size = -1

    def mapTo(self, mapto):
        if self.active:
            print "ERROR: Unable to remap '%s'," % self.name + \
                  "because it is already active."
            return 0
        self.device = "/dev/" % mapto
        return 1

    def assemble(self):
        command = "%s --assemble '%s'" % (RAID.prog, self.device) + \
                  " %s" % (" ".join(self.devices))
        if config.verbose:
            print command
        (status, rusage, msg) = functions.runScript(script=command,
                                                    chroot=self.chroot)
        config.log(msg)
        if status != 0:
            print "ERROR: mdadm failed on '%s' with error code %d" % \
                  (self.name, status)
            return 1
        self.active = True

        dict = self.info(self.device, self.chroot)
        if not dict:
            self.stop()
            return 0
        self.level = dict["level"]
        self.spares = dict["spare-devices"]
        self.preferred_minor = dict["preferred-minor"]
        self.size = dict["size"]
        return 0

    def create(self, level, spares=0):
        num = len(self.devices) - spares
        self.level = level
        self.spares = spares
        command = "%s --create '%s' --run" % (RAID.prog, self.device) + \
                " --raid-devices=%d" % (num) + \
                " --spare-devices=%d" % (self.spares) + \
                " --level=%d" % (self.level) + \
                " %s" % (" ".join(self.devices))
        if config.verbose:
            print command
        (status, rusage, msg) = functions.runScript(script=command,
                                                    chroot=self.chroot)
        config.log(msg)
        if status != 0:
            print "ERROR: Failed to create raid '%s'." % \
                  (self.name)
            return 0
        self.active = True

        dict = self.info(self.device, self.chroot)
        if not dict:
            self.stop()
            return 0
        self.preferred_minor = dict["preferred-minor"]
        self.size = dict["size"]
        return 1

    def stop(self):
        if not self.active:
            return 1
        command = "%s --stop '%s'" % (RAID.prog, self.device)
        if config.verbose:
            command
        (status, rusage, msg) = functions.runScript(script=command,
                                                    chroot=self.chroot)
        config.log(msg)
        if status != 0:
            print "ERROR: Deactivation of raid '%s' failed: %s" % \
                  (self.name, msg)
            return 0
        self.active = False
        return 1

    def writeConfig(self, file):
        print "TODO: RAID.writeConfig() ######################################"
    	return 0

    # get size of raid device
    def info(device, chroot=None):
        command = "%s --detail '%s'" % (RAID.prog, device)
        if config.verbose:
            print command
        (status, rusage, msg) = functions.runScript(script=command,
                                                    chroot=chroot)
        if status != 0:
            print "ERROR: Failed to get details for '%s'" % device
            config.log(msg)
            return None

        dict = { }
        error = 0
        for line in msg.split("\n"):
            line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            if line.find(":") == -1:
                continue
            (key, value) = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            try:
                if key == "Raid Level":
                    dict["level"] = long(value[4:])
                elif key == "Array Size":
                    dict["size"] = 1024L * long(value.split()[0])
                elif key == "Total Devices":
                    dict["total-devices"] = long(value)
                elif key == "Active Devices":
                    dict["active-devices"] = long(value)
                elif key == "Working Devices":
                    dict["working-devices"] = long(value)
                elif key == "Spare Devices":
                    dict["spare-devices"] = long(value)
                elif key == "Preferred Minor":
                    dict["preferred-minor"] = long(value)
                elif key == "Failed Devices":
                    dict["failed-devices"] = long(value)
                elif key == "State":
                    dict["state"] = value
                elif key == "Layout":
                    dict["layout"] = value
                elif key == "Chunk Size":
                    dict["chunk-size"] = value
                elif key == "UUID":
                    dict["uuid"] = value

                # uuid is not usable, because it changes with device names
                # /dev/loopX is not good to get an uuid
            except:
                print "ERROR: mdadm output malformed."
                return None
        dict["device"] = device
        return dict
    info = staticmethod(info)

    # static function to get raid information for a raid partition
    def examine(device, chroot=None):
        command = "%s -E '%s'" % (RAID.prog, device)
        if config.verbose:
            print command
        (status, rusage, msg) = functions.runScript(script=command,
                                                    chroot=chroot)
        if status != 0:
            print "ERROR: Unable to get raid information for '%s'." % \
                  device
            config.log(msg)
            return None

        dict = { }
        for line in msg.split("\n"):
            line.strip()
            if not line or len(line) < 1:
                continue
            if line.find(":") != -1:
                (key, value) = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                try:
                    if key == "Magic":
                        dict["magic"] = value
                    elif key == "UUID":
                        dict["uuid"] = value
                    elif key == "Raid Level":
                        dict["level"] = long(value[4:])
                    elif key == "Raid Devices":
                        dict["raid-devices"] = long(value)
                    elif key == "Total Devices":
                        dict["total-devices"] = long(value)
                    elif key == "Preferred Minor":
                        dict["preferred-minor"] = long(value)
                    elif key == "State":
                        dict["state"] = value
                    elif key == "Active Devices":
                        dict["active-devices"] = long(value)
                    elif key == "Working Devices":
                        dict["working-devices"] = long(value)
                    elif key == "Failed Devices":
                        dict["failed-devices"] = long(value)
                    elif key == "Spare Devices":
                        dict["spare-devices"] = long(value)
                    elif key == "Layout":
                        dict["layout"] = value
                    elif key == "Chunk Size":
                        dict["chunk-size"] = value
                except:
                    print "ERROR: mdadm output malformed."
                    return None
            else:
                splits = line.split()
                try:
                    if splits[0] == "this":
                        dict["device-number"] = long(splits[1])
                except:
                    print "ERROR: mdadm output malformed."
                    return None

        for key in [ "magic", "uuid", "level", "raid-devices", "total-devices",
                     "preferred-minor", "state", "active-devices",
                     "failed-devices", "device-number" ]:
            if not dict.has_key(key):
                print "WARNING: Raid information for '%s' is incomplete: %s" % (device, key)
                return None
        dict["device"] = device
        return dict
    examine = staticmethod(examine)
