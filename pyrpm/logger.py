#
# Copyright (C) 2005,2006 Red Hat, Inc.
# Author: Thomas Woerner <twoerner@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Library General Public License as published by
# the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# Copyright 2004, 2005 Red Hat, Inc.
#
# AUTHOR: Thomas Woerner <twoerner@redhat.com>
#

import os
import sys
import types
import time
import inspect
import fnmatch
import syslog

class Logger:
    """
    Format string
    
    %(class)s      Calling class the function belongs to, else empty
    %(date)s       Date using Logger.date_format, see time module
    %(domain)s     Full Domain: %(module)s.%(class)s.%(function)s
    %(file)s       Filename of the module
    %(function)s   Funciton name, empty in __main__
    %(label)s      Label according to log function call from Logger.label
    %(line)d       Line number in module
    %(module)s     Module name
    %(message)s    Log message

    Example:
    from logger import log
    log.setLogLevel(log.DEBUG2)
    log.setLogLabel(log.INFO, "INFO: ")
    log.setFormat("%(date)s %(module)s:%(line)d [%(domain)s] %(label)s: "
                  "%(level)d %(message)s")
    log.setDateFormat("%Y-%m-%d %H:%M:%S")
    log.addLogging("*", FileLog("/tmp/log", "a"))

    log.debug3ln("debug3")
    log.debug2ln("debug2")
    log.debug1ln("debug1")
    log.infoln("info")
    log.warning("warning\n")
    log.error("error\n")
    log.fatalln("fatal")
    log.logln(log.INFO, "raw info")
    
    """
    ALL     = None
    FATAL   = -3
    ERROR   = -2
    WARNING = -1
    INFO    =  0
    DEBUG1  =  1
    DEBUG2  =  2
    DEBUG3  =  3
    DEBUG4  =  4
    DEBUG5  =  5
    DEBUG6  =  6
    DEBUG7  =  7
    DEBUG8  =  8
    DEBUG9  =  9
    DEBUG10 = 10

    def __init__(self):
        self._level = 0
        self._format = "%(date)s %(file)s:%(line)d [%(domain)s] " \
                       "%(label)s%(message)s"
        self._label = { Logger.FATAL   : "FATAL ERROR: ",
                        Logger.ERROR   : "ERROR: ",
                        Logger.WARNING : "WARNING: ",
                        Logger.INFO    : ""}
        self._date_format = "%d %b %Y %H:%M:%S"
        self._logging = { Logger.FATAL   : [ ("*", sys.stderr, None), ],
                          Logger.ERROR   : [ ("*", sys.stderr, None), ],
                          Logger.WARNING : [ ("*", sys.stdout, None), ],
                          Logger.INFO    : [ ("*", sys.stdout, None), ] }
        for _level in xrange(Logger.DEBUG1, Logger.DEBUG10+1):
            self._label[_level] = "DEBUG%d: " % _level
            self._logging[_level] = [ ("*", sys.stdout, None), ]

    def _checkLogLevel(self, level, min=FATAL, max=DEBUG10):
        if level < min or level > max:
            raise ValueError, "Level %d out of range, should be [%d..%d]." % \
                  (level, min, max)

    def setLogLevel(self, level):
        self._checkLogLevel(level)
        self._level = level

    def setLogLabel(self, level, label):
        self._checkLogLevel(level)
        self._label[level] = label

    def setFormat(self, format):
        self._format = format

    def setDateFormat(self, format):
        self._date_format = format

    def setLogging(self, domain, target, level=ALL, format=None):
        if level:
            if isinstance(level, types.ListType) or \
                   isinstance(level, types.TupleType):
                levels = level
            else:
                levels = [ level ]
            for level in levels:
                self._checkLogLevel(level)
        else:
            levels = [ i for i in xrange(log.FATAL, log.DEBUG10+1) ]
        for level in levels:
            self._logging[level] = [ (domain, target, format) ]

    def addLogging(self, domain, target, level=ALL, format=None):
        if level:
            if isinstance(level, types.ListType) or \
                   isinstance(level, types.TupleType):
                levels = level
            else:
                levels = [ level ]
            for level in levels:
                self._checkLogLevel(level)
        else:
            levels = [ i for i in xrange(log.FATAL, log.DEBUG10+1) ]
        for level in levels:
            self._logging.setdefault(level, [ ]).append((domain, target,
                                                         format))

    def delLogging(self, domain, target, level=ALL, format=None):
        if level:
            if isinstance(level, types.ListType) or \
                   isinstance(level, types.TupleType):
                levels = level
            else:
                levels = [ level ]
            for level in levels:
                self._checkLogLevel(level)
        else:
            levels = [ i for i in xrange(log.FATAL, log.DEBUG10+1) ]
        for level in levels:
            if self._logging.has_key(level):
                if (domain, target, format) in self._logging[level]:
                    self._logging[level].remove( (domain, target, format) )
                    if len(self._logging[level]) == 0:
                        del self._logging[level]
                        return
            raise ValueError, "No mathing logging for " \
                  "level %d, domain %s, target %s and format %s." % \
                  (level, domain, target, format)

    def log(self, level, data):
        self._checkLogLevel(level)
        self._log(level, 0, 1, "%s", data)

    def logln(self, level, data):
        self._checkLogLevel(level)
        self._log(level, 1, 1, "%s", data)

    def debug(self, level, format, *args):
        self._checkLogLevel(min=Logger.DEBUG1)
        self._log(level, 0, 0, format, *args)

    def debugln(self, level, format, *args):
        self._checkLogLevel(level, min=Logger.DEBUG1)
        self._log(level, 1, 0, format, *args)

    def info(self, format, *args):
        self._log(Logger.INFO, 0, 0, format, *args)

    def infoln(self, format, *args):
        self._log(Logger.INFO, 1, 0, format, *args)

    def warning(self, format, *args):
        self._log(Logger.WARNING, 0, 0, format, *args)

    def warningln(self, format, *args):
        self._log(Logger.WARNING, 1, 0, format, *args)

    def error(self, format, *args):
        self._log(Logger.ERROR, 0, 0, format, *args)

    def errorln(self, format, *args):
        self._log(Logger.ERROR, 1, 0, format, *args)

    def fatal(self, format, *args):
        self._log(Logger.FATAL, 0, 0, format, *args)

    def fatalln(self, format, *args):
        self._log(Logger.FATAL, 1, 0, format, *args)

    def _getClass(self, frame):
        # get class by first function argument, if there are any
        if frame.f_code.co_argcount > 0:
            selfname = frame.f_code.co_varnames[0]
            if frame.f_locals.has_key(selfname):
                _self = frame.f_locals[selfname]
                obj = self._getClass2(_self.__class__, frame.f_code)
                if obj:
                    return obj

        module = inspect.getmodule(frame.f_code)
        code = frame.f_code

        # function in module?
        if module.__dict__.has_key(code.co_name):
            if hasattr(module.__dict__[code.co_name], "func_code") and \
                   module.__dict__[code.co_name].func_code  == code:
                return None

        # class in module
        for (name, obj) in module.__dict__.iteritems():
            if isinstance(obj, types.ClassType):
                if hasattr(obj, code.co_name):
                    value = getattr(obj, code.co_name)
                    if type(value) == types.FunctionType:
                        if value.func_code == code:
                            return obj

        # nothing found
        return None

    def _getClass2(self, obj, code):
	for value in obj.__dict__.values():
            if type(value) == types.FunctionType:
                if value.func_code == code:
                    return obj
                
        for base in obj.__bases__:
            _obj = self._getClass2(base, code)
            if _obj:
                return _obj
        return None

    def _log(self, level, newline, raw, format, *args):
        # log level higher than logging level?
        if level > self._level:
            return

        # no logging for this level specified
        if not self._logging.has_key(level):
            return

        domains = [ ]
        for (domain, target, _format) in self._logging[level]:
            if domain == "":
                domain = "*"
            if domain not in domains:
                domains.append(domain)
        # no logging domains
        if len(domains) < 0:
            return

        f = inspect.currentframe()
        # go outside of Log class
        while f and self._getClass(f) == self.__class__:
            f = f.f_back
        if not f:
            raise ValueError, "Frame information not available."

        co = f.f_code

        module_name = inspect.getmodule(f).__name__

        # optimization: bail out early if domain can not match at all
        _len = len(module_name)
        for domain in domains:
            i = domain.find("*")
            if i == 0:
                continue
            if _len >= len(domain):
                if not module_name.startswith(domain):
                    return
            else:
                if not domain.startswith(module_name):
                    return

        # generate dict for format output
        level_str = ""
        if self._label.has_key(level):
            level_str = self._label[level]
        dict = { 'file': co.co_filename,
                 'line': f.f_lineno,
                 'module': module_name,
                 'class': '',
                 'function': co.co_name,
                 'domain': '',
                 'label' : level_str,
                 'level' : level,
                 'date' : time.strftime(self._date_format, time.localtime()),
                 'message': format % args }
        if dict["function"] == "?":
            dict["function"] = ""

        # do we need to get the class object?
        if self._format.find("%(domain)") >= 0 or \
               self._format.find("%(class)") >= 0 or \
               (len(domains) > 1 and domains[0] != "*"):
            obj = self._getClass(f)
            if obj:
                dict["class"] = obj.__name__

        # build domain string
        if dict["module"] != "":
            dict["domain"] = dict["module"]
        if dict["class"] != "":
            if len(dict["domain"]) > 0:
                dict["domain"] += "."
            dict["domain"] += dict["class"]
        if dict["function"] != "":
            if len(dict["domain"]) > 0:
                dict["domain"] += "."
            dict["domain"] += dict["function"]
        point_domain = dict["domain"] + "."

        # log to target(s)
        for (domain, target, _format) in self._logging[level]:
            if domain == "":
                domain = "*"
            if domain == "*" or point_domain.startswith(domain) or \
                   fnmatch.fnmatch(dict["domain"], domain):
                if not _format:
                    _format = self._format
                if raw:
                    target.write(dict["message"])
                else:
                    target.write(_format % dict)
                if newline:
                    target.write("\n")

