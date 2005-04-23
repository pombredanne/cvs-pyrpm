# Creating libxml2 subtrees of RPM metadata from RpmPackage objects
#
# Copyright (C) 2004 Duke University
# Copyright (C) 2005 Red Hat, Inc.
#
# Author: Miloslav Trmac
# Based on createrepo 0.4.2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#

import os, re, stat
import base, config, functions


# Files included in primary.xml
_filerc = re.compile('^(.*bin/.*|/etc/.*|/usr/lib/sendmail)$')
_dirrc = re.compile('^(.*bin/.*|/etc/.*)$')


def _utf8String(string):
    """Return string converted to UTF-8"""

    if string == None:
        return ''
    elif isinstance(string, unicode):
        return string
    try:
        x = unicode(string, 'ascii')
        return string
    except UnicodeError:
        encodings = ['utf-8', 'iso-8859-1', 'iso-8859-15', 'iso-8859-2']
        for enc in encodings:
            try:
                x = unicode(string, enc)
            except UnicodeError:
                pass
            else:
                if x.encode(enc) == string:
                    return x.encode('utf-8')
    newstring = ''
    for char in string:
        if ord(char) > 127:
            newstring = newstring + '?'
        else:
            newstring = newstring + char
    return newstring


def _textChildFromTag(parent, ns, tag, value):
    """Return a new child <ns:tag> under parent from {,i18n}string value."""
    if type(value) in [list, tuple]:
        value = value[0]
    value = re.sub("\n$", '', _utf8String(value))
    parent.newTextChild(ns, tag, value)


def _archOrSrc(pkg):
    if pkg.isSourceRPM():
        return 'src'
    else:
        return pkg['arch']


def _listVal(val):
    """Return [] if val is None, val otherwise"""
    if val:
        return val
    return []


_depString = {
    base.RPMSENSE_LESS: 'LT',
    base.RPMSENSE_GREATER: 'GT',
    base.RPMSENSE_EQUAL: 'EQ',
    base.RPMSENSE_LESS | base.RPMSENSE_EQUAL: 'LE',
    base.RPMSENSE_GREATER | base.RPMSENSE_EQUAL: 'GE'
}

def _entryNode(parent, ns, dep):
    """Create an <ns:entry> node for dependency dep under parent.

    dep is (name, flags, ver). Return the created node."""

    entry = parent.newChild(ns, 'entry', None)
    (name, flags, ver) = dep
    entry.newProp('name', name)
    fl = flags & base.RPMSENSE_SENSEMASK
    if fl != 0:
        entry.newProp('flags', _depString[fl])
        (e, v, r) = functions.evrSplit(ver)
        # if we've got a flag we've got a version, I hope :)
        if e != '':
            entry.newProp('epoch', e)
        if v != '':
            entry.newProp('ver', v)
        if r != '':
            entry.newProp('rel', r)
    return entry


def metadataReadPackage(filename):
    """Read RPM package filename, without verification or reading the payload.

    For convenience only, other metadata* functions work with any RpmPackage
    as long it contains all needed tags."""
    return functions.readRpmPackage(config.rpmconfig, "file:/" + filename,
                                  verify = None, hdronly = True)


