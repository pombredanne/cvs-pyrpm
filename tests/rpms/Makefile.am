SPECS = $(shell ls -1 *.spec)
ARCHES = noarch i386 x86_64
NAMES = $(SPECS:.spec=)

PACKAGES = $(shell for name in $(NAMES); do for arch in $(ARCHES); do echo "$$name.$$arch.rpm "; done; done)

EXTRA_DIST = $(SPECS)

WORKDIR := $(shell pwd)
SOURCEDIR = $(WORKDIR)
BUILDDIR = $(WORKDIR)
SRCRPMDIR = $(WORKDIR)
RPMDIR = $(WORKDIR)
RPM := $(shell if test -f /usr/bin/rpmbuild ; then echo rpmbuild ; else echo rpm ; fi)
RPMBUILD = $(RPM) --define "_sourcedir $(SOURCEDIR)" \
		--define "_builddir $(BUILDDIR)" \
                --define "_srcrpmdir $(SRCRPMDIR)" \
                --define "_rpmdir $(RPMDIR)"

all:: $(PACKAGES)

$(PACKAGES):
	$(RPMBUILD) -bb --target=$(shell echo $@ | sed -e "s/\.rpm//" | sed -e "s/.*\.//") $(shell echo $@ | awk -F"." '{v=$$1; for(i=2; i<=NF-2; i++) v=v"."$$i; print v}').spec

clean:
	@echo Cleaning..
	@for dir in $(ARCHES); do \
		$(RM) -rf $$dir; \
	done
