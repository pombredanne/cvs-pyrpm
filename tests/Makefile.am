TESTS_ENVIRONMENT = PYTHONPATH=${srcdir}/../pyrpm:@PY_PYTHONPATH@
TESTS = yumconfigtest functionstest
EXTRA_DIST = $(TESTS) yum-test.tgz coverage.py

CLEANFILES := .coverage stdout stderr $(notdir $(wildcard *,cover)) $(notdir $(wildcard *~)) $(notdir $(wildcard *\#))


