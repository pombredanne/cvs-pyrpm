#!/bin/sh
rm -rf pyrpm-*.tar.bz2
aclocal
automake -a -c
autoconf
./configure
make build
