#
# Copyright 2004, 2005, 2006, 2007 Red Hat, Inc.
# Copyright (C) 2005 Harald Hoyer <harald@redhat.com>
# Copyright (C) 2006, 2007 Florian La Roche <laroche@redhat.com>
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


import os, os.path, glob, re, fnmatch
from time import clock, time
from pyrpm.resolver import RpmResolver
from pyrpm.control import RpmController
from pyrpm.functions import *
from pyrpm.io import *
import pyrpm.database as database
import pyrpm.database.repodb
# from pyrpm.database.repodb import RpmRepoDB
from pyrpm.database.jointdb import JointDB
from pyrpm.database.rhndb import RhnRepoDB
from pyrpm.logger import log

MainVarnames = ("cachedir", "reposdir", "debuglevel", "errorlevel",
        "logfile", "gpgcheck", "assumeyes", "alwaysprompt", "tolerant",
        "exclude", "exactarch",
        "installonlypkgs", "kernelpkgnames", "showdupesfromrepos", "obsoletes",
        "overwrite_groups", "installroot", "rss-filename", "distroverpkg",
        "diskspacecheck", "tsflags", "recent", "retries", "keepalive",
        "timeout", "http_caching", "throttle", "bandwidth", "commands",
        "keepcache", "proxy", "proxy_username", "proxy_password", "pkgpolicy",
        "plugins", "pluginpath", "pluginconfpath", "metadata_expire",
        "mirrorlist_expire")
RepoVarnames = ("name", "baseurl", "mirrorlist", "enabled", "gpgcheck",
        "gpgkey", "exclude", "includepkgs", "enablegroups", "failovermethod",
        "keepalive", "timeout", "http_caching", "retries", "throttle",
        "bandwidth", "metadata_expire", "proxy", "proxy_username",
        "proxy_password", "mirrorlist_expire")
MultilineVarnames = ("exclude", "installonlypkgs", "kernelpkgnames",
        "commands", "pluginpath", "pluginconfpath", "baseurl", "gpgkey",
        "includepkgs")

class YumConf(dict):
    def __init__(self, relver, arch, rpmdb=None, filenames=["/etc/yum.conf"],
                 reposdirs=None):

        # load config files
        found = False
        for filename in filenames:
            if os.path.isfile(filename):
                found = True
                self.parseFile(filename)
            else:
                log.warning("Couldn't find given yum config file, skipping "
                            "read of repo %s", filename)

        if not found:
            return

        if reposdirs == None:
            reposdirs = ["/etc/yum.repos.d", "/etc/yum/repos.d"]

        k = self.get("main", {}).get("reposdir")
        if k != None:
            reposdirs = k.split(" \t,;")
        # read in repos files
        for reposdir in reposdirs:
            for filename in glob.glob(reposdir + "/*.repo"):
                self.parseFile(filename)
        # get relver
        if relver is None and rpmdb:
            distroverpkg = self.get('main', {}).get(
                'distroverpkg', "redhat-release")
            for pkg in rpmdb.searchProvides(distroverpkg, 0, ""):
                relver = pkg["version"]
        if relver is None:
            relver = ''

        self._buildReplaceVars(relver, arch)

        for (name, section) in self.iteritems():
            for (key, value) in section.iteritems():
                if isinstance(value, list):
                    section[key] = [self.replaceVars(item) for item in value]
                else:
                    section[key] = self.replaceVars(value)

    def _buildReplaceVars(self, releasever, arch):
        basearch = buildarchtranslate[arch]
        replacevars = {}
        for name, value in (("$RELEASEVER", releasever),
                            ("$ARCH", arch),
                            ("$BASEARCH", basearch)):
            replacevars[name] = value
            replacevars[name.lower()] = value
        for i in xrange(10):
            key = "YUM%d" % i
            value = os.environ.get(key)
            if value:
                replacevars[key.lower()] = value
                replacevars[key] = value
        self._replacevars = replacevars

    def parseFile(self, filename):
        lines = []
        if os.path.isfile(filename) and os.access(filename, os.R_OK):
            log.info2("Reading in config file %s", filename)
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
                    if prevcommand in MultilineVarnames:
                        line = line.split()
                    else:
                        line = [line]
                    self[stanza][prevcommand].extend(line)
            else:
                line = line.strip()
                if line[:1] in "#;" or not line:
                    pass # comment line
                elif line.find("=") != -1:
                    (key, value) = line.split("=", 1)
                    (key, value) = (key.strip(), value.strip())
                    if stanza == "main":
                        if key not in MainVarnames:
                            raise ValueError, "could not read line %d in %s" % (linenum + 1, filename)
                    elif key not in RepoVarnames:
                        raise ValueError, "could not read line %d in %s" % (linenum + 1, filename)
                    prevcommand = None
                    if key in MultilineVarnames:
                        value = value.split()
                        prevcommand = key
                    self.setdefault(stanza, {})[key] = value
                else:
                    raise ValueError, "could not read line %d in %s" % (linenum + 1, filename)
        return None

    def replaceVars(self, line):
        for (key, value) in self._replacevars.iteritems():
            line = line.replace(key, value)
        return line


