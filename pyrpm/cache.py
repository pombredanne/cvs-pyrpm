#
# Copyright (C) 2006 Red Hat, Inc.
# Author: Phil Knirsch
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


import os, os.path, md5, sha, shutil, sys
from pyrpm.functions import _uriToFilename, updateDigestFromFile

try:
    from urlgrabber import urlgrab, urlopen
    from urlgrabber.grabber import URLGrabError
except ImportError:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module for NetworkCache."


class NetworkCache:
    """Class to handle caching network files to a local directory"""

    def __init__(self, baseurls, cachedir="/var/cache/pyrpm/", name='default'):
        self.default_name = name
        self.cachedir = cachedir
        self.baseurls = { }
        self.pos = { }
        self.is_local = { }
        self.baseurls[name] = baseurls
        self.pos[name] = 0
        self.is_local[name] = self.__isLocalURI(self.baseurls[name])

    def __isLocalURI(self, uris):
        is_local = True
        for uri in uris:
            is_local = is_local and uri.startswith("file://")
        return is_local

    def __isURI(self, uri):
        return uri.startswith("http://") or uri.startswith("ftp://") or \
               uri.startswith("file://")

    def __makeRel(self, uri):
        if uri[0] == "/":
            return uri[1:]
        return uri

    def __createSourceURI(self, uri, name=None):
        if name == None:
            name == self.default_name
        if self.__isURI(uri):
            sourceurl = uri
        else:
            sourceurl = os.path.join(self.getBaseURL(), uri)
        return sourceurl

    def __getCachedir(self, name=None):
        if name == None:
            name == self.default_name
        cdir = os.path.join(self.cachedir, name)
        return os.path.join(cdir, "cache")

    def __getExternalCachedir(self, name=None):
        if name == None:
            name == self.default_name
        cdir = os.path.join(self.cachedir, name)
        return os.path.join(cdir, "external")

    def addCache(self, baseurls, name=None):
        """Adds the given baseurls to the cache. If no name is given the
        None is assumed."""

        if name == None:
            name = self.default_name
        self.baseurls.setdefault(name, []).extend(baseurls)
        self.is_local[name] = self.__isLocalURI(self.baseurls[name])

    def setCache(self, baseurls, name=None):
        """Sets the given baseurls of the cache. If no name is given the
        None is assumed."""

        if name == None:
            name = self.default_name
        self.baseurls[name] = baseurls
        self.pos[name] = 0
        self.is_local[name] = self.__isLocalURI(self.baseurls[name])

    def delCache(self, baseurls, name=None):
        """Deletes the given baseurls from the cache. If no name is given the
        None is assumed."""

        if name == None:
            name = self.default_name
        self.baseurls.setdefault(name, [])
        for url in baseurls:
            self.baseurls[name].remove(url)
        self.pos[name] = 0
        self.is_local[name] = self.__isLocalURI(self.baseurls[name])

    def getBaseURL(self, name=None):
        """Return the current baseurl for the given cache name."""

        if name == None:
            name = self.default_name
        return self.baseurls[name][self.pos[name]]

    def getBaseURLs(self, name=None):
        """Return a list of baseurl for the given cache name."""

        if name == None:
            name = self.default_name
        return self.baseurls[name]

    def isCached(self, uri, name=None):
        """Check if the given uri/file is already cached."""

        if name == None:
            name = self.default_name
        return os.path.isfile(self.getCachedFilename(uri, name))

    def getCachedFilename(self, uri, name=None):
        """Returns the local cached filename of the given uri/file"""

        if name == None:
            name = self.default_name
        if self.baseurls.has_key(name):
            for baseurl in self.baseurls[name]:
                if uri.startswith(baseurl):
                    uri = uri[len(baseurl):]
                    break
        if self.__isURI(uri):
            return os.path.join(self.__getExternalCachedir(name), uri)
        if self.__isLocalURI([uri,]):
            return _uriToFilename(uri)
        return os.path.join(self.__getCachedir(name), self.__makeRel(uri))

    def open(self, uri, name=None):
        """Tries to open the given URI and returns a filedescriptor if
        successfull, None otherwise."""

        if name == None:
            name = self.default_name
        if self.is_local[name] and not self.__isURI(uri):
            path = os.path.join(self.baseurl, self.__makeRel(uri))
            try:
                return open(path)
            except IOError:
                return None
        opos = self.pos[name]
        while True:
            sourceurl = self.__createSourceURI(uri, name)
            try:
                f = urlopen(sourceurl)
            except IOError:
                f = None
            # We managed to find and open the file, return the descriptor.
            if f != None:
                return f
            # If we didn't find that file go to next baseurl in our list. In
            # case we wrap and have tried all our baseurls finally return an
            # error.
            self.pos[name] = (self.pos[name] + 1) % len(self.baseurls[name])
            if self.pos[name] == opos:
                return None

    def cache(self, uri, force=False, copy_local=False, size=-1, md5=0, async=False, name=None):
        """Cache the given uri/file. If the uri is a real uri then we cache it
        in our external cache, otherwise we use our baseurl and treat the
        parameter as a relative path to it."""

        if name == None:
            name = self.default_name
        if not copy_local:
            path = None
            if  self.__isLocalURI([uri,]):
                path = _uriToFilename(uri)
            elif self.is_local[name] and not self.__isURI(uri):
                path = _uriToFilename(os.path.join(self.getBaseURL(), self.__makeRel(uri)))
            if path:
                if os.path.exists(path):
                    return path
                return None
        destfile = self.getCachedFilename(uri, name)
        if not os.path.isdir(os.path.dirname(destfile)):
            try:
                os.makedirs(os.path.dirname(destfile))
            except OSError:
                pass
        opos = self.pos[name]
        while True:
            sourceurl = self.__createSourceURI(uri, name)
            try:
                if force:
                    f = urlgrab(sourceurl, destfile,
                                timeout=30.0, copy_local=copy_local)
                else:
                    f = urlgrab(sourceurl, destfile, timeout=30.0,
                                reget='check_timestamp', copy_local=copy_local)
            except Exception, e:
                # urlgrab fails with invalid range for already completely
                # transfered files, pretty strange to me to be honest... :)
                if e[0] == 9:
                    f = destfile
                else:
                    f = None
            # We managed to find and cache a file, so return it.
            if f != None:
                return f
            # If we didn't find that file go to next baseurl in our list. In
            # case we wrap and have tried all our baseurls finally return an
            # error.
            self.pos[name] = (self.pos[name] + 1) % len(self.baseurls[name])
            if self.pos[name] == opos:
                return None

    def clear(self, uri=None, name=None):
        """Clears either the single given uri/file or the whole cache"""

        if name == None:
            name = self.default_name
        # If no URI is give clears the whole cache. Use with caution. ;)
        if not uri:
            try:
                shutil.rmtree(self.cachedir[name])
                shutil.rmtree(self.external_cachedir[name])
                return 1
            except EnvironmentError:
                return 0
        if self.isCached(uri):
            os.unlink(self.getCachedFilename(uri, name))
        return 1

    def checksum(self, uri, cstype, name=None):
        """Calculates and returns the checksum for a give URL and corresponding
        subdir. The type parameter is either "sha" or "md5".

        Returns None if no cache file for the given URL is there or a wrong type
        was given, otherwise the calculated checksum."""

        if name == None:
            name = self.default_name
        digest = None
        if   cstype == "sha":
            digest = sha.new()
        elif cstype == "md5":
            digest = md5.new()
        else:
            return (None, None)

        fname = self.getCachedFilename(uri, name)

        if (not os.path.exists(fname) and
            self.is_local[name] and not self.__isURI(uri)):
            fname = os.path.join(self.getBaseURL(), self.__makeRel(uri))
        try:
            fd = open(fname)
            updateDigestFromFile(digest, fd)
            return (digest.hexdigest(), fname)
        except IOError:
            return (None, None)


