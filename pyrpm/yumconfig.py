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

from glob import glob

import sys
from string import *
import re
import os
from types import DictType


class Conf:
    def __init__(self, filename, commenttype='#',
                 separators='\t ', separator='\t',
		 merge=1, create_if_missing=1):
        self.commenttype = commenttype
        self.separators = separators
        self.separator = separator
        self.codedict = {}
        self.splitdict = {}
	self.merge = merge
	self.create_if_missing = create_if_missing
        self.line = 0
	self.rcs = 0
        self.mode = -1
        # self.line is a "point" -- 0 is before the first line;
        # 1 is between the first and second lines, etc.
        # The "current" line is the line after the point.
        self.filename = filename
        self.read()
    def rewind(self):
        self.line = 0
    def fsf(self):
        self.line = len(self.lines)
    def tell(self):
        return self.line
    def seek(self, line):
        self.line = line
    def nextline(self):
        self.line = min([self.line + 1, len(self.lines)])
    def findnextline(self, regexp=None):
        # returns false if no more lines matching pattern
        while self.line < len(self.lines):
            if regexp:
                if hasattr(regexp, "search"):
                    if regexp.search(self.lines[self.line]):
                        return 1
                elif re.search(regexp, self.lines[self.line]):
                    return 1
            elif not regexp:
                return 1
            self.line = self.line + 1
        # if while loop terminated, pattern not found.
        return 0
    def findnextcodeline(self):
        # optional whitespace followed by non-comment character
        # defines a codeline.  blank lines, lines with only whitespace,
        # and comment lines do not count.
        if not self.codedict.has_key((self.separators, self.commenttype)):
            self.codedict[(self.separators, self.commenttype)] = \
                                           re.compile('^[' + self.separators \
                                                      + ']*' + '[^' + \
                                                      self.commenttype + \
                                                      self.separators + ']+')
        codereg = self.codedict[(self.separators, self.commenttype)]
        return self.findnextline(codereg)
    def findlinewithfield(self, fieldnum, value):
	if self.merge:
	    seps = '['+self.separators+']+'
	else:
	    seps = '['+self.separators+']'
	rx = '^'
	for i in range(fieldnum - 1):
	    rx = rx + '[^'+self.separators+']*' + seps
	rx = rx + value + '\(['+self.separators+']\|$\)'
	return self.findnextline(rx)
    def getline(self):
        if self.line >= len(self.lines):
            return ''        
        return self.lines[self.line]
    def getfields(self):
        # returns list of fields split by self.separators
        if self.line >= len(self.lines):
            return []
	if self.merge:
	    seps = '['+self.separators+']+'
	else:
	    seps = '['+self.separators+']'
        #print "re.split(%s, %s) = " % (self.lines[self.line], seps) + str(re.split(seps, self.lines[self.line]))

        if not self.splitdict.has_key(seps):
            self.splitdict[seps] = re.compile(seps)
        regexp = self.splitdict[seps]
        return regexp.split(self.lines[self.line])
    def setfields(self, list):
	# replaces current line with line built from list
	# appends if off the end of the array
	if self.line < len(self.lines):
	    self.deleteline()
	self.insertlinelist(list)
    def insertline(self, line=''):
        self.lines.insert(self.line, line)
    def insertlinelist(self, linelist):
        self.insertline(joinfields(linelist, self.separator))
    def sedline(self, pat, repl):
        if self.line < len(self.lines):
            self.lines[self.line] = re.sub(pat, repl, \
                                           self.lines[self.line])
    def changefield(self, fieldno, fieldtext):
        fields = self.getfields()
        fields[fieldno:fieldno+1] = [fieldtext]
        self.setfields(fields)
    def setline(self, line=[]):
        self.deleteline()
        self.insertline(line)
    def deleteline(self):
        self.lines[self.line:self.line+1] = []
    def chmod(self, mode=-1):
	self.mode = mode
    def read(self):
	file_exists = 0
        if os.path.isfile(self.filename):
	    file_exists = 1
	if not self.create_if_missing and not file_exists:
	    raise FileMissing, self.filename + ' does not exist.'
	if file_exists and os.access(self.filename, os.R_OK):
            self.file = open(self.filename, 'r', -1)
            self.lines = self.file.readlines()
            # strip newlines
            for index in range(len(self.lines)):
                if len(self.lines[index]) and self.lines[index][-1] == '\n':
                    self.lines[index] = self.lines[index][:-1]
                if len(self.lines[index]) and self.lines[index][-1] == '\r':
                    self.lines[index] = self.lines[index][:-1]                
            self.file.close()
	else:
	    self.lines = []
    def write(self):
	# rcs checkout/checkin errors are thrown away, because they
	# aren't this tool's fault, and there's nothing much it could
	# do about them.  For example, if the file is already locked
	# by someone else, too bad!  This code is for keeping a trail,
	# not for managing contention.  Too many deadlocks that way...
	if self.rcs or os.path.exists(os.path.split(self.filename)[0]+'/RCS'):
	    self.rcs = 1
	    os.system('/usr/bin/co -l '+self.filename+' </dev/null >/dev/null 2>&1')
        self.file = open(self.filename, 'w', -1)
	if self.mode >= 0:
	    os.chmod(self.filename, self.mode)
        # add newlines
        for index in range(len(self.lines)):
            self.file.write(self.lines[index] + '\n')
        self.file.close()
	if self.rcs:
	    mode = os.stat(self.filename)[0]
	    os.system('/usr/bin/ci -u -m"control panel update" ' +
		      self.filename+' </dev/null >/dev/null 2>&1')
	    os.chmod(self.filename, mode)

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
    sys.exit(0)
