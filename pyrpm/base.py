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
# Copyright 2004 Red Hat, Inc.
#
# Author: Phil Knirsch, Thomas Woerner, Florian La Roche
#

from config import *

class RpmFileInfo:
    def __init__(self, filename, inode, mode, uid, gid, mtime, filesize, dev, rdev, md5sum):
        self.filename = filename
        self.inode = inode
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.mtime = mtime
        self.filesize = filesize
        self.dev = dev
        self.rdev = rdev
        self.md5sum = md5sum


# RPM Constants - based from rpmlib.h and elsewhere

# rpm tag types
#RPM_NULL = 0
RPM_CHAR = 1
RPM_INT8 = 2
RPM_INT16 = 3
RPM_INT32 = 4
RPM_INT64 = 5 # currently unused
RPM_STRING = 6
RPM_BIN = 7
RPM_STRING_ARRAY = 8
RPM_I18NSTRING = 9

# new type internal to this tool:
# STRING_ARRAY for app + params or STRING otherwise
RPM_ARGSTRING = 12

# header private tags
HEADER_IMAGE = 61
HEADER_SIGNATURES = 62 # starts a header with signatures
HEADER_IMMUTABLE = 63 # starts a header with other rpm tags
HEADER_REGIONS = 64
HEADER_I18NTABLE = 100

HEADER_SIGBASE = 256 # starting tag for sig information
HEADER_TAGBASE = 1000 # starting tag for other rpm tags

# RPM header tags
RPMTAG_HEADERIMAGE = HEADER_IMAGE
RPMTAG_HEADERSIGNATURES = HEADER_SIGNATURES
RPMTAG_HEADERIMMUTABLE = HEADER_IMMUTABLE
RPMTAG_HEADERREGIONS = HEADER_REGIONS
RPMTAG_HEADERI18NTABLE = HEADER_I18NTABLE

RPMTAG_SIG_BASE = HEADER_SIGBASE
RPMTAG_SIGSIZE = RPMTAG_SIG_BASE+1
RPMTAG_SIGLEMD5_1 = RPMTAG_SIG_BASE+2
RPMTAG_SIGPGP = RPMTAG_SIG_BASE+3
RPMTAG_SIGLEMD5_2 = RPMTAG_SIG_BASE+4
RPMTAG_SIGMD5 = RPMTAG_SIG_BASE+5
RPMTAG_SIGGPG = RPMTAG_SIG_BASE+6
RPMTAG_SIGPGP5 = RPMTAG_SIG_BASE+7
RPMTAG_BADSHA1_1 = RPMTAG_SIG_BASE+8
RPMTAG_BADSHA1_2 = RPMTAG_SIG_BASE+9
RPMTAG_PUBKEYS = RPMTAG_SIG_BASE+10
RPMTAG_DSAHEADER = RPMTAG_SIG_BASE+11
RPMTAG_RSAHEADER = RPMTAG_SIG_BASE+12
RPMTAG_SHA1HEADER = RPMTAG_SIG_BASE+13

RPMSIGTAG_SIZE = 1000
RPMSIGTAG_LEMD5_1 = 1001
RPMSIGTAG_PGP = 1002
RPMSIGTAG_LEMD5_2 = 1002
RPMSIGTAG_MD5 = 1004
RPMSIGTAG_GPG = 1005
RPMSIGTAG_PGP5 = 1006
RPMSIGTAG_PAYLOADSIZE = 1007

