#!python
# -*- python -*-
# -*- coding: utf-8 -*-
## Copyright (C) 2005 Red Hat, Inc.
## Copyright (C) 2005 Harald Hoyer <harald@redhat.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

"""Simple yum.conf parser (read only)
mostly copied from rhpl.ConfSMB
"""


from rhpl.Conf import Conf
from glob import glob

import sys
from string import *
import re
import os
from types import DictType

class YumConfSubDict(DictType):
    def __init__(self, parent_conf, stanza, initdict=None):
        DictType.__init__(self, initdict)
        self.conf = parent_conf
        self.stanza = stanza
        
class YumConf(Conf):
    """Simple Yum config file parser
    """

    MainVarnames = ( "cachedir",
                     "reposdir",
                     "debuglevel",
                     "errorlevel",
                     "logfile",
                     "gpgcheck",
                     "assumeyes",
                     "tolerant",
                     "exclude",
                     "exactarch",
                     "installonlypkgs",
                     "kernelpkgnames",
                     "showdupesfromrepos",
                     "obsoletes",
                     "overwrite_groups",
                     "installroot",
                     "rss-filename",
                     "distroverpkg",
                     "diskspacecheck",
                     "tsflags",
                     "recent",
                     "retries",
                     "keepalive",
                     "throttle",
                     "bandwidth",
                     "commands",
                     "proxy",
                     "proxy_username",
                     "proxy_password",
                     # undocumented
                     "pkgpolicy",
                     )

    RepoVarnames = ( "name",
                     "baseurl",
                     "mirrorlist",
                     "enabled",
                     "gpgcheck",
                     "gpgkey",
                     "exclude",
                     "includepkgs",
                     "enablegroups",
                     "failovermethod",
                     "keepalive",
                     "retries",
                     "throttle",
                     "bandwidth",
                     "proxy",
                     "proxy_username",
                     "proxy_password" )    

    Variables = ( "releasever", "arch", "basearch" )
    
    def __init__(self, releasever, arch, basearch, filename = '/etc/yum.conf'):
        """releasever - version of release (e.g. 3 for Fedora Core 3)
        arch - architecure (e.g. i686)
        basearch - base architecture (e.g. i386)
        """
        self.releasever = releasever
        self.arch = arch
        self.basearch = basearch
        self.myfilename = filename
        
        self.stanza_re = re.compile('^\s*\[(?P<stanza>[^\]]*)]\s*(?:;.*)?$', re.I)
        Conf.__init__(self, "/etc/yum.conf", '#;', '=', '=',
                      merge=1, create_if_missing = 0)

    def extendValue(self, value):
        """replaces known $vars in values"""
        for var in YumConf.Variables:
            if value.find("$" + var) != -1:
                value = value.replace("$" + var, self.__dict__[var])
        return value

    def checkVar(self, stanza, varname):
        """check variablename, if allowed in the config file"""        
        if stanza == "main":
            if varname in YumConf.MainVarnames:
                return 0
        else:
            if varname in YumConf.RepoVarnames:
                return 0
        return 1
        
    def read(self):
        """read all config files"""
        self.vars = {}
        self.filename = self.myfilename
        Conf.read(self)
        self.parseFile()
        repodir = '/etc/yum.repos.d'
        if self.vars.has_key("main") and self.vars["main"].has_key("reposdir"):
            repodir = self.vars["main"]["reposdir"]

        if not repodir:
            return
        
        filenames = glob(repodir + '/*.repo')
        for filename in filenames:
            self.filename = filename
            Conf.read(self)
            self.parseFile()    
        
    def parseFile(self):
        """parse one config file with the help of Conf"""
        self.rewind()
        stanza = None
        while 1:
            stanza = self.nextStanza()
            if not stanza:
                break
            stanzavars = {}
            
            self.nextline()
            
            while self.findnextcodeline():
                vars = self.nextEntry()
                if not vars:
                    break

                if self.checkVar(stanza, vars[0]):
                    sys.stderr.write("Bad variable %s in %s\n" \
                                     % (vars[0], self.filename))
                    self.nextline()
                    continue
                
                name = vars[0]
                value = self.extendValue(vars[1])
            
                stanzavars[name] = value
                self.nextline()

            self.vars[stanza] = YumConfSubDict(self, stanza, stanzavars)
            
        self.rewind()

    def getEntry(self):
        vars = self.getfields()
            
        try:            
            vars = [vars[0], joinfields(vars[1:len(vars)], '=')]
        except(LookupError):
            return 0

        if not vars:
            return 0
      
        return [strip(vars[0]), strip(vars[1])]

    def nextEntry(self):
        while self.findnextcodeline():
            #print "nextEntry: " + self.getline()
            if self.isStanzaDecl():
                return 0
            
            vars = self.getEntry()
            
            if vars:
                return vars
            
            self.nextline()            
            
        return 0
                
    def findnextcodeline(self):
        # cannot rename, because of inherited class
        return self.findnextline('^[\t ]*[\[A-Za-z_]+.*')
    
    def isStanzaDecl(self):
        # return true if the current line is of the form [...]
        if self.stanza_re.match(self.getline()):
            return 1
        return 0
                
    def nextStanza(self):
        # leave the current line at the first line of the stanza
        # (the first line after the [stanza_name] entry)
        while self.findnextline('^[\t ]*\[.*\]'):
            m = self.stanza_re.match(self.getline())
            if m:
                stanza = m.group('stanza')
                if stanza:
                    return stanza
                
            self.nextline()
            
        self.rewind()
        return 0
                
    def __getitem__(self, stanza):               
        return self.vars[stanza]
        
    def __setitem__(self, stanza, value):
        raise Exception, "read only"
            
    def __delitem__(self, stanza):
        raise Exception, "read only"
            
    def keys(self):
        # no need to return list in order here, I think.
        return self.vars.keys()
    
    def has_key(self, key):
        return self.vars.has_key(key)

    
if __name__ == '__main__':
    conf = YumConf("3", "i686", "i386")
    print conf.vars
    for confkey in conf.vars.keys():
        print "key:", confkey
