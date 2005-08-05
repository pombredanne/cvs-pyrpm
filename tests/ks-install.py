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

import os, sys, md5, stat, tempfile, string, time, stat, getopt
import rhpl.diskutil as diskutil
import pyrpm


PYRPMDIR = ".."
if not PYRPMDIR in sys.path:
    sys.path.append(PYRPMDIR)

################################### classes ###################################

class KickstartConfig(dict):
    def __init__(self, filename):
        dict.__init__(self)
        self.parse(filename)

    def __getitem__(self, item):
        if not self.has_key(item):
            return None
        return dict.__getitem__(self, item)

    def parse(self, filename):
        self["filename"] = filename
        fd = open(filename, "r")

        in_packages = 0
        in_post = 0
        while 1:
            line = fd.readline()
            
            if not line: break
            
            if line[-1:] == "\n":
                line = line[:-1]
            if len(line) < 1: continue
            if line[0] == '#': continue

            line = string.rstrip(line)

            if line == "%packages":
                in_packages = 1
                continue
            if line[0:4] == "%post": # --nochroot --interpreter=<>
                in_packages = 0
                in_post = 1
                if not self["post"]:
                    self["post"] = { }
                self["post"]["script"] = ""
                self["post"]["nochroot"] = 0
                self["post"]["interpreter"] = "/bin/sh"

                (opts, args) = getopt(string.split(line[4:0]), "",
                                      ["nochroot", "interpreter="])
                for (opt, val) in opts:
                    if opt == "--nochroot":
                        self["post"]["nochroot"] = 1
                    elif opt == "--interpreter":
                        self["post"]["interpreter"] = val
                    else:
                        raise ValueError, "'%s' is unsupported" % line
                if len(args) > 0:
                    raise ValueError, "'%s' is unsupported" % line

                continue

            if not in_packages and not in_post:
                if line == "install":
                    self["operation"] = line
                elif line[0:3] == "nfs":
                    nfs = { }
                    (opts, args) = getopt(string.split(line[3:]), "",
                                          ["server=", "dir="])
                    for (opt, val) in opts:
                        if opt == "--server":
                            nfs["server"] = val
                        elif opt == "--dir":
                            nfs["dir"] = val
                        else:
                            raise ValueError, "'%s' is unsupported" % line
                    if len(args) > 0:
                        raise ValueError, "'%s' is unsupported" % line
                    self["nfs"] = nfs                    
                elif line[0:4] == "auth":
                    self["authconfig"] = line[4:]
                elif line[0:10] == "authconfig":
                    self["authconfig"] = line[10:]
#                elif line[0:9] == "clearpart": # --all --initlabel
#                    self["clearpart"] = 1
#                elif line[0:4] == "part" or line[0:9] == "partition":
#                    if line[0:9] == "partition":
#                        l = line[9:]
#                    else:
#                        l = line[4:]
#                    part = { }
#                    (opts, args) = getopt(string.split(l), "",
#                                          ["fstype=","onpart=", "noformat"])
#                    for (opt, val) in opts:
#                        if opt == "--size":
#                            part["size"] = val
#                        elif opt == "--grow":
#                            part["grow"] = 1
#                        elif opt == "--maxsize":
#                            part["maxsize"] = val
#                        elif opt == "--noformat":
#                            part["noformat"] = 1
#                        elif opt == "--onpart":
#                            part["onpart"] = val
#                        elif opt == "--fstype":
#                            part["fstype"] = val
#                        elif opt == "--label":
#                            part["label"] = val
#                        else:
#                            raise ValueError, "'%s' is unsupported" % line
#                    if len(args) != 1:
#                        raise ValueError, "'%s': No partition given" % line
#                    if not self["part"]:
#                        self["part"] = { }
#                    self["part"][args[0]] = part
                elif line[0:7] == "network":
                    net = { }                    
                    (opts, args) = getopt(string.split(line[7:]), "",
                                          ["device:", "bootproto:"])
                    for (opt, val) in opts:
                        if opt == "--device":
                            net["device"] = val
                        elif opt == "--bootproto":
                            net["bootproto"] = val
                        else:
                            raise ValueError, "'%s' is unsupported" % line
                    if len(args) != 0:
                        raise ValueError, "'%s' is unsupported" % line

                    if not self["network"]:
                        self["network"] = [ ]
                    self["network"] = net
                else:
                    # print "ignoring '%s'" % line
                    pass
            elif in_packages:
                if not self["packages"]:
                    self["packages"] = { }
                if line[0] == "@":
                    group = string.lstrip(line[1:])
                    if not self["packages"].has_key("groups"):
                        self["packages"]["groups"] = [ ]
                    if not group in self["packages"]["groups"]:
                        self["packages"]["groups"].append(group)
                elif line[0] != "-":
                    if not self["packages"].has_key("add"):
                        self["packages"]["add"] = [ ]
                    if not line in self["packages"]["add"]:
                        self["packages"]["add"].append(line)
                else:
                    if not self["packages"].has_key("drop"):
                        self["packages"]["drop"] = [ ]
                    if not line in self["packages"]["drop"]:
                        self["packages"]["drop"].append(line)
            elif in_post:
                self["post"]["script"] += line+"\n"

        fd.close()