RPMTAG_NAME = 1000
RPMTAG_VERSION = 1001
RPMTAG_RELEASE = 1002
RPMTAG_EPOCH = 1003
RPMTAG_SUMMARY = 1004
RPMTAG_DESCRIPTION = 1005
RPMTAG_BUILDTIME = 1006
RPMTAG_BUILDHOST = 1007
RPMTAG_INSTALLTIME = 1008
RPMTAG_SIZE = 1009
RPMTAG_DISTRIBUTION = 1010
RPMTAG_VENDOR = 1011
RPMTAG_GIF = 1012
RPMTAG_XPM = 1013
RPMTAG_LICENSE = 1014
RPMTAG_PACKAGER = 1015
RPMTAG_GROUP = 1016
RPMTAG_CHANGELOG = 1017
RPMTAG_SOURCE = 1018
RPMTAG_PATCH = 1019
RPMTAG_URL = 1020
RPMTAG_OS = 1021
RPMTAG_ARCH = 1022
RPMTAG_PREIN = 1023
RPMTAG_POSTIN = 1024
RPMTAG_PREUN = 1025
RPMTAG_POSTUN = 1026
RPMTAG_OLDFILENAMES = 1027
RPMTAG_FILESIZES = 1028
RPMTAG_FILESTATES = 1029
RPMTAG_FILEMODES = 1030
RPMTAG_FILEUIDS = 1031
RPMTAG_FILEGIDS = 1032
RPMTAG_FILERDEVS = 1033
RPMTAG_FILEMTIMES = 1034
RPMTAG_FILEMD5S = 1035
RPMTAG_FILELINKTOS = 1036
RPMTAG_FILEFLAGS = 1037
RPMTAG_ROOT = 1038
RPMTAG_FILEUSERNAME = 1039
RPMTAG_FILEGROUPNAME = 1040
RPMTAG_EXCLUDE = 1041
RPMTAG_EXCLUSIVE = 1042
RPMTAG_ICON = 1043
RPMTAG_SOURCERPM = 1044
RPMTAG_FILEVERIFYFLAGS = 1045
RPMTAG_ARCHIVESIZE = 1046
RPMTAG_PROVIDENAME = 1047
RPMTAG_REQUIREFLAGS = 1048
RPMTAG_REQUIRENAME = 1049
RPMTAG_REQUIREVERSION = 1050
RPMTAG_NOSOURCE = 1051
RPMTAG_NOPATCH = 1052
RPMTAG_CONFLICTFLAGS = 1053
RPMTAG_CONFLICTNAME = 1054
RPMTAG_CONFLICTVERSION = 1055
RPMTAG_DEFAULTPREFIX = 1056
RPMTAG_BUILDROOT = 1057
RPMTAG_INSTALLPREFIX = 1058
RPMTAG_EXCLUDEARCH = 1059
RPMTAG_EXCLUDEOS = 1060
RPMTAG_EXCLUSIVEARCH = 1061
RPMTAG_EXCLUSIVEOS = 1062
RPMTAG_AUTOREQPROV = 1063
RPMTAG_RPMVERSION = 1064
RPMTAG_TRIGGERSCRIPTS = 1065
RPMTAG_TRIGGERNAME = 1066
RPMTAG_TRIGGERVERSION = 1067
RPMTAG_TRIGGERFLAGS = 1068
RPMTAG_TRIGGERINDEX = 1069
RPMTAG_VERIFYSCRIPT = 1079
RPMTAG_VERIFYSCRIPT2 = 15
RPMTAG_CHANGELOGTIME = 1080
RPMTAG_CHANGELOGNAME = 1081
RPMTAG_CHANGELOGTEXT = 1082
RPMTAG_BROKENMD5 = 1083
RPMTAG_PREREQ = 1084
RPMTAG_PREINPROG = 1085
RPMTAG_POSTINPROG = 1086
RPMTAG_PREUNPROG = 1087
RPMTAG_POSTUNPROG = 1088
RPMTAG_BUILDARCHS = 1089
RPMTAG_OBSOLETENAME = 1090
RPMTAG_VERIFYSCRIPTPROG = 1091
RPMTAG_TRIGGERSCRIPTPROG = 1092
RPMTAG_DOCDIR = 1093
RPMTAG_COOKIE = 1094
RPMTAG_FILEDEVICES = 1095
RPMTAG_FILEINODES = 1096
RPMTAG_FILELANGS = 1097
RPMTAG_PREFIXES = 1098
RPMTAG_INSTPREFIXES = 1099
RPMTAG_TRIGGERIN = 1100
RPMTAG_TRIGGERUN = 1101
RPMTAG_TRIGGERPOSTUN = 1102
RPMTAG_AUTOREQ = 1103
RPMTAG_AUTOPROV = 1104
RPMTAG_CAPABILITY = 1105
RPMTAG_SOURCEPACKAGE = 1106
RPMTAG_OLDORIGFILENAMES = 1107
RPMTAG_BUILDPREREQ = 1108
RPMTAG_BUILDREQUIRES = 1109
RPMTAG_BUILDCONFLICTS = 1110
RPMTAG_BUILDMACROS = 1111
RPMTAG_PROVIDEFLAGS = 1112
RPMTAG_PROVIDEVERSION = 1113
RPMTAG_OBSOLETEFLAGS = 1114
RPMTAG_OBSOLETEVERSION = 1115
RPMTAG_DIRINDEXES = 1116
RPMTAG_BASENAMES = 1117
RPMTAG_DIRNAMES = 1118
RPMTAG_ORIGDIRINDEXES = 1119
RPMTAG_ORIGBASENAMES = 1120
RPMTAG_ORIGDIRNAMES = 1121
RPMTAG_OPTFLAGS = 1122
RPMTAG_DISTURL = 1123
RPMTAG_PAYLOADFORMAT = 1124
RPMTAG_PAYLOADCOMPRESSOR = 1125
RPMTAG_PAYLOADFLAGS = 1126
RPMTAG_INSTALLCOLOR = 1127
RPMTAG_INSTALLTID = 1128
RPMTAG_REMOVETID = 1129
RPMTAG_SHA1RHN = 1130
RPMTAG_RHNPLATFORM = 1131
RPMTAG_PLATFORM = 1132
RPMTAG_PATCHESNAME = 1133
RPMTAG_PATCHESFLAGS = 1134
RPMTAG_PATCHESVERSION = 1135
RPMTAG_CACHECTIME = 1136
RPMTAG_CACHEPKGPATH = 1137
RPMTAG_CACHEPKGSIZE = 1138
RPMTAG_CACHEPKGMTIME = 1139
RPMTAG_FILECOLORS = 1140
RPMTAG_FILECLASS = 1141
RPMTAG_CLASSDICT = 1142
RPMTAG_FILEDEPENDSX = 1143
RPMTAG_FILEDEPENDSN = 1144
RPMTAG_DEPENDSDICT = 1145
RPMTAG_SOURCEPKGID = 1146
RPMTAG_FILECONTEXTS = 1147
RPMSIGTAG_BADSHA1_1 = RPMTAG_BADSHA1_1
RPMSIGTAG_BADSHA1_2 = RPMTAG_BADSHA1_2
RPMSIGTAG_SHA1 = RPMTAG_SHA1HEADER
RPMSIGTAG_DSA = RPMTAG_DSAHEADER
RPMSIGTAG_RSA = RPMTAG_RSAHEADER

