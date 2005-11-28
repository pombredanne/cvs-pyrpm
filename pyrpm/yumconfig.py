#!/usr/bin/python
#
# Copyright (C) 2005 Red Hat, Inc.
# Copyright (C) 2005 Harald Hoyer <harald@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

"""Simple yum.conf parser (read only)
mostly copied from rhpl.ConfSMB
"""

from types import DictType
from glob import glob
import sys, re, os, string

class Conf:
    """A generic .ini file parser."""

    def __init__(self, filename, commenttype='#',
                 separators='\t ', separator='\t',
                 merge=1, create_if_missing=1):
        """Open and read (not parse) filename.

        Use commenttype to start comment lines.  Use separators to separate
        fields in file on input, separator on output (note that lines starting
        with separators are interpreted as having a zero-length first field).
        Allow more than one separator between two fields if merge.

        Don't report error if filename does not exist and create_if_missing.
        Raise IOError."""

        self.commenttype = commenttype
        self.separators = separators
        self.separator = separator
        # A cache for self.findnextcodeline():
        # (separators, commenttype) => RE for non-empty, non-comment lines
        self.codedict = {}
        # A cache for self.getfields(): regexp => compiled RE
        self.splitdict = {}
        self.merge = merge
        self.create_if_missing = create_if_missing
        # self.line is a "point" -- 0 is before the first line;
        # 1 is between the first and second lines, etc.
        # The "current" line is the line after the point.
        self.line = 0
        self.rcs = 0 # The file is managed by RCS, attempt to commit changes
        self.mode = -1                  # Mode to use in self.write()
        self.filename = filename
        self.read()

    def rewind(self):
        """Seek to the first line."""

        self.line = 0

    def nextline(self):
        """Seek to the next line, if any."""

        self.line = min([self.line + 1, len(self.lines)])

    def findnextline(self, regexp):
        """Starting at the current line, skip all lines not containing a match
        to regexp.

        Return 1 if found a match, 0 otherwise."""

        if not hasattr(regexp, "search"):
            regexp = re.compile(regexp)
        while self.line < len(self.lines):
            if regexp.search(self.lines[self.line]):
                return 1
            self.line = self.line + 1
        return 0

    def findnextcodeline(self):
        """Starting at the current line, skip all empty or comment lines.

        Return 1 if found a "value" line, 0 otherwise."""

        # optional whitespace followed by non-comment character
        # defines a codeline.  blank lines, lines with only whitespace,
        # and comment lines do not count.
        if not self.codedict.has_key((self.separators, self.commenttype)):
            self.codedict[(self.separators, self.commenttype)] = \
                re.compile('^[' + self.separators + ']*' + \
                '[^' + self.commenttype + self.separators + ']+')
        codereg = self.codedict[(self.separators, self.commenttype)]
        return self.findnextline(codereg)

    def getline(self):
        """Return current line, or '' if past EOF."""

        if self.line >= len(self.lines):
            return ''
        return self.lines[self.line]

    def getfields(self):
        """Return a list of fields on the current line, or [] if past EOF."""

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
        """Replace current line with fields list, or append it if at EOF."""

        if self.line < len(self.lines):
            self.deleteline()
        self.insertlinelist(list)

    def insertline(self, line=''):
        """Insert line to current position in self.lines."""

        self.lines.insert(self.line, line)

    def insertlinelist(self, linelist):
        """Insert line with fields linelist to self.lines at current
        position."""

        self.insertline(string.joinfields(linelist, self.separator))

    def sedline(self, pat, repl):
        """Replace pat with repl in current line."""

        if self.line < len(self.lines):
            self.lines[self.line] = re.sub(pat, repl, self.lines[self.line])

    def deleteline(self):
        """Remove current line from self.lines."""

        self.lines[self.line:self.line+1] = []

    def chmod(self, mode=-1):
        """Set file permissions to enforce in write () to mode.

        mode -1 means only umask should be used."""

        self.mode = mode

    def read(self):
        """Read (not parse) the config file into self.lines.

        Raise IOError."""

        self.lines = []
        if self.create_if_missing and not os.path.isfile(self.filename):
            return
        f = open(self.filename, 'r')
        for line in f:
            if line.endswith('\n'):
                line = line[:-1]
            if line.endswith('\r'):
                line = line[:-1]
            self.lines.append(line)
        f.close()

# FIXME: dict would be good enough, .conf and .stanza are not used.
class YumConfSubDict(DictType):
    def __init__(self, parent_conf, stanza, initdict=None):
        DictType.__init__(self, initdict)
        self.conf = parent_conf
        self.stanza = stanza

