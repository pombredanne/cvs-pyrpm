install-exec-local:
	$(mkinstalldirs) $(DESTDIR)$(bindir)
	install -m 0755 $(srcdir)/pyrpminstall $(DESTDIR)$(bindir)/pyrpminstall

install-data-local:
	$(mkinstalldirs) $(DESTDIR)$(datadir)/pyrpm
	$(INSTALL_DATA) $(srcdir)/pyrpm/*.py $(DESTDIR)$(datadir)/pyrpm

build: tar
	rpm -tb pyrpm-@VERSION@.tar.bz

clean:
	rm -rf aclocal.m4 autom4te.cache config.log config.status configure INSTALL install-sh Makefile Makefile.in missing

tar:
	tar jcf pyrpm-1.0.0.tar.bz configure.in NEWS AUTHORS ChangeLog FILES INFO Makefile.am pyrpm/ pyrpm.spec.in pyrpm.spec pyrpminstall pyrpmlib.py README TODO