for _level in xrange(Logger.DEBUG1, Logger.DEBUG10+1):
    setattr(Logger, "debug%d" % (_level),
            (lambda x:
             lambda self, message, *args:
             self.debug(x, message, *args))(_level))
    setattr(Logger, "debug%dln" % (_level),
            (lambda x:
             lambda self, message, *args:
             self.debugln(x, message, *args))(_level))
del _level

# ---------------------------------------------------------------------------

class FileLog:
    def __init__(self, filename, mode="w"):
        self.filename = filename
        self.mode = mode
        self.fd = None

    def open(self):
        if self.fd:
            return
        self.fd = open(self.filename, self.mode)

    def write(self, data):
        if not self.fd:
            self.open()
        self.fd.write(data)
        self.fd.flush()

    def close(self):
        if not self.fd:
            return
        self.fd.close()
        self.fd = None

    def flush(self):
        if self.fd:
            self.fd.flush()

# ---------------------------------------------------------------------------

class SyslogLog:
    def __init__(self):
        pass

    def open(self):
        pass

    def write(self, data):
        if data.endswith("\n"):
            data = data[:len(data)-1]
        if len(data) > 0:
            syslog.syslog(data)

    def close(self):
        pass

    def flush(self):
        pass

# ---------------------------------------------------------------------------

log = Logger()

if __name__ == '__main__':
    log.setLogLevel(log.DEBUG2)
    log.setLogLabel(log.INFO, "INFO: ")
    log.setFormat("%(date)s %(module)s:%(line)d %(label)s"
                  "%(message)s")
    log.setDateFormat("%Y-%m-%d %H:%M:%S")
    log.addLogging("*", FileLog("/tmp/log", "a"))
#    log.addLogging("*", SyslogLog(), "%(label)s%(message)s")

    log.debug3ln("debug3")
    log.debug2ln("debug2")
    log.debug1ln("debug1")
    log.infoln("info")
    log.warning("warning\n")
    log.error("error\n")
    log.fatalln("fatal")
    log.logln(log.INFO, "raw info")
