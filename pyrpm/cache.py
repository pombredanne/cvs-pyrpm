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
    from urlgrabber import urlgrab
    from urlgrabber.grabber import URLGrabError
except:
    print >> sys.stderr, "Error: Couldn't import urlgrabber python module for NetworkCache."


class NetworkCache:
    """Class to handle caching network files to a local directory"""

    def __init__(self, baseurl, cachepath="/var/cache/pyrpm/"):
        self.baseurl = baseurl
        self.main_cachepath = os.path.join(cachepath, "main")
        self.external_cachepath = os.path.join(cachepath, "external")
        self.is_local = self.__isLocalURI(baseurl)
        if self.is_local:
            self.baseurl = _uriToFilename(self.baseurl)

    def __isLocalURI(self, uri):
        return uri.startswith("file://")

    def __isURI(self, uri):
        return uri.startswith("http://") or uri.startswith("ftp://") or \
               uri.startswith("file://")

    def __createSourceURI(self, uri):
        if self.__isURI(uri):
            sourceurl = uri
        else:
            sourceurl = os.path.join(self.baseurl, uri)
        return sourceurl

    def isCached(self, uri):
        """Check if the given uri/file is already cached."""

        return os.path.isfile(self.getCachedFilename(uri))

    def getCachedFilename(self, uri):
        """Returns the local cached filename of the given uri/file"""
        if self.__isURI(uri):
            return os.path.join(self.external_cachepath, uri)
        if self.__isLocalURI(uri):
            return _uriToFilename(uri)
        return os.path.join(self.main_cachepath, uri)

    def open(self, uri):
        """Tries to open the given URI and returns a filedescriptor if
        successfull, None otherwise."""

        if self.is_local and not self.__isURI(uri):
            path = os.path.join(self.baseurl, uri)
            try:
                return open(path)
            except:
                return None
        sourceurl = self.__createSourceURI(uri)
        try:
            return urlopen(sourceurl)
        except:
            return None

    def cache(self, uri, force=0):
        """Cache the given uri/file. If the uri is a real uri then we cache it
        in our external cache, otherwise we use our baseurl and treat the
        parameter as a relative path to it."""

        if self.is_local and not self.__isURI(uri):
            path = os.path.join(self.baseurl, uri)
            if os.path.exists(path):
                return path
            return None
        sourceurl = self.__createSourceURI(uri)
        destfile = self.getCachedFilename(uri)
        if not os.path.isdir(os.path.dirname(destfile)):
            try:
                os.makedirs(os.path.dirname(destfile))
            except:
                pass
        try:
            if force:
                f = urlgrab(sourceurl, destfile, timeout=30.0)
            else:
                f = urlgrab(sourceurl, destfile, timeout=30.0, reget='check_timestamp')
        except Exception, e:
            # urlgrab fails with invalid range for already completely transfered
            # files, pretty strange to me to be honest... :)
            if e[0] == 9:
                return destfile
            else:
                return None
        return f

    def clear(self, uri=None):
        """Clears either the single given uri/file or the whole cache"""
        # If no URI is give clears the whole cache. Use with caution. ;)
        if not uri:
            try:
                shutil.rmtree(self.cachedir)
                return 1
            except:
                return 0
        if self.isCached(uri):
            os.unlink(self.getCachedFilename(uri))
        return 1

    def checksum(self, uri, cstype):
        """Calculates and returns the checksum for a give URL and corresponding
        subdir. The type parameter is either "sha" or "md5".

        Returns None if no cache file for the given URL is there or a wrong type
        was given, otherwise the calculated checksum."""

        digest = None
        if   cstype == "sha":
            digest = sha.new()
        elif cstype == "md5":
            digest = md5.new()
        else:
            return (None, None)
        if self.is_local and not self.__isURI(uri):
            fname = os.path.join(self.baseurl, uri)
        else:
            fname = self.getCachedFilename(uri)
        try:
            fd = open(fname)
            updateDigestFromFile(digest, fd)
            return (digest.hexdigest(), fname)
        except:
            return (None, None)

# vim:ts=4:sw=4:showmatch:expandtab