class XenConfig(dict):
    def __init__(self, filename):
        dict.__init__(self)
        self.parse(filename)

    def __getitem__(self, item):
        if not self.has_key(item):
            return None
        return dict.__getitem__(self, item)

    def parse(self, filename):
        self["filename"] = filename
        fd = open(filename, "r")

        in_packages = 0
        in_post = 0
        while 1:
            line = fd.readline()
            
            if not line: break
            
            if line[-1:] == "\n":
                line = line[:-1]
            if len(line) < 1: continue
            if line[0] == '#': continue

            line = string.rstrip(line)

            # TODO

        fd.close()

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

    while len(_args) > 0:
        arg = _args[0]

        if arg[0:2] == "--": # longopts
            a = arg[2:]
            if a in _longopts:
                if not _longopts[a]:
                    _opts.append((arg, None))
                    _args.remove(arg)
                    continue
                elif _longopts[a] == ":":
                    if len(args) > 1:
                        val = _args[1]
                        _opts.append((arg, val))
                        _args.remove(arg)
                        _args.remove(val)
                        continue
                    else:
                        raise ValueError, "Missing value for '%s'" % arg
            
            i = arg.find("=")
            if i > 0: # found '='
                a = arg[2:i]
                if a in _longopts and \
                       (_longopts[a] == "=" or _longopts[a] == ":"):
                    _opts.append((arg[:i], arg[i+1:]))
                    _args.remove(arg)
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
                        val = _args[1]
                        _opts.append((arg, val))
                        _args.remove(arg)
                        _args.remove(val)
                    else:
                        raise ValueError, "Invalid option '%s'" % arg
                    _args.remove(arg)
                else:
                    raise ValueError, "Invalid option '%s'" % arg
        else: # no opts anymore
            break

    return (_opts,_args)


def rm_rf(name):
    if not os.path.exists(name) or not os.path.isdir(name):
        return
    if os.path.ismount(name):
        umount(name)
        return
    list = os.listdir(name)
    for file in list:
        if os.path.isdir(name+"/"+file) and not os.path.islink(name+"/"+file):
            rm_rf(name+"/"+file)
        else:
            os.unlink(name+"/"+file)
    os.rmdir(name)


def mount(what, where, fstype="ext3", options=None):
    print "Mounting '%s' on '%s'" % (what, where)

    opts = ""
    if options:
        opts = "-o '%s'" % options
    stat = os.system("mount %s -t '%s' '%s' '%s'" % \
                     (opts, fstype, what , where))
    if stat != 0:
        raise IOError, "mount of '%s' on '%s' failed" % (what , where)


def umount(what):
    if not os.path.ismount(what):
        return
    print "Umounting '%s'" % what
    
    i = 0
    failed = 0
    while os.path.ismount(what) and i < 100:
        if i == 1:
            # kill all processes running in dir
            print "Killing all processes running in  '%s'" % what
        if i > 0:
            pid = os.fork()
            if pid != 0:
                (rpid, status) = os.waitpid(pid, 0)
                if status != 0:
                    sys.exit(1)
            else:
                pyrpm.runScript(script="/sbin/fuser -k '%s'" % what)
                sys.exit(0)

            print "Trying to umount '%s'" % source_dir
            time.sleep(0.5)
        stat = os.system("umount '%s'" % what)
        if stat != 0:
            failed = 1
        else:
            failed = 0
        i += 1
    if failed == 1:
        print "Umount of '%s' failed" % what

#################################### main ####################################

verbose = 0
buildroot = ""
xen = 0

def usage():
    print """Usage: ks-install <options> <file> [<disk image> | <device>]

OPTIONS
  -h  | --help       print help
  -v  | --verbose    be verbose, and more, ..

  -x  | --xen        prepare for xen
"""

#(opts, args) = getopt.getopt(sys.argv[1:], "hvx", ["help", "verbose", "xen"])

try:
    (opts, args) = getopt(sys.argv[1:], "hvx", ["help", "verbose", "xen"])
