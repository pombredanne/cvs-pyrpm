scripts = oldpyrpm.py pyrpmcheck pyrpmcheckinstall pyrpmcheckrepo \
	pyrpmcreatefilereq pyrpmcreaterepo pyrpmdbverify pyrpminstall \
	pyrpmkickstart pyrpmrandomizer pyrpmrebuilddb pyrpmspecinfo pyrpmyum
EXTRA_DIST = $(scripts)

bin_SCRIPTS = $(scripts)

install-exec-local:
	@for i in $(scripts); do \
	    sed -i -e 's#^PYRPMDIR\s*=\s*".*".*#PYRPMDIR = "$(pkgdatadir)"#g' \
		$(DESTDIR)$(bindir)/$$i;\
	done

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) \
	$(notdir $(wildcard \.\#*)) $(wildcard *\.pyc)

