SUBDIRS = doc pyrpm scripts
EXTRA_DIST = pyrpm.spec build.sh FILES README TODO NEWS AUTHORS ChangeLog INFO pyrpmlib.py

build: dist-bzip2
	rpmbuild -tb pyrpm-@VERSION@.tar.bz2

CLEANFILES := COPYING INSTALL pyrpm.spec $(notdir $(wildcard *.pyc))  pyrpm-*.tar.bz2 pyrpm-*.tar.gz

