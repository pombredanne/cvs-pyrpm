install-exec-local:
	$(mkinstalldirs) $(DESTDIR)$(bindir)
	install -m 0755 $(srcdir)/scripts/pyrpminstall $(DESTDIR)$(bindir)/pyrpminstall

install-data-local:
	$(mkinstalldirs) $(DESTDIR)$(datadir)/pyrpm
	$(mkinstalldirs) $(DESTDIR)$(datadir)/doc/pyrpm-@VERSION@
	$(INSTALL_DATA) $(srcdir)/pyrpm/*.py $(DESTDIR)$(datadir)/pyrpm
	$(INSTALL_DATA) $(srcdir)/doc/* $(DESTDIR)$(datadir)/doc/pyrpm-@VERSION@

build: tar
	rpm -tb pyrpm-@VERSION@.tar.bz2

clean:
	rm -rf aclocal.m4 autom4te.cache config.log COPYING config.status configure INSTALL install-sh Makefile Makefile.in missing pyrpm.spec *.pyc pyrpm/*.pyc pyrpm-*.tar.bz2

tar:
	tar -jc --exclude=CVS -f pyrpm-1.0.0.tar.bz2 configure.in NEWS AUTHORS ChangeLog FILES INFO Makefile.am pyrpm/ pyrpm.spec.in pyrpm.spec scripts/ tests/ doc/ pyrpmlib.py README TODO

