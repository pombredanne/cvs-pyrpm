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

class Cards:
    def __init__(self, buildroot):
        self.cards = { }
        try:
            fd = open(buildroot+'/usr/share/hwdata/Cards')
        except:
            raise IOError, "Could not load '%s/usr/share/hwdata/Cards'." % \
                  buildroot

        dict = None
        card = None
        while 1:
            line = fd.readline()
            if not line:
                break
            line = line.strip()
            if len(line) < 1 or line[0] == "#":
                continue

            if line[:4] == "NAME":
                if dict and len(dict) > 0 and card:
                    self.cards[card] = dict
                dict = { }
                card = line[4:].strip()
            elif line[:6] == "DRIVER":
                dict["driver"] = line[6:].strip()
            elif line[:7] == "CHIPSET":
                dict["chipset"] = line[7:].strip()
            elif line[:6] == "SERVER":
                dict["server"] = line[6:].strip()
            elif line[:6] == "RAMDAC":
                dict["ramdac"] = line[6:].strip()
            elif line[:8] == "DACSPEED":
                dict["dacspeed"] = line[9:].strip()
            elif line[:9] == "CLOCKCHIP":
                dict["clockchip"] = line[9:].strip()
            elif line == "NOCLOCKPROBE":
                dict["noclockprobe"] = 1
            elif line[:4] == "LINE":
                dict.setdefault("options", [ ]).append(line[4:].strip())
            elif line[:3] == "SEE":
                dict.setdefault("ref", [ ]).append(line[3:].strip())
            elif line == "END":
                continue
            else:
                print "Unknown entry '%s'"% line
        fd.close()

    def _get(self, card, dict, cards):
        if card in cards:
            return
        if self.cards.has_key(card):
            cards.append(card)
            for key in self.cards[card].keys():
                if key == "ref":
                    continue
                if key == "options":
                    if not dict.has_key(key):
                        dict[key] = [ ]
                    for value in self.cards[card][key]:
                        if not value in dict[key]:
                            dict[key].append(value)
                else:
                    if dict.has_key(key):
                        continue
                    dict[key] = self.cards[card][key]
            if self.cards[card].has_key("ref"):
                for _card in self.cards[card]["ref"]:
                    self._get(_card, dict, cards)

    def get(self, card):
        dict = { }
        cards = [ ]
        self._get(card, dict, cards)
        if len(cards) == 0:
            return None
        return dict

class Monitors:
    def __init__(self, buildroot):
        self.monitors = { }
        try:
            fd = open(buildroot+'/usr/share/hwdata/MonitorsDB')
        except:
            raise IOError, \
                  "Could not load '%s/usr/share/hwdata/MonitorsDB'." % \
                  buildroot

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
            if xargs[1].strip() in self.monitors:
                continue
            key = xargs[1].strip()
            self.monitors[key] = { }
            self.monitors[key]["vendor"] = xargs[0].strip()
            self.monitors[key]["eisa_id"] = xargs[2].strip()
            self.monitors[key]["hsync"] = xargs[3].strip()
            self.monitors[key]["vsync"] = xargs[4].strip()
            self.monitors[key]["dpms"] = 0
            if len(xargs) == 6:
                self.monitors[key]["dpms"] = xargs[5].strip()
        fd.close()

    def get(self, monitor):
        if not self.monitors.has_key(monitor):
            return None
        return self.monitors[monitor]
