#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Thomas Woerner
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

import os, stat, string, time
import parted
import functions, loop

# pyparted classes:
#
# PedDeviceType
#   DEVICE_UNKNOWN        0
#   DEVICE_SCSI           1
#   DEVICE_IDE            2
#   DEVICE_DAC960         3
#   DEVICE_CPQARRAY       4
#  (DEVICE_FILE           5) *not defined*
#   DEVICE_ATARAID        6
#   DEVICE_I2O            7
#  (DEVICE_DASD           8) *not defined*
#  (DEVICE_VIODASD        9) *not defined*
#   DEVICE_SX8            10
#
# PedPartitionType
#   PARTITION_PRIMARY     0x00
#   PARTITION_LOGICAL     0x01
#   PARTITION_EXTENDED    0x02
#   PARTITION_FREESPACE   0x04
#   PARTITION_METADATA    0x08
#   PARTITION_PROTECTED   0x10
#
# PedDevice
#   model                 string
#   path                  string
#   type                  PedDeviceType
#   sector_size           uint
#   length                PedSector
#   cylinders             uint
#   heads                 uint
#   sectors               uint
#
# PedDiskType
#   name                  string
#
# PedGeometry
#   dev                   PedDevice (disk)
#   start                 PedSector
#   end                   PedSector
#   length                PedSector
#
# PedDisk
#   dev                   PedDevice
#   type                  PedDiskType
#
# PedFileSystemType
#   name                  string
#
# PedPartition
#   disk                  PedDisk
#   geom                  PedGeometry
#   num                   int
#   type                  PedPartitionType
#   fs_type               PedFileSystemType
#

############################### partition class ###############################

