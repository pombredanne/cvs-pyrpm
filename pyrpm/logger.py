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

# ---------------------------------------------------------------------------

# abstract class for logging targets
class LogTarget:
    """ Abstract class for logging targets. """
    def __init__(self):
        self.fd = None

    def write(self, data, level, logger):
        raise NotImplementedError, "LogTarget.write is an abstract method"

    def flush(self):
        raise NotImplementedError, "LogTarget.flush is an abstract method"

    def close(self):
        raise NotImplementedError, "LogTarget.close is an abstract method"

# ---------------------------------------------------------------------------

# private class for stdout
class _StdoutLog(LogTarget):
    def __init__(self):
        LogTarget.__init__(self)
        self.fd = sys.stdout

    def write(self, data, level, logger):
        # ignore level
        self.fd.write(data)
        self.flush()

    def close(self):
        self.flush()

    def flush(self):
        self.fd.flush()

# ---------------------------------------------------------------------------

# private class for stderr
class _StderrLog(_StdoutLog):
    def __init__(self):
        _StdoutLog.__init__(self)
        self.fd = sys.stderr

# ---------------------------------------------------------------------------

# private class for syslog
class _SyslogLog(_StdoutLog):
    fd = None

    def write(self, data, level, logger):
        if level > logger.NO_DEBUG:
            priority = syslog.LOG_DEBUG
        elif level >= logger.INFO1:
            priority = syslog.LOG_INFO
        elif level == logger.WARNING:
            priority = syslog.LOG_WARNING
        elif level == logger.ERROR:
            priority = syslog.LOG_ERR
        elif level == logger.FATAL:
            priority = syslog.LOG_CRIT

        if data.endswith("\n"):
            data = data[:len(data)-1]
        if len(data) > 0:
            syslog.syslog(priority, data)

    def flush(self):
        pass

# ---------------------------------------------------------------------------

