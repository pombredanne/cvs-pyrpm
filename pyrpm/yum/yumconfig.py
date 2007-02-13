#
# Copyright (C) 2005 Red Hat, Inc.
# Copyright (C) 2005 Harald Hoyer <harald@redhat.com>
# Copyright (C) 2006, 2007 Florian La Roche <laroche@redhat.com>
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

"""Simple yum.conf parser"""

import os, os.path, glob
from pyrpm.logger import log

MainVarnames = ("cachedir", "reposdir", "debuglevel", "errorlevel",
        "logfile", "gpgcheck", "assumeyes", "alwaysprompt", "tolerant",
        "exclude", "exactarch",
        "installonlypkgs", "kernelpkgnames", "showdupesfromrepos", "obsoletes",
        "overwrite_groups", "installroot", "rss-filename", "distroverpkg",
        "diskspacecheck", "tsflags", "recent", "retries", "keepalive",
        "timeout", "http_caching", "throttle", "bandwidth", "commands",
        "keepcache", "proxy", "proxy_username", "proxy_password", "pkgpolicy",
        "plugins", "pluginpath", "metadata_expire")
RepoVarnames = ("name", "baseurl", "mirrorlist", "enabled", "gpgcheck",
        "gpgkey", "exclude", "includepkgs", "enablegroups", "failovermethod",
        "keepalive", "timeout", "http_caching", "retries", "throttle",
        "bandwidth", "metadata_expire", "proxy", "proxy_username",
        "proxy_password")

def YumConf(buildroot="", filename="/etc/yum.conf", reposdirs=[]):
    data = {}
    ret = YumConf2(filename, data)
    if ret != None:
        raise ValueError, "could not read line %d in %s" % (ret, filename)
    reposdirs2 = reposdirs[:]
    k = data.get("main", {}).get("reposdir")
    if k != None:
        k = buildroot + k
        if k not in reposdirs2:
            reposdirs2.append(k)
    for reposdir in reposdirs2:
        for filename in glob.glob(reposdir + "/*.repo"):
            ret = YumConf2(filename, data)
            if ret != None:
                raise ValueError, "could not read line %d in %s" % (ret,
                    filename)
    return data

def YumConf2(filename, data):
    lines = []
    if os.path.isfile(filename) and os.access(filename, os.R_OK):
        log.info1Ln("Reading in config file %s.", filename)
        lines = open(filename, "r").readlines()
    stanza = "main"
    prevcommand = None
    for linenum in xrange(len(lines)):
        line = lines[linenum].rstrip("\n\r")
        if line[:1] == "[" and line.find("]") != -1:
            stanza = line[1:line.find("]")]
            prevcommand = None
        elif prevcommand and line[:1] in " \t":
            # continuation line
            line = line.strip()
            if line and line[:1] not in "#;":
                data[stanza][prevcommand].append(line)
        else:
            line = line.strip()
            if line[:1] in "#;" or not line:
                pass # comment line
            elif line.find("=") != -1:
                (key, value) = line.split("=", 1)
                (key, value) = (key.strip(), value.strip())
                if stanza == "main":
                    if key not in MainVarnames:
                        return linenum + 1 # unknown key value
                elif key not in RepoVarnames:
                    return linenum + 1 # unknown key value
                prevcommand = None
                if key in ("baseurl", "mirrorlist"):
                    value = [value]
                    prevcommand = key
                data.setdefault(stanza, {})[key] = value
            else:
                return linenum + 1 # not parsable line
    return None

# vim:ts=4:sw=4:showmatch:expandtab