class RpmYum:
    def __init__(self, config):
        self.config = config
        # Default: Don't autoerase packages that have unresolved symbols in
        # install or update
        self.autoerase = 0
        # package names/globs to be excluded from autoerasing of autoerase is
        # enabled.
        self.autoeraseexclude = [ ]
        # Default: Ask user for confirmation of complete operation
        self.confirm = 1
        # Default: No command
        self.command = None
        # List of RpmRepo's
        self.repos = JointDB(config, "Yum repos")
        # List of languages we want to install for.
        self.langs = [ ]
        # Flag if RHN support is enabled or not. True by default
        self.rhnenabled = True
        # Internal list of packages that are have to be erased
        self.erase_list = [ ]
        # Internal list of packages that were used for obsoleting
        self.opkg_list = [ ]
        # Our database
        self.pydb = None
        # Flag wether we already read all the repos
        self.repos_read = 0
        # Our list of package names that get installed instead of updated
        self.always_install = [
            "kernel", "kernel-PAE", "kernel-bigmem", "kernel-enterprise",
            "kernel-hugemem", "kernel-summit", "kernel-smp", "kernel-largesmp",
            "kernel-xen", "kernel-xen0", "kernel-xenU", "kernel-kdump",
            "kernel-BOOT", "kernel-debug", "kernel-devel",
            "kernel-debug-devel", "kernel-PAE-debug", "kernel-PAE-debug-devel",
            "kernel-PAE-devel", "kernel-hugemem-devel", "kernel-smp-devel",
            "kernel-largesmp-devel", "kernel-xen-devel", "kernel-xen0-devel",
            "kernel-xenU-devel", "kernel-kdump-devel", "kernel-source",
            "kernel-unsupported", "kernel-modules"
        ]
        # List of valid commands
        self.command_list = ["install", "update", "upgrade", "remove",
                             "groupinstall", "groupupdate", "groupupgrade",
                             "groupremove", "list", "info", "search",
                             "check-update", "provides", "whatprovides",
                             "resolvedep", "deplist"]
        # Flag if we have been called with arguments or not
        self.has_args = True

        # lockfile for yum calls
        self.lockfile = None

        # Internal lists, don't ask. ;)
        self.__iinstalls = [ ]
        self.__ierases = [ ]
        self.__iupdates = { }
        self.__iobsoletes = { }

        # Delay obsolete handling and just collect the packages in an internal
        # list. By default false (direct obsolete handling).
        self.delay_obsolete = False
        self.delay_obsolete_list = [ ]

    def setAutoerase(self, flag):
        """Enable or disable erasing packages with unresolved dependencies
        according to flag."""

        self.autoerase = flag

    def setAutoeraseExclude(self, exlist):
        """Sets the names/globs to be excluded from autoerasing."""
        nlist = []
        for name in exlist:
            name = fnmatch.translate(name)
            regex = re.compile(name)
            nlist.append(regex)
        self.autoeraseexclude = nlist

    def setConfirm(self, flag):
        """Enable or disable asking the user for confirmation according to
        flag."""

        self.confirm = flag

    def setLanguages(self, languages):
        """Sets the supported languges for an installation."""

        self.langs = languages

    def setCommand(self, command):
        """Set the command to perform to commmand.

        Return 1 on success, 0 on error (after warning the user)."""

        self.command = command.lower()
        if self.command not in self.command_list:
            log.error("Invalid command")
            return 0
        #if self.command == "upgrade" or self.command == "groupupgrade":
        #    self.always_install = [ ]
        return 1

    def addRepos(self, files, db):
        """Read yum configuration file and add repositories it uses.

        sys.exit() on error."""

        try:
            conf = YumConf(self.config.relver, self.config.machine, db,
                           files)
            self.yumconfig = conf
        except IOError, e:
            log.error("Error reading configuration: %s", e)
            return 0
        erepo = []
        for ritem in self.config.enablerepo:
            ritem = fnmatch.translate(ritem)
            regex = re.compile(ritem)
            erepo.append(regex)
        drepo = []
        for ritem in self.config.disablerepo:
            ritem = fnmatch.translate(ritem)
            regex = re.compile(ritem)
            drepo.append(regex)
        for key in conf.keys():
            sec = conf[key]
            if key == "main":
                # exactarch can only be found in main section. Default False
                if sec.get("exactarch") == "1":
                    self.config.exactarch = True
                # keepcache can only be found in main section. Default True
                if sec.get("keepcache") == "0":
                    self.config.exactarch = False
            else:
                # Check if the current repo should be enabled or disabled
                enabled = True      # Default is enabled
                if sec.get("enabled") == "0":
                    enabled = False
                for regex in erepo:
                    if regex.match(key):
                        enabled = True
                        break
                for regex in drepo:
                    if regex.match(key):
                        enabled = False
                        break
                # Repo is not enabled: skip it.
                if not enabled:
                    continue
                if self.config.timer:
                    time1 = clock()
                log.info2("Reading repository '%s'", key)
                repo = database.getRepoDB(self.config, conf, self.config.buildroot, key)
                if repo.read() == 0:
                    log.error("Error reading repository %s", key)
                    return 0
                self.repos.addDB(repo)
                if self.config.timer:
                    log.info2("Reading repository took %s seconds",
                        (clock() - time1))
        return 1

    def prepareTransaction(self, localDb=None):
        """Open the RPM database and prepare the transaction.

        Return 1 in success, 0 on error (after warning the user).  If localDb
        is not None, use it as a local RPM database instead of reading the
        database again."""

        self.erase_list = []
        self.opkg_list = [ ]
        self.__iinstalls = [ ]
        self.__ierases = [ ]
        self.__iupdates = { }
        self.__iobsoletes = { }
        if localDb is not None:
            self.pydb = localDb
        else:
            if self.config.timer:
                time1 = clock()
            # Create and read db
            log.info2("Reading local RPM database")
            self.pydb = database.getRpmDB(self.config,
                                          self.config.dbpath,
                                          self.config.buildroot)
            self.pydb.open()
            if not self.pydb.read():
                log.error("Error reading the RPM database")
                return 0
            if self.config.timer:
                log.info2("Reading local RPM database took %s seconds",
                          (clock() - time1))
        if self.config.timer:
            time1 = clock()

        db = self.pydb.getMemoryCopy(self.repos)

        for pkg in db.searchProvides("redhat-release", 0, ""):
            self.config.relver = pkg["version"]

        if self.rhnenabled and os.access(self.config.buildroot + \
            "/etc/sysconfig/rhn/systemid", os.R_OK):
            log.info2("Reading RHN repositories")
            rhnrepo = RhnRepoDB(self.config, None, self.config.buildroot)
            rhnrepo.read()
            self.repos.addDB(rhnrepo)
        if not self.repos_read and not self.command == "remove":
            if not self.addRepos(self.config.yumconf, db):
                return 0

        self.repos_read = 1
        justquery = not ("install" in self.command or
                         "update" in self.command or
                         "upgrade" in self.command or
                         "remove" in self.command)
        self.opresolver = RpmResolver(self.config, db,
                                      nocheck=justquery)
        if not justquery:
            self.__generateObsoletesList()
        if self.config.timer:
            log.info2("Preparing transaction took %s seconds",
                      (clock() - time1))

        return 1

    def getGroupPackages(self, name):
        """Return a list of package names from all repositories matching that
        group"""

        pkglist = []
        for repo in self.repos.dbs:
            if repo.comps != None:
                pkglist.extend(repo.comps.getPackageNames(name))
                lang = repo.comps.getGroupLanguage(name)
                if lang and not lang in self.langs:
                    self.langs.append(lang)
        return pkglist

    def lock(self):
        """ Generate /var/run/yum.pid in buildroot to prevent multiple yum
        calls at the same time in the buildroot. """

        if self.lockfile:
            return 0

        if os.getuid() != 0 or self.config.test:
            return 1
        if self.config.buildroot != None:
            self.lockfile = self.config.buildroot + "/var/run/yum.pid"
        else:
            self.lockfile = "/var/run/yum.pid"
        try:
            makeDirs(self.lockfile)
        except OSError:
            pass
        if tryUnlock(self.lockfile) == 1: # FIXME: IOError
            return 0
        if doLock(self.lockfile) == 0: # FIXME: OSError
            return 0
        return 1

    def isLocked(self):
        """ Check if yum is locked. """
        if self.lockfile:
            return 1
        return 0

    def unLock(self):
        """ Remove lockfile if it exists. """
        if self.lockfile:
            try:
                os.unlink(self.lockfile)
            except OSError:
                return 0
            self.lockfile = None
        return 1

    def install(self, name, exact=False):
        pkglist = self.__findPkgs(name, exact)
        ret = self.__handleBestPkg("install", pkglist)
        return ret

    def groupInstall(self, name, exact=False):
        args = self.getGroupPackages(name)
        ret = 0
        for pkgname in args:
            ret |= self.install(pkgname, exact)
        return ret

    def update(self, name, exact=False, do_obsolete=True):
        # First find all matching packages. Remember, name can be a glob, too,
        # so we might get a list of packages with different names.
        pkglist = self.__findPkgs(name, exact)
        # Next we generate two temporary hashes. One with just a list of
        # packages for each name and a second with a subhash for each package
        # for each arch. Both are needed for speed reasons. The first one for
        # the general case where we either have:
        #  - install only package
        #  - no previously installed package
        #  - previously installed packages but exactarch in yum.conf is False.
        # The second one is needed for exactarch updates to find matching
        # updates fast for specific installed archs of packages.
        pkgnamehash = {}
        pkgnamearchhash = {}
        for pkg in pkglist:
            pkgnamehash.setdefault(pkg["name"], []).append(pkg)
            pkgnamearchhash.setdefault(pkg["name"], {}).setdefault(pkg["arch"],
                                       []).append(pkg)
        # Now go over all package names we found and find the correct update
        # packages.
        ret = 0
        for name in pkgnamehash.keys():
            # Get a copy of the current db packages for the given name
            dbpkgs = self.opresolver.getDatabase().getPkgsByName(name)[:]
            # If the package name is either in our always_install list or no
            # package with that name was installed we simply try to select the
            # best matching package update for this arch.
            if name in self.always_install or len(dbpkgs) == 0:
                ret |= self.__handleBestPkg("update", pkgnamehash[name],
                                            do_obsolete=do_obsolete)
                continue
            # Next trick: We now know that this is an update package and we
            # have at least 1 package with that name installed. In order to
            # updated 32 and 64 bit archs properly we now have to determine
            # how and what needs to be updated properly in case exactarch
            # isn't set.
            if not self.config.exactarch:
                arch = None
                is_multi = False
                # Check if all packages share them same buildarch translation.
                for ipkg in dbpkgs:
                    if arch != None and arch != buildarchtranslate[ipkg["arch"]]:
                        is_multi = True
                        break
                    arch = buildarchtranslate[ipkg["arch"]]
                    march = ipkg["arch"]
                # If not and we're not exactarch then just find the best
                # matching package again as we allow arch switches to 64bit
                # for updates. The best match is as close as possible to the
                # original arch of the installed package.
                if not is_multi:
                    l = self._filterPkgVersion(max(dbpkgs), pkgnamehash[name])
                    ret |= self.__handleBestPkg("update", l, march,
                                                do_obsolete=do_obsolete)
                    continue
                # OK, we have several archs for this package installed, we now
                # need to filter them to 32bit and 64bit buckets and later
                # use our standard algorithm to select the best matching
                # package for each arch.
                for arch in pkgnamearchhash[name].keys():
                    if buildarchtranslate[arch] == arch:
                        continue
                    pkgnamearchhash[name].setdefault(buildarchtranslate[arch], []).extend(pkgnamearchhash[name][arch])
                    del pkgnamearchhash[name][arch]
            # Ok, now we have to find matching updates for all installed archs.
            for ipkg in dbpkgs:
                # First see if we're dealing with a noarch package. Just allow
                # any package to be used then.
                if   ipkg["arch"] == "noarch":
                    arch = "noarch"
                    march = self.config.machine
                    for a in pkgnamearchhash[name].keys():
                        if a == arch:
                            continue
                        pkgnamearchhash[name].setdefault(arch, []).extend(pkgnamearchhash[name][a])
                # Now for exactarch we really need to find a perfect arch match.
                elif self.config.exactarch:
                    arch = ipkg["arch"]
                    march = arch
                    # Add all noarch packages for arch -> noarch transitions
                    pkgnamearchhash[name].setdefault(arch, []).extend(pkgnamearchhash[name].setdefault("noarch", {}))
                # If we are not doing exactarch we allow archs to be switched
                # inside of the given buildarch translation.
                else:
                    arch = buildarchtranslate[ipkg["arch"]]
                    march = self.config.machine
                    # Add all noarch packages for arch -> noarch transitions
                    pkgnamearchhash[name].setdefault(arch, []).extend(pkgnamearchhash[name].setdefault("noarch", {}))
                if arch not in pkgnamearchhash[name]:
                    log.error("Can't find update package with matching arch "
                              "for package %s", ipkg.getNEVRA())
                    return 0

                # Filter packages with lower versions from our final list
                l = self._filterPkgVersion(ipkg, pkgnamearchhash[name][arch])
                if len(l) == 0:
                    pkgnamearchhash[name][arch] = []
                    continue
                # Find the best matching package for the given list of packages
                # and archs.
                r = self.__handleBestPkg("update", l, march,
                                         self.config.exactarch,
                                         do_obsolete=do_obsolete)
                # In case we had a successfull update make sure we erase the
                # package we just updated. Otherwise cross arch switches won't
                # work properly with our current resolver.
                if r > 0 and ipkg in self.opresolver.getDatabase():
                    self.opresolver.erase(ipkg)
                ret |= r
                # Trick to avoid multiple adds for same arch, after handling
                # it once we clear the update package list.
                pkgnamearchhash[name][arch] = []
        return ret

    def _filterPkgVersion(self, pkg, pkglist):
        l = []
        for p in pkglist:
            if pkgCompare(pkg, p) < 0:
                l.append(p)
        return l

    def groupUpdate(self, name, exact=False):
        args = self.getGroupPackages(name)
        ret = 0
        for pkgname in args:
            ret |= self.update(pkgname, exact)
        return ret

    def remove(self, name, exact=False):
        if exact:
            pkglist = self.pydb.getPkgsByName(name)
        else:
            pkglist = self.pydb.searchPkgs([name])
        ret = self.__handleBestPkg("remove", pkglist)
        return ret

    def groupRemove(self, name, exact=False):
        args = self.getGroupPackages(name)
        ret = 0
        for pkgname in args:
            ret |= self.remove(pkgname, exact)
        return ret

    def __findPkgs(self, name, exact=False):
        if name[0] != "/":
            if exact:
                return self.repos.getPkgsByName(name)
            else:
                return self.repos.searchPkgs([name])
        else:
            return self.repos.searchFilenames(name)

    def __handleBestPkg(self, cmd, pkglist, arch=None, exactarch=False, is_filereq=0, do_obsolete=True, single=False):
        # Handle removes directly here, they don't need any special handling.
        if cmd.endswith("remove"):
            for upkg in pkglist:
                self.opresolver.erase(upkg)
            return 1
        # If no arch has been set use the one of our current machine
        if arch == None:
            arch = self.config.machine
        # Order the elements of the potential packages by machine
        # distance and evr
        orderList(pkglist, arch)
        # Hash for names. Each name key will have a ordered list of packages.
        pkgnamehash = {}
        # Hash for types. Each type will have a ordered list of packages.
        typehash = {}
        for upkg in pkglist:
            # Skip all packages that are either blocked via our erase_list
            # or that are already in the opresolver
            if upkg in self.erase_list or \
               upkg in self.opresolver.getDatabase():
                continue
            # If exactarch is set skip all packages that don't match
            # the arch exactly.
            if exactarch and upkg["arch"] != arch and \
                             upkg["arch"] != "noarch":
                continue
            # Only try to update if the package itself or the update package
            # are noarch or if they are buildarchtranslate or arch
            # compatible. Some exception needs to be done for
            # filerequirements.
            if not (is_filereq or \
                    archDuplicate(upkg["arch"], arch) or \
                    archCompat(upkg["arch"], arch) or \
                    archCompat(arch, upkg["arch"])):
                continue
            # Populate our 2 dicts properly
            pkgnamehash.setdefault(upkg["name"], []).append(upkg)
            typehash.setdefault(upkg.compstype, []).append(upkg)
        # In case of a single package selection we iterate over the various
        # types and try until we find a package that works. This way we ensure
        # that we're honoring the types properly and for each type try to use
        # the newest/best packages first.
        if single:
            for ttype in ("mandatory", "default", "optional", None):
                if not typehash.has_key(ttype):
                    continue
                for pkg in typehash[ttype]:
                    ret = self.__handleSinglePkg(cmd, pkg, arch, is_filereq,
                                                 do_obsolete)
                    if ret > 0:
                        return 1
            # In case we couldn't add any package we need to report that
            # failure.
            return 0
        # For the normal case we try to add a package for each name and for
        # each name start with the best package.
        ret = False
        for name in pkgnamehash.keys():
            r = False
            for upkg in pkgnamehash[name]:
                r = self.__handleSinglePkg(cmd, upkg, arch, is_filereq,
                                            do_obsolete)
                if r > 0:
                    break
            ret |= (r > 0)
        return ret

    def __handleSinglePkg(self, cmd, upkg, arch=None, is_filereq=0, do_obsolete=True):
        # "fake" Source RPMS to be noarch rpms without any reqs/deps
        # etc. except if we want pyrpmyum to install the buildprereqs
        # from the srpm.
        if upkg.isSourceRPM():
            upkg["arch"] = "noarch"
            upkg["provides"] = []
            upkg["conflicts"] = []
            upkg["obsoletes"] = []
        # Depending on the command we gave to handle we need to either
        # install, update or remove the package now.
        if   cmd.endswith("install"):
            r = self.opresolver.install(upkg)
        elif cmd.endswith("update") or cmd.endswith("upgrade"):
            if upkg["name"] in self.always_install:
                r = self.opresolver.install(upkg)
            else:
                r = self.opresolver.update(upkg)
        # We just handled one package, make sure we handle it's
        # obsoletes and language related packages
        if upkg and r > 0:
            l = []
            for repo in self.repos.dbs:
                if hasattr(repo, 'comps') and repo.comps:
                    for lang in self.langs:
                        l.extend(repo.comps.getLangOnlyPackageNames(lang,
                                                                upkg["name"]))
            normalizeList(l)
            for name in l:
                self.update(name)
            if do_obsolete:
                if self.delay_obsolete:
                    self.delay_obsolete_list.append(upkg)
                else:
                    self.__handleObsoletes([upkg])
        return r

    def runArgs(self, args, exact=False):
        """Find all packages that match the args and run the given command on
        them.

        Return 1 on success, 0 on error (after warning the user)."""

        if self.config.timer:
            time1 = clock()
        log.info2("Selecting packages for operation")
        # We unfortunatly still need to special case the argless remove
        self.has_args = True
        if len(args) == 0:
            self.has_args = False
            if self.command == "update" or self.command == "upgrade":
                # For complete updates we need to do a full obsoletes run, not
                # on a specific package.
                for name in self.opresolver.getDatabase().getNames():
                    self.update(name, exact=True, do_obsolete=False)
                #self.__handleObsoletes()
        # Select proper function to be called for every argument. We have
        # a fixed operation for runArgs(), so use a reference to the
        # corresponding function.
        func_hash = {
            "groupremove": self.groupRemove,
            "groupinstall": self.groupInstall,
            "groupupdate":  self.groupUpdate,
            "groupupgrade": self.groupUpdate,
            "remove":       self.remove,
            "install":      self.install,
            "update":       self.update,
            "upgrade":      self.update}
        all_args_func_hash = {
            "list" : self.list,
            "info" : self.list,
            "search" : self.search,
            "check-update" : self.checkupdate,
            "provides" : self.resolvedep,
            "whatprovides" : self.resolvedep,
            "resolvedep" : self.resolvedep,
            "deplist" : self.deplist,
            }
        op_func = func_hash.get(self.command)
        if op_func is None and all_args_func_hash.has_key(self.command):
            op_func = all_args_func_hash.get(self.command)
            return op_func(args)
        if op_func is None:
            return 0
        # First pass through our args to find any directories and/or binary
        # rpms and create a memory repository from them to avoid special
        # cases.
        memory_repo = pyrpm.database.repodb.RpmRepoDB(self.config, [], self.config.buildroot, "pyrpmyum-memory-repo")
        new_args = []
        for name in args:
            if   os.path.isfile(name) and name.endswith(".rpm"):
                pkg = readRpmPackage(self.config, name, db=self.pydb,
                                     tags=self.config.resolvertags)
                if pkg != None:
                    memory_repo.addPkg(pkg)
                    new_args.append(pkg.getNVRA())
            elif os.path.isdir(name):
                pkglist = []
                functions.readDir(name, pkglist)
                for pkg in pkglist:
                    memory_repo.addPkg(pkg)
                    new_args.append(pkg.getNVRA())
            else:
                new_args.append(name)
        # Append our new temporary repo to our internal repositories
        if memory_repo:
            self.repos.addDB(memory_repo)
        args = new_args
        self.delay_obsolete = True
        self.delay_obsolete_list = [ ]
        # Loop over all args and call the appropriate handler function for each
        for name in new_args:
            # We call our operation function which will handle all the
            # details for each specific case.
            ret = op_func(name, exact)
            if self.has_args and not ret:
                log.info1("No match for argument: %s", name)
        if self.config.timer:
            log.info2("package selection took %s seconds", (clock() - time1))
        if self.command.endswith("install") or self.command.endswith("remove"):
            self._generateTransactionState()
            return 1
        log.info2("Processing obsoletes")
        if self.config.timer:
            time1 = clock()
        self.__handleObsoletes(self.delay_obsolete_list)
        self.delay_obsolete = False
        self.delay_obsolete_list = [ ]
        if self.config.timer:
            log.info2("handling obsoletes took %s seconds", (clock() - time1))
        self._generateTransactionState()
        return 1

    def _generateTransactionState(self):
        resolver = self.opresolver
        # Remember the current state of the transaction before we do depsolving
        # so we know what operations were requested directly via commandline
        self.__iinstalls = list(resolver.installs)
        self.__ierases = list(resolver.erases)
        self.__iupdates = { }
        self.__iobsoletes = { }
        for p in resolver.updates:
            self.__iupdates[p] = [ ]
            if p in self.__iinstalls:
                self.__iinstalls.remove(p)
            for p2 in resolver.updates[p]:
                if p2 in self.__ierases:
                    self.__ierases.remove(p2)
                self.__iupdates[p].append(p2)
        for p in resolver.obsoletes:
            self.__iobsoletes[p] = [ ]
            if p in self.__iinstalls:
                self.__iinstalls.remove(p)
            for p2 in resolver.obsoletes[p]:
                if p2 in self.__ierases:
                    self.__ierases.remove(p2)
                self.__iobsoletes[p].append(p2)

    def runDepRes(self):
        """Run the complete depresolution.

        Return 1."""
        # ... or 0 if __runDepResolution fails, which currently can't happen.
        ret = 1
        if self.config.timer:
            time1 = clock()
        if not self.config.nodeps:
            ret = self.__runDepResolution()
        if self.config.timer:
            log.info2("runDepRes() took %s seconds", (clock() - time1))
        return ret

    def runCommand(self, clearrepos=False):
        """Perform operations from self.opresolver.

        Return 1 on success, 0 on error (after warning the user)."""

        # Get the current operations of the final transaction and generate
        # the difference to the pre-depsolver operations. That way we know
        # which operations were required because of dependencies.
        resolver = self.opresolver
        installs = resolver.installs.copy()
        erases = resolver.erases.copy()
        updates = { }
        obsoletes = { }
        totsize = ipkgs = epkgs = opkgs = upkgs = 0

        if len(installs) == 0 and len(erases) == 0:
            log.info2("Nothing to do.")
            return 1

        for p in resolver.updates:
            updates[p] = [ ]
            if p in installs:
                installs.remove(p)
            for p2 in resolver.updates[p]:
                if p2 in erases:
                    erases.remove(p2)
                updates[p].append(p2)
        for p in resolver.obsoletes:
            obsoletes[p] = [ ]
            if p in installs:
                installs.remove(p)
            for p2 in resolver.obsoletes[p]:
                if p2 in erases:
                    erases.remove(p2)
                obsoletes[p].append(p2)

        # Output the whole transaction in a very yummy format. ;)
        d = [{"NEVRA": "Package", "VRA": "Version", "NAME": "Package", "ARCH": "Arch", "VERSION": "Version", "REPO": "Repository", "SIZE": "Size"}]
        log.info2("\n===============================================================================")
        self.outputPkgList(d)
        log.info2("===============================================================================")

        if len(self.__iinstalls) > 0:
            log.info2("\nInstalling:")
            self.__iinstalls.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in self.__iinstalls:
                ipkgs += 1
                totsize += p.size
                if p in installs:
                    installs.remove(p)
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size)})
            self.outputPkgList(d)

        if len(self.__iupdates) > 0:
            log.info2("\nUpdating:")
            pl = self.__iupdates.keys()
            pl.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in pl:
                upkgs += 1
                totsize += p.size
                l = self.__iupdates[p]
                for p2 in l:
                    if p in updates.keys() and p2 in updates[p]:
                        updates[p].remove(p2)
                if p in updates.keys() and len(updates[p]) == 0:
                    del updates[p]
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size)})
            self.outputPkgList(d)

        if len(self.__iobsoletes) > 0:
            log.info2("\nObsoleting:")
            pl = self.__iobsoletes.keys()
            pl.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in pl:
                opkgs += 1
                totsize += p.size
                l = self.__iobsoletes[p]
                for p2 in l:
                    if p in obsoletes.keys() and p2 in obsoletes[p]:
                        obsoletes[p].remove(p2)
                if p in obsoletes.keys() and len(obsoletes[p]) == 0:
                    del obsoletes[p]
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size), "COMMENT": "replacing "+l[0].getNEVRA()})
            self.outputPkgList(d)

        if len(self.__ierases) > 0:
            log.info2("\nErasing:")
            self.__ierases.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in self.__ierases:
                epkgs += 1
                if p in erases:
                    erases.remove(p)
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(int(p["signature"]["payloadsize"][0]))})
            self.outputPkgList(d)

        # Dependency fooshizzle output
        if len(installs) > 0:
            log.info2("\nInstalling for dependencies:")
            installs = list(installs)
            installs.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in installs:
                ipkgs += 1
                totsize += p.size
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size)})
            self.outputPkgList(d)

        if len(updates) > 0:
            log.info2("\nUpdating for dependencies:")
            pl = updates.keys()
            pl.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in pl:
                upkgs += 1
                totsize += p.size
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size)})
            self.outputPkgList(d)

        if len(obsoletes) > 0:
            log.info2("\nObsoleting due to dependencies:")
            pl = obsoletes.keys()
            pl.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in pl:
                opkgs += 1
                totsize += p.size
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(p.size), "COMMENT": "replacing "+obsoletes[p][0].getNEVRA()})
            self.outputPkgList(d)

        if len(erases) > 0:
            log.info2("\nErasing due to dependencies:")
            erases = list(erases)
            erases.sort(lambda x,y:cmp(x["name"], y["name"]))
            d = []
            for p in erases:
                epkgs += 1
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(int(p["signature"]["payloadsize"][0]))})
            self.outputPkgList(d)

        self.erase_list = [pkg for pkg in self.erase_list
                           if pkg in self.pydb]

        if len(self.erase_list) > 0:
            log.info2("\nWarning: Following packages will be automatically "
                      "removed from your system:")
            d = []
            for p in self.erase_list:
                d.append({"NEVRA": p.getNEVRA(), "VRA": p.getVRA(), "NAME": p["name"], "ARCH": p["arch"], "VERSION": p.getVR(), "REPO": p.reponame, "SIZE": int2str(int(p["signature"]["payloadsize"][0]))})
            self.outputPkgList(d, 2)

        if self.confirm:
            log.info2("\nTransaction Summary")
            log.info2("===============================================================================")
            if ipkgs > 0:
                log.info2("Install      %5d package(s)" % ipkgs)
            if upkgs > 0:
                log.info2("Update       %5d package(s)" % upkgs)
            if opkgs > 0:
                log.info2("Obsolete     %5d package(s)" % opkgs)
            if epkgs > 0:
                log.info2("Erase        %5d package(s)" % epkgs)

        if totsize > 0:
            log.info2("\nTotal download size: %s" % int2str(totsize))

        if self.confirm and not self.config.test:
            if not is_this_ok():
                return 1

        if self.config.timer:
            time1 = clock()
        if self.command.endswith("remove"):
            control = RpmController(self.config, OP_ERASE, self.pydb)
        else:
            control = RpmController(self.config, OP_UPDATE, self.pydb)
        ops = control.getOperations(self.opresolver, self.repos, self.pydb)
        self.repos.clearPkgs(ntags=self.config.nevratags)

        if ops is None:
            return 0

        if self.config.timer:
            log.info2("runCommand() took %.2f seconds", (clock() - time1))
        if self.config.test:
            log.info1("Test run stopped")
        else:
            if clearrepos:
                self.repos.clear()
                self.read_repos = False
            if control.runOperations(ops) == 0:
                return 0
        self.pydb.close()
        return 1

    def outputPkgList(self, pkglist, level=2):
        #fmtstr = " %(NAME)-22.22s  %(ARCH)-9.9s  %(VERSION)-15.15s  %(REPO)-16.16s  %(SIZE)8.8s"
        #fmtstr  = " %(NEVRA)-50.50s  %(REPO)-16.16s  %(SIZE)8.8s"
        fmtstr  = " %(NAME)-30.30s %(VRA)-30.30s %(REPO)-10.10s %(SIZE)5.5s"
        fmtstr2 = "     %(COMMENT)-70.70s"
        for d in pkglist:
            log.info(level, fmtstr % d)
            if d.has_key("COMMENT"):
                log.info(level, fmtstr2 % d)

    def __generateObsoletesList(self):
        """Generate a list of all installed/available RpmPackage's that
        obsolete something and store it in self.__obsoleteslist."""

        obsoletes = set()
        self.__obsoleteslist = [ ]
        for entry in self.repos.iterObsoletes():
            obsoletes.add(entry[-1])
        self.__obsoleteslist = list(obsoletes)
        orderList(self.__obsoleteslist, self.config.machine)
        nhash = { }
        nlist = [ ]
        for pkg in self.__obsoleteslist:
            if nhash.has_key(pkg["name"]):
                continue
            nlist.append(pkg)
            nhash[pkg["name"]] = 1
        self.__obsoleteslist = nlist

    def __runDepResolution(self):
        """Try to resolve all dependencies and remove all conflicts..

        Return 1 after reaching a steady state."""

        log.info2("Resolving dependencies...")
        # List of filereqs we already checked
        self.filereqs = []
        self.iteration = 1

        # As long as either __handleUnresolvedDeps() or __handleConflicts()
        # changes something to the package set we need to continue the loop.
        # Afterwards there may still be unresolved deps or conflicts for which
        # we then have to check.
        self.delay_obsolete = True
        working = 1
        while working:
            working = 0
            working += self.__handleUnresolvedDeps()
            working += self.__handleObsoletes(self.delay_obsolete_list)
            working += self.__handleConflicts()
            working += self.__handleObsoleteConflicts()
            self.delay_obsolete_list = [ ]
        unresolved = self.opresolver.getUnresolvedDependencies()
        conflicts = self.opresolver.getConflicts()
        obsoleteconflicts = list(self.opresolver.getObsoleteConflicts())
        if len(unresolved) > 0:
            log.error("Unresolvable dependencies:")
            for pkg in unresolved.keys():
                log.error("Unresolved dependencies for %s", pkg.getNEVRA())
                for dep in unresolved[pkg]:
                    log.error("\t%s", depString(dep))
        if len(conflicts) > 0:
            log.error("Unresolvable conflicts:")
            for pkg in conflicts.keys():
                log.error("Unresolved conflicts for %s", pkg.getNEVRA())
                for (dep, r) in conflicts[pkg]:
                    log.error("\t%s", depString(dep))
        if len(obsoleteconflicts) > 0:
            log.error("Already installed obsoletes:")
            for pkg in conflicts.keys():
                log.error("Obsolete conflicts for %s", pkg.getNEVRA())
                for (dep, r) in conflicts[pkg]:
                    log.error("\t%s on %s", depString(dep), r.getNEVRA())
        if len(unresolved) == 0 and len(conflicts) == 0 and \
               len(obsoleteconflicts) == 0:
            return 1
        return 0

    def __handleUnresolvedDeps(self):
        """Try to install/remove packages to reduce the number of unresolved
        dependencies.

        Return 1 if some package changes have been done, 0 otherwise."""

        # Otherwise get first unresolved dep and then try to solve it as long
        # as we have unresolved deps. If we fail to resolve a dep we try the
        # next one until only unresolvable deps remain.
        ret = 0
        unresolved = self.opresolver.iterUnresolvedDependencies()
        # Store our unresolvable deps in here.
        unresolvable = []
        while True:
            for pkg, dep in unresolved:
                # Have we already tried to resolve this dep? If yes, skip it
                if dep in unresolvable:
                    continue
                log.info3("Dependency iteration %s", str(self.iteration))
                self.iteration += 1
                log.info3("Resolving dependency for %s", pkg.getNEVRA())
                # If we were able to resolve this dep in any way we reget the
                # deps and do the next internal iteration
                if self.__resolveDep(pkg, dep):
                    ret = 1
                    unresolved = self.opresolver.iterUnresolvedDependencies()
                    break
                # Add this dep to the ones we can't resolve at the moment
                unresolvable.append(dep)
            else: # exit while loop if we got through the for loop
                break
        return ret

    def __resolveDep(self, pkg, dep):
        """Attempt to resolve (name, RPMSENSE_* flag, EVR string) dependency of
        RpmPackage pkg.

        Return 1 after doing something that might have improved the situation,
        0 otherwise."""

        # Remove is the easy case: Just remove all packages that have
        # unresolved deps ;)
        if self.command.endswith("remove"):
            self.opresolver.erase(pkg)
            return 1
        # We need to first check if we might need to load the complete filelist
        # in case of file requirements for every repo.
        # In order to do so efficently we remember which filerequirements we
        # already handled and only handle each one once.
        modified_repo = 0
        if dep[0][0] == "/" and not dep[0] in self.filereqs:
            self.filereqs.append(dep[0])
            for repo in self.repos.dbs:
                if not hasattr(repo, 'isFilelistImported') or \
                       repo.isFilelistImported():
                    continue
                if not repo._matchesFile(dep[0]):
                    log.info2("Importing filelist from repository %s for "
                              "filereq %s", repo.reponame, dep[0])
                    if self.config.timer:
                        time1 = clock()
                    repo.importFilelist()
                    repo.reloadDependencies()
                    if self.config.timer:
                        log.info2("Importing filelist took %.2f seconds",
                                  (clock() - time1))
                    modified_repo = 1
            # In case we have modified at least one repository we now check if
            # by loading the filelist we already fullfilled the dependency in
            # case the package was already added to the transaction.
            if modified_repo:
                self.opresolver.getDatabase().reloadDependencies()
                if len(self.opresolver.getDatabase().searchDependency(dep[0], dep[1], dep[2])) > 0:
                    return 1
        # Now for all other cases we need to find packages in our repos
        # that resolve the given dependency
        pkg_list = [ ]
        log.info3("\t%s", depString(dep))
        for upkg in self.repos.searchDependency(dep[0], dep[1], dep[2]):
            if upkg in pkg_list:
                continue
            pkg_list.append(upkg)
        # Now add the first package that ist not in our erase list or
        # already in our opresolver to it and check afterwards if
        # there are any obsoletes for that package and handle them
        # Order the elements of the potential packages by machine
        # distance and evr.
        # Special handling of filerequirements need to be done here in order to
        # allow cross buildarchtranslate compatible package updates.
        ret = self.__handleBestPkg("update", pkg_list, None, False, dep[0][0] == "/", single=True)
        if ret > 0:
            return 1
        # Ok, we didn't find any package that could fullfill the
        # missing deps. Now what we do is we look for updates of that
        # package in all repos and try to update it.
        ret = self.update(pkg["name"])
        if ret > 0:
            return 1
        # OK, left over unresolved deps, but now we already have the
        # filelists from the repositories. We can now either:
        #   - Scrap it as we can't update the system without unresolved deps
        #   - Erase the packages that had unresolved deps (autoerase option)
        if self.autoerase:
            if self.__doAutoerase(pkg):
                log.info2("Autoerasing package %s due to unresolved symbols.",
                          pkg.getNEVRA())
                return 1
        return 0

    def __handleConflicts(self):
        """Try to update packages to fix conflicts in self.opresolver.

        Return 1 if all conflicts have been resolved or no more conflicts are
        there, otherwise return 0."""

        conflicts = self.opresolver.getConflicts()
        handled_conflict = 1
        ret = 0
        while len(conflicts) > 0 and handled_conflict:
            handled_conflict = 0
            for pkg1 in conflicts:
                for (c, pkg2) in conflicts[pkg1]:
                    if   c[1] & RPMSENSE_LESS != 0:
                        if self.update(pkg2["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    elif c[1] & RPMSENSE_GREATER != 0:
                        if self.update(pkg1["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                    else:
                        if   self.update(pkg1["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                        elif self.update(pkg2["name"]) > 0:
                            handled_conflict = 1
                            ret = 1
                            break
                if handled_conflict:
                    break
            conflicts = self.opresolver.getConflicts()
        handled_fileconflict = 1
        if not self.config.nofileconflicts:
            conflicts = self.opresolver.getFileConflicts()
            while len(conflicts) > 0 and handled_fileconflict:
                handled_fileconflict = 0
                for pkg1 in conflicts:
                    for (c, pkg2) in conflicts[pkg1]:
                        if self.update(pkg2["name"]) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                        elif self.update(pkg1["name"]) > 0:
                            handled_fileconflict = 1
                            ret = 1
                            break
                    if handled_fileconflict:
                        break
                conflicts = self.opresolver.getFileConflicts()
        if not (handled_conflict and handled_fileconflict) and self.autoerase:
            return self.__handleConflictAutoerases()
        return ret

    def __handleObsoleteConflicts(self):
        if not self.autoerase:
            return 0
        ret = 0
        for (old_pkg, new_pkgs) in self.opresolver.getObsoleteConflicts().iteritems():
            for obsolete, new_pkg in new_pkgs:
                if self.__doAutoerase(new_pkg):
                    log.info2("Autoerasing package %s due to conflicting obsoletes.",
                              new_pkg.getNEVRA())
                    ret = 1
        return ret

    def __handleObsoletes(self, pkglist=None):
        """Try to replace RpmPackage pkg in self.opresolver by a package
        obsoleting it, iterate until no obsoletes: applies.

        Return 1 if pkg was obsoleted, 0 if not."""

        if pkglist is None:
            pkglist = [ ]
        full = (len(pkglist) == 0)  # Flag if we need to do a full run
        obsoleted = False
        namehash = { }
        for pkg in pkglist:
            namehash.setdefault(pkg["name"], [ ]).append(pkg)
        # Loop until we have found the end of the obsolete chain
        while 1:
            found = False
            # Go over all packages we know have obsoletes
            for opkg in self.__obsoleteslist:
                # If the obsolete package has already been tried once or is in
                # our erase_list skip it.
                if opkg in self.opkg_list or opkg in self.erase_list:
                    continue
                # Never add obsolete packages for packages with the same name.
                if len(pkglist) > 0:
                    if len(pkglist) == len(namehash.get(opkg["name"], [ ])):
                        continue
                # Go through all obsoletes
                for u in opkg["obsoletes"]:
                    # Reinit plist
                    plist = [ ]
                    # Look in our current database for matches
                    s = self.opresolver.getDatabase().searchDependency(u[0], u[1], u[2])
                    # If we got no results, we don't obsolete.
                    if len(s) == 0:
                        continue
                    # Same as for the outer loop, if the package names match
                    # we never obsolete.
                    if s[0]["name"] == opkg["name"]:
                        continue
                    # In case of a full run we always obsolete if we found a
                    # match. Otherwise if the packages for which we were
                    # checking the obsoletes right now isn't in the list skip
                    # it.
                    if len(pkglist) > 0:
                        for p in s:
                            if p["name"] != opkg["name"] and p in pkglist:
                                plist.append(p)
                        if len(plist) == 0:
                            continue
                    # Found a matching obsoleting package. Try adding it to
                    # our opresolver with an update so it obsoletes the
                    # installed package
                    ret = self.opresolver.update(opkg)
                    # If it has already been added before readd it by erasing
                    # it and adding it again. This will ensure that the
                    # obsoleting will occur in the resolver.
                    if ret == self.opresolver.ALREADY_ADDED:
                        self.opresolver.erase(opkg)
                        ret = self.opresolver.update(opkg)
                    # If everything went well note this and terminate the
                    # inner obsoletes loop
                    if ret > 0:
                        obsoleted = True
                        found = True
                        break
                # If we found and handled one obsolete proplerly break the
                # loop over the obsoletes packages and restart
                if found:
                    break
            # In case we found an obsolete in the last round replace the package
            # we're trying to obsolete with the one we just added if we had an
            # initial package. If we need to do a full run reset the package to
            # None. The just do another iteration.
            # If nothing was found we're finished and can return.
            if found:
                self.opkg_list.append(opkg)
                if not full:
                    pkglist.append(opkg)
                    for p in plist:
                        pkglist.remove(p)
            else:
                break
        # Return wether we obsoleted any package this time or not.
        return obsoleted

    def __doAutoerase(self, pkg):
        """Try to remove RpmPackage pkg from self.opresolver to resolve a
        dependency.

        Return 1 on success, 0 on error (after warning the user)."""

        for reex in self.autoeraseexclude:
            if reex.match(pkg["name"]) and \
             len(self.opresolver.getDatabase().getPkgsByName(pkg["name"])) == 1:
                self.erase_list.append(pkg)
                log.Info2("No autoerase of package %s due to exclude list.",
                          pkg.getNEVRA())
                return 0
        if self.opresolver.updates.has_key(pkg):
            updates = self.opresolver.updates[pkg]
        else:
            updates = [ ]
        ret = self.opresolver.erase(pkg)
        if ret > 0:
            self.erase_list.append(pkg)
            for upkg in updates:
                if upkg in self.erase_list:
                    continue
                self.opresolver.update(upkg)
        else:
            return 0
        return 1

    def __handleConflictAutoerases(self):
        """Erase packages from self.opresolver to get rid of all conflicts.

        Return 1 if at least one package was successfuly chosen for erasing."""

        ret = 0
        # The loops will finish because __doConflictAutoerase() always removes
        # at least one of the conflicting packages for each conflict.
        conflicts = self.opresolver.getConflicts()
        while len(conflicts) > 0:
            pkg1 = conflicts.keys()[0]
            (c, pkg2) = conflicts[pkg1][0]
            if self.__doConflictAutoerase(pkg1, pkg2):
                ret = 1
            conflicts = self.opresolver.getConflicts()
        if not self.config.nofileconflicts:
            conflicts = self.opresolver.getFileConflicts()
            while len(conflicts) > 0:
                pkg1 = conflicts.keys()[0]
                (c, pkg2) = conflicts[pkg1][0]
                if self.__doConflictAutoerase(pkg1, pkg2):
                    ret = 1
                conflicts = self.opresolver.getFileConflicts()
        return ret

    def __doConflictAutoerase(self, pkg1, pkg2):
        """Resolve one single conflict by semi intelligently selecting one of
        the two packages to be autoereased.

        Return 1 if one package was successfully removed, 0 otherwise."""

        ret = 0
        log.info3("Resolving conflicts for %s:%s", pkg1.getNEVRA(),
                  pkg2.getNEVRA())
        if   pkg1 in self.erase_list:
            pkg = pkg2
        elif pkg2 in self.erase_list:
            pkg = pkg1
        elif pkg1 in self.pydb and \
             not pkg1 in self.erase_list:
            pkg = pkg1
        elif pkg2 in self.pydb and \
             not pkg2 in self.erase_list:
            pkg = pkg2
        elif machineDistance(pkg2["arch"], self.config.machine) < \
             machineDistance(pkg1["arch"], self.config.machine):
            pkg = pkg1
        elif machineDistance(pkg2["arch"], self.config.machine) > \
             machineDistance(pkg1["arch"], self.config.machine):
            pkg = pkg2
        elif pkg1.has_key("sourcerpm") and \
             pkg2.has_key("sourcerpm") and \
             envraSplit(pkg1["sourcerpm"])[1] == envraSplit(pkg2["sourcerpm"])[1]:
            (e1, n1, v1, r1, a1) = envraSplit(pkg1["sourcerpm"])
            (e2, n2, v2, r2, a2) = envraSplit(pkg2["sourcerpm"])
            ccmp = labelCompare((e1, v1, r1), (e2, v2, r2))
            if   ccmp < 0:
                pkg = pkg1
            elif ccmp > 0:
                pkg = pkg2
            else:
                if len(pkg1.getNEVRA()) < len(pkg2.getNEVRA()):
                    pkg = pkg2
                else:
                    pkg = pkg1
        elif doesObsolete(pkg1, pkg2):
            pkg = pkg2
        elif doesObsolete(pkg2, pkg1):
            pkg = pkg1
        elif len(pkg1.getNEVRA()) < len(pkg2.getNEVRA()):
            pkg = pkg2
        else:
            pkg = pkg1
        # Returns 0 if pkg was already erased - but warns the user
        if self.__doAutoerase(pkg):
            log.info2("Autoerasing package %s due to conflicts",
                      pkg.getNEVRA())
            ret = 1
        return ret

    ###  search/list/info commands ##########################################

    def search(self, args):
        pkgs = self._mergePkgLists(self.pydb.search(args),
                                   self.repos.search(args))
        self.formatPkgs(pkgs)
        return 0

    def checkupdate(self, args):
        log.error("Not invented here")
        return 0

    def deplist(self, args):
        pkgs = self._mergePkgLists(self.getInstalled(args),
                                   self.getRepoPkgs(args))
        pkgs.sort()
        for pkg in pkgs:
            log.info1("Package: %s %s", pkg.getNA(), pkg.getVR())
            for name, flag, version in pkg['requires']:
                if name.startswith('rpmlib('):
                    continue
                log.info1("\tdependency: %s %s %s",
                          name, rpmFlag2Str(flag), version)
                resolvers = self._mergePkgLists(
                    self.pydb.searchDependency(name, flag, version),
                    self.repos.searchDependency(name, flag, version))
                resolvers = [(rpkg.getNA(), rpkg.getVR())
                             for rpkg in resolvers]
                resolvers.sort()
                for na, vr in resolvers:
                    log.info1('\t\tprovider: %s %s', na, vr)
        return 0

    def resolvedep(self, args):
        for arg in args:
            split_arg = arg.split()
            if len(split_arg) == 3:
                name, flag, version = split_arg
            else:
                name, flag, version = arg.strip(), 0, ''
            flag = str2RpmFlag(flag)
            resolvers = self._mergePkgLists(
                self.pydb.searchDependency(name, flag, version),
                self.repos.searchDependency(name, flag, version))
            resolvers = [(rpkg.getNA(), rpkg.getVR(), rpkg.db.reponame)
                         for rpkg in resolvers]
            resolvers.sort()
            
            if self.command == 'resolvedep' and resolvers:
                # XXX prefere installed?
                log.info1('%s %s %s', *resolvers[-1])
                return 0
            for na, vr, repo in resolvers:
                log.info1('%s %s %s', na, vr, repo)
        return 0

    def list(self, args):
        if not args:
            command, patterns = 'all', []
        else:
            command, patterns = args[0].lower(), args[1:]
        if command == "available":
            self.__generateObsoletesList()
            self.formatPkgs(self.getAvailable(patterns),
                            "Available Packages:")
        elif command == "updates":
            self.__generateObsoletesList()
            self.formatPkgs(self.getUpdates(patterns),
                            "Available Updates:")
        elif command == "installed":
            self.formatPkgs(self.getInstalled(patterns),
                            "Installed Packages:")
        elif command == "extras":
            self.formatPkgs(self.getExtras(patterns),
                            "Installed Extra Packages:")
        elif command == "obsoletes":
            self.__generateObsoletesList()
            obsoletes = self.getObsoletes(patterns)
            if not obsoletes:
                return 0
            log.info1("")
            log.info1("Available Obsoleting Packages:")
            for new, old in obsoletes.iteritems():
                log.info("%32s obsoletes %32s" %
                         (new.getNEVRA(), old.getNEVRA()))
        elif command == "recent":
            self.formatPkgs(self.getRecent(patterns), "Recent Packages:")
        elif command == "all":
            self.formatPkgs(self.getInstalled(patterns),
                            "Installed Packages:")
            self.__generateObsoletesList()
            self.formatPkgs(self.getAvailable(patterns),
                            "Available Packages:")
        else:
            self.formatPkgs(self.getInstalled(args), "Installed Packages:")
            self.__generateObsoletesList()
            self.formatPkgs(self.getAvailable(args), "Available Packages:")
        return 0

    def _mergePkgLists(self, *lists):
        d = {}
        for l in lists:
            for pkg in l:
                nevra = pkg.getNEVRA()
                if not nevra in d:
                    d[nevra] = pkg
        return d.values()

    def _pkgNameDict(self, pkgs, dict_=None):
        if dict_ is None:
            dict_ = {}
        for pkg in pkgs:
            dict_.setdefault(pkg['name'], []).append(pkg)
        return dict_

    def _pkgNameArchDict(self, pkgs, dict_=None):
        if dict_ is None:
            dict_ = {}
        for pkg in pkgs:
            dict_.setdefault(pkg.getNA(), []).append(pkg)
        return dict_

    def _NEVRADict(self, pkgs):
        return dict([(pkg.getNEVRA(), pkg) for pkg in pkgs])

    def formatPkgs(self, pkgs, msg=''):
        if not pkgs:
            return
        log.info1("")
        if msg:
            log.info1(msg)
        
        pkgs = [(p.getNA(), p.getVR(), p.db.reponame, p)
                for p in pkgs]
        pkgs.sort()
        if self.command in ("info", "search"):
            for p in pkgs:
                pkg = p[-1]
                log.info1("Package : %s", p[0])
                log.info1("Version : %s", p[1])
                log.info1("Repo    : %s", p[2])
                log.info1("Size    : %s", int2str(
                    (pkg['size'] and pkg['size'][0]) or 0))
                log.info1("Summary : %s", (
                    pkg['summary'] and pkg['summary'][0]) or '')
                log.info1("Description:")
                log.info1((pkg['description'] and pkg['description'][0])
                          or '')
                log.info1('')
        else:
            for p in pkgs:
                log.info1("%-40s %-22s %-16s", *p[:-1])

    def getInstalled(self, patterns=[]):
        if not patterns:
            return self.pydb.getPkgs()
        else:
            return self.pydb.searchPkgs(patterns)

    def getRepoPkgs(self, patterns=[]):
        if not patterns:
            return self.repos.getPkgs()
        else:
            return self.repos.searchPkgs(patterns)

    def getAvailable(self, patterns):
        pkg_dict = self._pkgNameArchDict(self.getRepoPkgs(patterns))
        for pkg in self.getInstalled(patterns):
            na = pkg.getNA()
            if na in pkg_dict:
                del pkg_dict[na]
        result = []
        for name, l in pkg_dict.iteritems():
            l.sort()
            result.append(l[-1])
        result +=  self.getUpdates(patterns)
        normalizeList(result)
        return result

    def getExtras(self, patterns):
        pkgs = self.getInstalled(patterns)
        result = []
        for pkg in pkgs:
            if not self.repos.searchPkgs([pkg.getNEVRA()]):
                result.append(pkg)
        return result

    def getUpdates(self, patterns):
        self.__handleObsoletes()
        if patterns:
            names = dict(((pkg['name'], None) for pkg in
                          self.opresolver.getDatabase().searchPkgs(patterns)))
            names = names.keys()
        else:
            names = self.opresolver.getDatabase().getNames()
        for name in names:
            self.update(name, exact=True, do_obsolete=False)
        return self.opresolver.installs

    def getObsoletes(self, patterns):
        self.__handleObsoletes()
        if not patterns:
            return self.opresolver.obsoletes
        result = {}
        for pkg, opkg in self.opresolver.obsoletes.iteritems():
            found = False
            for pattern in patterns:
                regex = re.compile(fnmatch.translate(pattern))
                for n in pkg.getAllNames():
                    if regex.match(n):
                        result[pkg] = opkg
                        found = True
                        break
                if found:
                    break
        return result

    def getRecent(self, patterns):
        now = time()
        result = []
        for pkg in self.getRepoPkgs(patterns):
            t = pkg["time_file"] or pkg['time_build']
            if not t:
                continue
            if now - int(t) < self.yumconfig.get('recent', 7) * 86400:
                result.append(pkg)
        return result

# vim:ts=4:sw=4:showmatch:expandtab