class Logger:
    r"""
    Format string:

    %(class)s      Calling class the function belongs to, else empty
    %(date)s       Date using Logger.date_format, see time module
    %(domain)s     Full Domain: %(module)s.%(class)s.%(function)s
    %(file)s       Filename of the module
    %(function)s   Function name, empty in __main__
    %(label)s      Label according to log function call from Logger.label
    %(level)d      Internal logging level
    %(line)d       Line number in module
    %(module)s     Module name
    %(message)s    Log message

    Standard levels:

    FATAL                 Fatal error messages
    ERROR                 Error messages
    WARNING               Warning messages
    INFOx, x in [1..5]    Information
    DEBUGy, y in [1..10]  Debug messages
    NO_INFO               No info output
    NO_DEBUG              No debug output
    INFO_MAX              Maximum info level
    DEBUG_MAX             Maximing debug level

    x and y depend on info_max and debug_max from Logger class initialization.
    See __init__ function.

    Default logging targets:

    stdout        Logs to stdout
    stderr        Logs to stderr
    syslog        Logs to syslog

    Example:

    from logger import log
    log.setLogLevel(log.INFO1)
    log.setDebugLogLevel(log.NO_DEBUG)
    for i in xrange(1, log.INFO_MAX-log.NO_INFO+1):
        log.setLogLabel(i+log.NO_INFO, "INFO%d: " % i)
    log.setFormat("%(date)s %(module)s:%(line)d [%(domain)s] %(label)s: "
                  "%(level)d %(message)s")
    log.setDateFormat("%Y-%m-%d %H:%M:%S")
    log.addLogging("*", FileLog("/tmp/log", "a"))
    log.addLogging("*", Logger.syslog, format="%(label)s%(message)s")

    log.debug3Ln("debug3")
    log.debug2Ln("debug2")
    log.debug1Ln("debug1")
    log.infoLn("info")
    log.warning("warning\n")
    log.error("error\n")
    log.fatalLn("fatal")
    log.logLn(log.INFO, "raw info")

    """

    ALL       = -1
    NOTHING   =  0
    FATAL     =  1
    ERROR     =  2
    WARNING   =  3

    # Additional levels are generated in class initilization

    stdout = _StdoutLog()
    stderr = _StderrLog()
    syslog = _SyslogLog()

    def __init__(self, info_max=5, debug_max=10):
        """ Logger class initialization """
        self._level = { }
        self._debug_level = { }
        self._format = ""
        self._date_format = ""
        self._label = { }
        self._logging = { }
        self._domains = { }

        # INFO1 is required for standard log level
        if info_max < 1:
            raise ValueError, "Logger: info_max %d is too low" % info_max
        if debug_max < 0:
            raise ValueError, "Logger: debug_max %d is too low" % debug_max

        self.NO_INFO   = self.WARNING
        self.INFO_MAX  = self.NO_INFO + info_max
        self.NO_DEBUG  = self.INFO_MAX
        self.DEBUG_MAX = self.NO_DEBUG + debug_max

        self.setLogLabel(self.FATAL, "FATAL ERROR: ")
        self.setLogLabel(self.ERROR, "ERROR: ")
        self.setLogLabel(self.WARNING, "WARNING: ")

        # generate info levels, infox and infoxLn functions
        for _level in xrange(1, self.INFO_MAX-self.NO_INFO+1):
            setattr(self, "INFO%d" % _level, _level+self.NO_INFO)
            self.setLogLabel(_level+self.NO_INFO, "")
            setattr(self, "info%d" % (_level),
                    (lambda self, x:
                     lambda message, *args:
                     self.info(x, message, *args))(self, _level))
            setattr(self, "info%dLn" % (_level),
                    (lambda self, x:
                     lambda message, *args:
                     self.infoLn(x, message, *args))(self, _level))

        # generate debug levels, debugx and debugxLn functions
        for _level in xrange(1, self.DEBUG_MAX-self.NO_DEBUG+1):
            setattr(self, "DEBUG%d" % _level, _level+self.NO_DEBUG)
            self.setLogLabel(_level+self.NO_DEBUG, "DEBUG%d: " % _level)
            setattr(self, "debug%d" % (_level),
                    (lambda self, x:
                     lambda message, *args:
                     self.debug(x, message, *args))(self, _level))
            setattr(self, "debug%dLn" % (_level),
                    (lambda self, x:
                     lambda message, *args:
                     self.debugLn(x, message, *args))(self, _level))

        # set initial log levels, formats and targets
        self.setLogLevel(self.INFO1)
        self.setDebugLogLevel(self.NO_DEBUG)
        self.setFormat("%(label)s%(message)s")
        self.setDateFormat("%d %b %Y %H:%M:%S")
        self.setLogging("*", self.stderr, [ self.FATAL, self.ERROR ])
        self.setLogging("*", self.stdout,
                        [ i for i in xrange(self.WARNING, self.DEBUG_MAX+1) ])

    def close(self):
        """ Close all logging targets """
        for level in xrange(self.FATAL, self.DEBUG_MAX+1):
            if not self._logging.has_key(level):
                continue
            for (domain, target, _format) in self._logging[level]:
                target.close()

    def _checkLogLevel(self, level, min, max):
        if level < min or level > max:
            raise ValueError, "Level %d out of range, should be [%d..%d]." % \
                  (level, min, max)

    def _checkDomain(self, domain):
        if not domain or domain == "":
            raise ValueError, "Domain '%s' is not valid." % domain

    def getLogLevel(self, domain="*"):
        """ Get log level. """
        self._checkDomain(domain)
        if self._level.has_key(domain):
            return self._level[domain]
        return self.NOTHING

    def setLogLevel(self, level, domain="*"):
        """ Set log level [NOTHING .. INFO_MAX] """
        self._checkDomain(domain)
        if level < self.NOTHING:
            level = self.NOTHING
        if level > self.INFO_MAX:
            level = self.INFO_MAX
        self._level[domain] = level

    def getDebugLogLevel(self, domain="*"):
        """ Get debug log level. """
        self._checkDomain(domain)
        if self._debug_level.has_key(domain):
            return self._debug_level[domain] - self.NO_DEBUG
        return self.NO_DEBUG

    def setDebugLogLevel(self, level, domain="*"):
        """ Set debug log level [NO_DEBUG .. DEBUG_MAX] """
        self._checkDomain(domain)
        if level < 0:
            level = 0
        if level > self.DEBUG_MAX - self.NO_DEBUG:
            level = self.DEBUG_MAX - self.NO_DEBUG
        self._debug_level[domain] = level - self.NO_DEBUG

    def setFormat(self, format):
        self._format = format

    def setDateFormat(self, format):
        self._date_format = format

    def _getLevels(self, level):
        """ Generate log level array. """
        if level != self.ALL:
            if isinstance(level, types.ListType) or \
                   isinstance(level, types.TupleType):
                levels = level
            else:
                levels = [ level ]
            for level in levels:
                self._checkLogLevel(level, min=self.FATAL, max=self.DEBUG_MAX)
        else:
            levels = [ i for i in xrange(self.FATAL, self.DEBUG_MAX+1) ]
        return levels

    def _getTargets(self, target):
        """ Generate target array. """
        if isinstance(target, types.ListType) or \
               isinstance(target, types.TupleType):
            targets = target
        else:
            targets = [ target ]
        for _target in targets:
            if not issubclass(_target.__class__, LogTarget):
                raise ValueError, "'%s' is no valid logging target." % \
                      _target.__class__.__name__
        return targets

    def setLogLabel(self, level, label):
        """ Set log label for level. Level can be a single level or an array
        of levels. """
        levels = self._getLevels(level)
        for level in levels:
            self._checkLogLevel(level, min=self.FATAL, max=self.DEBUG_MAX)
            self._label[level] = label

    # private method for self._domains array creation, speeds up
    def _genDomains(self):
        """ Generate dict with domain by level. """
        if len(self._domains) > 0:
            self._domains = { }
        for level in xrange(self.FATAL, self.DEBUG_MAX+1):
            if not self._logging.has_key(level):
                continue
            for (domain, target, _format) in self._logging[level]:
                if domain not in self._domains:
                    self._domains.setdefault(level, [ ]).append(domain)

    def setLogging(self, domain, target, level=ALL, format=None):
        """ Set log target for domain and level. Level can be a single level
        or an array of levels. Use level ALL to set for all levels.
        If no format is specified, the default format will be used. """
        self._checkDomain(domain)
        levels = self._getLevels(level)
        targets = self._getTargets(target)
        for level in levels:
            for target in targets:
                self._logging[level] = [ (domain, target, format) ]
        self._genDomains()

    def addLogging(self, domain, target, level=ALL, format=None):
        """ Add log target for domain and level. Level can be a single level
        or an array of levels. Use level ALL to set for all levels.
        If no format is specified, the default format will be used. """
        self._checkDomain(domain)
        levels = self._getLevels(level)
        targets = self._getTargets(target)
        for level in levels:
            for target in targets:
                self._logging.setdefault(level, [ ]).append((domain, target,
                                                             format))
        self._genDomains()

    def delLogging(self, domain, target, level=ALL, format=None):
        """ Delete log target for domain and level. Level can be a single level
        or an array of levels. Use level ALL to set for all levels.
        If no format is specified, the default format will be used. """
        self._checkDomain(domain)
        levels = self._getLevels(level)
        targets = self._getTargets(target)
        for _level in levels:
            for target in targets:
                if not self._logging.has_key(_level):
                    continue
                if (domain, target, format) in self._logging[_level]:
                    self._logging[_level].remove( (domain, target, format) )
                    if len(self._logging[_level]) == 0:
                        del self._logging[_level]
                        continue
                if level != self.ALL:
                    raise ValueError, "No mathing logging for " \
                          "level %d, domain %s, target %s and format %s." % \
                          (_level, domain, target.__class__.__name__, format)
        self._genDomains()

    def isLoggingHere(self, level):
        """ Is there currently any logging for this log level (and domain)? """
        dict = self._genDict(level)
        if not dict:
            return False

        point_domain = dict["domain"] + "."

        # do we need to log?
        for (domain, target, format) in self._logging[level]:
            if domain == "*" or \
                   point_domain.startswith(domain) or \
                   fnmatch.fnmatchcase(dict["domain"], domain):
                return True
        return False

    def log(self, level, data):
        """ Log data without and prefix. """
        self._checkLogLevel(level, min=self.FATAL, max=self.DEBUG_MAX)
        self._log(level, 0, 1, "%s", data)

    def logLn(self, level, data):
        """ Log data without and prefix, but append a newline. """
        self._checkLogLevel(level, min=self.FATAL, max=self.DEBUG_MAX)
        self._log(level, 1, 1, "%s", data)

    def debug(self, level, format, *args):
        """ Debug log using debug level [1..debug_max].
        There are additional debugx functions according to debug_max
        from __init__"""
        self._checkLogLevel(level, min=1, max=self.DEBUG_MAX-self.NO_DEBUG)
        self._log(level+self.NO_DEBUG, 0, 0, format, *args)

    def debugLn(self, level, format, *args):
        """ Debug log with newline using debug level [1..debug_max].
        There are additional debugxLn functions according to debug_max
        from __init__"""
        self._checkLogLevel(level, min=1, max=self.DEBUG_MAX-self.NO_DEBUG)
        self._log(level+self.NO_DEBUG, 1, 0, format, *args)

    def info(self, level, format, *args):
        """ Information log using info level [1..info_max].
        There are additional infox functions according to info_max from
        __init__"""
        self._checkLogLevel(level, min=self.INFO1-self.NO_INFO,
                            max=self.INFO_MAX)
        self._log(level+self.NO_INFO, 0, 0, format, *args)

    def infoLn(self, level, format, *args):
        """ Information log with newline using info level [1..info_max].
        There are additional infoxLn functions according to info_max from
        __init__"""
        self._checkLogLevel(level, min=self.INFO1-self.NO_INFO,
                            max=self.INFO_MAX)
        self._log(level+self.NO_INFO, 1, 0, format, *args)

    def warning(self, format, *args):
        """ Warning log. """
        self._log(self.WARNING, 0, 0, format, *args)

    def warningLn(self, format, *args):
        """ Warning log with newline. """
        self._log(self.WARNING, 1, 0, format, *args)

    def error(self, format, *args):
        """ Error log. """
        self._log(self.ERROR, 0, 0, format, *args)

    def errorLn(self, format, *args):
        """ Error log with newline. """
        self._log(self.ERROR, 1, 0, format, *args)

    def fatal(self, format, *args):
        """ Fatal error log. """
        self._log(self.FATAL, 0, 0, format, *args)

    def fatalLn(self, format, *args):
        """ Fatal error log with newline. """
        self._log(self.FATAL, 1, 0, format, *args)

    def _getClass(self, frame):
        """ Function to get calling class. Returns class or None. """
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
        """ Internal function to get calling class. Returns class or None. """
        for value in obj.__dict__.values():
            if type(value) == types.FunctionType:
                if value.func_code == code:
                    return obj

        for base in obj.__bases__:
            _obj = self._getClass2(base, code)
            if _obj:
                return _obj
        return None

    # internal log class
    def _log(self, level, newline, raw, format, *args):
        dict = self._genDict(level)
        if not dict:
            return

        if len(args) > 0:
            dict['message'] = format % args
        else:
            dict['message'] = format

        point_domain = dict["domain"] + "."

        used_targets = [ ]
        # log to target(s)
        for (domain, target, _format) in self._logging[level]:
            if target in used_targets:
                continue
            if domain == "*" \
                   or point_domain.startswith(domain+".") \
                   or fnmatch.fnmatchcase(dict["domain"], domain):
                if not _format:
                    _format = self._format
                if raw:
                    target.write(dict["message"], level, self)
                else:
                    target.write(_format % dict, level, self)
                if newline:
                    target.write("\n", level, self)
                used_targets.append(target)

    # internal function to generate the dict, needed for logging
    def _genDict(self, level):
        """ Internal function. """
        check_domains = [ ]
        simple_match = False

        if level > self.INFO_MAX:
            # debug
            _dict = self._debug_level
        else:
            _dict = self._level

        # no debug
        for domain in _dict:
            if domain == "*":
                # '*' matches everything: simple match
                if _dict[domain] >= level:
                    simple_match = True
                    if len(check_domains) > 0:
                        check_domains = [ ]
                    break
            else:
                if _dict[domain] >= level:
                    check_domains.append(domain)

        if not simple_match and len(check_domains) < 1:
            return None

        f = inspect.currentframe()

        # go outside of logger module as long as there is a lower frame
        while f and f.f_back and f.f_globals["__name__"] == self.__module__:
            f = f.f_back

        if not f:
            raise ValueError, "Frame information not available."

        # get module name
        module_name = f.f_globals["__name__"]

        # simple module match test for all entries of check_domain
        point_module = module_name + "."
        for domain in check_domains:
            if point_module.startswith(domain):
                # found domain in module name
                check_domains = [ ]
                break

        # get code
        co = f.f_code

        # optimization: bail out early if domain can not match at all
        _len = len(module_name)
        for domain in self._domains[level]:
            i = domain.find("*")
            if i == 0:
                continue
            elif i > 0:
                d = domain[:i]
            else:
                d = domain
            if _len >= len(d):
                if not module_name.startswith(d):
                    return None
            else:
                if not d.startswith(module_name):
                    return None

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
                 'date' : time.strftime(self._date_format, time.localtime()) }
        if dict["function"] == "?":
            dict["function"] = ""

        # domain match needed?
        domain_needed = False
        for domain in self._domains[level]:
            # standard domain, matches everything
            if domain == "*":
                continue
            # domain is needed
            domain_needed = True
            break

        # do we need to get the class object?
        if self._format.find("%(domain)") >= 0 or \
               self._format.find("%(class)") >= 0 or \
               domain_needed or \
               len(check_domains) > 0:
            obj = self._getClass(f)
            if obj:
                dict["class"] = obj.__name__

        # build domain string
        dict["domain"] = "" + dict["module"]
        if dict["class"] != "":
            dict["domain"] += "." + dict["class"]
        if dict["function"] != "":
            dict["domain"] += "." + dict["function"]

        if len(check_domains) < 1:
            return dict

        point_domain = dict["domain"] + "."
        for domain in check_domains:
            if point_domain.startswith(domain) or \
                   fnmatch.fnmatchcase(dict["domain"], domain):
                return dict

        return None

