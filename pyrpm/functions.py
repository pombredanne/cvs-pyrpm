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
from cpio import *


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
    dirname = fullname[:fullname.rfind("/")]
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
def printDebug(msg):
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

# vim:ts=4:sw=4:showmatch:expandtab
