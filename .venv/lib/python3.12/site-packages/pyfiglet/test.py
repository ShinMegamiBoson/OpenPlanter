#!/usr/bin/env python

from __future__ import print_function
import os.path
import sys
from optparse import OptionParser
from pyfiglet import Figlet
from subprocess import Popen, PIPE
try:
    from colorama import init
    init(strip=not sys.stdout.isatty())
    from termcolor import cprint
except:
    def cprint(text, color):
        print(text)

__version__ = '0.1'

def fail(text):
    cprint(text, 'red')

def win(text):
    cprint(text, 'green')

def dump(text):
    for line in text.split('\n'):
        print(repr(line))

class Test(object):
    def __init__(self, opts):
        self.opts = opts
        self.ok = 0
        self.fail = 0
        self.failed = []
        self.oked = []
        # known bugs...
        self.skip = ['konto', 'konto_slant']

        self.f = Figlet()

    def outputUsingFigletorToilet(self, text, font, fontpath):
        if os.path.isfile(fontpath + '.flf'):
            cmd = ('figlet', '-d', 'pyfiglet/fonts', '-f', font, text)
        elif os.path.isfile(fontpath + '.tlf'):
            cmd = ('toilet', '-d', 'pyfiglet/fonts', '-f', font, text)
        else:
            raise Exception('Missing font file: {}'.format(fontpath))

        p = Popen(cmd, bufsize=4096, stdout=PIPE)
        try:
            outputFiglet = p.communicate()[0].decode('utf8')
        except UnicodeDecodeError as e:
            print("Unicode Error handling font {}".format(font))
            outputFiglet = ''
        return outputFiglet

    def validate_font_output(self, font, outputFiglet, outputPyfiglet):
        if outputPyfiglet == outputFiglet:
            win('[OK] %s' % font)
            self.ok += 1
            self.oked.append(font)
            return

        fail('[FAIL] %s' % font)
        self.fail += 1
        self.failed.append(font)
        self.show_result(outputFiglet, outputPyfiglet, font)

    def show_result(self, outputFiglet, outputPyfiglet, font):
        if self.opts.show is True:
            print('[PYTHON] *** %s\n\n' % font)
            dump(outputPyfiglet)
            print('[FIGLET] *** %s\n\n' % font)
            dump(outputFiglet)
            input()

    def check_font(self, text, font, use_tlf):
        # Skip flagged bad fonts
        if font in self.skip:
            return

        # Our TLF rendering isn't perfect, yet
        fontpath = os.path.join('pyfiglet', 'fonts', font)
        fig_file = os.path.isfile(fontpath + '.flf')
        if not use_tlf and not fig_file:
            return

        self.f.setFont(font=font)
        outputPyfiglet = self.f.renderText(text)
        outputFiglet = self.outputUsingFigletorToilet(text, font, fontpath)
        self.validate_font_output(font, outputFiglet, outputPyfiglet)


    def check_text(self, text, use_tlf):
        for font in self.f.getFonts():
            self.check_font(text, font, use_tlf)

    def check_result(self):
        print('OK = %d, FAIL = %d' % (self.ok, self.fail))
        if len(self.failed) > 0:
            print('FAILED = %s' % set(self.failed))

        return self.failed, self.oked

def banner(text):
    cprint(Figlet().renderText(text), "blue")

def main():
    parser = OptionParser(version=__version__)

    parser.add_option('-s', '--show', action='store_true', default=False,
                      help='pause at each failure and compare output '
                           '(default: %default)')

    opts, args = parser.parse_args()
    test = Test(opts)
    banner("TESTING one word")
    test.check_text("foo", True)
    banner("TESTING cut at space")
    test.check_text("This is a very long text with many spaces and little words", False)
    banner("TESTING cut at last char")
    test.check_text("Averylongwordthatwillbecutatsomepoint I hope", False)
    banner("TESTING explicit new line")
    test.check_text("line1\nline2", True)
    if len(test.check_result()[0]) == 0:
        return 0
    else:
        return 1


if __name__ == '__main__':
    sys.exit(main())
