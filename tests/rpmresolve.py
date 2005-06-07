#!/usr/bin/python
#
# rpmresolve
#
# list dependency tree
#
# (c) 2004 Thomas Woerner <twoerner@redhat.com>
#
# version 2005-03-09-01
#

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

rpms = [ ]

ignore_epoch = 0
verbose = 0
installed_dir = None
installed = [ ]

tags = [ "name", "epoch", "version", "release", "arch",
         "providename", "provideflags", "provideversion", "requirename",
         "requireflags", "requireversion", "obsoletename", "obsoleteflags",
         "obsoleteversion", "conflictname", "conflictflags",
         "conflictversion", "filesizes", "filemodes", "filemd5s",
         "dirindexes", "basenames", "dirnames" ]


def main():
    global ignore_epoch, tags
    global verbose, installed_dir, installed
    global rpms
    
    if len(sys.argv) == 1:
        usage()
        sys.exit(0)

    ops = [ ]
    i = 1
    op = pyrpm.OP_INSTALL
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
            op = pyrpm.OP_INSTALL
        elif sys.argv[i] == "-U":
            op = pyrpm.OP_UPDATE
        elif sys.argv[i] == "-F":
            op = pyrpm.OP_FRESHEN
        elif sys.argv[i] == "-e":
            op = pyrpm.OP_ERASE
        elif sys.argv[i] == "-E"or sys.argv[i] == "--ignore-epoch":
            ignore_epoch = 1
        elif sys.argv[i] == "--installed":
            i += 1
            installed_dir = sys.argv[i]+"/"
        else:
            ops.append((op, sys.argv[i]))
        i += 1

    pyrpm.rpmconfig.debug = verbose
    pyrpm.rpmconfig.warning = verbose
    pyrpm.rpmconfig.verbose = verbose

    pyrpm.rpmconfig.checkinstalled = 0

    if len(ops) == 0:
        usage()
        sys.exit(0)        

    # -- load installed

    if installed_dir != None:
        list = os.listdir(installed_dir)
        for i in xrange(len(list)):
            f = list[i]
            if verbose > 0:
                progress_write("Loading installed [%d/%d] " % (i+1, len(list)))

            r = pyrpm.RpmPackage(pyrpm.rpmconfig, "%s%s" % (installed_dir, f))
            try:
                r.read(tags=tags)
                r.close()
            except Exception, msg:
                print msg
                print "Loading of %s%s failed, ignoring." % (installed_dir, f)
                continue
            installed.append(r)

        if verbose > 0 and len(list) > 0:
            print
            del list    

    resolver = pyrpm.RpmResolver(pyrpm.rpmconfig, installed)

    print "==============================================================="

    # -- load install/update/erase

    i = 1
    for op, f in ops:
        if verbose > 0:
            progress_write("Reading %d/%d " % (i, len(ops)))
        r = pyrpm.RpmPackage(pyrpm.rpmconfig, f)
        try:
            r.read(tags=tags)
            r.close()
        except Exception, msg:
            print msg
            print "Loading of %s failed, exiting." % f
            sys.exit(-1)
        r.close()
        if op == pyrpm.OP_INSTALL:
            ret = resolver.install(r)
        elif op == pyrpm.OP_UPDATE:
            ret = resolver.update(r)
        elif op == pyrpm.OP_FRESHEN:
            ret = resolver.freshen(r)
        else: # op == pyrpm.OP_ERASE
            ret = resolver.erase(r)
        if ret != pyrpm.RpmResolver.OK:
            print ret
            sys.exit(0)
        i += 1
    if verbose > 0 and len(ops) > 0:
        print
    del ops

    if len(resolver.installs) == 0 and len(resolver.erases) == 0:
        print "Nothing to do."
        sys.exit(0)

    # -----------------------------------------------------------------------
        
    print "- Installed unresolved -----------------------------------------"
    for pkg in resolver.installed_unresolved:
        print pkg.getNEVRA()
        for c in resolver.installed_unresolved[pkg]:
            print "\t%s" % pyrpm.depString(c)
    print "- Installed conflicts ------------------------------------------"
    for pkg in resolver.installed_conflicts:
        print pkg.getNEVRA()
        for (c,rpm) in resolver.installed_conflicts[pkg]:
            print "\t%s: %s" % (pyrpm.depString(c), rpm.getNEVRA())
    print "- Installed file conflicts -------------------------------------"
    for pkg in resolver.installed_file_conflicts:
        print pkg.getNEVRA()
        for (c,rpm) in resolver.installed_file_conflicts[pkg]:
            print "\t%s: %s" % (pyrpm.depString(c), rpm.getNEVRA())
