#!/usr/bin/python
#
# rpmtree.py
#
# list dependency tree
#
# (c) 2004 Thomas Woerner <twoerner@redhat.com>
#
# version 2005-01-13-01

import sys, os

import pyrpm

def usage():
    print """Usage: %s [-v[v]] {-i|-U|-r} [--installed <dir>]
                       [<rpm name/package>...]

  -h  | --help                print help
  -v  | --verbose             be verbose, and more, ..
  -E  | --ignore-epoch        ignore epoch in provides and requires
  -i                          install packages
  -U                          update packages
  -e                          erase packages
  --installed <dir>           directory with installed rpms

This program prints a treee for package dependencies.
The asterisc in the listing is shown after dependencies, which are resolved in
a tree before. 

""" % sys.argv[0]

# ----------------------------------------------------------------------------

sout =  os.readlink("/proc/self/fd/1")
devpts = 0
if sout[0:9] == "/dev/pts/":
    devpts = 1

def progress_write(msg):
    if devpts == 1:
        sys.stdout.write("\r")
    sys.stdout.write(msg)
    if devpts == 0:
        sys.stdout.write("\n")
    sys.stdout.flush()

# ----------------------------------------------------------------------------

install = [ ]
update = [ ]
erase = [ ]

ignore_epoch = 0
verbose = 0
installed_dir = None
installed = [ ]
install_flag = 0
update_flag = 0
erase_flag = 0

tags = [ "name", "epoch", "version", "release", "arch", \
         "providename", "provideflags", "provideversion", \
         "requirename", "requireflags", "requireversion", \
         "obsoletename", "obsoleteflags", "obsoleteversion", \
         "conflictname", "conflictflags", "conflictversion", \
         "filesizes", "filemodes", "filerdevs", "filemtimes", \
         "filemd5s", "filelinktos", "fileflags", "fileusername", \
         "filegroupname", "fileverifyflags", "filedevices", "fileinodes", \
         "filelangs", "dirindexes", "basenames", "dirnames", "filecolors", \
         "fileclass", "classdict", "filedependsx", "filedependsn", \
         "dependsdict" ]

if __name__ == '__main__':
    if len(sys.argv) == 1:
        usage()
        sys.exit(0)

    pargs = [ ]
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "-h" or sys.argv[i] == "--help":
            usage()
            sys.exit(0)
        elif sys.argv[i][:2] == "-v":
            j = 1
            while j < len(sys.argv[i]) and sys.argv[i][j] == "v":
                verbose += 1
                j += 1
        elif sys.argv[i] == "--verbose":
            verbose += 1
        elif sys.argv[i] == "-i":
            install_flag = 1
        elif sys.argv[i] == "-U":
            update_flag = 1
        elif sys.argv[i] == "-e":
            erase_flag = 1
        elif sys.argv[i] == "-E"or sys.argv[i] == "--ignore-epoch":
            ignore_epoch = 1
        elif sys.argv[i] == "--installed":
            i += 1
            installed_dir = sys.argv[i]+"/"
        else:
            pargs.append(sys.argv[i])
        i += 1

    if install_flag + update_flag + erase_flag != 1:
        usage()
        sys.exit(0)

    pyrpm.rpmconfig.debug = verbose

    if len(pargs) == 0:
        usage()
        sys.exit(0)        

    for f in pargs:
        if verbose > 0:
            progress_write("Reading %d " % len(pargs))
        r = pyrpm.RpmPackage("file:/"+f)
        try:
            r.read(tags=tags)
        except:
            print "Loading of %s failed, exiting." % f
            sys.exit(-1)
        if install_flag == 1:
            install.append(r)
        elif update_flag == 1:
            update.append(r)
        else: # erase_flag
            erase.append(r)
    if verbose > 0 and len(pargs) > 0:
        print

    del pargs
    
    # -- load installed

    if installed_dir != None:
        list = os.listdir(installed_dir)
        for i in xrange(len(list)):
            f = list[i]
            if verbose > 0:
                progress_write("Loading installed [%d/%d] " % (i+1, len(list)))

            r = pyrpm.RpmPackage("file:/%s%s" % (installed_dir, f))
            try:
                r.read(tags=tags)
            except:
                print "Loading of %s%s failed, ignoring." % (installed_dir, f)
                continue
            installed.append(r)
        if verbose > 0 and len(list) > 0:
            print
            del list    

    # -----------------------------------------------------------------------

    if install_flag == 1:
        rpms = install
        operation = "install"
    elif update_flag == 1:
        rpms = update
        operation = "update"
    else: # erase_flag
        rpms = erase
        operation = "erase"

    resolver = pyrpm.RpmResolver(rpms, installed, operation)
    operations = resolver.resolve()

    for op,pkg in operations:
        print op, pkg.source

    sys.exit(0)
