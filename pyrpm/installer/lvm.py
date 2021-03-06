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
from pyrpm.functions import runScript
from functions import run_script

class LVM_PHYSICAL_VOLUME:
    prog = "LANG=C /usr/sbin/lvm"

    def __init__(self, device, chroot=None):
        self.device = device
        self.chroot = chroot

    def create(self):
        command = "%s pvcreate --zero y -ff -y -d %s" % \
                  (LVM_PHYSICAL_VOLUME.prog, self.device)
        if run_script(command, self.chroot, log) != 0:
            log.error("Creation of physical layer on '%s' failed.",
                      self.device)
            return 0
        return 1

    def scan(chroot=None):
        command = "%s pvscan 2>/dev/null" % LVM_PHYSICAL_VOLUME.prog
        log.debug1(command)
        (status, rusage, msg) = runScript(script=command, chroot=chroot)
        if msg and msg != "":
            log.debug1(msg, nofmt=1)
        if status != 0:
            log.error("Failed to scan for physical volumes.")
            return None

        dict = { }
        for line in msg.split("\n"):
            line = line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            splits = line.split()
            if len(splits) < 4 or splits[0] != "PV" or splits[2] != "VG":
                continue
            # set <volgroup>: <device>, ..
            dict.setdefault(splits[3], [ ]).append(splits[1])
        return dict
    scan = staticmethod(scan)

    def info(device, chroot=None):
        pvs = LVM_PHYSICAL_VOLUME.display(chroot=chroot)
        if not pvs.has_key(device) or \
               not pvs[device].has_key("vgname"):
            log.error("Unable to get physical volume information for '%s'.",
                      device)
            return None
        return pvs[device]
    info = staticmethod(info)

    def display(chroot=None):
        command = "%s pvdisplay --units b 2>/dev/null" % \
                  LVM_PHYSICAL_VOLUME.prog
        log.debug1(command)
        (status, rusage, msg) = runScript(script=command, chroot=chroot)
        if msg and msg != "":
            log.debug1(msg, nofmt=1)
        if status != 0:
            log.error("Failed to get general physical volume information.")
            return None

        dict = { }
        device = None
        for line in msg.split("\n"):
            line = line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            if line[:7] == "PV Name":
                device = line[7:].strip()
                dict[device] = { }
                d = dict[device]
            if not device:
                continue
            try:
                if line[:7] == "VG Name":
                    d["vgname"] = line[7:].strip()
                elif line[:7] == "PV UUID":
                    d["pvuuid"] = line[7:].strip()
            except:
                log.error("pvdisplay output malformed.")
                return None
        return dict
    display = staticmethod(display)

class LVM_VOLGROUP:
    prog = "LANG=C /usr/sbin/lvm"
    default_pesize = "4096k"

    def __init__(self, name, chroot=None):
        self.name = name
        self.active = False
        self.chroot = chroot
        self.format = None
        self.extent = -1
        self.size = -1

    def create(self, devices, extent=-1):
        command = "%s vgcreate" % LVM_VOLGROUP.prog
        if extent > 0:
            command += " --physicalextentsize '%s'" % extent
        command += " %s %s" % (self.name, " ".join(devices))
        if run_script(command, self.chroot, log) != 0:
            log.error("Creation of volume group '%s' on '%s' failed.",
                      self.name, devices)
            return 0
        self.active = 1

        vg = LVM_VOLGROUP.info(self.name, chroot=self.chroot)
        if not vg:
            self.stop()
            return 0
        self.format = vg["format"]
        self.extent = vg["pesize"]
        self.size = vg["vgsize"]
        return 1

    def start(self):
        command = "%s vgchange -a y '%s'" % (LVM_VOLGROUP.prog, self.name)
        if run_script(command, self.chroot, log) != 0:
            log.error("Activation of volume group '%s' failed.", self.name)
            return 0
        self.active = True
        return 1

    def stop(self):
        if not self.active:
            return 1
        command = "%s vgchange -a n '%s'" % (LVM_VOLGROUP.prog, self.name)
        if run_script(command, self.chroot, log) != 0:
            log.error("Deactivation of volume group '%s' failed.", self.name)
            return 0
        self.active = False
        return 1

    def scan(chroot=None):
        command = "%s vgscan --mknodes 2>/dev/null" % LVM_VOLGROUP.prog
        if run_script(command, chroot, log) != 0:
            log.error("Failed to scan for volume groups.")
            return 0
        return 1
    scan = staticmethod(scan)

    def info(name, chroot=None):
        vgs = LVM_VOLGROUP.display(chroot=chroot)
        if not vgs.has_key(name) or \
               not vgs[name].has_key("format") or \
               not vgs[name].has_key("pesize") or \
               not vgs[name].has_key("vgsize"):
            log.error("Unable to get volume group information for '%s'.",
                      name)
            return None
        return vgs[name]
    info = staticmethod(info)

    def display(chroot=None):
        command = "%s vgdisplay --units b 2>/dev/null" % LVM_VOLGROUP.prog
        log.debug1(command)
        (status, rusage, msg) = runScript(script=command, chroot=chroot)
        if msg and msg != "":
            log.debug1(msg, nofmt=1)
        if status != 0:
            log.error("Failed to get volume group information.")
            return None

        dict = { }
        group = None
        for line in msg.split("\n"):
            line = line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            if line[:7] == "VG Name":
                group = line[7:].strip()
                dict[group] = { }
                d = dict[group]
            if not group:
                continue
            try:
                if line[:6] == "Format":
                    d["format"] = line[7:].strip()
                elif line[:7] == "VG Size":
                    if line[-2:] == " B":
                        d["vgsize"] = long(line[7:-1].strip())
                elif line[:7] == "PE Size":
                    if line[-2:] == " B":
                        d["pesize"] = long(line[7:-1].strip())
                elif line[:8] == "Total PE":
                    d["pe"] = long(line[8:].strip())
            except:
                log.error("vgdisplay output malformed.")
                return None
        return dict
    display = staticmethod(display)