class Partition(dict):
    nativeType = {
        0x00: "Empty",
        0x01: "FAT12",
        0x02: "XENIX root",
        0x03: "XENIX usr",
        0x04: "FAT16 <32M",
        0x05: "Extended",         # DOS 3.3+ extended partition
        0x06: "FAT16",            # DOS 16-bit >=32M
        0x07: "HPFS/NTFS",        # OS/2 IFS, eg, HPFS or NTFS or QNX
        0x08: "AIX",              # AIX boot (AIX -- PS/2 port) or SplitDrive
        0x09: "AIX bootable",     # AIX data or Coherent
        0x0a: "OS/2 Boot Manager",# OS/2 Boot Manager
        0x0b: "W95 FAT32",
        0x0c: "W95 FAT32 (LBA)",  # LBA really is `Extended Int 13h'
        0x0e: "W95 FAT16 (LBA)",
        0x0f: "W95 Ext'd (LBA)",
        0x10: "OPUS",
        0x11: "Hidden FAT12",
        0x12: "Compaq diagnostics",
        0x14: "Hidden FAT16 <32M",
        0x16: "Hidden FAT16",
        0x17: "Hidden HPFS/NTFS",
        0x18: "AST SmartSleep",
        0x1b: "Hidden W95 FAT32",
        0x1c: "Hidden W95 FAT32 (LBA)",
        0x1e: "Hidden W95 FAT16 (LBA)",
        0x24: "NEC DOS",
        0x39: "Plan 9",
        0x3c: "PartitionMagic recovery",
        0x40: "Venix 80286",
        0x41: "PPC PReP Boot",
        0x42: "SFS",
        0x4d: "QNX4.x",
        0x4e: "QNX4.x 2nd part",
        0x4f: "QNX4.x 3rd part",
        0x50: "OnTrack DM",
        0x51: "OnTrack DM6 Aux1", # (or Novell)
        0x52: "CP/M",             # CP/M or Microport SysV/AT
        0x53: "OnTrack DM6 Aux3",
        0x54: "OnTrackDM6",
        0x55: "EZ-Drive",
        0x56: "Golden Bow",
        0x5c: "Priam Edisk",
        0x61: "SpeedStor",
        0x63: "GNU HURD or SysV", # GNU HURD or Mach or Sys V/386
                                  # (such as ISC UNIX)
        0x64: "Novell Netware 286",
        0x65: "Novell Netware 386",
        0x70: "DiskSecure Multi-Boot",
        0x75: "PC/IX",
        0x80: "Old Minix",        # Minix 1.4a and earlier
        0x81: "Minix / old Linux",# Minix 1.4b and later
        0x82: "Linux swap / Solaris",
        0x83: "Linux",
        0x84: "OS/2 hidden C: drive",
        0x85: "Linux extended",
        0x86: "NTFS volume set",
        0x87: "NTFS volume set",
        0x88: "Linux plaintext",
        0x8e: "Linux LVM",
        0x93: "Amoeba",
        0x94: "Amoeba BBT",       # (bad block table)
        0x9f: "BSD/OS",           # BSDI
        0xa0: "IBM Thinkpad hibernation",
        0xa5: "FreeBSD",          # various BSD flavours
        0xa6: "OpenBSD",
        0xa7: "NeXTSTEP",
        0xa8: "Darwin UFS",
        0xa9: "NetBSD",
        0xab: "Darwin boot",
        0xb7: "BSDI fs",
        0xb8: "BSDI swap",
        0xbb: "Boot Wizard hidden",
        0xbe: "Solaris boot",
        0xbf: "Solaris",
        0xc1: "DRDOS/sec (FAT-12)",
        0xc4: "DRDOS/sec (FAT-16 < 32M)",
        0xc6: "DRDOS/sec (FAT-16)",
        0xc7: "Syrinx",
        0xda: "Non-FS data",
        0xdb: "CP/M / CTOS / ...",# CP/M or Concurrent CP/M or
                                  # Concurrent DOS or CTOS
        0xde: "Dell Utility",     # Dell PowerEdge Server utilities
        0xdf: "BootIt",           # BootIt EMBRM
        0xe1: "DOS access",       # DOS access or SpeedStor 12-bit FAT
                                  # extended partition
        0xe3: "DOS R/O",          # DOS R/O or SpeedStor
        0xe4: "SpeedStor",        # SpeedStor 16-bit FAT extended
                                  # partition < 1024 cyl.
        0xeb: "BeOS fs",
        0xee: "EFI GPT",          # Intel EFI GUID Partition Table
        0xef: "EFI (FAT-12/16/32)",# Intel EFI System Partition
        0xf0: "Linux/PA-RISC boot",# Linux/PA-RISC boot loader
        0xf1: "SpeedStor",
        0xf4: "SpeedStor",        # SpeedStor large partition
        0xf2: "DOS secondary",    # DOS 3.3+ secondary
        0xfd: "Linux raid autodetect", # New (2.2.x) raid partition with
                                       # autodetect using persistent
                                       # superblock
        0xfe: "LANstep",          # SpeedStor >1024 cyl. or LANstep
        0xff: "BBT",              # Xenix Bad Block Table
        }

    PARTITION_PRIMARY = parted.PARTITION_PRIMARY
    PARTITION_EXTENDED = parted.PARTITION_EXTENDED
    PARTITION_LOGICAL = parted.PARTITION_LOGICAL

    def __init__(self, ped_partition):
        self.ped_partition = ped_partition

    def __getitem__(self, item):
        if item == "name":
            return "%s%d" % (self["disk"]["name"], self.ped_partition.num)
        elif item == "id":
            return self.ped_partition.num
        elif item == "type":
            return self.ped_partition.type
        elif item == "type-name":
            return Partition.partitionType(self.ped_partition.type)
        elif item == "fstype":
            if self.ped_partition.fs_type and self.ped_partition.fs_type.name:
                return self.ped_partition.fs_type.name
            return None
        elif item == "start":
            return self.ped_partition.geom.start
        elif item == "end":
            return self.ped_partition.geom.end
        elif item == "length":
            return self.ped_partition.geom.length
        elif item == "unit-start":
            return self.ped_partition.geom.start / self["disk"]["units"] + 1
        elif item == "unit-end":
            return (self.ped_partition.geom.end + self["disk"]["units"]/2) \
                   / self["disk"]["units"]
        elif item == "unit-length":
            return self.ped_partition.geom.length / self["disk"]["units"]
        elif item == "boot":
            return self.ped_partition.get_flag(parted.PARTITION_BOOT)
        elif item == "native_type":
            return self.ped_partition.native_type
        else:
            return dict.get(self, item)

    def partitionType(type):
        t = [ ]
        if type == parted.PARTITION_PRIMARY:
            t.append("primary")
        elif type & parted.PARTITION_EXTENDED:
            t.append("extended")
        elif type & parted.PARTITION_LOGICAL:
            t.append("logical")

        if type & parted.PARTITION_FREESPACE:
            t.append("freespace")
        if type & parted.PARTITION_METADATA:
            t.append("metadata")
        if type & parted.PARTITION_PROTECTED:
            t.append("protected")
        if len(t) == 0:
            return "-unknown-"
        return string.join(t, ",")

    # make partitionType a static class method
    partitionType = staticmethod(partitionType)

    def set_type(self, type):
