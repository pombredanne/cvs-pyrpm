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
import config
from installer import keyboard_models
from pyrpm.functions import runScript
from functions import create_file

def firewall_config(ks, buildroot, installation):
    if (installation.release == "RHEL" and installation.version < 4) or \
           (installation.release == "FC" and installation.version < 2) or \
           not os.path.exists(buildroot+"/usr/sbin/lokkit"):
        # lokkit is not able to configure firewall for pre RHEL-4 and
        # pre FC-2
        _trusted = ""
        if ks["firewall"].has_key("trusted"):
            for iface in ks["firewall"]["trusted"]:
                _trusted += '-A RH-Firewall-1-INPUT -i %s -j ACCEPT\n' % \
                            iface
        _open_ports = ""
        if ks["firewall"].has_key("ports"):
            ports = ks["firewall"]["ports"][:]
            ports.sort()
            for port in ports:
                _open_ports += '-A RH-Firewall-1-INPUT ' + \
                               '-m state --state NEW ' + \
                               '-m %s -p %s --dport %d -j ACCEPT\n' % \
                               (port[1], port[1], port[0])
        content = [ \
            '# Firewall configuration written by pyrpmkickstart\n',
            '# Manual customization of this file is not recommended.\n',
            '*filter\n',
            ':INPUT ACCEPT [0:0]\n',
            ':FORWARD ACCEPT [0:0]\n',
            ':OUTPUT ACCEPT [0:0]\n',
            ':RH-Firewall-1-INPUT - [0:0]\n',
            '-A INPUT -j RH-Firewall-1-INPUT\n',
            '-A FORWARD -j RH-Firewall-1-INPUT\n',
            '-A RH-Firewall-1-INPUT -i lo -j ACCEPT\n',
            _trusted,
            '-A RH-Firewall-1-INPUT -p icmp --icmp-type any -j ACCEPT\n',
            '-A RH-Firewall-1-INPUT -p 50 -j ACCEPT\n',
            '-A RH-Firewall-1-INPUT -p 51 -j ACCEPT\n',
            '-A RH-Firewall-1-INPUT -p udp --dport 5353 -d 224.0.0.251 -j ACCEPT\n',
            '-A RH-Firewall-1-INPUT -p udp -m udp --dport 631 -j ACCEPT\n',
            '-A RH-Firewall-1-INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT\n',
            _open_ports,
            '-A RH-Firewall-1-INPUT -j REJECT --reject-with icmp-host-prohibited\n',
            'COMMIT\n' ]

        create_file(buildroot, "/etc/sysconfig/iptables", content)

        # enable firewall
        if ks["firewall"].has_key("enabled"):
            (status, rusage, msg) = runScript(\
                script="/sbin/chkconfig iptables on", chroot=buildroot)
            config.log(msg)
            if status != 0:
                print "ERROR: Could not enable firewall."
    else:
        # use lokkit to configure firewall
        fwargs = [ ]
        if ks["firewall"].has_key("enabled"):
            fwargs.append("--enabled")
        if ks["firewall"].has_key("disabled"):
            fwargs.append("--disabled")
        if ks["firewall"].has_key("trusted"):
            for trusted in ks["firewall"]["trusted"]:
                fwargs.append("--trusted=%s" % trusted)
        if ks["firewall"].has_key("ports"):
            for port in ks["firewall"]["ports"]:
                fwargs.append("--port=%s:%s" % (port[0], port[1]))

        lokkit = "/usr/sbin/lokkit --quiet --nostart -f %s" % \
                 " ".join(fwargs)
        (status, rusage, msg) = runScript(script=lokkit, chroot=buildroot)
        config.log(msg)
        if status != 0:
            print "ERROR: Configuration of firewall failed"

        create_file(buildroot, "/etc/sysconfig/system-config-securitylevel",
                    [ '# Configuration file for system-config-securitylevel\n',
                      "\n",
                      "%s" % "\n".join(fwargs) ])

# vim:ts=4:sw=4:showmatch:expandtab
