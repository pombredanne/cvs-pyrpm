#
# Copyright (C) 2005,2006 Red Hat, Inc.
# Author: Thomas Woerner <twoerner@redhat.com>
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

from pyrpm.database import repodb, sqlitedb
from pyrpm.yum import Conf
from disk import *
import config
from devices import *
from filesystem import *

#################################### dicts ####################################

grp_st_gl = 'grp:shift_toggle,grp_led:scroll'

keyboard_models = {
    'ar-azerty'           : ['us,ar(azerty)', 'pc105', '', grp_st_gl],
    'ar-azerty-digits'    : ['us,ar(azerty_digits)', 'pc105', '', grp_st_gl],
    'ar-digits'           : ['us,ar(digits)', 'pc105', '', grp_st_gl],
    'ar-qwerty'           : ['us,ar(qwerty)', 'pc105', '', grp_st_gl],
    'ar-qwerty-digits'    : ['us,ar(qwerty_digits)', 'pc105', '', grp_st_gl],
    'be-latin1'           : ['be', 'pc105', '', ''],
    'ben'                 : ['us,ben', 'pc105', '', grp_st_gl],
    'ben-probhat'         : ['us,ben(probhat)', 'pc105', '', grp_st_gl],
    'bg'                  : ['us,bg', 'pc105', '', grp_st_gl],
    'br-abnt2'            : ['br', 'abnt2', '', ''],
    'cf'                  : ['ca_enhanced', 'pc105', '', ''],
    'croat'               : ['hr', 'pc105', '', ''],
    'cz-lat2'             : ['cz_qwerty', 'pc105', '', ''],
    'cz-us-qwertz'        : ['us,cz', 'pc105', '', grp_st_gl],
    'de'                  : ['de', 'pc105', '', ''],
    'de-latin1'           : ['de', 'pc105', '', ''],
    'de-latin1-nodeadkeys': ['de', 'pc105', 'nodeadkeys', ''],
    'dev'                 : ['us,dev', 'pc105', '', grp_st_gl],
    'dk'                  : ['dk', 'pc105', '', ''],
    'dk-latin1'           : ['dk', 'pc105', '', ''],
    'dvorak'              : ['dvorak', 'pc105', '', ''],
    'es'                  : ['es', 'pc105', '', ''],
    'et'                  : ['ee', 'pc105', '', ''],
    'fi'                  : ['fi', 'pc105', '', ''],
    'fi-latin1'           : ['fi', 'pc105', '', ''],
    'fr'                  : ['fr', 'pc105', '', ''],
    'fr-latin1'           : ['fr', 'pc105', '', ''],
    'fr-latin9'           : ['fr-latin9', 'pc105', '', ''],
    'fr-pc'               : ['fr', 'pc105', '', ''],
    'fr_CH'               : ['fr_CH', 'pc105', '', ''],
    'fr_CH-latin1'        : ['fr_CH', 'pc105', '', ''],
    'gr'                  : ['us,el', 'pc105', '', grp_st_gl],
    'guj'                 : ['us,guj', 'pc105', '', grp_st_gl],
    'gur'                 : ['us,gur', 'pc105', '', grp_st_gl],
    'hu'                  : ['hu', 'pc105', '', ''],
    'hu101'               : ['hu_qwerty', 'pc105', '', ''],
    'is-latin1'           : ['is', 'pc105', '', ''],
    'it'                  : ['it', 'pc105', '', ''],
    'it-ibm'              : ['it', 'pc105', '', ''],
    'it2'                 : ['it', 'pc105', '', ''],
    'jp106'               : ['jp', 'jp106', '', ''],
    'la-latin1'           : ['la', 'pc105', '', ''],
    'mk-utf'              : ['us,mk', 'pc105', '', grp_st_gl],
    'nl'                  : ['nl', 'pc105', '', ''],
    'no'                  : ['no', 'pc105', '', ''],
    'pl'                  : ['pl', 'pc105', '', ''],
    'pt-latin1'           : ['pt', 'pc105', '', ''],
    'ro_win'              : ['ro', 'pc105', '', ''],
    'ru'                  : ['us,ru', 'pc105', '', grp_st_gl],
    'ru-cp1251'           : ['us,ru', 'pc105', '', grp_st_gl],
    'ru-ms'               : ['us,ru', 'pc105', '', grp_st_gl],
    'ru.map.utf8ru'       : ['us,ru', 'pc105', '', grp_st_gl],
    'ru1'                 : ['us,ru', 'pc105', '', grp_st_gl],
    'ru2'                 : ['us,ru', 'pc105', '', grp_st_gl],
    'ru_win'              : ['us,ru', 'pc105', '', grp_st_gl],
    'sg'                  : ['de_CH', 'pc105', '', ''],
    'sg-latin1'           : ['de_CH', 'pc105', '', ''],
    'sk-qwerty'           : ['sk_qwerty', 'pc105', '', ''],
    'slovene'             : ['si', 'pc105', '', ''],
    'sv-latin1'           : ['se', 'pc105', '', ''],
    'tml-inscript'        : ['us,tml(INSCRIPT)', 'pc105', '', grp_st_gl],
    'tml-uni'             : ['us,tml(UNI)', 'pc105', '', grp_st_gl],
    'trq'                 : ['tr', 'pc105', '', ''],
    'ua-utf'              : ['us,ua', 'pc105', '', grp_st_gl],
    'uk'                  : ['gb', 'pc105', '', ''],
    'us'                  : ['us', 'pc105', '', ''],
    'us-acentos'          : ['us_intl', 'pc105', '', ''],
    }