#        if not type in Partition.nativeType.keys():
#            print "ERROR: Unknown partition type %s" % type
        try:
            fst = parted.file_system_type_get(type)
        except Exception, msg:
            print msg
            return
        return self.ped_partition.set_system(fst)

    def keys(self):
        k = dict.keys(self)
        k.append("name")
        k.append("id")
        k.append("type")
        k.append("type-name")
        k.append("fstype")
        k.append("start")
        k.append("end")
        k.append("length")
        k.append("unit-start")
        k.append("unit-end")
        k.append("unit-length")
        k.append("boot")
        k.append("native-type")
        if "disk" in k:
            k.remove("disk")
        return k

################################# disk class #################################

class Disk(dict):
    diskType = { }
    # fill in Disk.diskType data
    type = parted.disk_type_get_next()
    while type:
        diskType[type.name] = type
        type = parted.disk_type_get_next(type)

    def __init__(self, name, alloc_loop=0, as_image=0):
        self.ped_disk = None
        self.__clear_partitions()
        self.alloc_loop = alloc_loop
        self.open(name, as_image)

    def __clear_partitions(self):
        self.partition = { }
        self.primary = { }
        self.extended = { }
        self.logical = { }
        self.freespace = [ ]
        self.freespace_primary = [ ]
        self.freespace_logical = [ ]

    def open(self, name, as_image=0):
        device = name
        mode = os.stat(device).st_mode

        if stat.S_ISBLK(mode) and not as_image:
            self["device"] = device
        elif stat.S_ISREG(mode) or as_image:
            self["image"] = device
            device = loop.losetup(self["image"])
            if not device:
                raise IOError, "Unable to get loop device for '%s'." % \
                      self["image"]
            self["device"] = device
        else:
            print "ERROR: %s: Unsupported device type." % device
            return

        self.ped_device = parted.PedDevice.get(self["device"])
        self.reload()

    def has_disklabel(self):
        return (self.ped_disk != None)

    def reload(self):
        if not self.ped_disk:
            try:
                self.ped_disk = parted.PedDisk.new(self.ped_device)
            except Exception, msg:
#                print Exception, msg
                pass
        if not self.ped_disk:
            return
        if self.has_key("image"):
            for part in self["partition"].keys():
                if self["partition"][part].has_key("device"):
                    if self["partition"][part]["device"]:
                        loop.lofree(self["partition"][part]["device"])
        self.__clear_partitions()

        ped_partition = self.ped_disk.next_partition()
        while ped_partition:
            if ped_partition.num == -1:
                # special partitions
                if ped_partition.type & parted.PARTITION_FREESPACE:
                    # free space
                    p = Partition(ped_partition)
                    p["disk"] = self
                    self.freespace.append(p)
                    if ped_partition.type & parted.PARTITION_LOGICAL:
                        self.freespace_logical.append(p)
                    else:
                        self.freespace_primary.append(p)
            # all other partitions
            elif (ped_partition.type == parted.PARTITION_PRIMARY or \
                  ped_partition.type & parted.PARTITION_EXTENDED or \
                  ped_partition.type & parted.PARTITION_LOGICAL):

                num = ped_partition.num
                self.partition[num] = Partition(ped_partition)
                self.partition[num]["disk"] = self
                if self.has_key("image"):
                    if self.alloc_loop:
                        device = loop.losetup(self["image"],
                                              self.partition[num]["start"] * \
                                              self["sector_size"])
                        loop.lo_set_maxsize(device,
                                            self.partition[num]["length"] * \
                                            self["sector_size"])
                        if not device:
                            raise IOError, "Unable to get loop device " + \
                                  "for partition %d of '%s'." % \
                                  (num, self["image"])
                    else:
                        device = None
                    self.partition[num]["device"] = device
                else:
                    self.partition[num]["device"] = "%s%d" % \
                                                    (self["device"], num)
                if ped_partition.type == parted.PARTITION_PRIMARY:
                    self.primary[num] = self.partition[num]
                elif ped_partition.type & parted.PARTITION_EXTENDED:
                    self.extended[num] = self.partition[num]
                elif ped_partition.type & parted.PARTITION_LOGICAL:
                    self.logical[num] = self.partition[num]

            ped_partition = self.ped_disk.next_partition(ped_partition)

    def close(self):
        if self.has_key("image"):
            # free loop device
            if self["device"]:
                loop.lofree(self["device"])
                for part in self["partition"].keys():
                    if self["partition"][part].has_key("device"):
                        if self["partition"][part]["device"]:
                            loop.lofree(self["partition"][part]["device"])
                    del self["partition"][part]
        self.__clear_partitions()
        del self.ped_disk
        del self.ped_device
        self.clear()

    def keys(self):
        k = dict.keys(self)
        k.append("model")