except:
    usage()
    sys.exit(1)

for (opt, val) in opts:
    if opt in ["-h", "--help"]:
        usage()
        sys.exit(1)
    elif opt in ["-v", "--verbose"]:
        verbose += 1
        pyrpm.rpmconfig.verbose += 1
    elif opt in ["-x", "--xen"]:
        xen = 1
    else:
        print "Unknown option '%s'" % opt
        usage()
        sys.exit(1)

if len(args) < 1 or len(args) > 2:
    print "args=%s" % args
    usage()
    sys.exit(1)

ks_file = args[0]
target = args[1]

# test target
if not os.path.exists(target):
    print "'%s' does not exist." % target
    sys.exit(1)

# image or block device
install_image = 0
install_device = 0
mode = os.stat(target).st_mode
if stat.S_ISREG(mode):
    install_image = 1
elif stat.S_ISBLK(mode):
    install_device = 1

if not install_image and not install_device:
    print "No image and no device?"
    sys.exit(1)    

# load kickstart file
ks = KickstartConfig(ks_file)

if not ks["nfs"] or not ks["nfs"]["server"] or not ks["nfs"]["dir"]:
    print "Only nfs install via server and dir is supported, exiting!"
    sys.exit(1)

if not ks["operation"]:
    print "No operation defined, exiting!"
    sys.exit(1)

if ks["operation"] not in ["install"]:
    print "Operation '%s' not supported."
    sys.exit(1)

print ks

# create temp dir

tempdir = tempfile.mkdtemp(prefix="ks-install_")
source_dir = tempdir+"/source"
target_dir = tempdir+"/target"

### mounting ###

# create source mount point and mount source (nfs)
os.mkdir(source_dir)
source = "%s:%s" % (ks["nfs"]["server"], ks["nfs"]["dir"])
mount(source, source_dir, fstype="nfs")

os.mkdir(target_dir)
if install_image:
    mount(target, target_dir, fstype="ext3", options="loop")
if install_device:
    mount(target, target_dir, fstype="ext3")

buildroot = target_dir
pyrpm.rpmconfig.buildroot = buildroot

# set default group "base" if no groups are specified
if not ks["packages"]:
    ks["packages"] = { }
if not ks["packages"].has_key("groups"):
    ks["packages"]["groups"] = [ ]

if len(ks["packages"]["groups"]) == 0:
    ks["packages"]["groups"].append("base")

# load comps file for groups and default packages
comps = pyrpm.RpmCompsXML(pyrpm.rpmconfig,
                          "%s/repodata/comps.xml" % source_dir)
comps.read()
pkgs = [ ]
for group in ks["packages"]["groups"]:
    pkgs.extend(comps.getPackageNames(group))
del comps

# add and remove packages from default list
if ks["packages"].has_key("drop"):
    for pkg in ks["packages"]["drop"]:
        if pkg in pkgs:
            pkgs.remove(pkg)
if ks["packages"].has_key("add"):
    for pkg in ks["packages"]["add"]:
        if not pkg in pkgs:
            pkgs.append(pkg)

# add comps package (FC-4)
if not "comps" in pkgs:
    pkgs.append("comps")

# append authconfig, if we want to configure it
if ks["authconfig"] and not "authconfig" in pkgs:
    print "Adding package authconfig"
    pkgs.append("authconfig")

if len(pkgs) < 1:
    print "Nothing to do."
    sys.exit(1)

# greate essential directories and files
os.umask(000)
if not os.path.exists(buildroot+"/dev"):
    os.mkdir(buildroot+"/dev")
    os.mknod(buildroot+"/dev/console", 0666 | stat.S_IFCHR, os.makedev(5, 1))
    os.mknod(buildroot+"/dev/null", 0666 | stat.S_IFCHR, os.makedev(1, 3))
    os.mknod(buildroot+"/dev/zero", 0666 | stat.S_IFCHR, os.makedev(1, 5))

if not os.path.exists(buildroot+"/etc"):
    os.mkdir(buildroot+"/etc")
    fd = open(buildroot+"/etc/fstab", "w")
    fd.write("/dev/root\t\t/\t\text3\tdefaults\t1 1\n")
    fd.write("/dev/devpts\t\t/dev/pts\t\tdevpts\tgid=5,mode=620\t0 0\n")
    fd.write("/dev/shm\t\t/dev/shm\t\ttmpfs\tdefaults\t0 0\n")
    fd.write("/dev/proc\t\t/proc\t\tproc\tdefaults\t0 0\n")
    fd.write("/dev/sys\t\t/sys\t\tsysfs\tdefaults\t0 0\n")
    fd.close()
    fd = open(buildroot+"/etc/hosts", "w")
    fd.write("# Do not remove the following line, or various programs\n")
    fd.write("# that require network functionality will fail.\n")
    fd.write("127.0.0.1\t\tlocalhost.localdomain\tlocalhost\n")
    fd.close()
    fd = open(buildroot+"/etc/modprobe.conf", "w")
    fd.close()

