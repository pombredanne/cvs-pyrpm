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

#################################### dicts ####################################

_grp_st_gl = 'grp:shift_toggle,grp_led:scroll'

keyboard_models = {
    'ar-azerty'           : ['us,ar(azerty)', 'pc105', '', _grp_st_gl],
    'ar-azerty-digits'    : ['us,ar(azerty_digits)', 'pc105', '', _grp_st_gl],
    'ar-digits'           : ['us,ar(digits)', 'pc105', '', _grp_st_gl],
    'ar-qwerty'           : ['us,ar(qwerty)', 'pc105', '', _grp_st_gl],
    'ar-qwerty-digits'    : ['us,ar(qwerty_digits)', 'pc105', '', _grp_st_gl],
    'be-latin1'           : ['be', 'pc105', '', ''],
    'ben'                 : ['us,ben', 'pc105', '', _grp_st_gl],
    'ben-probhat'         : ['us,ben(probhat)', 'pc105', '', _grp_st_gl],
    'bg'                  : ['us,bg', 'pc105', '', _grp_st_gl],
    'br-abnt2'            : ['br', 'abnt2', '', ''],
    'cf'                  : ['ca_enhanced', 'pc105', '', ''],
    'croat'               : ['hr', 'pc105', '', ''],
    'cz-lat2'             : ['cz_qwerty', 'pc105', '', ''],
    'cz-us-qwertz'        : ['us,cz', 'pc105', '', _grp_st_gl],
    'de'                  : ['de', 'pc105', '', ''],
    'de-latin1'           : ['de', 'pc105', '', ''],
    'de-latin1-nodeadkeys': ['de', 'pc105', 'nodeadkeys', ''],
    'dev'                 : ['us,dev', 'pc105', '', _grp_st_gl],
    'dk'                  : ['dk', 'pc105', '', ''],
    'dk-latin1'           : ['dk', 'pc105', '', ''],
    'dvorak'              : ['dvorak', 'pc105', '', ''],
    'es'                  : ['es', 'pc105', '', ''],
    'et'                  : ['ee', 'pc105', '', ''],
    'fi'                  : ['fi', 'pc105', '', ''],
    'fi-latin1'           : ['fi', 'pc105', '', ''],
    'fr'                  : ['fr', 'pc105', '', ''],
    'fr-latin1'           : ['fr', 'pc105', '', ''],
    'fr-latin9'           : ['fr-latin9', 'pc105', '', ''],
    'fr-pc'               : ['fr', 'pc105', '', ''],
    'fr_CH'               : ['fr_CH', 'pc105', '', ''],
    'fr_CH-latin1'        : ['fr_CH', 'pc105', '', ''],
    'gr'                  : ['us,el', 'pc105', '', _grp_st_gl],
    'guj'                 : ['us,guj', 'pc105', '', _grp_st_gl],
    'gur'                 : ['us,gur', 'pc105', '', _grp_st_gl],
    'hu'                  : ['hu', 'pc105', '', ''],
    'hu101'               : ['hu_qwerty', 'pc105', '', ''],
    'is-latin1'           : ['is', 'pc105', '', ''],
    'it'                  : ['it', 'pc105', '', ''],
    'it-ibm'              : ['it', 'pc105', '', ''],
    'it2'                 : ['it', 'pc105', '', ''],
    'jp106'               : ['jp', 'jp106', '', ''],
    'la-latin1'           : ['la', 'pc105', '', ''],
    'mk-utf'              : ['us,mk', 'pc105', '', _grp_st_gl],
    'nl'                  : ['nl', 'pc105', '', ''],
    'no'                  : ['no', 'pc105', '', ''],
    'pl'                  : ['pl', 'pc105', '', ''],
    'pt-latin1'           : ['pt', 'pc105', '', ''],
    'ro_win'              : ['ro', 'pc105', '', ''],
    'ru'                  : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru-cp1251'           : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru-ms'               : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru.map.utf8ru'       : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru1'                 : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru2'                 : ['us,ru', 'pc105', '', _grp_st_gl],
    'ru_win'              : ['us,ru', 'pc105', '', _grp_st_gl],
    'sg'                  : ['de_CH', 'pc105', '', ''],
    'sg-latin1'           : ['de_CH', 'pc105', '', ''],
    'sk-qwerty'           : ['sk_qwerty', 'pc105', '', ''],
    'slovene'             : ['si', 'pc105', '', ''],
    'sv-latin1'           : ['se', 'pc105', '', ''],
    'tml-inscript'        : ['us,tml(INSCRIPT)', 'pc105', '', _grp_st_gl],
    'tml-uni'             : ['us,tml(UNI)', 'pc105', '', _grp_st_gl],
    'trq'                 : ['tr', 'pc105', '', ''],
    'ua-utf'              : ['us,ua', 'pc105', '', _grp_st_gl],
    'uk'                  : ['gb', 'pc105', '', ''],
    'us'                  : ['us', 'pc105', '', ''],
    'us-acentos'          : ['us_intl', 'pc105', '', ''],
    }

# vim:ts=4:sw=4:showmatch:expandtab
