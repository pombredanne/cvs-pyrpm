scripts = pyrpmdb2rpmdb  pyrpminstall pyrpmspecinfo pyrpmyum rpmdb2pyrpmdb
EXTRA_DIST = $(scripts)
bin_SCRIPTS = $(scripts)

all-local:
	perl -pi -e 's#^PYRPMDIR\s*=\s*".*".*#PYRPMDIR = "$(pkgdatadir)"#g' $(scripts)

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) $(notdir $(wildcard \.\#*))