def metadataPrimaryNode(parent, formatns, pkg, pkgid, sumtype, filename, url):
    """Return a <package> node for primary.xml, created from pkg."""

    pkgNode = parent.newChild(None, "package", None)
    pkgNode.newProp('type', 'rpm')
    pkgNode.newChild(None, 'name', pkg['name'])
    pkgNode.newChild(None, 'arch', _archOrSrc(pkg))
    version = pkgNode.newChild(None, 'version', None)
    version.newProp('epoch', pkg.getEpoch())
    version.newProp('ver', pkg['version'])
    version.newProp('rel', pkg['release'])
    csum = pkgNode.newChild(None, 'checksum', pkgid)
    csum.newProp('type', sumtype)
    csum.newProp('pkgid', 'YES')
    for tag in ['summary', 'description', 'packager', 'url']:
        _textChildFromTag(pkgNode, None, tag, pkg[tag])

    stats = os.stat(filename)
    time = pkgNode.newChild(None, 'time', None)
    time.newProp('file', str(stats.st_mtime))
    time.newProp('build', str(pkg['buildtime'][0]))
    size = pkgNode.newChild(None, 'size', None)
    size.newProp('package', str(stats.st_size))
    size.newProp('installed', str(pkg['size'][0]))
    size.newProp('archive', str(pkg['signature']['payloadsize'][0]))
    location = pkgNode.newChild(None, 'location', None)
    if url != None:
        location.newProp('xml:base', url)
    location.newProp('href', filename)
    format = pkgNode.newChild(None, 'format', None)
    for tag in ['license', 'vendor', 'group', 'buildhost', 'sourcerpm']:
        _textChildFromTag(format, formatns, tag, pkg[tag])

    hr = format.newChild(formatns, 'header-range', None)
    hr.newProp('start', str(pkg.range_header[0]))
    hr.newProp('end', str(pkg.range_header[0] + pkg.range_header[1]))
    for nodename in ['provides', 'conflicts', 'obsoletes']:
        lst = [(name, flags & base.RPMSENSE_SENSEMASK, ver)
               for (name, flags, ver) in pkg[nodename]]
        if len(lst) > 0:
            functions.normalizeList(lst)
            rpconode = format.newChild(formatns, nodename, None)
            for dep in lst:
                _entryNode(rpconode, formatns, dep)

    depsList = [(name, flags & (base.RPMSENSE_SENSEMASK
                                | base.RPMSENSE_PREREQ), ver)
                for (name, flags, ver) in pkg['requires']]
    if len(depsList) > 0:
        functions.normalizeList(depsList)
        rpconode = format.newChild(formatns, 'requires', None)
        for dep in depsList:
            entry = _entryNode(rpconode, formatns, dep)
            if (dep[1] & base.RPMSENSE_PREREQ) != 0:
                entry.newProp('pre', '1')

    files = _listVal(pkg['filenames'])
    fileflags = _listVal(pkg['fileflags'])
    filemodes = _listVal(pkg['filemodes'])
    for (filename, mode, flag) in zip(files, filemodes, fileflags):
        if stat.S_ISDIR(mode):
            if _dirrc.match(filename):
                files = format.newTextChild(None, 'file',
                                            _utf8String (filename))
                files.newProp('type', 'dir')
        elif _filerc.match(filename):
            files = format.newTextChild(None, 'file', _utf8String (filename))
            if flag & base.RPMFILE_GHOST:
                files.newProp('type', 'ghost')
    return pkgNode


def metadataFilelistsNode(parent, pkg, pkgid):
    """Return a <package> node for filelists.xml, created from pkg."""

    pkgNode = parent.newChild(None, 'package', None)
    pkgNode.newProp('pkgid', pkgid)
    pkgNode.newProp('name', pkg['name'])
    pkgNode.newProp('arch', _archOrSrc(pkg))
    version = pkgNode.newChild(None, 'version', None)
    version.newProp('epoch', pkg.getEpoch())
    version.newProp('ver', pkg['version'])
    version.newProp('rel', pkg['release'])
    files = _listVal(pkg['filenames'])
    fileflags = _listVal(pkg['fileflags'])
    filemodes = _listVal(pkg['filemodes'])
    for (filename, mode, flag) in zip(files, filemodes, fileflags):
        node = pkgNode.newTextChild(None, 'file', _utf8String(filename))
        if stat.S_ISDIR(mode):
            node.newProp('type', 'dir')
        elif flag & base.RPMFILE_GHOST:
            node.newProp('type', 'ghost')
    return pkgNode


def metadataOtherNode(parent, pkg, pkgid):
    """Return a <package> node for other.xml, created from pkg."""

    pkgNode = parent.newChild(None, 'package', None)
    pkgNode.newProp('pkgid', pkgid)
    pkgNode.newProp('name', pkg['name'])
    pkgNode.newProp('arch', _archOrSrc(pkg))
    version = pkgNode.newChild(None, 'version', None)
    version.newProp('epoch', pkg.getEpoch())
    version.newProp('ver', pkg['version'])
    version.newProp('rel', pkg['release'])
    names = _listVal(pkg['changelogname'])
    times = _listVal(pkg['changelogtime'])
    texts = _listVal(pkg['changelogtext'])
    for (name, time, text) in zip(names, times, texts):
        clog = pkgNode.newTextChild(None, 'changelog', _utf8String(text))
        clog.newProp('author', _utf8String(name))
        clog.newProp('date', str(time))
    return pkgNode

# vim:ts=4:sw=4:showmatch:expandtab
