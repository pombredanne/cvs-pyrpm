#
# Copyright (C) 2005 Red Hat, Inc.
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

import types, string

##############################################################################
#
# Partitions
#   partition ("swap" | (<name> --fstype:)) [<global options>] \
#                                           [<placement options>]
#
# Global options:
#   --fsoptions:
#   --label:
#   --bytes-per-inode:
#   --onbiosdisk
#
# Placement options:
#   1) --usepart: [--noformat]
#   2) [ --asprimary ] --start: --ondisk: ( --size: | --end: )
#   3) [ --asprimary ] [ --ondisk: ] --size: [ --grow [ --maxsize: ] ]
#   4) [ --asprimary ] [ --ondisk: ] --recommended
#
##############################################################################


################################### classes ###################################

class KickstartConfig(dict):
    REQUIRED_TAGS = [ "authconfig", "bootloader", "keyboard", "lang",
                      "langsupport", "rootpw", "timezone" ]
    # Currently unsupported tags:
    # driverdisk

    def __init__(self, filename):
        dict.__init__(self)
        self.parse(filename)

    def clear(self):
        for key in self.keys():
            del self[key]

    def parse(self, filename):
        self["filename"] = filename
        try:
            _fd = open(filename, "r")
        except:
            raise IOError, "Unable to open '%s'" % filename

        swap_id = 0
        in_packages = 0
        in_post = 0
        in_pre = 0
        fd = [ _fd ]
        open_files = [ filename ]
        while 1:
            line = fd[0].readline()

            if not line:
                if len(fd) > 0:
                    _fd = fd.pop(0)
                    _fd.close()
                if len(fd) == 0:
                    break

            line = line.rstrip()
            if len(line) < 1: continue
            if line[0] == '#': continue

            args = KickstartConfig.noquote_split(line)
            opt = args[0]

            if opt == "%packages":
                self.parseSimple(opt[1:], args[1:],
                                 [ "resolvedeps", "ignoredeps",
                                   "ignoremissing" ])
                in_packages = 1
                in_post = 0
                in_pre = 0
                continue
            elif opt == "%post":
                self.parseSimple(opt[1:], args[1:],
                                 [ "nochroot", "interpreter=",
                                   "erroronfail" ])
                in_packages = 0
                in_post = 1
                in_pre = 0
                continue
            elif opt == "%pre":
                self.parseSimple(opt[1:], args[1:],
                                 [ "erroronfail", "interpreter=" ])
                in_packages = 0
                in_post = 0
                in_pre = 1
                continue
            elif opt == "%include":
                if len(args) == 2:
                    try:
                        _fd = open(args[1], "r")
                    except:
                        print "Unable to open '%s', ignoring." % args[1]
                    else:
                        if args[1] in open_files:
                            raise ValueError, \
                                  "Include loop detected for '%s'" % args[1]
                        fd.insert(0, _fd)
                        open_files.append(args[1])
                else:
                    raise ValueError, "Error in line '%s'" % line
                continue

            if not in_packages and not in_post and not in_pre:
                if len(args) == 1:
                    if opt in [ "autopart", "autostep", "cmdline",
                                "halt", "install", "interactive", "poweroff",
                                "reboot", "shutdown", "skipx", "text",
                                "upgrade", "mouse", "zerombr" ]:
                        self[opt] = None
                    else:
                        print "'%s' is unsupported" % line
                    continue

                if opt in [ "keyboard", "lang", "zerombr" ]:
                    if len(args) > 2:
                        raise ValueError, "Error in line '%s'" % line
                    self[opt] = args[1]
                    continue

                if opt == "auth" or opt == "authconfig":
                    self.parseSimple("authconfig", args[1:],
                                     [ "enablemd5", "enablenis", "nisdomain=",
                                       "nisserver=", "useshadow",
                                       "enableshadow", "enableldap",
                                       "enableldapauth", "ldapserver=",
                                       "ldapbasedn=", "enableldaptls",
                                       "enablekrb5", "krb5realm=", "krb5kdc=",
                                       "disablekrb5kdcdns",
                                       "disablekrb5realmdns",
                                       "krb5adminserver=", "enablehesiod",
                                       "hesiodlhs=", "hesiodrhs=",
                                       "enablesmbauth", "smbservers=",
                                       "smbworkgroup=", "enablecache" ],
                                     { "useshadow": "enableshadow" })
                elif opt == "bootloader":
                    self.parseSimple(opt, args[1:],
                                     [ "append:", "driveorder:", "location:",
                                       "password:", "md5pass:", "lba32",
                                       "upgrade" ])
                    if self["bootloader"].has_key("driveorder"):
                        order = self["bootloader"]["driveorder"].split(",")
                        self["bootloader"]["driveorder"] = order
                elif opt == "cdrom":
                    self.parseSimple(opt, args[1:], [ "exclude:" ])
                    if self[opt].has_key("exclude"):
                        self[opt]["exclude"] = string.split( \
                            self[opt]["exclude"], ",")
                elif opt == "clearpart":
                    self.parseSimple(opt, args[1:],
                                     [ "all", "drives:", "initlabel", "linux",
                                       "none" ])
                    if self["clearpart"].has_key("drives"):
                        order = self["bootloader"]["drives"].split(",")
                        self["bootloader"]["drives"] = order
                elif opt == "device":
                    (_dict, _args) = self.parseArgs(opt, args[1:], [ "opts:" ])
                    if len(_args) != 2:
                        raise ValueError, "'%s' is unsupported" % line
                    if not self.has_key(opt):
                        self[opt] = { }
                    if not self[opt].has_key(_args[0]):
                        self[opt][_args[0]] = { }
                    self[opt][_args[0]][_args[1]] = _dict
                # TODO: driverdisk
                elif opt == "firewall":
                    # firewall is special, so we have to do it by hand
                    if self.has_key(opt):
                        raise ValueError, "%s already set." % opt

                    (_opts, _args) = KickstartConfig.getopt(args[1:], "",
                                            [ "enabled", "enable",
                                              "disabled", "disable", "trust:",
                                              "ssh", "telnet", "smtp",
                                              "http", "ftp", "port:" ])
                    replace_tags = { "enable": "enabled",
                                     "disable": "disabled" }
                    self[opt] = { }
                    for (_opt, _val) in _opts:
                        if replace_tags and replace_tags.has_key(_opt):
                            _opt = replace_tags[_opt]
                        if _opt == "--enabled" or _opt == "--enable":
                            self[opt]["enabled"] = None
                        elif _opt == "--disabled" or _opt == "--disable":
                            self[opt]["disabled"] = None
                        elif _opt == "--trust" and _val:
                            if not self[opt].has_key("trust"):
                               self[opt]["trusted"] = [ ]
                            self[opt]["trusted"].append(_val)
                        elif _opt in [ "--ssh", "--telnet", "--smtp", "--http",
                                       "--ftp" ]:
                            if not self[opt].has_key("ports"):
                                self[opt]["ports"] = [ ]
                            if _opt == "--ftp":
                                self[opt]["ports"].append([21,"tcp"])
                            elif _opt == "--ssh":
                                self[opt]["ports"].append([22,"tcp"])
                            elif _opt == "--telnet":
                                self[opt]["ports"].append([23,"tcp"])
                            elif _opt == "--smtp":
                                self[opt]["ports"].append([25,"tcp"])
                            elif _opt == "--http":
                                self[opt]["ports"].append([80,"tcp"])
                        elif _opt == "--port":
                            _vals = KickstartConfig.noquote_split(_val, ",")
                            for v in _vals:
                                if not self[opt].has_key("ports"):
                                    self[opt]["ports"] = [ ]
                                a = v.split(":")
                                if len(a) != 2:
                                    raise ValueError, \
                                          "ERROR: port '%s' invalid" % v
                                self[opt]["ports"].append(a)
                        else:
                            print "'%s': option '%s' not recognized" % (line,
                                                                        _opt)
                    for arg in _args:
                        self[opt].setdefault("devices", [ ]).append(arg)
                elif opt == "firstboot":
                    self.parseSimple(opt, args[1:],
                                     [ "enable", "enabled", "disable",
                                       "disabled", "reconfig" ],
                                     { "enable": "enabled",
                                       "disable": "disabled" })
                elif opt == "harddrive":
                    self.parseSimple(opt, args[1:],
                                     [ "partition:", "dir:" ])
                    if not self[opt].has_key("partition") or \
                       not self[opt].has_key("dir"):
                        raise ValueError, "Error in line '%s'" % line
                elif opt == "langsupport":
                    (_dict, _args) = self.parseArgs(opt, args[1:],
                                                    [ "default:" ])
                    self[opt] = _dict
                    if len(args) > 0:
                        self[opt]["supported"] = _args
                    if len(self[opt]) == 0:
                        raise ValueError, "Error in line '%s'" % line
                elif opt == "logvol":
                    if args[1] == "swap":
                        args[1] = "swap.%d" % swap_id
                        swap_id += 1
                    dict = self.parseSub(opt, args[1:],
                                         [ "vgname:", "size:", "name:",
                                           "noformat", "useexisting",
                                           "fstype:", "fsoptions:",
                                           "bytes-per-inode:", "grow",
                                           "maxsize:", "recommended",
                                           "percent" ])
                    self.convertLong(dict, "bytes-per-inode")
                    self.convertDouble(dict, "percent")
                elif opt == "network":
                    dict = self.parseMultiple(opt, args[1:],
                                              [ "bootproto:", "device:", "ip:",
                                                "gateway:", "nameserver:",
                                                "nodns", "netmask:",
                                                "hostname:", "ethtool:",
                                                "essid:", "wepkey:", "onboot:",
                                                "class:" ])
                    if dict.has_key("nameserver"):
                        splits = string.split(dict["nameserver"], ",")
                        dict["nameserver"] = [ ]
                        for split in splits:
                            dict["nameserver"].append(string.strip(split))
                elif opt == "nfs":
                    self.parseSimple(opt, args[1:],
                                     [ "server:", "dir:", "exclude:" ])
                    if not self[opt].has_key("server") or \
                       not self[opt].has_key("dir"):
                        raise ValueError, "Error in line '%s'" % line
                    if self[opt].has_key("exclude"):
                        self[opt]["exclude"] = string.split( \
                            self[opt]["exclude"], ",")
                elif opt == "part" or opt == "partition":
                    if args[1] == "swap":
                        args[1] = "swap.%d" % swap_id
                        swap_id += 1
                    dict = self.parseSub("partition", args[1:],
                                         [ "size:", "grow", "maxsize:",
                                           "noformat", "onpart:", "usepart:",
                                           "ondisk:", "ondrive:", "asprimary",
                                           "fstype:", "fsoptions:", "label:",
                                           "start:", "end:",
                                           "bytes-per-inode:", "recommended",
                                           "onbiosdisk" ],
                                         { "usepart": "onpart",
                                           "ondrive": "ondisk" })
                    self.convertLong(dict, "size")
                    self.convertLong(dict, "maxsize")
                    self.convertLong(dict, "start")
                    self.convertLong(dict, "end")
                    self.convertLong(dict, "bytes-per-inode")
                elif opt == "raid":
                    (_dict, _args) = self.parseArgs(opt, args[1:],
                                                    [ "level:", "device:",
                                                      "spares:", "fstype:",
                                                      "fsoptions:", "noformat",
                                                      "useexisting" ])

                    if len(_args) < 2:
                        raise ValueError, "'%s' is unsupported" % line
                    if not self.has_key(opt):
                        self[opt] = { }
                    if self[opt].has_key(_args[0]):
                        raise ValueError, "raid '%s' is not unique.", _args[0]
                    if _dict.has_key("level") and \
                           _dict["level"].lower()[:4] == "raid":
                        _dict["level"] = _dict["level"][4:]
                    self.convertLong(_dict, "level")
                    self.convertLong(_dict, "spares")
                    _dict["partitions"] = _args[1:]
                    self[opt][_args[0]] = _dict
                elif opt == "repo":
                    (_dict, _args) = self.parseArgs(opt, args[1:],
                                                    [ "name:", "baseurl:",
                                                      "mirrorlist:",
                                                      "exclude:" ])
                    if not _dict.has_key("name"):
                        raise ValueError, "repo name not specified in '%s'" % \
                              line
                    if not self.has_key(opt):
                        self[opt] = {}
                    if self.has_key(opt) and _dict["name"] in self[opt]:
                        raise ValueError, "repo name '%s' is not unique." % \
                              _dict["name"]

                    if _dict.has_key("exclude"):
                        _dict["exclude"] = string.split(_dict["exclude"], ",")
                    self[opt][_dict["name"]] = _dict
                    del _dict["name"]
                elif opt == "rootpw":
                    self.parseSub(opt, args[1:], [ "iscrypted" ])
                elif opt == "selinux":
                    self.parseSimple(opt, args[1:],
                                     [ "enforcing", "permissive", "disabled" ])
                elif opt == "timezone":
                    self.parseSub(opt, args[1:], [ "utc" ])
                elif opt == "url":
                    self.parseSimple(opt, args[1:], [ "url:", "exclude:" ])
                    if not self[opt].has_key("url"):
                        raise ValueError, "Error in line '%s'" % line
                    if self[opt].has_key("exclude"):
                        self[opt]["exclude"] = self[opt]["exclude"].split(",")
                elif opt == "xconfig":
                    self.parseSimple("xconfig", args[1:],
                                     [ "noprobe", "card:", "videoram:",
                                       "monitor:", "hsync:", "vsync:",
                                       "defaultdesktop:", "startxonboot",
                                       "resolution:", "depth:", "driver:" ],
                                     { "startX": "startxonboot",
                                       "videoRam": "videoram" })
                elif opt == "volgroup":
                    (_dict, _args) = self.parseArgs(opt, args[1:],
                                                    [ "noformat",
                                                      "useexisting",
                                                      "pesize:" ])
                    if len(_args) < 2:
                        raise ValueError, "'%s' is unsupported" % line
                    _dict["partitions"] = _args[1:]
                    if not self.has_key(opt):
                        self[opt] = { }
                    if not self[opt].has_key(_args[0]):
                        self[opt][_args[0]] = { }
                    self[opt][_args[0]] = _dict
                else:
                    print "'%s' is unsupported" % line
            elif in_packages:
                if len(args) == 1:
                    # there was no space as delimiter
                    args = [ line[:1], line[1:] ]
                    opt = line

                if not self.has_key("packages"):
                    self["packages"] = { }
                if opt[0] == "@":
                    if not self["packages"].has_key("groups"):
                        self["packages"]["groups"] = [ ]
                    if not args[1] in self["packages"]["groups"]:
                        self["packages"]["groups"].append(args[1])
                elif opt[0] == "-":
                    if not self["packages"].has_key("drop"):
                        self["packages"]["drop"] = [ ]
                    if not line in self["packages"]["drop"]:
                        self["packages"]["drop"].append(args[1])
                else:
                    if not self["packages"].has_key("add"):
                        self["packages"]["add"] = [ ]
                    if not line in self["packages"]["add"]:
                        self["packages"]["add"].append(opt)
            elif in_post:
                if not self["post"].has_key("script"):
                    self["post"]["script"] = ""
                self["post"]["script"] += line+"\n"
            elif in_pre:
                if not self["pre"].has_key("script"):
                    self["pre"]["script"] = ""
                self["pre"]["script"] += line+"\n"

        self.verify()


    def verify(self):
        for tag in self.REQUIRED_TAGS:
            if not self.has_key(tag):
                raise ValueError, "ERROR: %s is required." % tag

        if not self.has_key("install") and not self.has_key("upgrade"):
            raise ValueError, "ERROR: No operation defined"

        if self.has_key("install") and not self.has_key("partition") and \
               not self.has_key("autopart"):
            raise ValueError, \
                  "ERROR: Partition has to be set for an installation."

        if self["authconfig"].has_key("enablenis"):
            if not self["authconfig"].has_key("nisdomain"):
                raise ValueError, "nisdomain not set"
            if not self["authconfig"].has_key("nisserver"):
                raise ValueError, "nisserver not set"
        if self["authconfig"].has_key("enableldap"):
            if not self["authconfig"].has_key("ldapserver"):
                raise ValueError, "ldapserver not set"
            if not self["authconfig"].has_key("ldapbasedn"):
                raise ValueError, "ldapbasedn not set"
        if self["authconfig"].has_key("enablekrb5"):
            if not self["authconfig"].has_key("krb5realm"):
                raise ValueError, "krb5realm not set"
            if not self["authconfig"].has_key("krb5kdc"):
                raise ValueError, "krb5kdc not set"
            if not self["authconfig"].has_key("krb5adminserver"):
                raise ValueError, "krb5adminserver not set"
        if self["authconfig"].has_key("enablehesiod"):
            if not self["authconfig"].has_key("hesiodlhs"):
                raise ValueError, "hesiodlhs not set"
            if not self["authconfig"].has_key("hesiodrhs"):
                raise ValueError, "hesiodrhs not set"
        if self["authconfig"].has_key("enablesmbauth"):
            if not self["authconfig"].has_key("smbservers"):
                raise ValueError, "smbservers not set"
            if not self["authconfig"].has_key("smbworkgroup"):
                raise ValueError, "smbworkgroup not set"

        if self["bootloader"].has_key("password") and \
               self["bootloader"].has_key("md5pass"):
            raise ValueError, "bootloader: password and md5pass set"
        if self["bootloader"].has_key("location") and \
               self["bootloader"]["location"] not in [ "mbr", "partition",
                                                       "none" ]:
            raise ValueError, "bootloader: location invalid."

        if self.has_key("clearpart"):
            if self["clearpart"].has_key("none") and \
                   len(self["clearpart"]) != 1:
                raise ValueError, "clearpart: none mixed with other tags."

        if self.has_key("device"):
            for key in self["device"].keys():
                if key not in [ "scsi", "eth" ]:
                    raise ValueError, "device: type %s not valid." % key

        if self.has_key("firstboot") and \
               self["firstboot"].has_key("enabled") and \
               self["firstboot"].has_key("disabled"):
            raise ValueError, "firstboot: enabled and disabled."

        if not self.has_key("cdrom") and not self.has_key("harddrive") and \
               not self.has_key("nfs") and not self.has_key("url"):
            raise ValueError, "No installation method specified."

        source = 0
        if self.has_key("cdrom"):
            source += 1
        if self.has_key("harddrive"):
            source += 1
        if self.has_key("nfs"):
            source += 1
        if self.has_key("url"):
            source += 1
        if source != 1:
            raise ValueError, "Multiple installation sources defined."

        if self.has_key("harddrive"):
            if not self["harddrive"].has_key("partition"):
                raise ValueError, "Harddrive: partition not set."
            if not self["harddrive"].has_key("dir"):
                raise ValueError, "Harddrive: dir not set."

        if self.has_key("nfs"):
            if not self["nfs"].has_key("server"):
                raise ValueError, "nfs: server not set."
            if not self["nfs"].has_key("dir"):
                raise ValueError, "nfs: dir not set."

        partitions = [ ]
        disk = { }
        if self.has_key("partition"):
            for name in self["partition"]:
                part = self["partition"][name]
                if name[:5] != "swap." and name[:5] != "raid." and \
                       name[:3] != "pv." and not part.has_key("fstype"):
                    raise ValueError, \
                          "Partition '%s' has no filesystem type." % name
                if part.has_key("fstype") and \
                       part["fstype"] not in [ "ext2", "ext3", "xfs", "jfs",
                                               "reiserfs" ]:
                    raise ValueError, \
                          "'%s': Filesystem type '%s' is not supported" % \
                          (name, part["fstype"])
                if part.has_key("onpart"):
                    if part["onpart"] in partitions:
                        raise ValueError, \
                              "Partition '%s' used multiple times" % \
                              part["onpart"]
                    partitions.append(part["onpart"])
                if part.has_key("grow") and not part.has_key("size"):
                    raise ValueError, \
                          "Growing partition '" + part["onpart"] + \
                          "' has no size."
                if part.has_key("maxsize") and not part.has_key("grow"):
                    raise ValueError, \
                          "Maxsize given for partition '" + part["onpart"] + \
                          "', but it is no growing partition."
                if part.has_key("start"):
                    if not part.has_key("end") and \
                           not part.has_key("size"):
                        raise ValueError, \
                              "Partition '" + part["onpart"] + \
                              "' has set start, but no end or size."
                    if not part.has_key("ondisk"):
                        raise ValueError, \
                              "Partition '" + part["onpart"] + \
                              "' has set start, but no disk."
                elif part.has_key("onpart"):
                    pass
                elif not part.has_key("recommended") and \
                         not part.has_key("size"):
                    raise ValueError, \
                          "Partition '" + part["onpart"] + "' has no size."
                ondisk = "default"
                if part.has_key("ondisk"):
                    ondisk = part["ondisk"]
                if not disk.has_key(ondisk):
                    disk[ondisk] = { }
                if part.has_key("grow"):
                    if disk[ondisk].has_key("grow"):
                        raise ValueError, \
                              "More than one grow partition on '%s' disk" % \
                              ondisk
                    disk[ondisk]["grow"] = name
            del partitions
            del disk
            if "/boot" in self["partition"] and \
                   self["partition"]["/boot"]["fstype"] not in \
                   [ "ext", "ext3" ]:
                raise ValueError, \
                      "Filesystem of '/boot' has to be ext2 or ext3."
            elif "/" in self["partition"] and \
                     self["partition"]["/"]["fstype"] not in [ "ext", "ext3" ]:
                raise ValueError, \
                      "Filesystem of '/' has to be ext2 or ext3 if there is " \
                      "no /boot partition with ext2 or ext3 filesystem."

        if self.has_key("raid"):
            partitions = [ ]
            devices = [ ]
            for name in self["raid"]:
                part = self["raid"][name]
                if not part.has_key("device"):
                    raise ValueError, "raid '%s': No device is specified." % \
                          part
                if not part["device"] in [ "md0", "md1", "md2", "md3",
                                           "md4", "md5", "md6", "md7" ]:
                    raise ValueError, "raid '%s': Illegal device %s." % \
                          (name, part["device"])
                if part["device"] in devices:
                    raise ValueError, "raid '%s': Device %s is not unique" % \
                          (name, part["device"])
                devices.append(part["device"])
                if not part.has_key("level"):
                    raise ValueError, "raid '%s': No level is specified." % \
                          part
                if not part["level"] in [ 0, 1, 5 ]:
                    raise ValueError, "raid '%s': Level %d is unsupported." % \
                          (part, part["level"])
                if not part.has_key("partitions"):
                    raise ValueError, "raid '%s': No partitions given." % part
                for p in part["partitions"]:
                    if p[:5] != "raid.":
                        raise ValueError, \
                              "'%s' is no valid raid partition." % p
                    if p in partitions:
                        raise ValueError, \
                              "Partition '%s' used more than once." % p
                    partitions.append(p)
                if part.has_key("fstype") and \
                       part["fstype"] not in [ "ext2", "ext3", "xfs", "jfs",
                                               "reiserfs", "swap" ]:
                    raise ValueError, \
                          "raid '%s': Filesystem type '%s' is not supported." % \
                          (name, part["fstype"])
            del partitions
            del devices
            if "/boot" in self["raid"]:
                if self["raid"]["/boot"]["level"] != 1:
                    raise ValueError, "Raid level of '/boot' has to be 1."
                if self["raid"]["/boot"].has_key("fstype") and \
                       self["raid"]["/boot"]["fstype"] not in [ "ext2",
                                                                "ext3" ]:
                    raise ValueError, "Filesystem of '/boot' has to be " \
                          "ext2 or ext3."
            if "/" in self["raid"] and self["raid"]["/"]["level"] != 1 and \
                   not "/boot" in self["raid"]:
                raise ValueError, "Raid level of '/' has to be 1 " \
                      "if there is no '/boot' partition."

        if self.has_key("volgroup"):
            for group in self["volgroup"]:
                for name in self["volgroup"][group]["partitions"]:
                    if name[:3] != "pv.":
                        raise ValueError, \
                              "volgroup '%s': Illegal partition name '%s'." % \
                              (group, name)
                    if not name in self["partition"]:
                        raise ValueError, \
                              "volgroup '%s': Partition '%s'" %(group, name) +\
                              " is not defined."

        if self.has_key("logvol"):
            if not self["volgroup"]:
                raise ValueError, "No volgroups defined."

            names = [ ]
            for mntpoint in self["logvol"]:
                if not self["logvol"][mntpoint].has_key("vgname"):
                    raise ValueError, "logvol '%s' has no vgname." % mntpoint
                if not self["logvol"][mntpoint].has_key("size"):
                    raise ValueError, "logvol '%s' has no size." % mntpoint
                if not self["logvol"][mntpoint].has_key("name"):
                    raise ValueError, "logvol '%s' has no name." % mntpoint
                if not self["logvol"][mntpoint]["vgname"] \
                       in self["volgroup"].keys():
                    raise ValueError, \
                          "logvol '%s': volgroup '%s' is not defined." % \
                          (mntpoint, self["logvol"][mntpoint]["vgname"])
                if self["logvol"][mntpoint]["name"] in names:
                    raise ValueError, "Name of logvol '%s' is not unique." % \
                          mntpoint
                names.append(self["logvol"][mntpoint]["name"])

        if self.has_key("repo"):
            for name in self["repo"]:
                repo = self["repo"][name]
                if not repo.has_key("baseurl") and \
                       not repo.has_key("mirrorlist"):
                    raise ValueError, "No source specified for repo '%s'." % \
                          repo
                if repo.has_key("baseurl") and repo.has_key("mirrorlist"):
                    raise ValueError, \
                          "Baseurl and mirrorlist specified for repo '%s'." % \
                          repo

        if self.has_key("url"):
            if not self["url"].has_key("url"):
                raise ValueError, "url not set for url."

    def parseArgs(self, tag, argv, allowed_args, replace_tags=None):
        dict = { }
        (opts, args) = KickstartConfig.getopt(argv, "", allowed_args)

        for (opt, val) in opts:
            if replace_tags and replace_tags.has_key(opt[2:]):
                opt = "--"+replace_tags[opt[2:]]
            if val:
                if opt[-1] == "=":
                    o = opt[2:-1]
                else:
                    o = opt[2:]
                dict[o] = self.stripQuotes(val)
            else:
                dict[opt[2:]] = None

        return (dict, args)

    def parseSimple(self, tag, argv, allowed_args, replace_tags=None):
        if self.has_key(tag):
            raise ValueError, "%s already set." % tag

        (dict, args) = self.parseArgs(tag, argv, allowed_args, replace_tags)

        if len(args) != 0:
            raise ValueError, "'%s %s' is unsupported" % (tag, " ".join(argv))
        self[tag] = dict

    def parseMultiple(self, tag, argv, allowed_args, replace_tags=None):
        (dict, args) = self.parseArgs(tag, argv, allowed_args, replace_tags)

        if len(args) != 0:
            raise ValueError, "'%s %s' is unsupported" % (tag, " ".join(argv))
        self.setdefault(tag, [ ]).append(dict)
        return dict

    def parseSub(self, tag, argv, allowed_args, replace_tags=None):
        (dict, args) = self.parseArgs(tag, argv, allowed_args, replace_tags)

        if len(args) != 1:
            raise ValueError, "'%s %s' is unsupported" % (tag, " ".join(argv))
        if not self.has_key(tag):
            self[tag] = { }
        elif self[tag].has_key(args[0]):
            raise ValueError, "%s already set." % tag

        self[tag][args[0]] = dict
        return dict

    def stripQuotes(self, var):
        if var and len(var) > 2:
            if (var[0] == '"' and var[-1] == '"') or \
                   (var[0] == "'" and var[-1] == "'"):
                var = var[1:-1]
        return var

    def convertLong(self, dict, key):
        if not dict.has_key(key):
            return
        try:
            dict[key] = long(dict[key])
        except Exception, msg:
            print "'%s'=%s is no valid long value." % (key, dict[key])

    def convertDouble(self, dict, key):
        if not dict.has_key(key):
            return
        try:
            dict[key] = double(dict[key])
        except Exception, msg:
            print "'%s'=%s is no valid double value." % (key, dict[key])

    ############################ static functions ############################

    # To combine option and value in longopts:
    #   "opt=" for --opt=val
    #   "opt:" for --opt val or --opt=val
    def getopt(args, shortopts, longopts=[ ]):
        _shortopts = { }
        _longopts = { }
        _opts = [ ]
        _args = args[:]

        for i in xrange(len(shortopts)):
            opt = shortopts[i]
            if i < len(shortopts) - 1 and shortopts[i+1] == ":":
                _shortopts[opt] = ":"
                i += 1
            else:
                _shortopts[opt] = None

        for opt in longopts:
            if len(opt) < 1:
                raise ValueError, "Invalid options"
            if opt[-1] == "=" or opt[-1] == ":":
                _longopts[opt[0:-1]] = opt[-1]
            else:
                _longopts[opt] = None

        idx = 0
        while len(_args) > idx:
            arg = _args[idx]

            if arg[0:2] == "--": # longopts
                a = arg[2:]
                if a in _longopts:
                    if not _longopts[a]:
                        _opts.append((arg, None))
                        _args.pop(idx)
                        continue
                    elif _longopts[a] == ":":
                        if len(args) > 1:
                            _args.pop(idx)
                            val = _args.pop(idx)
                            _opts.append((arg, val))
                            continue
                        else:
                            raise ValueError, "Missing value for '%s'" % arg

                i = arg.find("=")
                if i > 0: # found '='
                    a = arg[2:i]
                    if a in _longopts and \
                           (_longopts[a] == "=" or _longopts[a] == ":"):
                        _opts.append((arg[:i], arg[i+1:]))
                        _args.pop(idx)
                        continue

                raise ValueError, "Invalid option '%s'" % arg
            elif arg[0] == "-": # shortopts
                a = arg[1:]
                for c in a:
                    if c in _shortopts:
                        if not _shortopts[c]:
                            _opts.append(("-"+c, None))
                        elif _shortopts[c] == ":":
                            if len(a) > 1:
                                raise ValueError, "Invalid option '%s'" % arg
                            _args.pop(idx)
                            val = _args.pop(idx)
                            _opts.append((arg, val))
                        else:
                            raise ValueError, "Invalid option '%s'" % arg
                        _args.pop(idx)
                    else:
                        raise ValueError, "Invalid option '%s'" % arg

            else: # do not stop on no-opt, continue
                idx += 1

        return (_opts,_args)

    # make getopt a static class method
    getopt = staticmethod(getopt)

    def noquote_split(s, delimiter=None):
        delimiters = [ " ", "\t", "\r", "\n", "\f", "\v" ]
        tokens = [ ]
        single_quote = 0
        double_quote = 0
        if delimiter:
            if isinstance(delimiter, types.ListType):
                delimiters = delimiter
            else:
                delimiters = [ delimiter ]
        for i in xrange(len(delimiters)):
            if not isinstance(delimiters[i], types.StringType):
                raise ValueError, "delimiter is not of type string"
            if len(delimiters[i]) == 0:
                delimiters.pop(i)

        b = 0
        quote = [ ]
        i = 0
        while i < len(s):
            c = ""
            while i < len(s) and s[i] == "\\":
                c += s[i]
                i += 1
            if i == len(s):
                break
            c += s[i]
            if quote and c == quote[len(quote)-1]:
                quote.pop(len(quote)-1)
            else:
                if c == "'" or c == "\"":
                    quote.append(c)
            if len(quote) == 0:
                for delim in delimiters:
                    l = len(delim)
                    if s[i:i+l] == delim:
                        if i > 0 and len(s[b:i]) > 0:
                            tokens.append(s[b:i])
                        b = i + l
                        break
            i += 1
        if len(s[b:]) > 0:
            tokens.append(s[b:])

        return tokens

    # make noquote_split a static class method
    noquote_split = staticmethod(noquote_split)

# vim:ts=4:sw=4:showmatch:expandtab
