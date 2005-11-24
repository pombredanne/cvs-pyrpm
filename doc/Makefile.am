DOCFILES = pyrpm.txt pyrpm-devel.txt pyrpm-tools.txt pyrpm-links.txt
EXTRA_DIST = $(DOCFILES) pycheckrc

all: $(DOCFILES:.txt=.html)

.txt.html:
	asciidoc -b html4 $< > $@

clean:
	rm -rf $(DOCFILES:.txt=.html)