RPMTAG_DELTAHOFFSETORDER = 20001  # RPMTAG_NAME array
RPMTAG_DELTAVERSION =    20002 # RPM_PROVIDEVERSION array
RPMTAG_DELTAORIGSIGS = 20003 # BIN
RPMTAG_DELTAHINDEXORDER = 20004 # RPMTAG_NAME array
RPMTAG_DELTARAWPAYLOADXDELTA = 20005 # BIN
RPMTAG_DELTAORIGPAYLOADFORMAT = 20006 # RPMTAG_PAYLOADFORMAT
RPMTAG_DELTAFILEFLAGS = 20007 # INT16 array

# RPMSENSEFLAGS
RPMSENSE_ANY        = 0
RPMSENSE_SERIAL     = (1 << 0)     # @todo Legacy.
RPMSENSE_LESS       = (1 << 1)
RPMSENSE_GREATER    = (1 << 2)
RPMSENSE_EQUAL      = (1 << 3)
RPMSENSE_PROVIDES   = (1 << 4) # only used internally by builds
RPMSENSE_CONFLICTS  = (1 << 5) # only used internally by builds
RPMSENSE_PREREQ     = (1 << 6)     # @todo Legacy.
RPMSENSE_OBSOLETES  = (1 << 7) # only used internally by builds
RPMSENSE_INTERP     = (1 << 8)     # Interpreter used by scriptlet.
RPMSENSE_SCRIPT_PRE = ((1 << 9)|RPMSENSE_PREREQ) # %pre dependency.
RPMSENSE_SCRIPT_POST = ((1 << 10)|RPMSENSE_PREREQ) # %post dependency.
RPMSENSE_SCRIPT_PREUN = ((1 << 11)|RPMSENSE_PREREQ) # %preun dependency.
RPMSENSE_SCRIPT_POSTUN = ((1 << 12)|RPMSENSE_PREREQ) # %postun dependency.
RPMSENSE_SCRIPT_VERIFY = (1 << 13) # %verify dependency.
RPMSENSE_FIND_REQUIRES = (1 << 14) # find-requires generated dependency.
RPMSENSE_FIND_PROVIDES = (1 << 15) # find-provides generated dependency.
RPMSENSE_TRIGGERIN  = (1 << 16)    # %triggerin dependency.
RPMSENSE_TRIGGERUN  = (1 << 17)    # %triggerun dependency.
RPMSENSE_TRIGGERPOSTUN = (1 << 18) # %triggerpostun dependency.
RPMSENSE_MISSINGOK  = (1 << 19)    # suggests/enhances/recommends hint.
RPMSENSE_SCRIPT_PREP = (1 << 20)   # %prep build dependency.
RPMSENSE_SCRIPT_BUILD = (1 << 21)  # %build build dependency.
RPMSENSE_SCRIPT_INSTALL = (1 << 22)# %install build dependency.
RPMSENSE_SCRIPT_CLEAN = (1 << 23)  # %clean build dependency.
RPMSENSE_RPMLIB     = ((1 << 24) | RPMSENSE_PREREQ) # rpmlib(feature) dependency.
RPMSENSE_TRIGGERPREIN = (1 << 25)  # @todo Implement %triggerprein.
RPMSENSE_KEYRING    = (1 << 26)
RPMSENSE_PATCHES    = (1 << 27)
RPMSENSE_CONFIG     = (1 << 28)

