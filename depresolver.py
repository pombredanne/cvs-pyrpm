#!/usr/bin/python
#!/usr/bin/python2.2
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
# Copyright 2004 Red Hat, Inc.
#
# Author: Phil Knirsch
#
# This file contains a rpmlib independant depresolver using the pyrpm stuff.
#
# Beispiel: Installation von alle Packeten die mit k beginnen in ein leeres
#           System auf basis von FC3:
# ./depresolver.py --repo="`ls /mnt/raid/fedora/3/i386/os/Fedora/RPMS/*`" --add=`ls /mnt/raid/fedora/3/i386/os/Fedora/RPMS/k*`
#

import time, sys, getopt, string
from pyrpm import ReadRpm

class DepResolver:

    def __init__(self, install, repo):
        self.installrpms = install
        self.reporpms = repo
        self.repoprovides = {}
        self.installprovides = {}
        self.generateProvides()

    def generateProvides(self):
        for r in self.reporpms:
            self.addProvides(self.repoprovides, r)
        for r in self.installrpms:
            self.addProvides(self.installprovides, r)

    def addProvides(self, provides, rpm):
        for i in rpm.getProvides():
            provides[i[0]] = (i[1], i[2], rpm)
        for i in rpm.hdrfiletree.keys():
            provides[i] = (0, 8, rpm)

    def addRpms(self, rpms):
        addprovides = {}
        retrpms = []
        retrpms.extend(rpms)
        changed = 1
        print "Resolving deps..."
        while changed:
            addprovides = {}
            changed = 0
            for r in retrpms: 
                self.addProvides(addprovides, r)
            for r in retrpms:
                for i  in r.getRequires():
                    if addprovides.has_key(i[0]):
                        if addprovides[i[0]][2] == r:
#                            print "rpm provides it's own requires, skipping..."
                            continue
#                        print "other rpm that will be installed has key, advancing that in the order..."
                        continue
                    if self.installprovides.has_key(i[0]):
#                        print "installed rpm already satisfies requires, skipping..."
                        continue
                    if self.repoprovides.has_key(i[0]):
#                        print i[0], self.repoprovides[i[0]][2].getNVR()
#                        print "found rpm in repo that satisfies requires, adding..."
                        if self.repoprovides[i[0]][2] not in retrpms:
                            changed = 1
                            retrpms.insert(0, self.repoprovides[i[0]][2])
        for r in retrpms:
            print r.getNVR()

    def eraseRpms(self, rpms):
        return rpms

    def updateRpms(self, rpms):
        return rpms

def showHelp():
    print "depresolver [options]"
    print
    print "options:"
    print "--help this message"
    print "--installed=[rpms] List of installed RPMS on the system"
    print "--repo=[rpms] List of repository RPMS used for resolving"
    print "--add=[rpms] List of RPMS to be added to installed"
    print "--erase=[rpms] List of RPMS to be removed from installed"
    print "--update=[rpms] List of RPMS to be updated in installed"
    print
    print "Note: You can either add, erase or update rpms per run."


if __name__ == "__main__":
    installed = []
    finstalled = None
    repo = []
    frepo = None
    add = []
    fadd = None
    remove = []
    fremove = None
    update = []
    fupdate = None

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hqiraeu", ["help", "installed=", "repo=", "add=", "erase=", "update="])
    except getopt.error, e:
        print "Error parsing command list arguments: %s" % e
        showHelp()
        sys.exit(1)

    for (opt, val) in opts:
        if opt in ["-h", "--help"]:
            showHelp()
            sys.exit(1)
        if opt in ['-i', "--installed"]:
            finstalled = string.split(val)
        if opt in ['-r', "--repo"]:
            frepo = string.split(val)
        if opt in ['-a', "--add"]:
            fadd = string.split(val)
        if opt in ['-e', "--erase"]:
            ferase = string.split(val)
        if opt in ['-u', "--update"]:
            fupdate = string.split(val)

    if (fadd != None and fremove != None) or (fadd != None and fupdate != None) or (fremove != None and fupdate != None):
        print "Error: You can either add, erase or update rpms per run."
        sys.exit(1)

    print "Reading repository and other rpm headers..."
    for filename in frepo:
        rpm = ReadRpm(filename, legacy=0)
        rpm.readHeader()
        repo.append(rpm)

    for filename in fadd:
        rpm = ReadRpm(filename, legacy=0)
        rpm.readHeader()
        add.append(rpm)

    resolver = DepResolver(installed, repo)
    rpms = resolver.addRpms(add)
#    time.sleep(30)

# vim:ts=4:sw=4:showmatch:expandtab
