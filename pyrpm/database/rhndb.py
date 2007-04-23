#
# Copyright (C) 2007 Red Hat, Inc.
# Authors: Phil Knirsch <pknirsch@redhat.com>
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

#
# RHN Repository Database class. Based on rhnplugin.py for yum. Works only with
# RHEL5 or later yum comptaible RHN repositories yet.
#


import sys
from pyrpm.database.jointdb import JointDB
from pyrpm.database.sqliterepodb import SqliteRepoDB
from pyrpm.logger import log
sys.path.append("/usr/share/rhn/")
try:
    import up2date_client.up2dateAuth as up2dateAuth
    import up2date_client.config as rhnconfig
    from up2date_client import rhnChannel
    from up2date_client import rhnPackageInfo
    from up2date_client import up2dateErrors
    use_rhn = True
except:
    log.warning("Couldn't import up2date_client modules. Disabling RHN support.")
    use_rhn = False


class RhnRepoDB(JointDB):

    def __init__(self, config, source, buildroot='', nc=None):
        JointDB.__init__(self, config, source, buildroot)
        self.reponame = "rhnrepo"
        if not use_rhn:
            return
        up2date_cfg = rhnconfig.initUp2dateConfig()
        try:
            login_info = up2dateAuth.getLoginInfo()
        except up2dateErrors.RhnServerException, e:
            raise IOError, "Failed to get login info from RHN Server."
        try:
            svrChannels = rhnChannel.getChannelDetails()
        except up2dateErrors.NoChannelsError:
            raise IOError, "Failed to get channels from RHN Server."
        for channel in svrChannels: 
            rcdb = RhnChannelRepoDB(config, (channel['url']+'/GET-REQ/'+channel['label'], ), buildroot, channel['label'], nc)
            self.addDB(rcdb)

    def _matchesFile(self, fname):
        ret = True
        for db in self.dbs:
            ret &= (db._matchesFile(fname) != None)
        return ret


class RhnChannelRepoDB(SqliteRepoDB):
    """
    Database for Red Hat Network repositories.
    """

    rhn_needed_headers = ['X-RHN-Server-Id',
                          'X-RHN-Auth-User-Id',
                          'X-RHN-Auth',
                          'X-RHN-Auth-Server-Time',
                          'X-RHN-Auth-Expire-Offset']

    def __init__(self, config, source, buildroot='', channelname='default', nc=None):
        self.http_headers = { }
        self.__setupRhnHttpHeaders()
        SqliteRepoDB.__init__(self, config, source, buildroot, channelname, nc)
        self.nc.setHeaders(self.http_headers, channelname)

    def __setupRhnHttpHeaders(self):
        """ Set up self.http_headers with needed RHN X-RHN-blah headers """

        try:
            li = up2dateAuth.getLoginInfo()
        except up2dateErrors.RhnServerException, e:
            raise yum.Errors.RepoError(str(e))

        # TODO:  do evalution on li auth times to see if we need to obtain a
        # new session...

        for header in RhnChannelRepoDB.rhn_needed_headers:
            if not li.has_key(header):
                log.error("Missing required login information for RHN: %s" % header)
                raise ValueError
            self.http_headers[header] = li[header]

    def read(self):
        log.info2("Reading RHN channel repository '%s'", self.reponame)
        return SqliteRepoDB.read(self)

# vim:ts=4:sw=4:showmatch:expandtab