# ---------------------------------------------------------------------------

class FileLog(LogTarget):
    """ FileLog class.
    File will be opened on the first write. """
    def __init__(self, filename, mode="w"):
        LogTarget.__init__(self)
        self.filename = filename
        self.mode = mode

    def open(self):
        if self.fd:
            return
        self.fd = open(self.filename, self.mode)

    def write(self, data, level, logger):
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
        if not self.fd:
            return
        self.fd.flush()

# ---------------------------------------------------------------------------

# Global logging object.
log = Logger()

# ---------------------------------------------------------------------------

# Example
if __name__ == '__main__':
    log.setLogLevel(log.INFO2)
    log.setDebugLogLevel(log.DEBUG3)
    for i in xrange(1, log.INFO_MAX-log.NO_INFO+1):
        log.setLogLabel(i+log.NO_INFO, "INFO%d: " % i)
    log.setFormat("%(date)s %(module)s:%(line)d %(label)s"
                  "%(message)s")
    log.setDateFormat("%Y-%m-%d %H:%M:%S")
    log.addLogging("*", FileLog("/tmp/log", "a"))
#    log.addLogging("*", Logger.syslog, format="%(label)s%(message)s")

    log.debug10Ln("debug10")
    log.debug9Ln("debug9")
    log.debug8Ln("debug8")
    log.debug7Ln("debug7")
    log.debug6Ln("debug6")
    log.debug5Ln("debug5")
    log.debug4Ln("debug4")
    log.debug3Ln("debug3")
    log.debug2Ln("debug2")
    log.debug1Ln("debug1")
    log.info5Ln("info5")
    log.info4Ln("info4")
    log.info3Ln("info3")
    log.info2Ln("info2")
    log.info1Ln("info1")
    log.warning("warning\n")
    log.error("error\n")
    log.fatalLn("fatal")
    log.logLn(log.INFO1, "raw info")

# vim:ts=4:sw=4:showmatch:expandtab