RPMSENSE_SENSEMASK  = 15       # Mask to get senses, ie serial,
                               # less, greater, equal.

RPMSENSE_TRIGGER    = (RPMSENSE_TRIGGERIN | RPMSENSE_TRIGGERUN | RPMSENSE_TRIGGERPOSTUN)

_ALL_REQUIRES_MASK  = (RPMSENSE_INTERP | RPMSENSE_SCRIPT_PRE | RPMSENSE_SCRIPT_POST | RPMSENSE_SCRIPT_PREUN | RPMSENSE_SCRIPT_POSTUN | RPMSENSE_SCRIPT_VERIFY | RPMSENSE_FIND_REQUIRES | RPMSENSE_SCRIPT_PREP | RPMSENSE_SCRIPT_BUILD | RPMSENSE_SCRIPT_INSTALL | RPMSENSE_SCRIPT_CLEAN | RPMSENSE_RPMLIB | RPMSENSE_KEYRING)

def _notpre(x):
    return (x & ~RPMSENSE_PREREQ)

_INSTALL_ONLY_MASK = _notpre(RPMSENSE_SCRIPT_PRE|RPMSENSE_SCRIPT_POST|RPMSENSE_RPMLIB|RPMSENSE_KEYRING)
_ERASE_ONLY_MASK   = _notpre(RPMSENSE_SCRIPT_PREUN|RPMSENSE_SCRIPT_POSTUN)

def isLegacyPreReq(x):
    return (x & _ALL_REQUIRES_MASK) == RPMSENSE_PREREQ
def isInstallPreReq(x):
    return (x & _INSTALL_ONLY_MASK)
def isErasePreReq(x):
    return (x & _ERASE_ONLY_MASK)

# XXX: TODO for possible rpm changes:
# - arch should not be needed for src.rpms
# - deps could be left away from src.rpms
# - cookie could go away
# - rhnplatform could go away

