#
# Copyright (C) 2004, 2005 Red Hat, Inc.
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
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


from types import *
import libxml2, re, os, os.path, stat
from libxml2 import XML_READER_TYPE_ELEMENT, XML_READER_TYPE_END_ELEMENT
import memorydb
from pyrpm.base import *
from pyrpm.cache import NetworkCache
from comps import RpmCompsXML
import pyrpm.functions as functions
import pyrpm.package as package
import pyrpm.openpgp as openpgp
import lists, types
from pyrpm.logger import log
from pyrpm.io import PyGZIP
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

class RpmRepoDB(memorydb.RpmMemoryDB):
    """A (mostly) read-only RPM database storage in repodata XML.

    This is not a full implementation of Database: notably the file database
    is not populated at all."""

    # A mapping between strings and RPMSENSE_* comparison flags
    flagmap = { 0 : None,
                None: 0,
                "EQ": RPMSENSE_EQUAL,
                "LT": RPMSENSE_LESS,
                "GT": RPMSENSE_GREATER,
                "LE": RPMSENSE_EQUAL | RPMSENSE_LESS,
                "GE": RPMSENSE_EQUAL | RPMSENSE_GREATER,
                RPMSENSE_EQUAL: "EQ",
                RPMSENSE_LESS: "LT",
                RPMSENSE_GREATER: "GT",
                RPMSENSE_EQUAL | RPMSENSE_LESS: "LE",
                RPMSENSE_EQUAL | RPMSENSE_GREATER: "GE"}

    def __init__(self, config, source, buildroot='', reponame="default", nc=None):
        """Exclude packages matching whitespace-separated excludes.  Use
        reponame for cache subdirectory name and pkg["yumreponame"].

        Load PGP keys from URLs in key_urls."""

        memorydb.RpmMemoryDB.__init__(self, config, source, buildroot)
        self.reponame = reponame
        self.excludes = self.config.excludes[:]
        self.mirrorlist = None
        self.baseurls = None
        self.yumconf = None
        self.key_urls = []
        if nc:
            self.nc = nc
        else:
            self.nc = NetworkCache([], self.config.cachedir, self.reponame)
        if isinstance(source, types.DictType):
            found_urls = False
            self.yumconf = source
            if self.yumconf.has_key("main"):
                sec = self.yumconf["main"]
                if sec.has_key("exclude"):
                    self.excludes.extend(sec["exclude"])
            sec = self.yumconf[self.reponame]
            if sec.has_key("exclude"):
                self.excludes.extend(sec["exclude"])
            if sec.has_key("gpgkey"):
                self.key_urls = sec["gpgkey"]
            if sec.has_key("baseurl"):
                self.nc.addCache(sec["baseurl"], self.reponame)
                found_urls = True
            if sec.has_key("mirrorlist"):
                self.mirrorlist = sec["mirrorlist"]
                found_urls = True
            if not found_urls:
                raise ValueError, "yum.conf is missing mirrorlist or baseurl parameter"
        else:
            self.baseurls = source
            self.nc.addCache(self.baseurls, self.reponame)
        self.repomd = None
        self.filelist_imported  = 0
        # Files included in primary.xml
        self._filerc = re.compile('^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$')
        self._dirrc = re.compile('^(.*bin/.*|/etc/.*)$')
        self.comps = None

    def readMirrorList(self):
        if not self.is_read and self.mirrorlist and self.yumconf:
            fname = self.nc.cache(self.mirrorlist, 1)
            if fname:
                lines = open(fname).readlines()
                os.unlink(fname)
            else:
                lines = []
            for l in lines:
                l = l.strip()
                l = l.replace("$ARCH", "$basearch")
                l = self.yumconf.replaceVars(l)
                if l and l[0] != "#":
                    self.nc.addCache([l,])

    def getExcludes(self):
        return self.excludes

    def getMirrorList(self):
        return self.mirrorlist

    def isIdentitySave(self):
        """return if package objects that are added are in the db afterwards
        (.__contains__() returns True and the object are return from searches)
        """
        return False

    def readRepoMD(self):
        # First we try and read the repomd file as a starting point.
        filename = self.nc.cache("repodata/repomd.xml", 1)
        if not filename:
            log.error("Couldn't open repomd.xml")
            return 0
        try:
            fd = open(filename)
            ip = iterparse(fd, events=("start","end"))
            ip = iter(ip)
        except IOError:
            log.error("Couldn't parse repomd.xml")
            return 0
        # Create our network cache object
        self.repomd = self._parse(ip)
        return 1

    def readComps(self):
        # Try to read a comps.xml file if there is any before we parse the
        # primary.xml
        if self.repomd.has_key("group"):
            if not self.repomd["group"].has_key("location"):
                log.error("Couldn't find proper location for comps.xml in repomd")
                return 0
            comps = self.repomd["group"]["location"]
            (csum, destfile) = self.nc.checksum(comps, "sha")
            if self.repomd["group"].has_key("checksum") and \
                   csum == self.repomd["group"]["checksum"]:
                filename = destfile
            else:
                filename = self.nc.cache(comps, 1)
            if not filename:
                return 0
            try:
                self.comps = RpmCompsXML(self.config, filename)
                self.comps.read()
            except IOError:
                return 0
        return 1

    def readPrimary(self):
        # If we have either a local cache of the primary.xml.gz file or if
        # it is already local (nfs or local file system) we calculate it's
        # checksum and compare it with the one from repomd. If they are
        # the same we don't need to cache it again and can directly use it.
        if self.repomd.has_key("primary"):
            if not self.repomd["primary"].has_key("location"):
                return 0
            primary = self.repomd["primary"]["location"]
            (csum, destfile) = self.nc.checksum(primary, "sha")
            if self.repomd["primary"].has_key("checksum") and \
                   csum == self.repomd["primary"]["checksum"]:
                filename = destfile
            else:
                filename = self.nc.cache(primary, 1)
            if not filename:
                return 0
            try:
                fd = PyGZIP(filename)
                ip = iterparse(fd, events=("start","end"))
                ip = iter(ip)
            except IOError:
                log.error("Couldn't parse primary.xml")
                return 0
            self._parse(ip)
        return 1

    def readPGPKeys(self):
        for url in self.key_urls:
            filename = self.nc.cache(url, 1)
            try:
                f = file(filename)
                key_data = f.read()
                f.close()
            except Exception, e:
                log.error("Error reading GPG key %s: %s", filename, e)
                continue
            try:
                key_data = openpgp.isolateASCIIArmor(key_data)
                keys = openpgp.parsePGPKeys(key_data)
            except Exception, e:
                log.error("Invalid GPG key %s: %s", url, e)
                continue
            for k in keys:
                self.keyring.addKey(k)
        return 1

    def read(self):
        self.readMirrorList()
        #self.is_read = 1 # FIXME: write-only
        while True:
            if not self.readRepoMD():
                break
            if not self.readComps():
                break
            if not self.readPrimary():
                break
            if not self.readPGPKeys():
                break
            self.is_read = 1 # FIXME: write-only
            return 1
        return 0

    def getNetworkCache(self):
        return self.nc

    def addPkg(self, pkg):
        if self._isExcluded(pkg):
            return 0
        return memorydb.RpmMemoryDB.addPkg(self, pkg)

    def isFilelistImported(self):
        return self.filelist_imported

    def importFilelist(self):
        """Parse filelists.xml.gz if it was not parsed before.

        Return 1 on success, 0 on failure."""

        # We need to have successfully read a repo from one source before we
        # can import it's filelist.
        if not self.is_read:
            return 0
        if self.filelist_imported:
            return 1
        # Same as with primary.xml.gz: If we already have a local version and
        # it matches the checksum found in repomd then we don't need to
        # download it again.
        if self.repomd.has_key("filelists"):
            if not self.repomd["filelists"].has_key("location"):
                return 0
            filelists = self.repomd["filelists"]["location"]
            (csum, destfile) = self.nc.checksum(filelists, "sha")
            if self.repomd["filelists"].has_key("checksum") and \
                   csum == self.repomd["filelists"]["checksum"]:
                filename = destfile
            else:
                filename = self.nc.cache(filelists, 1)
            if not filename:
                return 0
            try:
                fd = PyGZIP(filename)
                ip = iterparse(fd, events=("start","end"))
                ip = iter(ip)
            except IOError:
                log.error("Couldn't parse filelists.xml")
                return 0
            self._parse(ip)
            self.filelist_imported = 1
        return 1

    def createRepo(self):
        """Create repodata metadata for self.source.

        Return 1 on success, 0 on failure.  Assumes self.source is a local file
        system path without schema prefix."""

        import gzip
        log.info1("Pass 1: Parsing package headers for file requires.")
        self.__readDir(self.source, "")
        filename = functions._uriToFilename(self.source)
        datapath = os.path.join(filename, "repodata")
        if not os.path.isdir(datapath):
            try:
                os.makedirs(datapath)
            except OSError, e:
                log.error("%s: Couldn't create repodata: %s", filename, e)
                return 0
        try:
            pfd = gzip.GzipFile(os.path.join(datapath, "primary.xml.gz"), "wb")
        except IOError:
            return 0
        try:
            ffd = gzip.GzipFile(os.path.join(datapath, "filelists.xml.gz"),
                                "wb")
        except IOError:
            return 0
        try:
            rfd = open(os.path.join(datapath, "repomd.xml"))
        except IOError:
            return 0
        #try:
        #    ofd = gzip.GzipFile(os.path.join(datapath, "other.xml.gz"), "wb")
        #except IOError:
        #    return 0
        pdoc = libxml2.newDoc("1.0")
        proot = pdoc.newChild(None, "metadata", None)
        fdoc = libxml2.newDoc("1.0")
        froot = fdoc.newChild(None, "filelists", None)
        #odoc = libxml2.newDoc("1.0")
        #oroot = odoc.newChild(None, "filelists", None)
        log.info1("Pass 2: Writing repodata information.")
        pfd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        pfd.write('<metadata xmlns="http://linux.duke.edu/metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="%d">\n' % len(self.getPkgs()))
        ffd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        ffd.write('<filelists xmlns:rpm="http://linux.duke.edu/filelists" packages="%d">\n' % len(self.getPkgs()))
        for pkg in self.getPkgs():
            log.info2("Processing complete data of package %s.",
                      pkg.getNEVRA())
            pkg.header_read = 0
            try:
                pkg.open()
                pkg.read()
            except (IOError, ValueError), e:
                log.warning("%s: %s", pkg.getNEVRA(), e)
                continue
            # If it is a source rpm change the arch to "src". Only valid
            # for createRepo, never do this anywhere else. ;)
            if pkg.isSourceRPM():
                pkg["arch"] = "src"
            try:
                checksum = self.__getChecksum(pkg)
            except (IOError, NotImplementedError), e:
                log.warning("%s: %s", pkg.getNEVRA(), e)
                continue
            pkg["yumchecksum"] = checksum
            self.__writePrimary(pfd, proot, pkg)
            self.__writeFilelists(ffd, froot, pkg)
