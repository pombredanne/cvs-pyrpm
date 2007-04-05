#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Authors: Phil Knirsch, Thomas Woerner, Florian La Roche, Karel Zak
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


try:
    # python-2.5 layout:
    from xml.etree.cElementTree import iterparse
except ImportError:
    try:
        # often older python versions add this to site-packages:
        from cElementTree import iterparse
    except ImportError:
        try:
            # maybe the python-only version is available?
            from ElementTree import iterparse
        except:
            raise "No ElementTree parser found. Aborting."

import pyrpm.functions as functions
from pyrpm.logger import log

class RpmCompsXML:
    def __init__(self, config, source):
        """Initialize the parser.

        source is a filename to comps.xml."""

        self.config = config
        self.source = source
        self.grouphash = {}             # group id => { key => value }
        self.pkgtypehash = {}           # pkgname => [type, ...]
        self.langhash = {}              # language => group

    def __str__(self):
        return str(self.grouphash)

    def read(self):
        """Open and parse the comps file.

        Return 1 on success, 0 on failure."""

        try:
            fd = open(self.source)
            ip = iterparse(fd, events=("start","end"))
            ip = iter(ip)
        except IOError:
            return 0
        return self.__parse(ip)

    def hasGroup(self, name):
        """Return true if group id or localized group name is valid."""
        if not self.getGroup(name):
            return False
        return True

    def getGroups(self):
        """Return all group ids."""
        return self.grouphash.keys()

    def getGroup(self, name):
        """Return group id for group names (even localized names)."""
        if not self.grouphash.has_key(name):
            # check name tag first then try again with localized names
            for group in self.grouphash.keys():
                if self.grouphash[group].has_key("name") and \
                       self.grouphash[group]["name"] == name:
                    return group
            for group in self.grouphash.keys():
                for key in self.grouphash[group].keys():
                    if key[:5] == "name:" and \
                           self.grouphash[group][key] == name:
                        return group
            return None
        else:
            return name

    def getNameOfGroup(self, group, lang=None):
        """Return localized group name if available or group name if set,
        but at least the group id."""
        if not self.grouphash.has_key(group):
            return None
        if lang and self.grouphash[group].has_key("name:%s" % lang):
            return self.grouphash[group]["name:%s" % lang]
        elif self.grouphash[group].has_key("name"):
            return self.grouphash[group]["name"]
        else:
            return group

    def getGroupNames(self, lang=None):
        """Return localized group names if available or group names if set,
        but at least group ids."""
        groups = [ ]
        for group in self.grouphash.keys():
            # the group is in the list, therefore direct use of getGroupName
            groups.append(self.getNameOfGroup(group, lang))
        return groups

    def getDefaultGroups(self):
        """Return list of default group ids."""
        groups = [ ]
        for group in self.grouphash.keys():
            if self.grouphash[group].has_key("default") and \
                   self.grouphash[group]["default"]:
                groups.append(group)
        return groups

    def getGroupLanguage(self, group):
        """Return the language of a given group. langonly entry or None."""
        name = self.getGroup(group)
        if name == None:
            return None
        return self.grouphash[name].get("langonly")

    def getPackageNames(self, group):
        """Return a list of mandatory an default packages from group and its
        dependencies and the dependencies of the packages.

        The list may contain a single package name more than once.  Only the
        first-level package dependencies are returned, not their transitive
        closure."""

        ret = self.__getPackageNames(group, ("mandatory", "default"))
        ret2 = []
        for val in ret:
            ret2.append(val[0])
            ret2.extend(val[1])
        return ret2

    def getOptionalPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        optional packages from group and its dependencies."""

        return self.__getPackageNames(group, ["optional"])

    def getDefaultPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        default packages from group and its dependencies."""

        return self.__getPackageNames(group, ["default"])

    def getMandatoryPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        mandatory packages from group and its dependencies."""

        return self.__getPackageNames(group, ["mandatory"])

    def getConditionalPackageNames(self, group):
        """Return a sorted list of (package name, [package requirement]) of
        conditional packages from group and its dependencies."""

        return self.__getPackageNames(group, ["conditional"])

    def getLangOnlyPackageNames(self, lang, pkgname):
        """Return a list of package names where the pkgname is required for the
        given language.
        """

        if not self.langhash.has_key(lang):
            return []
        ret = []
        group = self.langhash[lang]
        conlist = self.getConditionalPackageNames(group["id"])
        conlist.extend(self.getOptionalPackageNames(group["id"]))
        for pname, reqlist in conlist:
            if pkgname in reqlist:
                ret.append(pname)
        return ret

    def hasType(self, pkgname, type):
        if not self.pkgtypehash.has_key(pkgname):
            return False
        return type in self.pkgtypehash[pkgname]

    def __parse(self, ip):
        """Parse node and its siblings under the root element.

        Return 1 on success, 0 on failure.  Handle <group>, <grouphierarchy>,
        warn about other tags."""

        for event, elem in ip:
            tag = elem.tag
            if  tag == "comps":
                continue
            elif tag == "group" or tag == "category":
                self.__parseGroup(ip)
            elif tag == "grouphierarchy":
                ret = self.__parseGroupHierarchy(ip)
            else:
                log.warning("Unknown entry in comps.xml: %s", tag)
                return 0
        return 1

    def __parseGroup(self, ip):
        """Parse <group>."""

        group = {}
        for event, elem in ip:
            tag = elem.tag
            isend = (event == "end")
            if   not isend and tag == "packagelist":
                group["packagelist"] = self.__parsePackageList(ip)
            elif not isend and tag == "grouplist": 
                group["grouplist"] = self.__parseGroupList(ip)
            if not isend:
                continue
            if   tag == "name":
                lang = elem.attrib.get('{http://www.w3.org/XML/1998/namespace}lang')
                if lang:
                    group["name:"+lang] = elem.text
                else:
                    group["name"] = elem.text
            elif tag == "description":
                lang = elem.attrib.get('{http://www.w3.org/XML/1998/namespace}lang')
                if lang:
                    group["description:"+lang] = elem.text
                else:
                    group["description"] = elem.text
            elif tag == "id":
                group["id"] = elem.text
            elif tag == "default":
                group["default"] = functions.parseBoolean(elem.text)
            elif tag == "langonly":
                group["langonly"] = elem.text
                self.langhash[group["langonly"]] = group
            elif isend and (tag == "group" or tag == "category"):
                break
        self.grouphash[group["id"]] = group

    def __parsePackageList(self, ip):
        """Parse <packagelist>.

        Return { package => (selection, [requirement]) }."""

        plist = {}
        for event, elem in ip:
            tag = elem.tag
            if  event == "end" and tag == "packagereq":
                ptype = elem.attrib.get('type')
                if ptype == None:
                    ptype = "default"
                requires = elem.attrib.get('requires')
                if requires != None:
                    requires = requires.split()
                else:
                    requires = []
                plist[elem.text] = (ptype, requires)
                self.pkgtypehash.setdefault(elem.text, []).append(ptype)
            elif tag == "packagelist":
                break
        return plist

    def __parseGroupList(self, ip):
        """Parse <grouplist>.

        Return { "groupgreqs" => [requirement],
        "metapkgs" => { requirement => requirement type } }."""

        glist = {}
        glist["groupreqs"] = []
        glist["metapkgs"] = {}
        for event, elem in ip:
            tag = elem.tag
            isend = (event == "end")
            if   isend and (tag == "groupreq" or tag == "groupid"):
                glist["groupreqs"].append(elem.text)
            elif isend and tag == "metapkg":
                gtype = elem.attrib.get("type")
                if gtype == None:
                    gtype = "default"
                glist["metapkgs"][elem.text] = gtype
            elif tag == "grouplist":
                break
        return glist

    def __parseGroupHierarchy(self, node):
        """Parse <grouphierarchy>.

        Return 1."""

        # We don't need grouphierarchies, so don't parse them ;)
        return 1

    def __getPackageNames(self, group, typelist):
        """Return a sorted list of (package name, [package requirement]) of
        packages from group and its dependencies with selection type in
        typelist."""

        ret = []
        _group = self.getGroup(group)
        if not _group:
            return ret
        if self.grouphash[_group].has_key("packagelist"):
            pkglist = self.grouphash[_group]["packagelist"]
            for (pkgname, value) in pkglist.iteritems():
                if value[0] in typelist:
                    ret.append((pkgname, value[1]))
        if self.grouphash[_group].has_key("grouplist"):
            grplist = self.grouphash[_group]["grouplist"]
            # FIXME: Stack overflow with loops in group requirements
            for grpname in grplist["groupreqs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
            for grpname in grplist["metapkgs"]:
                ret.extend(self.__getPackageNames(grpname, typelist))
        # Sort and duplicate removal
        ret.sort()
        for i in xrange(len(ret)-2, -1, -1):
            if ret[i+1] == ret[i]:
                ret.pop(i+1)
        return ret

# vim:ts=4:sw=4:showmatch:expandtab
