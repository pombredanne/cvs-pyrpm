DOCFILES = pyrpm.txt pyrpm-devel.txt pyrpm-devel-db.txt pyrpm-tools.txt pyrpm-links.txt 
EXTRA_DIST = $(DOCFILES) $(DOCFILES:.txt=.html) pycheckrc asciidoc.conf \
	favicon.ico linux.gif

CLEANFILES := $(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) \
	$(notdir $(wildcard \.\#*)) $(notdir $(wildcard *\.bak))

# Not needed, we use %doc in the specfile
#docdir = $(datadir)/doc/$(PACKAGE)
#doc_DATA = $(DOCFILES:.txt=.html)

all: $(DOCFILES:.txt=.html)

.txt.html: asciidoc.conf
	asciidoc -f asciidoc.conf -b html4 -o $@ $<

clean:
	rm -rf $(DOCFILES:.txt=.html)

