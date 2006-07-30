scripts = oldpyrpm.py pyrpmcheck pyrpmcheckinstall pyrpmcheckrepo \
	pyrpmcreatefilereq pyrpmcreaterepo pyrpmdbverify pyrpminstall \
	pyrpmkickstart pyrpmrandomizer pyrpmrebuilddb pyrpmspecinfo pyrpmyum
EXTRA_DIST = $(scripts) pyrexoldpyrpm.py

bin_SCRIPTS = $(scripts)

pyrex: oldpyrpm2.so

oldpyrpm2.pyx: oldpyrpm.py
	./oldpyrpm.py --pyrex < oldpyrpm.py > oldpyrpm2.pyx

oldpyrpm2.c: oldpyrpm2.pyx
	pyrexc oldpyrpm2.pyx

oldpyrpm2.o: oldpyrpm2.c
	gcc -c -fPIC -O2 -I /usr/include/python2.4 oldpyrpm2.c

oldpyrpm2.so: oldpyrpm2.o
	gcc -shared -O2 oldpyrpm2.o -o oldpyrpm2.so

install-exec-local:
	@for i in $(scripts); do \
	    sed -i -e 's#^PYRPMDIR\s*=\s*".*".*#PYRPMDIR = "$(pkgdatadir)"#g' \
		$(DESTDIR)$(bindir)/$$i;\
	done

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) \
	$(notdir $(wildcard \.\#*)) $(wildcard *\.pyc) \
	oldpyrpm2.so oldpyrpm2.c oldpyrpm2.o oldpyrpm2.pyx