class SubNetworkCache:
    def __init__(self, nc, prefix):
        self.nc = nc
        self.prefix = prefix

    def addCache(self, baseurls, name=None):
        self.nc.addCache(baseurls, name)

    def setCache(self, baseurls, name=None):
        self.nc.setCache(baseurls, name)

    def delCache(self, baseurls, name=None):
        self.nc.delCache(baseurls, name)

    def getBaseURL(self, name=None):
        return self.nc.getBaseURL(name) + "/" + self.prefix

    def getBaseURLs(self, name=None):
        return ["%s/%s" % (url, self.prefix) for url in self.nc.getBaseURLs(name)]

    def isCached(self, uri, name=None):
        return self.nc.isCached(self.prefix + "/" + uri, name)

    def getCachedFilename(self, uri, name=None):
        return self.nc.getCachedFilename(self.prefix + "/" + uri, name)

    def open(self, uri, name=None):
        return self.nc.open(self.prefix + "/" + uri, name)

    def cache(self, uri, force=False, copy_local=False, size=-1, md5=0, async=False, name=None):
        return self.nc.cache(self.prefix + "/" + uri, force=False, copy_local=False, size=-1, md5=0, async=False, name=None)

    def clear(self, uri=None, name=None):
        if uri == None:
            uri == ''
        return self.nc.clear(self.prefix + "/" + uri, name)

    def checksum(self, uri, cstype, name=None):
        return self.nc.checksum(self.prefix + "/" + uri, cstype, name=None)

# vim:ts=4:sw=4:showmatch:expandtab
