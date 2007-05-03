#
# Copyright (C) 2007 Red Hat, Inc.
# Authors: Thomas Woerner
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

__enabled = -2 # not available
try:
    import selinux
except ImportError:
    selinux = None
else:
    __enabled = -1 # not usable
    # new selinux bindings have matchpathcon_fini defined
    try:
        __a = selinux.is_selinux_enabled
        __a = selinux.matchpathcon_init
        __a = selinux.matchpathcon_fini
        __a = selinux.matchpathcon
        __a = selinux.selinux_file_context_path
        __a = selinux.rpm_execcon
        __a = selinux.lsetfilecon
        __a = selinux.lgetfilecon
    except:
        selinux = None
    else:
        del __a
        __enabled = selinux.is_selinux_enabled()
        # enforcing: 1, permissive: 0

def is_selinux_enabled():
    return __enabled

def _gen_file_context_path(dir=""):
    policytree = None
    context_path = dir+"/etc/selinux/%s/contexts/files/file_contexts"
    try:
        fd = open(dir+"/etc/selinux/config")
    except:
        pass
    else:
        lines = fd.readlines()
        fd.close()
        for line in lines:
            if line[0:12] == "SELINUXTYPE=":
                policytree = line[12:].strip()
    if not policytree:
        raise ValueError, "Could not detect policy type."
    return context_path % policytree

def matchpathcon_init(filename=None):
    return selinux.matchpathcon_init(filename)

def matchpathcon_init_from_chroot(chroot):
    if __enabled < 0:
        return
    filename = _gen_file_context_path(chroot)
    return selinux.matchpathcon_init(filename)

def matchpathcon_fini():
    if __enabled < 0:
        return
    return selinux.matchpathcon_fini()

def matchpathcon(filename, mode):
    if __enabled < 0:
        return [None, None]
    return selinux.matchpathcon(filename, mode)

def file_context_path():
    if __enabled < 0:
        return None
    return selinux.selinux_file_context_path()

def rpm_execcon(verified, filename, argv, envp):
    if __enabled < 0:
        return
    return selinux.rpm_execcon(verified, filename, argv, envp)

def lsetfilecon(filename, context):
    if __enabled < 0:
        return
    return selinux.lsetfilecon(filename, context)
    
def lgetfilecon(filename):
    if __enabled < 0:
        return
    return selinux.lgetfilecon(filename)