#        k.append("type")
        k.append("sector_size")
        k.append("length")
        k.append("cylinders")
        k.append("units")
        k.append("heads")
        k.append("sectors")
        k.append("disklabel")
        k.append("partition")
        k.append("freespace")
        return k

    def __getitem__(self, item):
        if self.has_key(item):
            return dict.get(self, item)

        if item == "model":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.model
        elif item == "device":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.path
        elif item == "type":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.type.name
        elif item == "sector_size":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.sector_size
        elif item == "length":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.length * self["sector_size"]
        elif item == "cylinders":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.cylinders
        elif item == "units":
            if not self.ped_disk:
                return None
            return self["heads"] * self["sectors"]
        elif item == "heads":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.heads
        elif item == "sectors":
            if not self.ped_disk:
                return None
            return self.ped_disk.dev.sectors
        elif item == "disklabel":
            if not self.ped_disk:
                return None
            return self.ped_disk.type.name
        elif item == "partition":
            return self.partition
        elif item == "primary":
            return self.primary
        elif item == "extended":
            return self.extended
        elif item == "logical":
            return self.logical
        elif item == "freespace_primary":
            return self.freespace_primary
        elif item == "freespace_logical":
            return self.freespace_logical
        elif item == "freespace":
            return self.freespace
        else:
            return dict.get(self, item)

    def __setitem__(self, item, value):
        if self.ped_disk:
            if item == "model":
                self.ped_disk.dev.model = value
            elif item == "device":
                self.ped_disk.dev.path = value
            elif item == "type":
                self.ped_disk.dev.type.name = value
            elif item == "sector_size":
                self.ped_disk.dev.sector_size = value
            elif item == "length":
                self.ped_disk.dev.length = value
            elif item == "cylinders":
                self.ped_disk.dev.cylinders = value
            elif item == "heads":
                self.ped_disk.dev.heads = value
            elif item == "sectors":
                self.ped_disk.dev.sectors = value
            elif item == "disklabel":
                self.ped_disk.type.name = value
            else:
                return dict.__setitem__(self, item, value)
        else:
            return dict.__setitem__(self, item, value)

    def add_partition(self, id, start, end, type, fstype):
        _fstype = None
        if fstype:
            if fstype == "raid":
                _fstype = None
            else:
                _fstype = parted.file_system_type_get(fstype)

        temp = [ ]
        s = start
        # create temporary partitions for all free primary ids up to the 
        # desired id
        if self.ped_disk.type.name == "msdos":
            i = 1
            while i < id and id <= 4:
                if not self["partition"].has_key(i):
                    if s >= end:
                        raise Exception, "Unable to create partition."

                    part = self.ped_disk.partition_new( \
                            Partition.PARTITION_PRIMARY, None, s, s)
                    constraint = self.ped_disk.dev.constraint_any()
                    r = self.ped_disk.add_partition(part, constraint)
                    if r:
                        raise Exception, "Unable to create partition."
                    temp.append(part)
                    i += 1
                    s += self["units"]

        part = self.ped_disk.partition_new(type, _fstype, s, end)
        if fstype == "raid":
            part.set_flag(parted.PARTITION_RAID, 1)
        constraint = self.ped_disk.dev.constraint_any()
        r = self.ped_disk.add_partition(part, constraint)
        if r:
            raise Exception, "Unable to create partition."
        if len(temp) > 0:
            for part in temp:
                self.ped_disk.delete_partition(part)
        self.reload()
        return part.num

    def delete_partition(self, i):
        partition = self["partition"]
        if i in partition.keys():
            r = self.ped_disk.delete_partition(partition[i].ped_partition)
            self.reload()
            return r
        return 0

    def delete_all_partitions(self):
        r = self.ped_disk.delete_all()
        self.reload()
        return r

    def new_disklabel(self, label):
        if not label in Disk.diskType:
            print "ERROR: Disk label '%s' is not supported." % label
            return
        self.ped_disk = self.ped_device.disk_new_fresh(Disk.diskType[label])
        self.reload()

    def set_boot(self, i):
        partition = self["partition"]
        if i in partition.keys():
            if partition[i].ped_partition.type  & parted.PARTITION_EXTENDED:
                print "WARNING: Partition %d is an extended partition," % i, \
                      "unable to set boot flag."
                return 0
            return partition[i].ped_partition.set_flag(parted.PARTITION_BOOT,
                                                       1)
        return 0

    def commit(self):
        self.ped_disk.commit()

    def print_info(self):
        if not self.has_disklabel():
            return
        print
        device = self["device"]
        if self.has_key("image"):
            device = self["image"]
        print "Disk %s: %.1f GB, %d bytes" % (device,
                                              self["length"]/(1000*1000*1000),
                                              self["length"])
        print "%d heads, %d sectors/track, %d cylinders" % (self["heads"],
                                                            self["sectors"],
                                                            self["cylinders"])
        units = self["units"]
        print "Units = cylinders of %d * %d = %d bytes" % \
              (units, self["sector_size"], (units*self["sector_size"]))

    def print_partitions(self):
        if not self.has_disklabel():
            return
        print
        l = len("Device")
        for part in self["partition"]:
            partition = self["partition"][part]
            if partition["disk"].has_key("image"):
                device = "%s%d" % (self["image"], partition["id"])
            else:
                device = partition["device"]
            if l < len(device):
                l = len(device)
        print "%*s Boot      Start         End      Blocks   Id  System" % \
              (l, "Device")
        for part in self["partition"]:
            partition = self["partition"][part]
            blocks = partition["length"] * self["sector_size"]
            block_str = "%d" % (blocks / 1024)
            if partition["disk"].has_key("image"):
                device = "%s%d" % (self["image"], partition["id"])
            else:
                device = partition["device"]
            if blocks % 1024 > 0:
                block_str += "+"
            else:
                block_str += " "
            if partition["boot"]:
                boot = "*"
            else:
                boot = " "
            type = "---"
            try:
                type = Partition.nativeType[partition["native_type"]]
            except:
                pass
            print "%*s   %s  %10d  %10d  %11s  %2x  %s" % \
                  (l, device, boot, partition["unit-start"],
                   partition["unit-end"], block_str,
                   partition["native_type"], type)