# list of all rpm tags in Fedora Core development
# tagname: (tag, type, how-many, flags:legacy=1,src-only=2,bin-only=4)
rpmtag = {
    # basic info
    "name": (RPMTAG_NAME, RPM_STRING, None, 0),
    "epoch": (RPMTAG_EPOCH, RPM_INT32, 1, 0),
    "version": (RPMTAG_VERSION, RPM_STRING, None, 0),
    "release": (RPMTAG_RELEASE, RPM_STRING, None, 0),
    "arch": (RPMTAG_ARCH, RPM_STRING, None, 0),

    # dependencies: provides, requires, obsoletes, conflicts
    "providename": (RPMTAG_PROVIDENAME, RPM_STRING_ARRAY, None, 0),
    "provideflags": (RPMTAG_PROVIDEFLAGS, RPM_INT32, None, 0),
    "provideversion": (RPMTAG_PROVIDEVERSION, RPM_STRING_ARRAY, None, 0),
    "requirename": (RPMTAG_REQUIRENAME, RPM_STRING_ARRAY, None, 0),
    "requireflags": (RPMTAG_REQUIREFLAGS, RPM_INT32, None, 0),
    "requireversion": (RPMTAG_REQUIREVERSION, RPM_STRING_ARRAY, None, 0),
    "obsoletename": (RPMTAG_OBSOLETENAME, RPM_STRING_ARRAY, None, 4),
    "obsoleteflags": (RPMTAG_OBSOLETEFLAGS, RPM_INT32, None, 4),
    "obsoleteversion": (RPMTAG_OBSOLETEVERSION, RPM_STRING_ARRAY, None, 4),
    "conflictname": (RPMTAG_CONFLICTNAME, RPM_STRING_ARRAY, None, 0),
    "conflictflags": (RPMTAG_CONFLICTFLAGS, RPM_INT32, None, 0),
    "conflictversion": (RPMTAG_CONFLICTVERSION, RPM_STRING_ARRAY, None, 0),

    # triggers
    "triggername": (RPMTAG_TRIGGERNAME, RPM_STRING_ARRAY, None, 4),
    "triggerflags": (RPMTAG_TRIGGERFLAGS, RPM_INT32, None, 4),
    "triggerversion": (RPMTAG_TRIGGERVERSION, RPM_STRING_ARRAY, None, 4),
    "triggerscripts": (RPMTAG_TRIGGERSCRIPTS, RPM_STRING_ARRAY, None, 4),
    "triggerscriptprog": (RPMTAG_TRIGGERSCRIPTPROG, RPM_STRING_ARRAY, None, 4),
    "triggerindex": (RPMTAG_TRIGGERINDEX, RPM_INT32, None, 4),

    # scripts
    "prein": (RPMTAG_PREIN, RPM_STRING, None, 4),
    "preinprog": (RPMTAG_PREINPROG, RPM_ARGSTRING, None, 4),
    "postin": (RPMTAG_POSTIN, RPM_STRING, None, 4),
    "postinprog": (RPMTAG_POSTINPROG, RPM_ARGSTRING, None, 4),
    "preun": (RPMTAG_PREUN, RPM_STRING, None, 4),
    "preunprog": (RPMTAG_PREUNPROG, RPM_ARGSTRING, None, 4),
    "postun": (RPMTAG_POSTUN, RPM_STRING, None, 4),
    "postunprog": (RPMTAG_POSTUNPROG, RPM_ARGSTRING, None, 4),
    "verifyscript": (RPMTAG_VERIFYSCRIPT, RPM_STRING, None, 4),
    "verifyscriptprog": (RPMTAG_VERIFYSCRIPTPROG, RPM_ARGSTRING, None, 4),

    # addon information:
    # list of available languages
    "i18ntable": (HEADER_I18NTABLE, RPM_STRING_ARRAY, None, 0),
    "summary": (RPMTAG_SUMMARY, RPM_I18NSTRING, None, 0),
    "description": (RPMTAG_DESCRIPTION, RPM_I18NSTRING, None, 0),
    "url": (RPMTAG_URL, RPM_STRING, None, 0),
    "license": (RPMTAG_LICENSE, RPM_STRING, None, 0),
    "rpmversion": (RPMTAG_RPMVERSION, RPM_STRING, None, 0),
    "sourcerpm": (RPMTAG_SOURCERPM, RPM_STRING, None, 4),
    "changelogtime": (RPMTAG_CHANGELOGTIME, RPM_INT32, None, 0),
    "changelogname": (RPMTAG_CHANGELOGNAME, RPM_STRING_ARRAY, None, 0),
    "changelogtext": (RPMTAG_CHANGELOGTEXT, RPM_STRING_ARRAY, None, 0),
    # relocatable rpm packages
    "prefixes": (RPMTAG_PREFIXES, RPM_STRING_ARRAY, None, 4),
    # optimization flags for gcc
    "optflags": (RPMTAG_OPTFLAGS, RPM_STRING, None, 4),
    # %pubkey in .spec files
    "pubkeys": (RPMTAG_PUBKEYS, RPM_STRING_ARRAY, None, 4),
    "sourcepkgid": (RPMTAG_SOURCEPKGID, RPM_BIN, 16, 4),    # XXX
    "immutable": (RPMTAG_HEADERIMMUTABLE, RPM_BIN, 16, 0),  # XXX
    # less important information:
    # time of rpm build
    "buildtime": (RPMTAG_BUILDTIME, RPM_INT32, 1, 0),
    # hostname where rpm was built
    "buildhost": (RPMTAG_BUILDHOST, RPM_STRING, None, 0),
    "cookie": (RPMTAG_COOKIE, RPM_STRING, None, 0), # build host and time
    # ignored now, succ is comps.xml
    # XXX code allows hardcoded exception to also have type RPM_STRING
    #     for RPMTAG_GROUP
    "group": (RPMTAG_GROUP, RPM_I18NSTRING, None, 0),
    "size": (RPMTAG_SIZE, RPM_INT32, 1, 0),         # sum of all file sizes
    "distribution": (RPMTAG_DISTRIBUTION, RPM_STRING, None, 0),
    "vendor": (RPMTAG_VENDOR, RPM_STRING, None, 0),
    "packager": (RPMTAG_PACKAGER, RPM_STRING, None, 0),
    "os": (RPMTAG_OS, RPM_STRING, None, 0),         # always "linux"
    "payloadformat": (RPMTAG_PAYLOADFORMAT, RPM_STRING, None, 0), # "cpio"
    # "gzip" or "bzip2"
    "payloadcompressor": (RPMTAG_PAYLOADCOMPRESSOR, RPM_STRING, None, 0),
    "payloadflags": (RPMTAG_PAYLOADFLAGS, RPM_STRING, None, 0), # "9"
    "rhnplatform": (RPMTAG_RHNPLATFORM, RPM_STRING, None, 4),   # == arch
    "platform": (RPMTAG_PLATFORM, RPM_STRING, None, 0),

    # rpm source packages:
    "source": (RPMTAG_SOURCE, RPM_STRING_ARRAY, None, 2),
    "patch": (RPMTAG_PATCH, RPM_STRING_ARRAY, None, 2),
    "buildarchs": (RPMTAG_BUILDARCHS, RPM_STRING_ARRAY, None, 2),
    "excludearch": (RPMTAG_EXCLUDEARCH, RPM_STRING_ARRAY, None, 2),
    "exclusivearch": (RPMTAG_EXCLUSIVEARCH, RPM_STRING_ARRAY, None, 2),
    # ['Linux'] or ['linux']
    "exclusiveos": (RPMTAG_EXCLUSIVEOS, RPM_STRING_ARRAY, None, 2),

    # information about files
    "filesizes": (RPMTAG_FILESIZES, RPM_INT32, None, 0),
    "filemodes": (RPMTAG_FILEMODES, RPM_INT16, None, 0),
    "filerdevs": (RPMTAG_FILERDEVS, RPM_INT16, None, 0),
    "filemtimes": (RPMTAG_FILEMTIMES, RPM_INT32, None, 0),
    "filemd5s": (RPMTAG_FILEMD5S, RPM_STRING_ARRAY, None, 0),
    "filelinktos": (RPMTAG_FILELINKTOS, RPM_STRING_ARRAY, None, 0),
    "fileflags": (RPMTAG_FILEFLAGS, RPM_INT32, None, 0),
    "fileusername": (RPMTAG_FILEUSERNAME, RPM_STRING_ARRAY, None, 0),
    "filegroupname": (RPMTAG_FILEGROUPNAME, RPM_STRING_ARRAY, None, 0),
    "fileverifyflags": (RPMTAG_FILEVERIFYFLAGS, RPM_INT32, None, 0),
    "filedevices": (RPMTAG_FILEDEVICES, RPM_INT32, None, 0),
    "fileinodes": (RPMTAG_FILEINODES, RPM_INT32, None, 0),
    "filelangs": (RPMTAG_FILELANGS, RPM_STRING_ARRAY, None, 0),
    "dirindexes": (RPMTAG_DIRINDEXES, RPM_INT32, None, 0),
    "basenames": (RPMTAG_BASENAMES, RPM_STRING_ARRAY, None, 0),
    "dirnames": (RPMTAG_DIRNAMES, RPM_STRING_ARRAY, None, 0),
    "filecolors": (RPMTAG_FILECOLORS, RPM_INT32, None, 0),
    "fileclass": (RPMTAG_FILECLASS, RPM_INT32, None, 0),
    "classdict": (RPMTAG_CLASSDICT, RPM_STRING_ARRAY, None, 0),
    "filedependsx": (RPMTAG_FILEDEPENDSX, RPM_INT32, None, 0),
    "filedependsn": (RPMTAG_FILEDEPENDSN, RPM_INT32, None, 0),
    "dependsdict": (RPMTAG_DEPENDSDICT, RPM_INT32, None, 0),

    # legacy additions:
    # selinux filecontexts
    "filecontexts": (RPMTAG_FILECONTEXTS, RPM_STRING_ARRAY, None, 1),
    "archivesize": (RPMTAG_ARCHIVESIZE, RPM_INT32, 1, 1),
    "capability": (RPMTAG_CAPABILITY, RPM_INT32, None, 1),
    "xpm": (RPMTAG_XPM, RPM_BIN, None, 1),
    "gif": (RPMTAG_GIF, RPM_BIN, None, 1),
    "verifyscript2": (RPMTAG_VERIFYSCRIPT2, RPM_STRING, None, 1),
    "nosource": (RPMTAG_NOSOURCE, RPM_INT32, None, 1),
    "nopatch": (RPMTAG_NOPATCH, RPM_INT32, None, 1),
    "disturl": (RPMTAG_DISTURL, RPM_STRING, None, 1),
    "oldfilenames": (RPMTAG_OLDFILENAMES, RPM_STRING_ARRAY, None, 1),
    "triggerin": (RPMTAG_TRIGGERIN, RPM_STRING, None, 5),
    "triggerun": (RPMTAG_TRIGGERUN, RPM_STRING, None, 5),
    "triggerpostun": (RPMTAG_TRIGGERPOSTUN, RPM_STRING, None, 5)
}
rpmtagname = {}
# Add a reverse mapping for all tags and a new tag -> name mapping
for key in rpmtag.keys():
    v = rpmtag[key]
    rpmtag[v[0]] = v
    rpmtagname[v[0]] = key

