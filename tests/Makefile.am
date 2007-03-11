SUBDIRS = rpms
TESTS_ENVIRONMENT = PYTHONPATH=${srcdir}/../pyrpm:@PY_PYTHONPATH@
TESTS = yumconfigtest functionstest rpmgraph.py rpmdbtestPackages
EXTRA_DIST = $(TESTS) coverage.py deltaanalyze.py deltagen.py delta.py test10

CLEANFILES := .coverage stdout stderr $(notdir $(wildcard *,cover)) \
	$(notdir $(wildcard *~)) $(notdir $(wildcard *\#)) $(wildcard *\.pyc)

