SUBDIRS = doc pyrpm scripts
EXTRA_DIST = AUTHORS ChangeLog NEWS README build.sh pyrpm.spec

.PHONY: changelog build

build: dist-bzip2
	rpmbuild -ta pyrpm-@VERSION@.tar.bz2

changelog:
	rcs2log -v | sed -e 's|@.*\.redhat\.com|@redhat.com|g' > ChangeLog

CLEANFILES := COPYING INSTALL pyrpm.spec $(notdir $(wildcard *.pyc))  pyrpm-*.tar.bz2 pyrpm-*.tar.gz