if xen:
    # TODO: ?
    pass


# install
print "working.."
# YUM
os.mkdir("%s/yum.cache" % tempdir)
os.mkdir("%s/yum.repos.d" % tempdir)
yum_conf = tempdir+"/yum.conf"
fd = open(yum_conf, "w")
fd.write("[main]\n")
fd.write("cachedir=%s/yum.cache\n" % tempdir)
fd.write("debuglevel=0\n")
fd.write("errorlevel=0\n")
fd.write("pkgpolicy=newest\n")
fd.write("distroverpkg=redhat-release\n")
fd.write("tolerant=1\n")
fd.write("exactarch=1\n")
fd.write("retries=20\n")
fd.write("obsoletes=1\n")
fd.write("reposdir=%s/yum.repos.d\n" % tempdir)
fd.write("\n")
fd.write("[dist]\n")
fd.write("name=dist\n")
fd.write("baseurl=file:%s/source\n" % tempdir)
fd.close()
os.system("%s/scripts/pyrpmyum --servicehack -y -c '%s' -r '%s' %s %s" % \
          (PYRPMDIR, yum_conf, buildroot, ks["operation"], string.join(pkgs)))

# run kudzu
print "Running kudzu"
pid = os.fork()
if pid != 0:
    (rpid, status) = os.waitpid(pid, 0)
    if status != 0:
        sys.exit(1)
else:
    os.chroot(buildroot)
    pyrpm.runScript("/usr/sbin/kudzu")
    sys.exit(0)

# run authconfig if set
if ks["authconfig"]:
    print "Configuring authentication"
    pid = os.fork()
    if pid != 0:
        (rpid, status) = os.waitpid(pid, 0)
        if status != 0:
            sys.exit(1)
    else:
        os.chroot(buildroot)
        print "/usr/bin/authconfig --kickstart --nostart %s" % ks["authconfig"]
        pyrpm.runScript(script="/usr/bin/authconfig --kickstart --nostart %s >/dev/null 2>&1" % ks["authconfig"])
        sys.exit(0)

# setup networking
if ks["network"]:
    print "Configuring network"
    if not os.path.exists(buildroot+"/etc/sysconfig"):
        os.mkdir(buildroot+"/etc/sysconfig")
    fd = open(buildroot+"/etc/sysconfig/network", "w")
    fd.write("NETWORKING=yes\nHOSTNAME=localhost.localdomain\n")
    fd.close()
    if not os.path.exists(buildroot+"/etc/sysconfig/network-scripts"):
        os.mkdir(buildroot+"/etc/sysconfig/network-scripts")
    if ks["network"].has_key("device") and ks["network"].has_key("bootproto"):
        fd = open(buildroot+"/etc/sysconfig/network-scripts/ifcfg-%s" % \
                  ks["network"]["device"], "w")
        fd.write("DEVICE=%s\n" % ks["network"]["device"])
        fd.write("BOOTPROTO=%s\n" % ks["network"]["bootproto"])
        fd.write("ONBOOT=yes\n")
        fd.write("TYPE=Ethernet\n")
        fd.close()        

# run post script
if ks["post"] and len(ks["post"]["script"]) > 0:
    print "Running post script"
    pid = os.fork()
    if pid != 0:
        (rpid, status) = os.waitpid(pid, 0)
        if status != 0:
            sys.exit(1)
    else:
        if not ks["post"]["nochroot"]:
            os.chroot(buildroot)
        pyrpm.runScript(ks["post"]["interpreter"], ks["post"]["script"])
        sys.exit(0)

if xen:
    fd = open("xen.conf", "w")
#    fd.write('kernel = "/boot/vmlinuz-2.6.11-1.1369_FC4xenU"\n')
#    fd.write('ramdisk = "/boot/initrd-2.6.11-1.1369_FC4xen0.img"\n')
    fd.write('memory = 128\n')
    fd.write('name = "xen"\n')
    fd.write('nics = 1\n')
    if install_image:
        fd.write('disk = [ "file:%s,sda1,w" ]\n' % target)
    if install_device:
        fd.write('disk = [ "phy:%s,sda1,w" ]\n' % target)
    fd.write('root = "/dev/sda1"\n')
    fd.write('extra = "ro"\n')
    fd.close()

