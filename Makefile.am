SUBDIRS = doc pyrpm scripts tests
EXTRA_DIST = AUTHORS ChangeLog NEWS README pyrpm.spec

.PHONY: changelog build

build: dist-bzip2
	rpmbuild -ta pyrpm-@VERSION@.tar.bz2

srpm: dist-bzip2
	rpmbuild -ts pyrpm-@VERSION@.tar.bz2

changelog:
	rcs2log -v | sed -e 's|@.*\.redhat\.com|@redhat.com|g' > ChangeLog

CLEANFILES := pyrpm.spec $(notdir $(wildcard *.pyc)) pyrpm-*.tar.bz2 pyrpm-*.tar.gz $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) $(notdir $(wildcard \.\#*))

maintainer:
	rm -rf pyrpm-*.tar.bz2
	aclocal
	automake -a -c
	autoconf
	./configure
	make build