################################### classes ###################################

class Installation:
    def __init__(self, release, version, arch):
        self.release = release
        self.version = version
        self.arch = arch
        self.devices = Devices()

    def __str__(self):
        return "%s-%s" % (self.release, self.version)

    def __cmp__(self, other):
        return cmp(str(self), other)

class Repository:
    def __init__(self, config, dir, name):
        self.config = config
        self.dir = dir
        self.name = name
        self.baseurl = None
        self.mirrorlist = None
        self.exclude = None
        self.repo = None
        self.cache = None
        self.comps = None

    def get(self, filename):
        if self.cache:
            return self.cache.cache(filename)
        return None

    def load(self, baseurl, mirrorlist=None, exclude=None):
        source = baseurl
        if source == "cdrom":
            # mount cdrom
            what = "/dev/cdrom"
            if config.verbose:
                print "Mounting '%s' on '%s'" % (what, self.dir)
            mount(what, self.dir, fstype="auto", options="ro")
            source = "file://%s" % self.dir
        elif source[:6] == "nfs://":
            what = source[6:]
            splits = what.split("/", 1)
            if splits[0][-1] != ":":
                what = ":/".join(splits)
            del splits
            # mount nfs source
            if config.verbose:
                print "Mounting '%s' on '%s'" % (source, self.dir)
            mount(what, self.dir, fstype="nfs",
                  options="ro,rsize=32768,wsize=32768,hard,nolock")
            source = "file://%s" % self.dir
        # else: source == url

        if exclude or mirrorlist:
            yumconf = Conf()
            if exclude:
                yumconf["exclude"] = exclude
            if mirrorlist:
                yumconf["mirrorlist"] = mirrorlist
        else:
            yumconf = None

        self.baseurl_orig = baseurl
        self.baseurl = source
        self.mirrorlist = mirrorlist
        self.exclude = exclude

        self.repo = sqlitedb.SqliteDB(self.config, [ source ], yumconf=yumconf,
                                      reponame=self.name)
#        self.repo = repodb.RpmRepoDB(self.config, [ source ], yumconf=yumconf,
#                                     reponame=self.name)
        if not self.repo.read():
            print "ERROR: Could not read repository '%s'." % self.name
            return 0

        self.cache = self.repo.getNetworkCache()
        if not self.cache:
            print "ERROR: Could no get cache for repo '%s'." % self.name
            return 0

        self.comps = self.repo.comps
        return 1

    def close(self):
        self.cache = None
        self.comps = None
        self.repo.close()

# vim:ts=4:sw=4:showmatch:expandtab