# umount nfs source dir
umount(source_dir)

# umount target dir and included mount points
mounted = [ ]
fd = open("/proc/mounts", "r")
while 1:
    line = fd.readline()
    if not line:
        break
    args = string.split(line)
    i = args[1].find(target_dir)
    if i == 0:
        mounted.append(args[1])
fd.close()
# sort reverse
mounted.sort()
mounted.reverse()

for dir in mounted:
    umount(dir)

if tempdir != None and os.path.exists(tempdir):
    rm_rf(tempdir)

sys.exit(0)

##############################################################################

"""
########################## MUST ##########################

/etc/hosts
+# Do not remove the following line, or various programs
+# that require network functionality will fail.
+127.0.0.1              localhost.localdomain localhost

/etc/fstab
+/dev/root               /                       ext3    defaults        1 1
+/dev/devpts             /dev/pts                devpts  gid=5,mode=620  0 0
+/dev/shm                /dev/shm                tmpfs   defaults        0 0
+/dev/proc               /proc                   proc    defaults        0 0
+/dev/sys                /sys                    sysfs   defaults        0 0

/etc/shadow

######################### FOR XEN #########################

/etc/sysconfig/network
+NETWORKING=yes
+HOSTNAME=localhost.localdomain

/etc/sysconfig/network-scripts/ifcfg-eth0
+DEVICE=eth0
+BOOTPROTO=dhcp
+ONBOOT=yes
+TYPE=Ethernet

########################## MAYBE ##########################

/etc/localtime

/etc/nsswitch.conf
-netgroup:   nisplus
+netgroup:   files
-automount:  files nisplus
+automount:  files

/etc/rpm/platform
+i686-redhat-linux

/etc/sysconfig/authconfig
+USECRACKLIB=yes
+USEDB=no
+USEHESIOD=no
+USELDAP=no
+USENIS=no
+USEPASSWDQC=no
+USEWINBIND=no
+USEKERBEROS=no
+USELDAPAUTH=no
+USEMD5=yes
+USESHADOW=yes
+USESMBAUTH=no
+USEWINBINDAUTH=no
+USELOCAUTHORIZE=no

/etc/sysconfig/clock
+ZONE="Europe/Berlin"
+UTC=false
+ARC=false

/etc/sysconfig/desktop
+DESKTOP="GNOME"

/etc/sysconfig/hwconf

/etc/sysconfig/i18n
+LANG="en_US.UTF-8"
+SYSFONT="latarcyrheb-sun16"

/etc/sysconfig/installinfo
+INSTALLMETHOD=nfs

/etc/sysconfig/iptables
+# Firewall configuration written by system-config-securitylevel
+# Manual customization of this file is not recommended.
+*filter
+:INPUT ACCEPT [0:0]
+:FORWARD ACCEPT [0:0]
+:OUTPUT ACCEPT [0:0]
+:RH-Firewall-1-INPUT - [0:0]
+-A INPUT -j RH-Firewall-1-INPUT
+-A FORWARD -j RH-Firewall-1-INPUT
+-A RH-Firewall-1-INPUT -i lo -j ACCEPT
+-A RH-Firewall-1-INPUT -p icmp --icmp-type any -j ACCEPT
+-A RH-Firewall-1-INPUT -p 50 -j ACCEPT
+-A RH-Firewall-1-INPUT -p 51 -j ACCEPT
+-A RH-Firewall-1-INPUT -p udp --dport 5353 -d 224.0.0.251 -j ACCEPT
+-A RH-Firewall-1-INPUT -p udp -m udp --dport 631 -j ACCEPT
+-A RH-Firewall-1-INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
+-A RH-Firewall-1-INPUT -j REJECT --reject-with icmp-host-prohibited
+COMMIT

/etc/sysconfig/kernel
+# UPDATEDEFAULT specifies if new-kernel-pkg should make
+# new kernels the default
+UPDATEDEFAULT=yes
+
+# DEFAULTKERNEL specifies the default kernel package type
+DEFAULTKERNEL=kernel-smp

/etc/sysconfig/keyboard
+KEYBOARDTYPE="pc"
+KEYTABLE="de-latin1-nodeadkeys"

/etc/sysconfig/mouse
+FULLNAME="Generic - Wheel Mouse (USB)"
+MOUSETYPE="imps2"
+XEMU3="no"
+XMOUSETYPE="IMPS/2"
+DEVICE=/dev/input/mice

/etc/modprobe.conf
"""
