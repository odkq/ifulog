#!/usr/bin/env python
"""
I Fink U Logging (ifulog for short) is a simple and flexible
live log analyzer

Copyright (C) 2013 Pablo Martin <pablo.martin@acm.org>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import sys
import time
import shlex
import curses
import optparse
import datetime

IFULOG_VERSION = "0.1.0"

class CrazyParser:
    ''' Crazy LR parser over the crazy lexer shlex '''
    def __init__(self, path, rules):
        s = open(path).read()
        tokens = shlex.split(s, comments=True)
        self.tree = self.parse(tokens, rules, rules)

    def parse(self, toks, rules, prules, keyword=None):
        r = {}
        base = -1
        if 'argc' in rules:  # Terminal symbols to the right
            if len(toks) != rules['argc']:
                raise Exception('Wrong number of arguments -- ' +
                    str(len(toks)) + ' -- for keyword \'' + str(keyword) +
                    '\' expected ' + str(rules['argc']))
            if 'type' in rules:
                if not rules['type'] in prules['types']:
                    raise Exception('Mentioned type ' + rules['type'] +
                        ' non existant in rules')
                try:
                    type_enum = prules['types'][rules['type']]
                except KeyError:
                    raise Exception('Mentioned type ' + rules['type'] +
                        ' non existant in rules')
                ret = []
                for token in toks:
                    try:
                        ret.append(type_enum[token])
                    except KeyError:
                        raise Exception('Unknown value ' + token +
                        ' for type ' + rules['type'])
                return ret
            else:
                return toks
        toks.append('last')
        for i in range(len(toks)):  # Delimite substrings by tokens and parse
            if toks[i] in rules or toks[i] == 'last':
                if base == -1:
                    base = i
                    continue
                r[toks[base]] = self.parse(toks[base + 1:i],
                        rules[toks[base]], prules, toks[base])
                base = i
        return r

    def __getitem__(self, item):
        return self.tree[item]

    def __str__(self):
        return str(self.tree)


configuration_parser_rules = {
    'colors': {
        'first': {'argc': 2, 'type': 'color_enum'},
        'sub': {'argc': 2, 'type': 'color_enum'},
        'subsub': {'argc': 2, 'type': 'color_enum'}},
    'refresh': {
        'key': {'argc': 1},
        'display': {'argc': 1}},
    'types': {
        'color_enum': {'black': 0, 'red': 1, 'green': 2,
                       'yellow': 3, 'blue': 4, 'magenta': 5,
                       'cyan': 6, 'white': 7}}}


profile_parser_rules = {
    'delimiter': {'argc': 1},
    'condition': {
        'ocurrences': '*',      # Setup as an array of repetitions
        'nfields': {'argc': 1},
        'field': {'argc': 2}},
    'key': {'argc': 2},
    'dateformat': {'argc': 1},
    'show': {
        'first': {'argc': 3},
        'sub': {'argc': 3},
        'subsub': {'argc': 3}}}


class Display:
    def __init__(self, stdscr, config):
        self.width = 25
        self.s = stdscr
        self.config = config
        self.attrib_to_number = {'first': 1, 'sub': 2, 'subsub': 3}
        self.attrib_title = curses.A_STANDOUT
        if curses.has_colors():
            for name in self.attrib_to_number:
                number = self.attrib_to_number[name]
                curses.init_pair(number, config['colors'][name][0],
                    config['colors'][name][1])
        else:
            raise Exception('Use a color terminal for now' +
                    '(export TERM=xterm-color?)')

    def refresh(self, stats):
        self.y = 0
        self.x = 0
        # self.s.clear()
        title = 'I Fink U Logging ' + IFULOG_VERSION + \
            str(stats['processed']).rjust(12, ' ') \
            + ' lines processed ' + str(stats['count']).rjust(9, ' ') + \
            ' unique keys'
        if stats['filter']:
            title += ' from '
            title += str(len(stats['filter']))
        self.my, self.mx = self.s.getmaxyx()
        status = ' '
        if stats['count'] > 0:
            status = ' ' + stats['date'].strftime('%Y-%m-%d %H:%M:%S') + ' '
        self.s.addstr(self.y, 0, title + (' ' * (self.mx - len(title))),
            self.attrib_title)
        self.y = 2
        self.s.addstr(self.my - 1, 0, status + (' ' *
            (self.mx - len(status) - 1)), self.attrib_title)
        self.paint(stats)
        self.s.refresh()

    def paint(self, stats):
        for x in range(self.mx):
            self.s.addch(1, x, curses.ACS_HLINE)
        for k in stats['first']:
            s = k.ljust(12, ' ') + ' ' + \
                str(stats['first'][k]['count']).rjust(7, ' ')
            # s = k + ' ' + str(stats['first'][k]['count'])
            #    v['count'].rjust(7, ' ')
            self.putline(2, s, 'first')
            if 'sub' in stats['first'][k]:
            #    mark
                for k in stats['first'][k]['sub']:
                    s = k.ljust(12, ' ') + ' ' + \
                            str(stats['first'][k]['count']).rjust(7, ' ')
        for x in range(self.mx):
            self.s.addch(self.my - 2, x, curses.ACS_HLINE)

    def putline(self, indent, string, attrib):
        self.s.addstr(self.y, self.x, ' ' * self.width)
        self.s.addch(self.y, self.x, curses.ACS_VLINE)
        a = curses.color_pair(self.attrib_to_number[attrib])
        self.s.addstr(self.y, self.x + indent, string, a)
        self.y += 1
        if self.y >= (self.my - 3):
            self.x += self.width
            self.y = 2


class Stats:
    def __init__(self, profile):
        self.profile = profile
        self.data = {'keys': {}, 'count': 0, 'processed': 0, 'filter': None,
            'first': {}}
        self.delimiter = self.profile['delimiter'][0]

        self.keyeval = self.profile['key'][1]
        # ['first', 'sub', 'subsub']
        self.first_op = self.profile['show']['first'][0]
        self.firsteval = self.profile['show']['first'][1]
        self.first_name = self.profile['show']['first'][2]

    def process(self, line):
        ls = line.split(self.delimiter)
        try:
            key = eval(self.keyeval)
            first_value = eval(self.firsteval)
            date = eval(self.profile['dateformat'][0])
            self.data['date'] = date
            # Store start_date with the first line for the stats set
            if self.data['count'] == '0':
                self.startdate = date
            if self.insert_update(self.data['keys'], self.data['first'],
                                    self.first_op, key, first_value):
                self.data['count'] += 1
            if self.first_op == 'distinct':
                distinct = len(self.data['keys'][key])
                if distinct > int(self.first_name):
                    # FIXME: Bad name for something both name
                    # and threshold
                    self.update_result(self.data['first'], key,
                                  distinct)
            # Check for the end of the set (increment from start_date is
            # met)
            # XXX
        except IndexError:
            return
        self.data['processed'] += 1


    def add_result(self, r, first_value):
        # Only used in group aggregation, to either store
        # a new first or update it's count
        if not first_value in r:
            r[first_value] = {'count': 1}
        else:
            r[first_value]['count'] += 1

    def del_result(self, r, old_first):
        # Inversely remove one from the count when in group
        if not old_first in r:
            raise Exception('asked for del_result something that' +
                            ' was xnever here')
        r[old_first]['count'] -= 1
        if r[old_first]['count'] == 0:
            del r[old_first]

    def update_result(self, r, value, distinct):
        # update a distinct count using the absolute computed value
        if not value in r:
            r[value] = {'count': distinct}
        else:
            r[value]['count'] = distinct

    def insert_update(self, d, r, op, key, first_value):
        new = False
        if not key in d:
            if op == 'group':
                d[key] = {'first': first_value}
                self.add_result(r, first_value)
            elif op == 'distinct':
                d[key] = {'first': {first_value: 1}}
            new = True
        if op == 'group':
            if d[key]['first'] != first_value:
                self.add_result(r, first_value)
                self.del_result(r, d[key]['first'])
                d[key]['first'] = first_value
        elif op == 'distinct':
            if not first_value in d[key]:
                d[key][first_value] = 1
            else:
                d[key][first_value] += 1
        return new

    def __getitem__(self, item):
        return self.data[item]


def curses_main(stdscr, config, profile):
    display = Display(stdscr, config)
    last = 0.0
    stats = Stats(profile)

    while True:
        line = sys.stdin.readline()
        now = time.time()
        if now - last >= float(config['refresh']['display'][0]):
            display.refresh(stats)
            last = now
        if line == '':
            break
        line = line[:-1]
        stats.process(line)
    time.sleep(100)

if __name__ == '__main__':
    usage = 'Usage: ifulog.py [options] PROFILE'
    optp = optparse.OptionParser(usage=usage)
    optp.add_option("-c", "--check", dest="check",
        help="check configuration and profile syntax", action="store_true",
        default=False)
    optp.add_option("-f", "--config", dest="config",
        help="alternate configuration file", default='ifulog.conf')
    opts, args = optp.parse_args()
    config = CrazyParser(opts.config, configuration_parser_rules)
    if len(args) < 1:
        print 'ERROR: please specify a valid profile'
        exit(1)
    profile = CrazyParser(args[0], profile_parser_rules)
    if opts.check:
        print 'config -> ' + str(config)
        print 'profile -> ' + str(profile)
    else:
        curses.wrapper(curses_main, config, profile)
