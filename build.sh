#!/bin/sh
rm -rf pyrpm-*.tar.bz
aclocal
automake -a
autoconf
./configure
make tar
rpm -tb pyrpm-*.tar.bz