class LVM_LOGICAL_VOLUME:
    prog = "LANG=C /usr/sbin/lvm"

    def __init__(self, name, volgroup, chroot=None):
        self.name = name
        self.active = False
        self.volgroup = volgroup
        self.chroot = chroot

    def create(self, size):
        command = "%s lvcreate -n '%s' --size %dk '%s'" % \
                  (LVM_LOGICAL_VOLUME.prog, self.name, (size / 1024),
                   self.volgroup)
        if run_script(command, self.chroot, log) != 0:
            log.error("Creation of logical volume '%s' on '%s' failed.",
                      self.name, self.volgroup)
            return 0
        self.active = 1
        return 1

    def scan(chroot=None):
        command = "%s lvscan 2>/dev/null" % LVM_LOGICAL_VOLUME.prog
        log.debug1(command)
        (status, rusage, msg) = runScript(script=command, chroot=chroot)
        if msg and msg != "":
            log.debug1(msg, nofmt=1)
        if status != 0:
            log.error("Failed to scan for logical volumes.")
            return None

        dict = { }
        for line in msg.split("\n"):
            line = line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            splits = line.split("'")
            if len(splits) < 3:
                continue
            # set <volgroup>: <device>, ..
            d = splits[1].split("/")
            if len(d) != 3 or d[0] != "dev":
                continue
            dict[splits[1]] = d[1]
        return dict
    scan = staticmethod(scan)

    def info(name, chroot=None):
        lvs = LVM_LOGICAL_VOLUME.display(chroot=chroot)
        if not lvs.has_key(name) or \
               not lvs[name].has_key("device") or \
               not lvs[name].has_key("lvsize"):
            log.error("Unable to get logical volume information for '%s'.",
                      name)
            return None
        return lvs[name]
    info = staticmethod(info)

    def display(chroot=None):
        command = "%s lvdisplay --units b 2>/dev/null" % \
                  LVM_LOGICAL_VOLUME.prog
        log.debug1(command)
        (status, rusage, msg) = runScript(script=command, chroot=chroot)
        if msg and msg != "":
            log.debug1(msg, nofmt=1)
        if status != 0:
            log.error("Failed to get volume group information.")
            return None

        dict = { }
        volume = None
        for line in msg.split("\n"):
            line = line.strip()
            if len(line) < 1 or line[0] == '#':
                continue
            if line[:7] == "LV Name":
                volume = line[7:].strip()
                dict[volume] = { }
                d = dict[volume]
            if not volume:
                continue
            try:
                if line[:6] == "VG Name":
                    d["vgname"] = line[7:].strip()
                elif line[:6] == "LV UUID":
                    d["lvuuid"] = line[7:].strip()
                elif line[:7] == "LV Size":
                    if line[-2:] == " B":
                        d["lvsize"] = long(line[7:-1].strip())
                elif line[:7] == "Block device":
                    d["device"] = line[12:].strip()
            except:
                log.error("lvdisplay output malformed.")
                return None
        return dict
    display = staticmethod(display)

# vim:ts=4:sw=4:showmatch:expandtab