# Required tags in a header.
rpmtagrequired = []
for key in ["name", "version", "release", "arch"]:
    rpmtagrequired.append(rpmtag[key][0])

# Info within the sig header.
rpmsigtag = {
    # size of gpg/dsaheader sums differ between 64/65
    "dsaheader": (RPMTAG_DSAHEADER, RPM_BIN, None, 0),
    "gpg": (RPMSIGTAG_GPG, RPM_BIN, None, 0),
    "header_signatures": (HEADER_SIGNATURES, RPM_BIN, 16, 0),   # XXX
    "payloadsize": (RPMSIGTAG_PAYLOADSIZE, RPM_INT32, 1, 0),
    "size_in_sig": (RPMSIGTAG_SIZE, RPM_INT32, 1, 0),
    "sha1header": (RPMTAG_SHA1HEADER, RPM_STRING, None, 0),
    "md5": (RPMSIGTAG_MD5, RPM_BIN, 16, 0),
    # legacy entries:
    "pgp": (RPMSIGTAG_PGP, RPM_BIN, None, 1),
    "badsha1_1": (RPMTAG_BADSHA1_1, RPM_STRING, None, 1),
    "badsha1_2": (RPMTAG_BADSHA1_2, RPM_STRING, None, 1)
}
# Add a reverse mapping for all tags and a new tag -> name mapping
rpmsigtagname = {}
for key in rpmsigtag.keys():
    v = rpmsigtag[key]
    rpmsigtag[v[0]] = v
    rpmsigtagname[v[0]] = key