class YumConf(Conf):
    """Simple Yum config file parser"""

    # Variables valid in [main]
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

    # Variables that can have multi-line values
    MultiLines = ( "baseurl", "mirrorlist", "gpgkey" )

    # Variables valid in repository stanzas
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

    # $varname replaced by self.varname
    Variables = ( "releasever", "arch", "basearch" )

    def __init__(self, releasever, arch, basearch,
                 chroot = '',
                 filename = '/etc/yum.conf',
                 reposdir = '/etc/yum.repos.d',
                 ):
        """Open, read and parse filename and reposdir/*.repo.

        releasever - version of release (e.g. 3 for Fedora Core 3)
        arch - architecure (e.g. i686)
        basearch - base architecture (e.g. i386)
        chroot - a chroot to add to [main]/reposdir
        filename - the base config file

        Raise IOError."""

        if chroot == None:
            self.chroot = ''
        else:
            self.chroot = chroot

        if chroot and chroot[-1] != '/':
            self.chroot += '/'

        self.reposdir = reposdir
        self.releasever = releasever    # Used by extendValue()
        self.arch = arch                # Used by extendValue()
        self.basearch = basearch        # Used by extendValue()
        # Don't prefix the yum config file with the chroot
        self.myfilename = filename

        self.stanza_re = re.compile('^\s*\[(?P<stanza>[^\]]*)]\s*(?:;.*)?$', re.I)
        Conf.__init__(self, self.myfilename, '#;', '=', '=',
                      merge=1, create_if_missing=0)

    def extendValue(self, value):
        """Return value with all known $vars replaced by their values."""

        tval = value.lower()
        for var in YumConf.Variables:
            pos = tval.find("$" + var)
            while pos != -1:
                tval = tval[:pos] + self.__dict__[var] + tval[pos+len(var)+1:]
                value = value[:pos] + self.__dict__[var] + value[pos+len(var)+1:]
                pos = tval.find("$" + var)
        return value

    def checkVar(self, stanza, varname):
        """Return True if varname is allowed in stanza."""

        if stanza == "main":
            return varname in YumConf.MainVarnames
        else:
            return varname in YumConf.RepoVarnames

    def read(self):
        """Read and parse all config files to self.vars.

        Raise IOError."""

        self.vars = {}
        self.filename = self.myfilename
        Conf.read(self)
        self.parseFile()
        if self.vars.has_key("main") and self.vars["main"].has_key("reposdir"):
            self.reposdir = self.chroot + self.vars["main"]["reposdir"]

        if not self.reposdir:
            return

        filenames = glob(self.reposdir + '/*.repo')
        for filename in filenames:
            self.filename = filename
            Conf.read(self)
            self.parseFile()

    def parseFile(self):
        """Parse current self.lines into self.vars"""

        self.rewind()
        stanza = None
        while 1:
            stanza = self.nextStanza()
            if not stanza:
                break
            stanzavars = {}

            self.nextline()
            prevname = None

            while self.findnextcodeline():
                v = self.nextEntry()
                if not v:
                    break

                if not self.checkVar(stanza, v[0]):
                    # FIXME: not v[1] not quite correct, should use whole line
                    if (not v[1]) and (prevname in YumConf.MultiLines):
                        value = self.extendValue(v[0])
                        stanzavars[prevname].append(value)
                        self.nextline()
                        continue

                    #sys.stderr.write("\n++++++%s : %s\n+++++++++\n" % (prevname, str(v)))
                    sys.stderr.write("Bad variable %s in %s\n" \
                                     % (v[0], self.filename))
                    self.nextline()
                    continue

                name = v[0]
                value = self.extendValue(v[1])

                if name in YumConf.MultiLines:
                    stanzavars[name] = [ value ]
                else:
                    stanzavars[name] = value

                prevname = name
                self.nextline()

            self.vars[stanza] = YumConfSubDict(self, stanza, stanzavars)

        self.rewind()

    def getEntry(self):
        """Parse a single variable definition.

        Return [name, value] (both with leading and trailing white space
        stripped), or None if the line is invalid."""

        v = self.getfields()

        try:
            # FIXME: Loses white space around '=' in field values
            v = [v[0], string.joinfields(v[1:len(v)], '=')]
        except(LookupError):
            return None

        if not v:
            return None

        return [string.strip(v[0]), string.strip(v[1])]

    def nextEntry(self):
        """Starting at the current line, skip all lines that are not variable
        definitions.

        Return [name, value] (both with leading and trailing white space
        stripped) if found a "valud" line, None otherwise."""

        while self.findnextcodeline():
            #print "nextEntry: " + self.getline()
            if self.isStanzaDecl():
                return None

            v = self.getEntry()

            if v:
                return v

            self.nextline()

        return None

    def findnextcodeline(self):
        """Starting at the current line, skip all lines that can't be valid
        values or stanza headers.

        Return 1 if found a "valid" line, 0 otherwise."""

        # cannot rename, because of inherited class
        # XXX base class does not call this
        return self.findnextline('^[\t ]*[\[0-9A-Za-z_]+.*')

    def isStanzaDecl(self):
        """Return 1 if the current line is a stanza header."""

        if self.stanza_re.match(self.getline()):
            return 1
        return 0

    def nextStanza(self):
        """Starting at the current line, skip all lines until a stanza
        header.

        Return a stanza name if found, None otherwise."""

        # leave the current line at the first line of the stanza
        # (the first line after the [stanza_name] entry)
        while self.findnextline('^[\t ]*\[.*\]'):
            m = self.stanza_re.match(self.getline())
            if m:
                stanza = m.group('stanza')
                if stanza:
                    return stanza

            self.nextline()

        return None

    def __getitem__(self, stanza):
        """Return a YumConfSubDict for stanza.

        Raise KeyError."""

        return self.vars[stanza]

    def keys(self):
        """Return a list of known stanza names."""

        # no need to return list in order here, I think.
        return self.vars.keys()

    def has_key(self, key):
        """Return true if key is a valid stanza name."""

        return self.vars.has_key(key)


if __name__ == '__main__':
    conf = YumConf("3", "i686", "i386")
    print conf.vars
    for confkey in conf.vars.keys():
        print "key:", confkey
    sys.exit(0)

# vim:ts=4:sw=4:showmatch:expandtab