#            self.__writeOther(ofd, oroot, pkg)
            try:
                pkg.close()
            except IOError:
                pass # Should not happen when opening for reading anyway
            pkg.clear()
        pfd.write('</metadata>\n')
        ffd.write('</filelists>\n')
        pfd.close()
        ffd.close()
        # Write repomd.xml
        rfd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        rfd.write('<repomd xmlns="http://linux.duke.edu/metadata/repo">\n')
        rfd.write('  <data type="primary">\n')
        rfd.write('    <location href="repodata/primary.xml.gz"/>\n')
        rfd.write('  </data>\n')
        rfd.write('  <data type="filelists">\n')
        rfd.write('    <location href="repodata/filelists.xml.gz"/>\n')
        rfd.write('  </data>\n')
# how do we know that there is a comps file?
#        rfd.write('  <data type="group">\n')
#        rfd.write('    <location href="repodata/comps.xml"/>\n')
#        rfd.write('  </data>\n')
        rfd.write('</repomd>\n')
        rfd.close()
        return 1

    def _matchesFile(self, fname):
        return self._filerc.match(fname) or \
               self._dirrc.match(fname)

    def _parse(self, ip):
        """Parse <package> tags from libxml2.xmlTextReader reader."""

        for event, elem in ip:
            tag = elem.tag
            if event != "start":
                continue
            if not tag.endswith("}package") and \
               not tag.endswith("}repomd"):
                continue
            if tag.endswith("}repomd"):
                return self.__parseRepomd(ip)
            props = elem.attrib
            if   props.get("type") == "rpm":
                try:
                    pkg = self.__parsePackage(ip)
                except ValueError, e:
                    log.warning("%s: %s", pkg.getNEVRA(), e)
                    continue
                # pkg can be None if it is excluded
                if pkg == None:
                    continue
                pkg.yumrepo = self
                if self.comps != None:
                    if   self.comps.hasType(pkg["name"], "mandatory"):
                        pkg.compstype = "mandatory"
                    elif self.comps.hasType(pkg["name"], "default"):
                        pkg.compstype = "default"
                    elif self.comps.hasType(pkg["name"], "optional"):
                        pkg.compstype = "optional"
                self.addPkg(pkg)
            elif props.has_key("name"):
                arch = props.get("arch")
                if arch == None:
                    log.warning("%s: missing arch= in <package>",
                                pkg.getNEVRA())
                    continue
                self.__parseFilelist(ip, props["name"], arch)

    def _isExcluded(self, pkg):
        """Return True if RpmPackage pkg is excluded by configuration."""

        if pkg["arch"] == "src":
            return 1
        if not self.config.ignorearch and \
           (not functions.archCompat(pkg["arch"], self.config.machine) or \
            (self.config.archlist != None and not pkg["arch"] in self.config.archlist)) and \
           not pkg.isSourceRPM():
                log.warning("%s: Package excluded because of arch "
                            "incompatibility", pkg.getNEVRA())
                return 1

        index = lists.NevraList()
        index.addPkg(pkg)
        result = index.search(self.excludes)
        return bool(result)

    def __escape(self, s):
        """Return escaped string converted to UTF-8"""

        if s == None:
            return ''
        s = s.replace("&", "&amp;")
        if isinstance(s, unicode):
            return s
        try:
            x = unicode(s, 'ascii')
            return s
        except UnicodeError:
            encodings = ['utf-8', 'iso-8859-1', 'iso-8859-15', 'iso-8859-2']
            for enc in encodings:
                try:
                    x = unicode(s, enc)
                except UnicodeError:
                    pass
                else:
                    if x.encode(enc) == s:
                        return x.encode('utf-8')
        newstring = ''
        for char in s:
            if ord(char) > 127:
                newstring = newstring + '?'
            else:
                newstring = newstring + char
        return re.sub("\n$", '', newstring) # FIXME: not done in other returns

    def __parseRepomd(self, ip):
        """Parse repomd.xml for SHA1 checks of the files.
        Returns a hash of the form:
          name -> {location, checksum, timestamp, open-checksum}"""
        rethash = {}
        # Make local variables for heavy used functions to speed up this loop
        tmphash = {}
        fname = None
        for event, elem in ip:
            isend = (event == "end")
            props = elem.attrib
            tag = elem.tag
            if not isend and tag.endswith("}data"):
                fname = props.get("type")
                if not fname:
                    break
                tmphash = {}
                rethash[fname] = tmphash
            if not isend:
                continue
            if   tag.endswith("}repomd"):
                break
            elif tag.endswith("}location"):
                loc = props.get("href")
                if loc:
                    tmphash["location"] = loc
            elif tag.endswith("}checksum"):
                type = props.get("type")
                if type != "sha":
                    log.warning("Unsupported checksum type %s in repomd.xml "
                                "for file %s", type, fname)
                    continue
                tmphash["checksum"] = elem.text
            elif tag.endswith("}timestamp"):
                tmphash["timestamp"] = elem.text
            elif tag.endswith("}open-checksum"):
                type = props.get("type")
                if type != "sha":
                    log.warning("Unsupported open-checksum type %s in "
                                "repomd.xml for file %s", type, fname)
                    continue
                tmphash["open-checksum"] = elem.text
        return rethash

    def __parsePackage(self, ip):
        """Parse a package from current <package> tag at libxml2.xmlTextReader
        reader.

        Raise ValueError on invalid data."""

        pkg = package.RpmPackage(self.config, "dummy", db = self)
        pkg["signature"] = {}
        pkg["signature"]["size_in_sig"] = [0,]
        pkg.time_file = None
        pname = None
        pepoch = None
        pversion = None
        prelease = None
        parch = None
        excheck = 0
        for event, elem in ip:
            tag = elem.tag
            if tag.endswith("}format"):
                self.__parseFormat(ip, pkg)
            isend = (event == "end")
            if not isend:
                continue
            props = elem.attrib
            if tag.endswith("}package"):
                break
            elif not excheck and pname != None and pepoch != None and \
                 pversion != None and prelease != None and parch != None:
                excheck = 1
                if self._isExcluded(pkg):
                    return None
            if tag.endswith("}name"):
                pname = elem.text
                pkg["name"] = pname
            elif tag.endswith("}arch"):
                parch = elem.text
                pkg["arch"] = parch
                if parch != "src":
                    pkg["sourcerpm"] = ""
            elif tag.endswith("}version"):
                pversion = props.get("ver")
                prelease = props.get("rel")
                pepoch = props.get("epoch")
                if pversion == None or prelease == None or pepoch == None:
                    raise ValueError, "Missing attributes of <version>"
                pepoch = [int(pepoch),]
                pkg["version"] = pversion
                pkg["release"] = prelease
                pkg["epoch"] = pepoch
            elif tag.endswith("}checksum"):
                type_ = props.get("type")
                if   type_ == "md5":
                    pkg["signature"]["md5"] = elem.text
                elif type_ == "sha":
                    pkg["signature"]["sha1header"] = elem.text
                else:
                    raise ValueError, "Wrong or missing type= in <checksum>"
            elif tag.endswith("}location"):
                href = props.get("href")
                if href == None:
                    raise ValueError, "Missing href= in <location>"
                if self.config.nocache:
                    pkg.source = os.path.join(self.nc.getBaseURL(self.reponame), href)
                else:
                    pkg.source = href
                pkg.yumhref = href
            elif tag.endswith("}size"):
                size_in_sig = props.get("package")
                if size_in_sig == None:
                    raise ValueError, "Missing package= in <size>"
                pkg["signature"]["size_in_sig"][0] += int(size_in_sig)
                pkg.sizes = props
            elif tag.endswith("}time"):
                pkg.time_file = props.get('file')
                pkg['buildtime'] = props.get('build')
            else:
                for pkgtag, xmltag in (("summary", "summary"),
                                       ("description", "description"),
                                       ("url", "url"),
                                       ("packager", "packager")):
                    if not tag.endswith("}%s" % xmltag):
                        continue
                    if elem.text == None or elem.text == '\n  ':
                        pkg[pkgtag] = None # fix for empty tags
                    else:
                        pkg[pkgtag] = elem.text
                else:
                    continue
                break # break while loop if break in for loop
        pkg.header_read = 1
        pkg["provides"] = pkg.getProvides()
        pkg["requires"] = pkg.getRequires()
        pkg["obsoletes"] = pkg.getObsoletes()
        pkg["conflicts"] = pkg.getConflicts()
        pkg["triggers"] = pkg.getTriggers()
        # clean up list
        for tag in ("provide", "require", "obsolete",
                    "conflict", "trigger"):
            for suffix in ("name", "flags", "version"):
                pkg.pop(tag + suffix, None) # remove if set
        return pkg

    def __parseFilelist(self, ip, pname, arch):
        """Parse a file list from current <package name=pname> tag at
        libxml2.xmlTextReader reader for package with arch arch.

        Raise ValueError on invalid data."""

        filelist = []
        typelist = []
        version, release, epoch = None, None, None
        for event, elem in ip:
            tag = elem.tag
            isend = (event == "end")
            if not isend:
                continue
            props = elem.attrib
            if   tag.endswith("}file"):
                filelist.append(elem.text)
                typelist.append(props.get("type", "file"))
            elif tag.endswith("}version"):
                version = props.get("ver")
                release = props.get("rel")
                epoch   = props.get("epoch")
            elif tag.endswith("}package"):
                break
        if version is None or release is None or epoch is None:
            raise ValueError, "Missing version information"
        self._addFilesToPkg(pname, epoch, version, release, arch,
                           filelist, typelist)

    def __parseFormat(self, ip, pkg):
        """Parse data from current <format> tag at libxml2.xmlTextReader reader
        to RpmPackage pkg.

        Raise ValueError on invalid input."""

        pkg["oldfilenames"] = []
        pkg.filetypelist = []
        for event, elem in ip:
            tag = elem.tag
            isend = (event == "end")
            props = elem.attrib
            if not isend:
                for rtag in ("provide", "require", "obsolete", "conflict"):
                    if not tag.endswith("}%ss" % rtag):
                        continue
                    plist = self.__parseDeps(ip, rtag)
                    (pkg[rtag + 'name'], pkg[rtag + 'flags'],
                     pkg[rtag + 'version']) = plist
            if not isend:
                continue
            if   tag.endswith("}file"):
                pkg.filetypelist.append(props.get("type", "file"))
                pkg["oldfilenames"].append(elem.text)
            elif tag.endswith("}format"):
                break
            elif tag.endswith("}header-range"):
                header_start = props.get("start")
                header_end = props.get("end")
                if header_start == None or header_end == None:
                    raise ValueError, "Missing property in <rpm:header_range>"
                header_start = int(header_start)
                header_end = int(header_end)
                pkg["signature"]["size_in_sig"][0] -= header_start
                pkg.range_signature = [96, header_start-96]
                pkg.range_header = [header_start, header_end-header_start]
                pkg.range_payload = [header_end, None]
            else:
                for rtag in ("license", "sourcerpm",
                                       "vendor", "buildhost", "group"):
                    if not tag.endswith("}%s" % rtag):
                        continue
                    pkg[rtag] = elem.text

    def __parseDeps(self, ip, ename):
        """Parse a dependency list from currrent tag ename at
        libxml2.xmlTextReader reader.

        Return [namelist, flaglist, versionlist].  Raise ValueError on invalid
        input."""

        plist = [[], [], []]
        for event, elem in ip:
            tag = elem.tag
            isend = (event == "end")
            if not isend:
                continue 
            if tag.endswith("}%ss" % ename):
                break
            props = elem.attrib
            if tag.endswith("}entry"):
                name = props.get("name")
                if name == None:
                    raise ValueError, "Missing name= in <rpm.entry>"
                ver = props.get("ver")
                flags = props.get("flags")
                if props.has_key("pre"):
                    prereq = RPMSENSE_PREREQ
                else:
                    prereq = 0
                if ver == None:
                    plist[0].append(name)
                    plist[1].append(prereq)
                    plist[2].append("")
                    continue
                epoch = props.get("epoch")
                rel = props.get("rel")
                if epoch != None:
                    ver = "%s:%s" % (epoch, ver)
                if rel != None:
                    ver = "%s-%s" % (ver, rel)
                plist[0].append(name)
                try:
                    flags = self.flagmap[flags]
                except KeyError:
                    raise ValueError, "Unknown flags %s" % flags
                plist[1].append(flags + prereq)
                plist[2].append(ver)
        return plist

    def _addFilesToPkg(self, pname, epoch, version, release, arch,
                      filelist, filetypelist):
        nevra = "%s-%s:%s-%s.%s" % (pname, epoch, version, release, arch)
        pkgs = self.getPkgsByName(pname)
        dhash = {}
        for pkg in pkgs:
            if pkg.getNEVRA() == nevra:
                if len(dhash) == 0:
                    (didx, dnameold) = (-1, None)
                    (dnames, dindexes, bnames) = ([], [], [])
                    for f in filelist:
                        idx = f.rindex("/")
                        if idx < 0:
                            raise ValueError, "Couldn't find '/' in filename from filelist"
                        dname = f[:idx+1]
                        fname = f[idx+1:]
                        dhash.setdefault(dname, []).append(fname)
                        bnames.append(fname)
                        if dnameold == dname:
                            dindexes.append(didx)
                        else:
                            dnames.append(dname)
                            didx += 1
                            dindexes.append(didx)
                            dnameold = dname
                pkg["dirnames"] = dnames
                pkg["dirindexes"] = dindexes
                pkg["basenames"] = bnames
                if pkg.has_key("oldfilenames"):
                    del pkg["oldfilenames"]
                pkg.filetypelist = filetypelist
                # get rid of old dirnames, dirindexes and basenames
                #if pkg.has_key("dirnames"):
                #    del pkg["dirnames"]
                #if pkg.has_key("dirindexes"):
                #    del pkg["dirindexes"]
                #if pkg.has_key("basenames"):
                #    del pkg["basenames"]
                #pkg["oldfilenames"] = filelist

    def __readDir(self, dir, location):
        """Look for non-excluded *.rpm files under dir and add them to
        self.pkglist.

        dir must be a local file system path.  The remote location prefix
        corresponding to dir is location. Set pkg["yumlocation"] to the remote
        relative path to the package."""

        tmplist = []
        functions.readDir(dir, tmplist,
                          ("name", "epoch", "version", "release", "arch",
                           "sourcerpm", "requirename", "requireflags",
                           "requireversion"))
        for pkg in tmplist:
            if self._isExcluded(pkg):
                continue
            # FIXME: this is done in createRepo too
            # If it is a source rpm change the arch to "src". Only valid
            # for createRepo, never do this anywhere else. ;)
            if pkg.isSourceRPM():
                pkg["arch"] = "src"
            nevra = pkg.getNEVRA()
            log.info2("Adding %s to repo and checking file requires.", nevra)
            pkg["yumlocation"] = location+pkg.source[len(dir):]
            self.addPkg(pkg)

    def __writePrimary(self, fd, parent, pkg):
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('type', 'rpm')
        pkg_node.newChild(None, 'name', pkg['name'])
        pkg_node.newChild(None, 'arch', pkg['arch'])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        tnode = pkg_node.newChild(None, 'checksum', pkg["yumchecksum"])
        tnode.newProp('type', self.config.checksum)
        tnode.newProp('pkgid', 'YES')
        pkg_node.newChild(None, 'summary', self.__escape(pkg['summary'][0]))
        pkg_node.newChild(None, 'description', self.__escape(pkg['description'][0]))
        pkg_node.newChild(None, 'packager', self.__escape(pkg['packager']))
        pkg_node.newChild(None, 'url', self.__escape(pkg['url']))
        tnode = pkg_node.newChild(None, 'time', None)
        tnode.newProp('file', str(pkg['buildtime'][0]))
        tnode.newProp('build', str(pkg['buildtime'][0]))
        tnode = pkg_node.newChild(None, 'size', None)
        tnode.newProp('package', str(pkg['signature']['size_in_sig'][0]+pkg.range_signature[0]+pkg.range_signature[1]))
        tnode.newProp('installed', str(pkg['size'][0]))
        tnode.newProp('archive', str(pkg['signature']['payloadsize'][0]))
        tnode = pkg_node.newChild(None, 'location', None)
        tnode.newProp('href', pkg["yumlocation"])
        fnode = pkg_node.newChild(None, 'format', None)
        self.__generateFormat(fnode, pkg)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __writeFilelists(self, fd, parent, pkg):
        """Write primary.xml data about RpmPackage pkg to fd.

        Use libxml2.xmlNode parent as root of a temporary xml subtree."""

        pkg_node = parent.newChild(None, "package", None)
        pkg_node.newProp('pkgid', pkg["yumchecksum"])
        pkg_node.newProp('name', pkg["name"])
        pkg_node.newProp('arch', pkg["arch"])
        tnode = pkg_node.newChild(None, 'version', None)
        if pkg.has_key('epoch'):
            tnode.newProp('epoch', str(pkg['epoch'][0]))
        else:
            tnode.newProp('epoch', '0')
        tnode.newProp('ver', pkg['version'])
        tnode.newProp('rel', pkg['release'])
        self.__generateFilelist(pkg_node, pkg, 0)
        output = pkg_node.serialize('UTF-8', self.config.pretty)
        fd.write(output+"\n")
        pkg_node.unlinkNode()
        pkg_node.freeNode()
        del pkg_node

    def __getChecksum(self, pkg):
        """Return checksum of package source of RpmPackage pkg.

        Raise IOError, NotImplementedError."""

        from pyrpm.io import getRpmIOFactory
        io = getRpmIOFactory(pkg.source)
        if self.config.checksum == "md5":
            import md5
            s = md5.new()
        else:
            import sha
            s = sha.new()
        io.updateDigestFromRange(s, 0, None)
        return s.hexdigest()

    def __generateFormat(self, node, pkg):
        """Add RPM-specific tags under libxml2.xmlNode node for RpmPackage
        pkg."""

        node.newChild(None, 'rpm:license', self.__escape(pkg['license']))
        node.newChild(None, 'rpm:vendor', self.__escape(pkg['vendor']))
        node.newChild(None, 'rpm:group', self.__escape(pkg['group'][0]))
        node.newChild(None, 'rpm:buildhost', self.__escape(pkg['buildhost']))
        node.newChild(None, 'rpm:sourcerpm', self.__escape(pkg['sourcerpm']))
        tnode = node.newChild(None, 'rpm:header-range', None)
        tnode.newProp('start', str(pkg.range_signature[0] + pkg.range_signature[1]))
        tnode.newProp('end', str(pkg.range_payload[0]))
        if len(pkg["provides"]) > 0:
            self.__generateDeps(node, pkg, "provides")
        if len(pkg["requires"]) > 0:
            self.__generateDeps(node, pkg, "requires")
        if len(pkg["conflicts"]) > 0:
            self.__generateDeps(node, pkg, "conflicts")
        if len(pkg["obsoletes"]) > 0:
            self.__generateDeps(node, pkg, "obsoletes")
        self.__generateFilelist(node, pkg)

    def __generateDeps(self, node, pkg, name):
        """Add RPM-specific dependency info under libxml2.xmlNode node for
        RpmPackage pkg dependencies "name"."""

        dnode = node.newChild(None, 'rpm:%s' % name, None)
        deps = self.__filterDuplicateDeps(pkg[name])
        for dep in deps:
            enode = dnode.newChild(None, 'rpm:entry', None)
            enode.newProp('name', dep[0])
            if dep[1] != "":
                if (dep[1] & RPMSENSE_SENSEMASK) != 0:
                    enode.newProp('flags', self.flagmap[dep[1] & RPMSENSE_SENSEMASK])
                if isLegacyPreReq(dep[1]) or isInstallPreReq(dep[1]):
                    enode.newProp('pre', '1')
            if dep[2] != "":
                e,v,r = functions.evrSplit(dep[2])
                enode.newProp('epoch', e)
                enode.newProp('ver', v)
                if r != "":
                    enode.newProp('rel', r)

    def __generateFilelist(self, node, pkg, filter=1):
        """Add RPM-specific file list under libxml2.xmlNode node for RpmPackage
        pkg.

        Restrict the output to _dirrc/_filerc or known file requires if
        filter."""

        files = pkg['filenames']
        fileflags = pkg['fileflags']
        filemodes = pkg['filemodes']
        if files == None or fileflags == None or filemodes == None:
            return
        (writefile, writedir, writeghost) = ([], [], [])
        for (fname, mode, flag) in zip(files, filemodes, fileflags):
            if stat.S_ISDIR(mode):
                if not filter or \
                   self._dirrc.match(fname):
                    writedir.append(fname)
            elif not filter or \
                 self._filerc.match(fname):
                if flag & RPMFILE_GHOST:
                    writeghost.append(fname)
                else:
                    writefile.append(fname)
        writefile.sort()
        for f in writefile:
            tnode = node.newChild(None, "file", self.__escape(f))
        writedir.sort()
        for f in writedir:
            tnode = node.newChild(None, "file", self.__escape(f))
            tnode.newProp("type", "dir")
        writeghost.sort()
        for f in writeghost:
            tnode = node.newChild(None, "file", self.__escape(f))
            tnode.newProp("type", "ghost")

    def __filterDuplicateDeps(self, deps):
        """Return the list of (name, flags, release) dependencies deps with
        duplicates (when output by __generateDeps ()) removed."""

        fdeps = []
        for (name, flags, version) in deps:
            flags &= RPMSENSE_SENSEMASK | RPMSENSE_PREREQ
            if (name, flags, version) not in fdeps:
                fdeps.append((name, flags, version))
        fdeps.sort()
        return fdeps

# vim:ts=4:sw=4:showmatch:expandtab