# Required tags in a signature header.
rpmsigtagrequired = []
#for key in ["header_signatures", "payloadsize", "size_in_sig", \
#    "sha1header", "md5"]:
for key in ["md5"]:
    rpmsigtagrequired.append(rpmsigtag[key][0])

# check arch names against this list
possible_archs = ['noarch', 'i386', 'i486', 'i586', 'i686', 'athlon',
    'x86_64', 'ia32e', 'alpha', 'sparc', 'sparc64', 's390', 's390x', 'ia64',
    'ppc', 'ppc64', 'ppc64iseries', 'ppc64pseries', 'ppcpseries', 'ppciseries',
    'ppcmac', 'ppc8260', 'm68k',
    'arm', 'armv4l', 'mips', 'mipseb', 'hppa', 'mipsel', 'sh', 'axp',
    # these are in old rpms:
    'i786', 'i886', 'i986', 's390xc']

arch_compats = {
"alphaev67" : ("alphaev6", "alphapca56", "alphaev56", "alphaev5", "alpha", "axp", "noarch"),
"alphaev6" : ("alphapca56", "alphaev56", "alphaev5", "alpha", "axp", "noarch"),
"alphapca56" : ("alphaev56", "alphaev5", "alpha", "axp", "noarch"),
"alphaev56" : ("alphaev5", "alpha", "axp", "noarch"),
"alphaev5" : ("alpha", "axp", "noarch"),
"alpha" : ("axp", "noarch"),

"athlon" : ("i686", "i586", "i486", "i386", "noarch"),
"i686" : ("i586", "i486", "i386", "noarch"),
"i586" : ("i486", "i386", "noarch"),
"i486" : ("i386", "noarch"),
"i386" : ("noarch"),

"osfmach3_i686": ("i686", "osfmach3_i586", "i586", "osfmach3_i486", "i486", "osfmach3_i386", "i486", "i386", "noarch"),
"osfmach3_i586": ("i586", "osfmach3_i486", "i486", "osfmach3_i386", "i486", "i386", "noarch"),
"osfmach3_i486": ("i486", "osfmach3_i386", "i486", "i386", "noarch"),
"osfmach3_i386": ("i486", "i386", "noarch"),

"osfmach3_ppc" : ("ppc", "rs6000", "noarch"),
"powerpc" : ("ppc", "rs6000", "noarch"),
"powerppc" : ("ppc", "rs6000", "noarch"),
"ppc8260" : ("ppc", "rs6000", "noarch"),
"ppc8560" : ("ppc", "rs6000", "noarch"),
"ppc32dy4" : ("ppc", "rs6000", "noarch"),
"ppciseries" : ("ppc", "rs6000", "noarch"),
"ppcpseries" : ("ppc", "rs6000", "noarch"),
"ppc64" : ("ppc", "rs6000", "noarch"),
"ppc" : ("rs6000", "noarch"),
"rs6000" : ("noarch"),
"ppc64pseries" : ("ppc64", "ppc", "rs6000", "noarch"),
"ppc64iseries" : ("ppc64", "ppc", "rs6000", "noarch"),

"sun4c" : ("sparc", "noarch"),
"sun4d" : ("sparc", "noarch"),
"sun4m" : ("sparc", "noarch"),
"sun4u" : ("sparc64", "sparcv9", "sparc", "noarch"),
"sparc64" : ("sparcv9", "sparc", "noarch"),
"sparcv9" : ("sparc", "noarch"),
"sparcv8" : ("sparc", "noarch"),
"sparc" : ("noarch"),

"mips" : ("noarch"),
"mipsel" : ("noarch"),

"hppa2.0" : ("hppa1.2", "hppa1.1", "hppa1.0", "parisc", "noarch"),
"hppa1.2" : ("hppa1.1", "hppa1.0", "parisc", "noarch"),
"hppa1.1" : ("hppa1.0", "parisc", "noarch"),
"hppa1.0" : ("parisc", "noarch"),
"parisc" : ("noarch"),

"armv4b" : ("noarch"),
"armv4l" : ("armv3l", "noarch"),
"armv3l" : ("noarch"),

"atarist" : ("m68kmint", "noarch"),
"atariste" : ("m68kmint", "noarch"),
"ataritt" : ("m68kmint", "noarch"),
"falcon" : ("m68kmint", "noarch"),
"atariclone" : ("m68kmint", "noarch"),
"milan" : ("m68kmint", "noarch"),
"hades" : ("m68kmint", "noarch"),

"i370" : ("noarch"),
"s390" : ("noarch"),
"s390x" : ("s390", "noarch"),

"ia64" : ("noarch"),

"x86_64" : ("amd64", "athlon", "i686", "i586", "i486", "i386", "noarch"),
"amd64" : ("x86_64", "athlon", "i686", "i586", "i486", "i386", "noarch"),
"ia32e" : ("x86_64", "athlon", "i686", "i586", "i486", "i386", "noarch")
}