################################## functions ##################################

def mount(what, where, fstype="ext3", options=None, arguments=None):
    opts = ""
    if options:
        opts = "-o '%s'" % options
    args = ""
    if arguments:
        args = string.join(arguments)
    if fstype:
        _fstype = "-t '%s'" % fstype
    else:
        _fstype = ""
    mount = "/bin/mount %s %s %s '%s' '%s'" % (args, opts, _fstype, what,
                                               where)
    stat = os.system(mount)
    if stat != 0:
        raise IOError, "mount of '%s' on '%s' failed" % (what , where)


def umount(what):
    if not os.path.ismount(what):
        # TODO: ismount is not working for bind mounts
        stat = os.system("/bin/umount '%s' 2>/dev/null" % what)
        return stat

    i = 0
    failed = 0
    while os.path.ismount(what) and i < 100:
        if i == 1:
            # kill all processes running in dir
            print "Killing all processes running in  '%s'" % what
        if i > 0:
            (status, rusage) = functions.runScript(\
                script="/sbin/fuser -k '%s'" % what)
            if status != 0:
                print "WARNING: Failed to kill processes."
            time.sleep(1)
        stat = os.system("umount '%s' 2>/dev/null" % what)
        if stat != 0:
            failed = 1
        else:
            failed = 0
        i += 1
    if failed == 1:
        print "ERROR: Umount of '%s' failed" % what

    return failed

def swapon(device):
    swapon = "/sbin/swapon '%s'" % device
    print "Enable swap on '%s'" % device
    (status, rusage) = functions.runScript(script=swapon)
    if status != 0:
        print "ERROR: swapon failed."
        return 1
    return 0

def swapoff(device):
    swapoff = "/sbin/swapoff '%s'" % device
    print "Disable swap on '%s'" % device
    (status, rusage) = functions.runScript(script=swapoff)
    if status != 0:
        print "ERROR: swapoff failed."
        return 1
    return 0

def ext2Label(device):
    e2label = "/sbin/e2label %s 2>/dev/null" % device
    (child_stdin, child_stdout) = os.popen2(e2label)
    l = child_stdout.read()
    if l:
        l = string.strip(l)
    return l

def swapLabel(device):
    try:
        fd = open(device, "r")
    except:
        return None
    try:
        fd.seek(1052, 0) # TODO: verify, pagesize?
        l = fd.read(16)
    except:
        l = None
    fd.close()
    if not l:
        return None
    for i in xrange(len(l)):
        if i > 0 and l[i] == "\0":
            return l[:i]
    return l

def getLabel(device):
    label = ext2Label(device)
    if not label:
        label = swapLabel(device)
    return label

# vim:ts=4:sw=4:showmatch:expandtab
