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
#

import os.path
from installer import keyboard_models
from functions import create_file

def x_config(ks, buildroot, installation):
    # default: VGA graphics card, Generic extended super VGA monitor
    card = "Unknown video card"
    driver = "vga"
    videoram = 0
    monitor = "Unknown monitor"
    hsync = "31.5 - 37.9"
    vsync = "50 - 61"
    resolution = "800x600"
    depth = 8
    user_hsync = user_vsync = None
    options = [ ]

    # keyboard
    (kbd_layout, kbd_model, kbd_variant, kbd_options) = \
                 keyboard_models[ks["keyboard"]]

    kscard = None
    if ks["xconfig"].has_key("card"):
        kscard = ks["xconfig"]["card"]
    ksdriver = None
    if ks["xconfig"].has_key("driver"):
        ksdriver = ks["xconfig"]["driver"]
    ksoptions = [ ]

    if os.path.exists(buildroot+'/usr/share/hwdata/Cards'):
        if ksdriver and not kscard:
            print "ERROR: Card not specified, using default configuration."
        else:
            try:
                fd = open(buildroot+'/usr/share/hwdata/Cards')
            except:
                print "ERROR: Unable to open graphics card database."
            else:
                # TODO: honour SEE tags in file
                found = 0
                _card = None
                _driver = None
                _options = [ ]
                while 1:
                    line = fd.readline()
                    if not line:
                        break
                    line = line.strip()
                    if len(line) < 1 or line[0] == "#":
                        continue

                    if line[:4] == "NAME":
                        if kscard and kscard == _card:
                            card = _card
                            driver =_driver
                            options = _options
                            found = 1
                            break
                        _card = line[4:].strip()
                        _driver = None
                        _options = [ ]
                    elif line[:6] == "DRIVER":
                        _driver = line[6:].strip()
                    elif line[:4] == "LINE":
                        _options.append(line[4:].strip())
                    else:
                        continue
                fd.close()
                if not found:
                    print "ERROR: Card not found in graphics card database."

    elif os.path.exists(buildroot+'/usr/share/hwdata/videodrivers'):
        # There is no usable name in the videodrivers file, so fake it
        if ksdriver:
            driver = ksdriver
            card = driver + ' (generic)'
        else:
            print "ERROR: Driver not specified for xconfig, " +\
                  "using default configuration."
    else:
        print "ERROR: Could not find hardware database for video drivers."

    if ks["xconfig"].has_key("videoram"):
        videoram = ks["xconfig"]["videoram"]
    if ks["xconfig"].has_key("monitor"):
        try:
            fd = open(buildroot+'/usr/share/hwdata/MonitorsDB')
        except:
            print "ERROR: Unable to open monitor database."
        else:
            found = 0
            while 1:
                line = fd.readline()
                if not line:
                    break
                line = line.strip()
                if len(line) < 1 or line[0] == "#":
                    continue
                xargs = line.split(";")
                if len(xargs) < 5:
                    continue
                if xargs[1].strip() == ks["xconfig"]["monitor"]:
                    monitor = ks["xconfig"]["monitor"]
                    hsync = xargs[3].strip()
                    vsync = xargs[4].strip()
                    found = 1
                    break
            fd.close()
            if found != 1:
                print "ERROR: Monitor not found in hardware database."
    if ks["xconfig"].has_key("hsync"): # overwrite with user supplied value
        hsync = ks["xconfig"]["hsync"]
    if ks["xconfig"].has_key("vsync"):
        vsync = ks["xconfig"]["vsync"] # overwrite with user supplied value
    if ks["xconfig"].has_key("resolution"):
        resolution = ks["xconfig"]["resolution"]
    if ks["xconfig"].has_key("depth"):
        depth = ks["xconfig"]["depth"]


    if (installation.release == "RHEL" and installation.version < 4) or \
           (installation.release == "FC" and installation.version < 3.9):
        conf = "/etc/X11/XF86Config"
    else:
        conf = "/etc/X11/xorg.conf"

    _kbdvariant = _kbdoptions = ""
    if kbd_variant and len(kbd_variant) > 0:
        _kbdvariant = '        Option       "XkbVariant" "%s"\n' % kbd_variant
    if kbd_options and len(kbd_options) > 0:
        _kbdoptions = '        Option       "XkbOptions" "%s"\n' % kbd_options

    if (installation.release == "RHEL" and installation.version < 4) or \
           (installation.release == "FC" and installation.version < 2.9):
        mousedev = "/dev/mouse"
    else:
        mousedev = "/dev/input/mice"

    _hsync = _vsync = ""
    if hsync:
        _hsync = '        HorizSync    %s\n' % hsync
    if vsync:
        _vsync = '        VertRefresh  %s\n' % vsync

    _videoram = ""
    if videoram:
        _videoram = '        VideoRam     %s\n' % videoram
    _options = ""
    if len(options) > 0:
        for option in options:
            _options += '        %s\n' % option

    content = [ 'Section "ServerLayout"\n',
                '        Identifier   "Default Layout"\n',
                '        Screen       0 "Screen0" 0 0\n',
                '        InputDevice  "Mouse0" "CorePointer"\n',
                '        InputDevice  "Keyboard0" "CoreKeyboard"\n',
                'EndSection\n\n',
                'Section "Files"\n',
                '        FontPath     "unix/:7100"\n',
                'EndSection\n\n',
                'Section "Module"\n',
                '        Load         "dbe"\n',
                '        Load         "extmod"\n',
                '        Load         "fbdevhw"\n',
                '        Load         "record"\n',
                '        Load         "freetype"\n',
                '        Load         "type1"\n',
                '        Load         "glx"\n',
                '        Load         "dri"\n',
                'EndSection\n\n',
                'Section "InputDevice"\n',
                '        Identifier   "Keyboard0"\n',
                '        Driver       "kbd"\n',
                '        Option       "XkbModel" "%s"\n' % kbd_model,
                '        Option       "XkbLayout" "%s"\n' % kbd_layout,
                _kbdvariant,
                _kbdoptions,
                'EndSection\n\n',
                'Section "InputDevice"\n',
                '        Identifier   "Mouse0"\n',
                '        Driver       "mouse"\n',
                '        Option       "Protocol" "IMPS/2"\n',
                '        Option       "Device" "%s"\n' % mousedev,
                '        Option       "ZAxisMapping" "4 5"\n',
                '        Option       "Emulate3Buttons" "no"\n',
                'EndSection\n\n',
                'Section "Monitor"\n',
                '        Identifier   "Monitor0"\n',
                '        VendorName   "Monitor Vendor"\n',
                '        ModelName    "%s"\n' % monitor,
                _hsync,
                _vsync,
                '        Option       "dpms"\n',
                'EndSection\n\n',
                'Section "Device"\n',
                '        Identifier   "Videocard0"\n',
                '        VendorName   "Videocard vendor"\n',
                '        BoardName    "%s"\n' % card,
                '        Driver       "%s"\n' % driver,
                _videoram,
                _options,
                'EndSection\n\n',
                'Section "Screen"\n',
                '        Identifier   "Screen0"\n',
                '        Device       "Videocard0"\n',
                '        Monitor      "Monitor0"\n',
                '        DefaultDepth %s\n' % depth,
                '        SubSection "Display"\n',
                '                Viewport 0 0\n',
                '                Depth    %s\n' % depth,
                '                Modes    "%s"\n' % resolution,
                '        EndSubSection\n',
                'EndSection\n\n' ]
    if (installation.release == "RHEL" and installation.version < 4) or \
           (installation.release == "FC" and installation.version < 2.9):
        content.extend( ['Section "DRI"\n',
                         '        Group        0\n',
                         '        Mode         0666\n',
                         'EndSection\n' ] )
    create_file(buildroot, conf, content)