# Some special magics for binary rpms
RPM_HEADER_LEAD_MAGIC = '\xed\xab\xee\xdb'
RPM_HEADER_INDEX_MAGIC = "\x8e\xad\xe8\x01\x00\x00\x00\x00"

# rpm binary lead arch values
rpm_lead_arch = {
"alphaev67" : 2,
"alphaev6" : 2,
"alphapca56" : 2,
"alphaev56" : 2,
"alphaev5" : 2,
"alpha" : 2,
"athlon" : 1,
"i686" : 1,
"i586" : 1,
"i486" : 1,
"i386" : 1,
"osfmach3_i686": 1,
"osfmach3_i586": 1,
"osfmach3_i486": 1,
"osfmach3_i386": 1,
"osfmach3_ppc" : 5,
"powerpc" : 5,
"powerppc" : 5,
"ppc8260" : 5,
"ppc8560" : 5,
"ppc32dy4" : 5,
"ppciseries" : 5,
"ppcpseries" : 5,
"ppc64" : 5,
"ppc" : 5,
"rs6000" : 5,
"ppc64pseries" : 5,
"ppc64iseries" : 5,
"sun4c" : 3,
"sun4d" : 3,
"sun4m" : 3,
"sun4u" : 3,
"sparc64" : 3,
"sparcv9" : 3,
"sparcv8" : 3,
"sparc" : 3,
"mips" : 4,
"mipsel" : 4,
"hppa2.0" : 0,
"hppa1.2" : 0,
"hppa1.1" : 0,
"hppa1.0" : 0,
"parisc" : 0,
"armv4b" : 0,
"armv4l" : 0,
"armv3l" : 0,
"atarist" : 6,
"atariste" : 6,
"ataritt" : 6,
"falcon" : 6,
"atariclone" : 6,
"milan" : 6,
"hades" : 6,
"i370" : 0,
"s390" : 0,
"s390x" : 0,
"ia64" : 1,
"x86_64" : 1,
"amd64" : 1,
"ia32e" : 1,
"noarch" : 0
}

# vim:ts=4:sw=4:showmatch:expandtab
