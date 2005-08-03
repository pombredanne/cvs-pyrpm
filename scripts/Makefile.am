scripts = oldpyrpm.py pyrpmcheck pyrpmcheckrepo pyrpmcreaterepo pyrpmdb2rpmdb \
	pyrpmdbverify pyrpminstall pyrpmrandomizer pyrpmrebuilddb \
	pyrpmspecinfo pyrpmyum rpmdb2pyrpmdb
EXTRA_DIST = $(scripts)
bin_SCRIPTS = $(scripts)

install-exec-local:
	@for i in $(scripts); do \
		perl -pi -e 's#^PYRPMDIR\s*=\s*".*".*#PYRPMDIR = "$(pkgdatadir)"#g' $(DESTDIR)$(bindir)/$$i;\
	done

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) $(notdir $(wildcard \.\#*))

