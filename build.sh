#!/bin/sh
rm -rf pyrpm-*.tar.bz2
aclocal
automake -a
autoconf
./configure
make build
