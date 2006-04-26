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

import os.path
from functions import create_file

def network_config(ks, buildroot):
    if not os.path.exists(buildroot+"/etc/sysconfig/network-scripts"):
        os.mkdir(buildroot+"/etc/sysconfig/network-scripts")

    # generate loopback network configuration if it does not exist
    if not os.path.exists(buildroot+\
                          "/etc/sysconfig/network-scripts/ifcfg-lo"):
        print "Adding missing /etc/sysconfig/network-scripts/ifcfg-lo."
        create_file(buildroot, "/etc/sysconfig/network-scripts/ifcfg-lo",
                    [ 'DEVICE=lo\n',
                      'IPADDR=127.0.0.1\n',
                      'NETMASK=255.0.0.0\n',
                      'NETWORK=127.0.0.0\n',
                      "# If you're having problems with gated making 127.0.0.0/8 a martian,\n",
                      "# you can change this to something else (255.255.255.255, for example)\n",
                      'BROADCAST=127.255.255.255\n',
                      'ONBOOT=yes\n',
                      'NAME=loopback\n' ])

    _hostname = None
    _gateway = None
    if ks["network"] and len(ks["network"]) > 0:
        # check network devices and set device for entries where no device
        # is specified
        network_devices = [ ]
        for net in ks["network"]:
            if net.has_key("device"):
                if net["device"] in network_devices:
                    print "WARNING: '%s' is not unique." % net["device"]
                else:
                    network_devices.append(net["device"])
        for net in ks["network"]:
            # get device or next free device
            device = None
            if net.has_key("device"):
                device = net["device"]
            if not device:
                i = 0
                device = "eth%d" % i
                while device in network_devices:
                    i += 1
                    device = "eth%d" % i
                net["device"] = device

        for net in ks["network"]:
            if not _hostname and net.has_key("hostname"):
                _hostname = 'HOSTNAME=%s\n' % net["hostname"]
            if not _gateway and net.has_key("gateway"):
                _gateway = 'GATEWAY=%s\n' % net["gateway"]

            device = net["device"]

            if device[:3] == "ctc":
                type = "CTC"
            elif device[:4] == "iucv":
                type = "IUCV"
            elif device[:2] == "tr":
                type = '"Token Ring"'
            else:
                type = "Ethernet"

            bootproto = "none"
            if net["bootproto"] and net["bootproto"] != "static":
                bootproto = net["bootproto"]

            try:
                fd = open(buildroot + \
                          "/etc/sysconfig/network-scripts/ifcfg-%s" % \
                          device, "w")
            except Exception, msg:
                print "ERROR: Configuration of '/etc/sysconfig/network-scripts/ifcfg-%s' failed:" % device, msg
            else:
                fd.write('DEVICE=%s\n' % device)
                fd.write('BOOTPROTO=%s\n' % bootproto)
                if net.has_key("gateway"):
                    fd.write('GATEWAY=%s\n' % net["gateway"])
                if net.has_key("netmask"):
                    fd.write('NETMASK=%s\n' % net["netmask"])
                if net.has_key("ip"):
                    fd.write('IPADDR=%s\n' % net["ip"])
                if net.has_key("essid"):
                    fd.write('ESSID=%s\n' % net["essid"])
                if net.has_key("ethtool"):
                    fd.write('ETHTOOL_OPTS=%s\n' % net["ethtool"])
                if net.has_key("class"):
                    fd.write('DHCP_CLASSID=%s\n' % net["class"])
                if net.has_key("onboot"):
                    fd.write('ONBOOT=%s\n' % net["onboot"])
                else:
                    fd.write('ONBOOT=yes\n')
                fd.write('TYPE=%s\n' % type)
                fd.close()

            if net.has_key("wepkey"):
                try:
                    fd = open(buildroot + \
                              "/etc/sysconfig/network-scripts/keys-%s" % \
                              device, "w")
                except Exception, msg:
                    print "ERROR: Configuration of '/etc/sysconfig/network-scripts/keys-%s' failed:" % device, msg
                else:
                    fd.write('KEY=%s\n' % net["wepkey"])
                fd.close()

    if not _hostname:
        _hostname = 'HOSTNAME=localhost.localdomain\n'
    if not _gateway:
        _gateway = ""
    # write /etc/sysconfig/network
    create_file(buildroot, "/etc/sysconfig/network",
                [ 'NETWORKING=yes\n', _hostname, _gateway ])
