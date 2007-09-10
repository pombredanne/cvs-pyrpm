scripts = oldpyrpm.py pyrpmcheck pyrpmcheckinstall pyrpmcheckrepo \
	pyrpmcreaterepo pyrpmdbverify pyrpminstall \
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
	    sed -i -e 's#^PYRPMDIR\s*=.*#PYRPMDIR = "$(pkgdatadir)"#g' \
		$(DESTDIR)$(bindir)/$$i;\
	done

# Unsupported start to check about python3.0:
oldpyrpm3.py: oldpyrpm.py
	sed -e '/#PY3: /{s/#PY3: //g;n;d;}' < oldpyrpm.py > oldpyrpm3.py
	python ~/rpm/source/python/2to3/refactor.py -w oldpyrpm3.py

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) \
	$(notdir $(wildcard \.\#*)) $(wildcard *\.pyc) \
	oldpyrpm2.so oldpyrpm2.c oldpyrpm2.o oldpyrpm2.pyx

