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


import os.path, tempfile, sys
from config import *
from cpio import *
from base import *


# Collection of class indepedant helper functions
def runScript(prog=None, script=None, arg1=None, arg2=None):
    if prog == None:
        prog = "/bin/sh"
    if not os.path.exists("/var/tmp"):
        os.makedirs("/var/tmp")
    (fd, tmpfilename) = tempfile.mkstemp(dir="/var/tmp/", prefix="rpm-tmp.")
    if fd == None:
        return 0
    if script != None:
        os.write(fd, script)
    os.close(fd)
    fd = None
    args = [prog]
    if prog != "/sbin/ldconfig":
        args.append(tmpfilename)
        if arg1 != None:
            args.append(arg1)
        if arg2 != None:
            args.append(arg2)
    pid = os.fork()
    if pid != 0:
        (cpid, status) = os.waitpid(pid, 0)
    else:
        os.close(0)
        os.execv(prog, args)
        sys.exit()
    os.unlink(tmpfilename)
    if status != 0:
        print "Error in running script:"
        print prog
        print args
        return 0
    return 1

def installFile(rfi, data):
    filetype = rfi.mode & CP_IFMT
    if  filetype == CP_IFREG:
        makeDirs(rfi.filename)
        (fd, tmpfilename) = tempfile.mkstemp(dir=os.path.dirname(rfi.filename), prefix=rfi.filename+".")
        if not fd:
            return 0
        if os.write(fd, data) < 0:
            os.close(fd)
            os.unlink(tmpfilename)
            return 0
        os.close(fd)
        if not setFileMods(tmpfilename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            os.unlink(tmpfilename)
            return 0
        if os.rename(tmpfilename, rfi.filename) != None:
            return 0
    elif filetype == CP_IFDIR:
        if os.path.isdir(rfi.filename):
            return 1
        os.makedirs(rfi.filename)
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            return 0
    elif filetype == CP_IFLNK:
        symlinkfile = data.rstrip("\x00")
        if os.path.islink(rfi.filename) and os.readlink(rfi.filename) == symlinkfile:
            return 1
        makeDirs(rfi.filename)
        try:
            os.unlink(rfi.filename)
        except:
            pass
        os.symlink(symlinkfile, rfi.filename)
    elif filetype == CP_IFIFO:
        makeDirs(rfi.filename)
        if not os.path.exists(rfi.filename) and os.mkfifo(rfi.filename) != None:
            return 0
        if not setFileMods(rfi.filename, rfi.uid, rfi.gid, rfi.mode, rfi.mtime):
            os.unlink(rfi.filename)
            return 0
    elif filetype == CP_IFCHR or \
         filetype == CP_IFBLK:
        makeDirs(rfi.filename)
        try:
            os.mknod(rfi.filename, rfi.mode, rfi.rdev)
        except:
            pass
    else:
        raise ValueError, "%s: not a valid filetype" % (oct(rfi.filetype))
    return 1

def setFileMods(filename, uid, gid, mode, mtime):
    if os.chown(filename, uid, gid) != None:
        return 0
    if os.chmod(filename, (~CP_IFMT) & mode) != None:
        return 0
    if os.utime(filename, (mtime, mtime)) != None:
        return 0
    return 1

def makeDirs(fullname):
    idx = fullname.rfind("/")
    if idx > 0:
        dirname = fullname[:idx]
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

def createLink(src, dst):
    try:
        # First try to unlink the defered file
        os.unlink(dst)
    except:
        pass
    # Behave exactly like cpio: If the hardlink fails (because of different
    # partitions), then it has to fail
    if os.link(src, dst) != None:
        return 0
    return 1

# Error handling functions
def printDebug(level, msg):
    if level <= rpmconfig.debug_level:
        sys.stdout.write("Debug: "+msg+"\n")
        sys.stdout.flush()
    return 0

def printInfo(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()
    return 0

def printWarning(msg):
    sys.stdout.write("Warning: "+msg+"\n")
    sys.stdout.flush()
    return 0

def printError(msg):
    sys.stderr.write("Error: "+msg+"\n")
    sys.stderr.flush()
    return 0

def raiseFatal(msg):
    raise ValueError, "Fatal: "+msg+"\n"

# ----------------------------------------------------------------------------

# split EVR in epoch, version and release
def evrSplit(evr):
    i = 0
    p = evr.find(":") # epoch
    if p != -1:
        epoch = evr[:p]
        i = p+1
    else:
        epoch = "0"
    p = evr.find("-", i) # version
    if p != -1:
        version = evr[i:p]
        release = evr[p+1:]
    else:
        version = evr[i:]
        release = ""
    return (epoch, version, release)

# locale independend string methods
def _xislower(chr): return (chr >= 'a' and chr <= 'z')
def _xisupper(chr): return (chr >= 'A' and chr <= 'Z')
def _xisalpha(chr): return (_xislower(chr) or _xisupper(chr))
def _xisdigit(chr): return (chr >= '0' and chr <= '9')
def _xisalnum(chr): return (_xisalpha(chr) or _xisdigit(chr))

# compare two strings
def stringCompare(str1, str2):
    if str1 == "" and str2 == "": return 0;
    elif str1 == "" and str2 != "": return -1;
    elif str1 != "" and str2 == "": return 1;
    elif str1 == str2: return 0;

    i1 = i2 = 0
    while i1 < len(str1) and i2 < len(str2):
        # remove leading separators
        while i1 < len(str1) and not _xisalnum(str1[i1]): i1 += 1
        while i2 < len(str2) and not _xisalnum(str2[i2]): i2 += 1
        j1 = i1
        j2 = i2

        # search for numbers and comprare them
        while j1 < len(str1) and _xisdigit(str1[j1]): j1 += 1
        while j2 < len(str2) and _xisdigit(str2[j2]): j2 += 1
        if j1 > i1 or j2 > i1:
            if j1 == i1: return -1
            if j2 == i2: return 1
            if j1-i1 < j2-i2: return -1
            if j1-i1 > j2-i2: return 1
            while i1 < j1 and i2 < j2:
                if int(str1[i1]) < int(str2[i2]): return -1
                if int(str1[i1]) > int(str2[i2]): return 1
                i1 += 1
                i2 += 1
            # found right side 
            if i1 == len(str1): return -1
            if i2 == len(str2): return 1
        if i2 == len(str2): return -1

        # search for alphas and compare them
        while j1 < len(str1) and _xisalpha(str1[j1]): j1 += 1
        while j2 < len(str2) and _xisalpha(str2[j2]): j2 += 1
        if j1 > i1 or j2 > i1:
            if j1 == i1: return -1
            if j2 == i2: return 1
            if str1[i1:j1] < str2[i2:j2]: return -1
            if str1[i1:j1] > str2[i2:j2]: return 1
            # found right side 
            i1 = j1
            i2 = j2

    # still no difference
    if i2 == len(str2):
        return 0
    else:
        if i1 == len(str1):
            return -1
        else:
            return 1

# internal EVR compare, uses stringCompare to compare epochs, versions and
# release versions
def _evrCompare(e1, e2):
    if e2[2] == "": # no release
        e1 = (e1[0], e1[1], "")

    r = stringCompare(e1[0], e2[0])
    if r == 0: r = stringCompare(e1[1], e2[1])
    if r == 0: r = stringCompare(e1[2], e2[2])
# TODO: where is ignore_epoch from?
#    elif ignore_epoch == 1:
#        if stringCompare(e1[1], e2[1]) == 0:
#            if stringCompare(e1[2], e2[2]) == 0:
#                r = 0
    return r

# compares two EVR's with comparator
def evrCompare(evr1, comp, evr2):
    res = -1
    e1 = evrSplit(evr1)
    e2 = evrSplit(evr2)
    r = _evrCompare(e1, e2)
    if r == -1:
        if comp & RPMSENSE_LESS:
            res = 1
    elif r == 0:
        if comp & RPMSENSE_EQUAL:
            res = 1
    else: # res == 1
        if comp & RPMSENSE_GREATER:
            res = 1
    return res

def evrString(epoch, version, release):
    if epoch == None or epoch == "":
        return "%s-%s" % (version, release)
    else:
        return "%s:%s-%s" % (epoch, version, release)


# vim:ts=4:sw=4:showmatch:expandtab