#    print "- Conflicts ----------------------------------------------------"
#    for name in resolver.conflicts.provide:
#        for (flag,ver,rpm) in resolver.conflicts.provide[name]:
#            print "%s\n\t%s" % (rpm.getNEVRA(), pyrpm.depString((name, flag, ver)))
#    print "- File Conflicts -----------------------------------------------"
#    fconflicts = resolver.getFileConflicts()
#    for pkg in fconflicts:
#        print pkg.getNEVRA()
#        for (f,p) in fconflicts[pkg]:
#            print "\t%s: %s" % (f, p.getNEVRA())

    print "----------------------------------------------------------------"

    if resolver.resolve() != 1:
        sys.exit(-1)

#    for pkg in resolver.installs:
#        if resolver.updates.has_key(pkg):
#            print "update: %s" % pkg.getNEVRA()
#        else:
#            print "install: %s" % pkg.getNEVRA()
#    for pkg in resolver.erases:
#        print "erase: %s" % pkg.getNEVRA()

#    for pkg in resolver.installs:
#        for dep in pkg["requires"]:
#            reqs = ""
#            if pyrpm.isLegacyPreReq(dep[1]):
#                reqs += "legacy "
#            if pyrpm.isInstallPreReq(dep[1]):
#                reqs += "install "
#            if pyrpm.isErasePreReq(dep[1]):
#                reqs += "erase "
#            print "%s: (%s): %s" % (pkg.getNEVRA(), dep[0], reqs)
#    sys.exit(0)

#    print "installs:"
#    for pkg in resolver.installs:
#        print "\t%s" % pkg.getNEVRA()
#    print "updates:"
#    for pkg in resolver.updates:
#        print "\t%s" % pkg.getNEVRA()
#        for p in resolver.updates[pkg]:
#            print "\t\t%s" % p.getNEVRA()
#    print "obsoletes:"
#    for pkg in resolver.obsoletes:
#        print "\t%s" % pkg.getNEVRA()
#        for p in resolver.obsoletes[pkg]:
#            print "\t\t%s" % p.getNEVRA()
#    print "erases:"
#    for pkg in resolver.erases:
#        print "\t%s" % pkg.getNEVRA()


    orderer = pyrpm.RpmOrderer(pyrpm.rpmconfig,
                               resolver.installs, resolver.updates,
                               resolver.obsoletes, resolver.erases)
    del resolver
    operations = orderer.order()
    del orderer

    if operations == None:
        sys.exit(-1)

    for op,pkg in operations:
        print op, pkg.source

    sys.exit(0)

if __name__ == '__main__':
    hotshot = 0
    if hotshot:
        import tempfile
        from hotshot import Profile
        import hotshot.stats
        filename = tempfile.mktemp()
        prof = Profile(filename)
        try:
            prof = prof.runcall(main)
        except SystemExit:
            pass
        prof.close()
        del prof
        s = hotshot.stats.load(filename)
        s.strip_dirs().sort_stats('time').print_stats(20)
        s.strip_dirs().sort_stats('cumulative').print_stats(20)
        os.unlink(filename)
    else:
        main()
