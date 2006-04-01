DOCFILES = pyrpm.txt pyrpm-devel.txt pyrpm-tools.txt pyrpm-links.txt
EXTRA_DIST = $(DOCFILES) $(DOCFILES:.txt=.html) pycheckrc

# Not needed, we use %doc in the specfile
#docdir = $(datadir)/doc/$(PACKAGE)
#doc_DATA = $(DOCFILES:.txt=.html)

all: $(DOCFILES:.txt=.html)

.txt.html:
	asciidoc -b html4 $< > $@

clean:
	rm -rf $(DOCFILES:.txt=.html)

