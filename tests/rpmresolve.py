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

import sys, os, time

PYRPMDIR = ".."
if not PYRPMDIR in sys.path:
    sys.path.append(PYRPMDIR)
import pyrpm

def usage():
    print """Usage: %s [-v[v]] {-i|-U|-r} [--installed <dir>]
                       [<rpm name/package>...]

  -h  | --help                print help
  -v  | --verbose             be verbose, and more, ..
  -E  | --ignore-epoch        ignore epoch in provides and requires
  -i                          install packages
  -e                          erase packages
  -R                          no resolve call
  -O                          no operation list output
  -d <dir>                    load files from dir
  --installed <dir>           directory with installed rpms

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
dir = None
resolve = 1
output_op = 1

tags = pyrpm.rpmconfig.resolvertags

def main():
    global ignore_epoch, tags
    global verbose, installed_dir, installed
    global rpms
    global dir
    global output_op
    
#    if len(sys.argv) == 1:
#        usage()
#        sys.exit(0)

    ops = [ ]
    i = 1
    op = pyrpm.OP_UPDATE
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
        elif sys.argv[i] == "-F":
            op = pyrpm.OP_FRESHEN
        elif sys.argv[i] == "-e":
            op = pyrpm.OP_ERASE
        elif sys.argv[i] == "-R":
            resolve = 0
        elif sys.argv[i] == "-O":
            output_op = 0
        elif sys.argv[i] == "-E"or sys.argv[i] == "--ignore-epoch":
            ignore_epoch = 1
        elif sys.argv[i] == "--installed":
            i += 1
            installed_dir = sys.argv[i]+"/"
        elif sys.argv[i] == "-d":
            i += 1
            dir = sys.argv[i]
        else:
            ops.append((op, sys.argv[i]))
        i += 1

    if dir:
        if not os.path.exists(dir) or not os.path.isdir(dir):
            print "%s does not exists or is not a directory." % dir
            sys.exit(1)
        print "Loading rpm packages from %s" % dir
        list = os.listdir(dir)
        list.sort
        for entry in list:
            if not entry or not entry[-4:] == ".rpm":
                continue
            n = dir+"/"+entry
            if not os.path.isfile(n):
                continue
            ops.append((op, n))

    pyrpm.rpmconfig.debug = verbose
    pyrpm.rpmconfig.warning = verbose
    pyrpm.rpmconfig.verbose = verbose

    pyrpm.rpmconfig.checkinstalled = 0

#    if len(ops) == 0:
#        usage()
#        sys.exit(0)        

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

    pyrpm.rpmconfig.checkinstalled = 0
    pyrpm.rpmconfig.nofileconflicts = 1
    
    print "==============================================================="
    print "Loading Packages"
    # -- load install/update/erase

    i = 1
    _ops = [ ]
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
        _ops.append((op, r))
        i += 1
    if verbose > 0 and len(ops) > 0:
        print
    ops = _ops

    print "==============================================================="
    print "Feeding resolver"

    db = pyrpm.database.memorydb.RpmMemoryDB(pyrpm.rpmconfig, None)
    db.addPkgs(installed)
    resolver = pyrpm.RpmResolver(pyrpm.rpmconfig, db)
    del db

    i = 1
    l = len(ops)
    for op, r in ops:
        if verbose > 0:
            progress_write("Feeding %d/%d " % (i, len(ops)))
        if op == pyrpm.OP_INSTALL:
            ret = resolver.install(r)
        elif op == pyrpm.OP_UPDATE:
            ret = resolver.update(r)
        elif op == pyrpm.OP_FRESHEN:
            ret = resolver.freshen(r)
        else: # op == pyrpm.OP_ERASE
            ret = resolver.erase(r)
        if ret != pyrpm.RpmResolver.OK and \
               ret != pyrpm.RpmResolver.ALREADY_ADDED and \
               ret != pyrpm.RpmResolver.ALREADY_INSTALLED:
            if ret == pyrpm.RpmResolver.OLD_PACKAGE:
                print "old package: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.NOT_INSTALLED:
                print "not installed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.UPDATE_FAILED:
                print "update failed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.ARCH_INCOMPAT:
                print "arch incompat: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.OBSOLETE_FAILED:
                print "obsolete failed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.CONFLICT:
                print "conflict: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.FILE_CONFLICT:
                print "file conflicts: %s" % r.getNEVRA()
            else:
                print ret
        i += 1
    if verbose > 0 and len(ops) > 0:
        print
    del ops

    print "==============================================================="

    print "- Installed unresolved ----------------------------------------"
    for pkg in resolver.installed_unresolved:
        print pkg.getNEVRA()
        for c in resolver.installed_unresolved[pkg]:
            print "\t%s" % pyrpm.depString(c)
    print "- Installed conflicts -----------------------------------------"
    for pkg in resolver.installed_conflicts:
        print pkg.getNEVRA()
        for (c,rpm) in resolver.installed_conflicts[pkg]:
            print "\t%s: %s" % (pyrpm.depString(c), rpm.getNEVRA())
    print "- Installed file conflicts ------------------------------------"
    for pkg in resolver.installed_file_conflicts:
        print pkg.getNEVRA()
        for (f,rpm) in resolver.installed_file_conflicts[pkg]:
            print "\t%s: %s" % (f, rpm.getNEVRA())

    if len(resolver.installs) == 0 and len(resolver.erases) == 0:
        print "Nothing to do."
        sys.exit(0)

    print "- Conflicts ---------------------------------------------------"
    conflicts = resolver.getConflicts()
    for pkg in conflicts:
        for d,rpm in conflicts[pkg]:
            print "%s, %s:\n\t%s" % (pkg.getNEVRA(), rpm.getNEVRA(),
                                    pyrpm.depString(d))

#    print "- File Conflicts ----------------------------------------------"
#    pyrpm.rpmconfig.nofileconflicts = 0
#    fconflicts = resolver.getFileConflicts()
#    for pkg in fconflicts:
#        print pkg.getNEVRA()
#        for (f,p) in fconflicts[pkg]:
#            print "\t%s: %s" % (f, p.getNEVRA())
#    pyrpm.rpmconfig.nofileconflicts = 1

    print "---------------------------------------------------------------"

    if resolve == 1 and resolver.resolve() != 1:
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

#    print "- Installs ----------------------------------------------------"
#    for pkg in resolver.installs:
#        print "\t%s" % pkg.getNEVRA()
#    print "- Updates -----------------------------------------------------"
#    for pkg in resolver.updates:
#        print "\t%s" % pkg.getNEVRA()
#        for p in resolver.updates[pkg]:
#            print "\t\t%s" % p.getNEVRA()
#    print "- Obsoletes ---------------------------------------------------"
#    for pkg in resolver.obsoletes:
#        print "\t%s" % pkg.getNEVRA()
#        for p in resolver.obsoletes[pkg]:
#            print "\t\t%s" % p.getNEVRA()
#    print "- Erases ------------------------------------------------------"
#    for pkg in resolver.erases:
#        print "\t%s" % pkg.getNEVRA()
#    print "---------------------------------------------------------------"

    installs = resolver.installs
    updates = resolver.updates
    obsoletes = resolver.obsoletes
    erases = resolver.erases
    del resolver

    orderer = pyrpm.RpmOrderer(pyrpm.rpmconfig, installs, updates, obsoletes,
                               erases)

    cl = time.time()
    operations = orderer.order()
    print "orderer.order(): time=%f" % (time.time() - cl)
    
    del orderer

    if operations == None:
        sys.exit(-1)

    if output_op:
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
