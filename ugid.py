#!/usr/bin/python
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
# Author: Phil Knirsch <pknirsch@redhat.com>
#

import string

class Passwd:
    def __init__(self, pwfile="/etc/passwd"):
        self.pwfile = pwfile
        self.parseFile()

    def parseFile(self, pwfile=None):
        self.userlist = {}
        if pwfile == None:
            pwfile = self.pwfile
        try:
            fp = open(pwfile,"r")
        except:
            return
        lines = fp.readlines()
        for l in lines:
            tmp = string.split(l, ":")
            self.userlist[tmp[0]] = tmp[2]

    def getUID(self, name):
        if name not in self.userlist.keys():
            return -1
        return self.userlist[name]

class Group:
    def __init__(self, grpfile="/etc/group"):
        self.grpfile = grpfile
        self.parseFile()

    def parseFile(self, grpfile=None):
        self.grouplist = {}
        if grpfile == None:
            grpfile = self.grpfile
        try:
            fp = open(grpfile,"r")
        except:
            return
        lines = fp.readlines()
        for l in lines:
            tmp = string.split(l, ":")
            self.grouplist[tmp[0]] = tmp[2]

    def getGID(self, name):
        if name not in self.grouplist.keys():
            return -1
        return self.grouplist[name]

# vim:ts=4:sw=4:showmatch:expandtab
