#!/usr/bin/python
#
# (c) 2005 Red Hat, Inc.
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
# Copyright 2004, 2005 Red Hat, Inc.
#
# AUTHOR: Thomas Woerner <twoerner@redhat.com>
#

import types

################################### classes ###################################

class KickstartConfig(dict):
    REQUIRED_TAGS = [ "authconfig", "bootloader", "keyboard", "lang",
                      "langsupport", "rootpw", "timezone" ]
    # Currently unsupported tags:
    # driverdisk, logvol, raid, xconfig, volgroup


    def __init__(self, filename):
        dict.__init__(self)
        self.parse(filename)

    def __getitem__(self, item):
        if not self.has_key(item):
            return None
        return dict.__getitem__(self, item)

    def clear(self):
        for key in self.keys():
            del self[key]

    def parse(self, filename):
        self["filename"] = filename
        try:
            _fd = open(filename, "r")
        except:
            raise IOError, "Unable to open '%s'" % filename

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

            args = noquote_split(line)
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
                    if opt in [ "autopart", "autostep", "cdrom", "cmdline",
                                "install", "interactive", "reboot", "skipx",
                                "text", "upgrade", "mouse" ]:
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
                                       "enablekrb5", "krb5realm=",
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
                    if not self[opt]:
                        self[opt] = { }
                    if not self[opt].has_key(_args[0]):
                        self[opt][_args[0]] = { }
                    self[opt][_args[0]][_args[1]] = _dict
                # TODO: driverdisk
                elif opt == "firewall":
                    # firewall is special, so we have to do it by hand
                    if self[opt]:
                        raise ValueError, "%s already set." % opt

                    (_opts, _args) = getopt(args[1:], "",
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
                            _vals = noquote_split(_val, ",")
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
                        if not self[opt].has_key("devices"):
                            self[opt]["devices"] = [ ]
                        self[opt]["devices"].append(arg)
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
                # TODO: logvol
                elif opt == "network":
                    self.parseSimple(opt, args[1:],
                                     [ "bootproto:", "device:", "ip:",
                                       "gateway:", "nameserver:", "nodns",
                                       "netmask:", "hostname:", "ethtool:",
                                       "essid:", "wepkey:", "onboot:",
                                       "class:" ])
                elif opt == "nfs":
                    self.parseSimple(opt, args[1:],
                                     [ "server:", "dir:" ])
                    if not self[opt].has_key("server") or \
                       not self[opt].has_key("dir"):
                        raise ValueError, "Error in line '%s'" % line
                elif opt == "part" or opt == "partition":
                    self.parseSub("partition", args[1:],
                                  [ "size:", "grow", "maxsize:", "noformat",
                                    "onpart:", "usepart:", "ondisk:",
                                    "ondrive:", "asprimary", "fstype:",
                                    "fsoptions:", "label:", "start:", "end:",
                                    "bytes-per-inode:", "recommended",
                                    "onbiosdisk" ],
                                  { "usepart": "onpart", "ondrive": "ondisk" })
                # TODO: raid
                elif opt == "rootpw":
                    self.parseSub(opt, args[1:], [ "iscrypted" ])
                elif opt == "selinux":
                    self.parseSimple(opt, args[1:],
                                     [ "enforcing", "permissive", "disabled" ])
                elif opt == "timezone":
                    self.parseSub(opt, args[1:], [ "utc" ])
                elif opt == "url":
                    self.parseSimple(opt, args[1:], [ "url:" ])
                    if not self[opt].has_key("url"):
                        raise ValueError, "Error in line '%s'" % line
                elif opt == "xconfig":
                    self.parseSimple("xconfig", args[1:],
                                     [ "noprobe", "card:", "videoram:",
                                       "monitor:", "hsync:", "vsync:",
                                       "defaultdesktop:", "startxonboot",
                                       "resolution:", "depth:" ])
                # TODO: volgroup
                else:
                    print "'%s' is unsupported" % line
            elif in_packages:
                if len(args) == 1:
                    # there was no space as delimiter
                    args = [ line[:1], line[1:] ]
                    opt = line

                if not self["packages"]:
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
            if not self[tag]:
                raise ValueError, "ERROR: %s is required." % tag

        if not self.has_key("install") and self.has_key("update"):
            raise ValueError, "ERROR: No operation defined"

        if self.has_key("install") and not self.has_key("partition"):
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

        if self["clearpart"]:
            if self["clearpart"].has_key("none") and \
                   len(self["clearpart"]) != 1:
                raise ValueError, "clearpart: none mixed with other tags."

        if self["device"] and self["device"].keys() not in [ "scsi", "eth" ]:
            raise ValueError, "device: type not valid."

        if self["firstboot"] and self["firstboot"].has_key("enabled") and \
               self["firstboot"].has_key("disabled"):
            raise ValueError, "firstboot: enabled and disabled."

        if not self["cdrom"] and not self["harddrive"] and \
               not self["nfs"] and not self["url"]:
            raise ValueError, "No installation method specified."

        if self["harddrive"]:
            if not self["harddrive"].has_key("partition"):
                raise ValueError, "harddrive: partition not set."
            if not self["harddrive"].has_key("dir"):
                raise ValueError, "harddrive: dir not set."

        if self["nfs"]:
            if not self["nfs"].has_key("server"):
                raise ValueError, "nfs: server not set."
            if not self["nfs"].has_key("dir"):
                raise ValueError, "nfs: dir not set."

        partitions = [ ]
        disk = { }
        for name in self["partition"]:
            part = self["partition"][name]
            if part.has_key("fstype") and \
                   part["fstype"] not in [ "ext2", "ext3" ]:
                raise ValueError, \
                      "'%s': Filesystem type '%s' is not supported" % \
                      (name, part["fstype"])
            if part.has_key("onpart"):
                if part["onpart"] in partitions:
                    raise ValueError, "Partition '%s' used multiple times" % \
                          part["onpart"]
                partitions.append(part["onpart"])
            ondisk = "default"
            if part.has_key("ondisk"):
                ondisk = part["ondisk"]
            if not disk.has_key(ondisk):
                disk[ondisk] = { }
            if part.has_key("grow"):
                if disk[ondisk].has_key("grow"):
                    raise ValueError, \
                          "More than one grow partition on '%s'" % \
                          disk[ondisk]
                disk[ondisk]["grow"] = name
        del partitions
        del disk

        if self["url"]:
            if not self["url"].has_key("url"):
                raise ValueError, "url not set."

    def parseArgs(self, tag, argv, allowed_args, replace_tags=None):
        dict = { }
        (opts, args) = getopt(argv, "", allowed_args)

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
        if self[tag]:
            raise ValueError, "%s already set." % tag

        (dict, args) = self.parseArgs(tag, argv, allowed_args, replace_tags)

        if len(args) != 0:
            raise ValueError, "'%s %s' is unsupported" % (tag, "".join(argv))
        self[tag] = dict

    def parseSub(self, tag, argv, allowed_args, replace_tags=None):
        (dict, args) = self.parseArgs(tag, argv, allowed_args, replace_tags)

        if len(args) != 1:
            raise ValueError, "'%s %s' is unsupported" % (tag, "".join(argv))
        if not self[tag]:
            self[tag] = { }
        elif self[tag].has_key(args[0]):
                raise ValueError, "%s already set." % tag

        self[tag][args[0]] = dict

    def stripQuotes(self, var):
        if var and len(var) > 2:
            if (var[0] == '"' and var[-1] == '"') or \
                   (var[0] == "'" and var[-1] == "'"):
                var = var[1:-1]
        return var

################################## functions ##################################

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

    b = 0;
    for i in xrange(len(s)):
        if s[i] == "'":
            if single_quote == 0 or double_quote > 0:
                single_quote += 1
            else:
                single_quote -= 1
        if s[i] =="\"":
            if double_quote == 0 or single_quote > 0:
                double_quote += 1
            else:
                double_quote -= 1
        if single_quote == 0 and double_quote == 0:
            for delim in delimiters:
                l = len(delim)
                if s[i:i+l] == delim:
                    if i > 0 and len(s[b:i]) > 0:
                        tokens.append(s[b:i])
                    b = i + l
                    break
    if len(s[b:]) > 0:
        tokens.append(s[b:])

    return tokens
