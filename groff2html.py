import re
import io

from special_chars import chars as special_chars

class GroffException(Exception): pass
class TokenizingError(GroffException): pass
class ParseError(GroffException): pass

# see the groff manual section 8.1 "gtroff output" for reference on
# the output of gtroff/ditroff.

# in a nutshell, you have single char commands followed by optional
# whitespace and arguments.  commands that feature subcommands (drawing,
# device control) get joined up in this code to form the two letter commands.

# the tokenizer has two states, CMD (looking for a command) and ARG
# (reading args).  for the most part I've only implemented the bare
# minimum needed to read manpages.

# the validator function in arg_types is pretty primitive, i didn't need
# anything fancier for the manpage subset that I was looking at.  if you
# need to extend the tokenizer it shouldn't be hard to replace it with a
# callable like validate(cmd, arg_list) that returns the arg list.  give
# it an attribute 'done' so that you can throw exceptions if you try and yield
# a token before all the required args have been validated.

# writing a ditroff parser/groff backend is the 'right' way to do this,
# unfortunately it seems that the pain of these ancient formats has scared
# everyone off.  generally people interested in troff toolchains seem to be
# screen scraping/regexing the output(w3mman, man.cgi, plenty others I'm sure)
# or just re-purposing grohtml (which produces dated markup and is
# inflexible).  sorry kerninghan, i don't think this one was a winner

CHAR_AND_SPACES = re.compile('\S\s*', flags=re.ASCII)
WORD = re.compile('\S+', flags=re.ASCII)
WORD_AND_SPACES = re.compile('\S+\s*', flags=re.ASCII)
LINE = re.compile('.*?\n', flags=re.DOTALL)

CMD = 0
ARG = 1

arg_types = {
    'C': (str, 1),
    'c': (str, 1),
    'f': (int, 1),
    'H': (int, 1),
    'h': (int, 1),
    'N': (int, 1),
    'p': (int, 1),
    's': (int, 1),
    'n': (int, 2),
    'mc': (int, 3),
    'mg': (int, 1),
    'mk': (int, 4),
    'mr': (int, 3),
    # the spec allows for a two argument t where the last one is a dummy value
    # we can't handle that now and we can't thrown an exc either :(
    't': (str, 1),
    'v': (int, 1),
    'V': (int, 1),
    'u': (str, 2),
# device control args
    'xF': (str, 1),
    'xf': (str, 2),
    'xH': (int, 1),
    'xi': (None, 0),
    'xp': (None, 0),
    'xr': (int, 3),
    'xS': (int, 1),
    'xs': (None, 0),
    'xt': (None, 0),
    'xT': (str, 1),
    'xu': (int, 1),
    'xX': (str, 0) # short-circuit and skip this one
}

def tokenizer(fd, encoding=None):
    fd = io.TextIOWrapper(fd, encoding=encoding)

    # two states - looking for a new command (CMD) or looking for args (ARG)

    buf = ''
    state = CMD
    cmd = None
    args = []
    grow = True
    while True:
        if grow or len(buf) < 50:
            buf += fd.read(50)
            grow = False
        if len(buf) == 0:
            break
        #print(buf.split('\n')[0])

        if state == CMD:
            # comment
            if buf[0] == '#':
                end = buf.find('\n')
                if not end:
                    grow = True
                    continue
                else:
                    buf = buf[end+1:]

            if buf[0] in ('C', 'c', 'f', 'H', 'h', 'N', 'p', 's', 'n',
                    't', 'V', 'v', 'u', 'x'):
                end = CHAR_AND_SPACES.match(buf)
                if not end:
                    grow = True
                    continue
                cmd = buf[0]
                buf = buf[end.end():]
                state = ARG
            elif buf[0] == 'm':
                if buf[1] == 'c':
                    cmd = 'mc'
                    state = ARG
                elif buf[1] == 'd':
                    yield 'md', []
                    cmd = ''
                elif buf[1] == 'g':
                    cmd = 'mg'
                    state = ARG
                elif buf[1] == 'k':
                    cmd = 'mk'
                    state = ARG
                elif buf[1] == 'r':
                    cmd = 'mr'
                    state = ARG
                else:
                    raise TokenizingError('Unsupported color type')
                end = WORD_AND_SPACES.match(buf)
                if not end:
                    grow = True
                    continue
                buf = buf[end.end():]
            elif buf[0] == 'w':
                yield 'w', []
                cmd = ''
                buf = buf[1:]
            elif buf[0] == 'D':
                if buf[0:3] == 'DFd':
                    yield 'DFd', []
                    cmd = ''
                    buf = buf[4:]
                else:
                    raise TokenizingError('Drawing command {0} not '
                        'implemented yet'.format(buf[0:2]))
            else:
                raise TokenizingError('Unknown cmd {0}'.format(buf[0]))

        if state == ARG:
            end = WORD.match(buf)
            if not end:
                grow = True
                continue
            # tokens that take a set number of args
            if cmd in arg_types:
                validator, count = arg_types[cmd]
                if validator:
                    try:
                        args.append(validator(buf[:end.end()]))
                    except ValueError:
                        raise TokenizingError('Command {0} takes an integer as '
                            'its argument'.format(cmd))
                if len(args) == count:
                    state = CMD
            # device control commands
            elif cmd == 'x':
                cmd += buf[0]
                if cmd in arg_types and arg_types[cmd][1] == 0:
                    state = CMD
            else:
                raise TokenizingError('Argument type not implemented yet '
                    'for cmd {0}'.format(cmd))

            end = WORD_AND_SPACES.match(buf)
            if not end:
                grow = True
                continue
            buf = buf[end.end():]

            # this is supposed to be a literal down to the
            # driver anyway
            if cmd == 'xX':
                end = LINE.match(buf)
                args.append(buf[:end.end()])
                buf = buf[end.end():]

            if state == CMD:
                yield cmd, args
                cmd = ''
                args = []

LINK_FONT = 0
BOLD_FONT = 1
UNDERLINE_FONT = 2

device_font_map = {
    ('1', 'R'): LINK_FONT,
    ('3', 'B'): BOLD_FONT,
    ('2', 'I'): UNDERLINE_FONT
}

class Output(object):
    def __init__(self, fd):
        self.fd = fd
        self.initial_typesetter = None
        self.resolution = None
        self.horiz_motion = None
        self.vert_motion = None
        self.page = None
        self.device_font = None
        self.font = None
        self.font_size = None
        self.horizontal_increment = 0
        self.line = 0
        self.reset_column = False

    def __iter__(self):
        for cmd, args in tokenizer(fd):
            if cmd == 't':
                self.horizontal_increment = 0
                yield args[0]
                #if args[0] == 'output.':
                #    import pdb; pdb.set_trace()
            elif cmd == 'h' or cmd == 'H':
                if args[0] % self.horiz_motion != 0:
                    raise ParseError('can only move multiples of horiz_motion')
                # we can't actually seek backwards, but not outputting any more
                # spaces does the trick
                if self.reset_column:
                    self.reset_column = False
                    continue
                yield ' '*((args[0] // self.horiz_motion) - self.horizontal_increment)
            elif cmd == 'n':
                continue
            elif cmd == 'N':
                self.horizontal_increment = 1
                if args[0] > 32 and args[0] < 127:
                    yield chr(args[0])
                elif args[0] > 160 and args[0] < 256:
                    yield bytes((args[0],)).decode('ISO-8859-1')
                else:
                    raise ParseError('N this big is not supported yet')
            elif cmd == 'C':
                if args[0] not in special_chars:
                    raise ParseError('Character {0} not supported for C yet'\
                        .format(args[0]))
                self.horizontal_increment = len(special_chars[args[0]])
                yield special_chars[args[0]]
            elif cmd == 'xT':
                if not self.initial_typesetter:
                    if args[0] != 'utf8':
                        raise ParseError('Only the utf8 device is supported')
                    self.initial_typesetter = args[0]
                else:
                    raise ParseError('Can\'t set the device twice')
            elif cmd == 'xr':
                if not self.resolution:
                    self.resolution = args[0]
                    self.horiz_motion = args[1]
                    self.vert_motion = args[2]
                    self.line = self.vert_motion
                else:
                    raise ParseError('Can\'t set the resolution twice')
            elif cmd == 'xi':
                continue
            elif cmd == 'xF':
                continue
            elif cmd == 'p':
                self.page = args[0]
                self.line = 0
            # fonts are primarily how we identify subsections
            elif cmd == 'xf':
                if (args[0], args[1]) not in device_font_map:
                    raise ParseError('We don\'t support that device font yet')
                self.device_font = device_font_map[(args[0], args[1])]
                # and maybe print stuff, probably
            elif cmd == 'f':
                self.font = args[0]
                # and maybe print stuff
            elif cmd == 's':
                if self.font_size and self.font_size != args[0]:
                    raise ParseError('switching font size not yet supported')
                self.font_size = args[0]
            elif cmd == 'V':
                if args[0] % self.vert_motion != 0:
                    raise ParseError('can only move multiples of vert_motion')
                yield '\n'*((args[0] // self.vert_motion) -
                    (self.line // self.vert_motion))
                #if args[0] == 2640 and yval != '\n':
                #    import pdb; pdb.set_trace()
                self.line = args[0]
                #yield yval
            elif cmd == 'H':
                continue
            elif cmd == 'md':
                continue
            elif cmd == 'DFd':
                continue
            elif cmd == 'xX':
                if args[0] == 'devtag:.col 1\n':
                    self.reset_column = True
                continue
            elif cmd == 'w':
                continue
            elif cmd == 'xt':
                continue
            elif cmd == 'xs':
                return
            else:
                raise Exception(cmd)

class Outputter():
    def __init__(self, fd):
        self.fd = fd

    def __iter__(self):
        for cmd, args in tokenizer(fd):
            if hasattr(self, cmd):
                yield getattr(self, cmd)(args)
            else:
                raise NotImplemented(cmd)

class TextOutput(Outputter):
    def __init__(self, fd):
        self.initial_typesetter = None
        self.resolution = None
        self.horiz_motion = None
        self.vert_motion = None
        self.page = None
        self.device_font = None
        self.font = None
        self.font_size = None
        self.horizontal_increment = 0
        self.line = 0
        self.reset_column = False

    def t(self, args):
        self.horizontal_increment = 0
        return args[0]

    def h(self, args):
        if args[0] % self.horiz_motion != 0:
            raise ParseError('can only move multiples of horiz_motion')
        # we can't actually seek backwards, but not outputting any more
        # spaces does the trick
        if self.reset_column:
            self.reset_column = False
            return ''
        return ' '*((args[0] // self.horiz_motion) - self.horizontal_increment)
    H = h

    def noop(self, args):
        return ''
    n = noop
    xi = noop
    xF = noop
    md = noop
    DFd = noop
    w = noop
    xt = noop

    def N(self, args):
        self.horizontal_increment = 1
        if args[0] > 32 and args[0] < 127:
            return chr(args[0])
        elif args[0] > 160 and args[0] < 256:
            return bytes((args[0],)).decode('ISO-8859-1')
        else:
            raise ParseError('N this big is not supported yet')

    def C(self, args):
        if args[0] not in special_chars:
            raise ParseError('Character {0} not supported for C yet'\
                .format(args[0]))
        self.horizontal_increment = len(special_chars[args[0]])
        return special_chars[args[0]]

    def xT(self, args):
        if not self.initial_typesetter:
            if args[0] != 'utf8':
                raise ParseError('Only the utf8 device is supported')
            self.initial_typesetter = args[0]
        else:
            raise ParseError('Can\'t set the device twice')
        return ''

    def xr(self, args):
        if not self.resolution:
            self.resolution = args[0]
            self.horiz_motion = args[1]
            self.vert_motion = args[2]
            self.line = self.vert_motion
        else:
            raise ParseError('Can\'t set the resolution twice')
        return ''

    def p(self, args):
        self.page = args[0]
        self.line = 0
        return ''

    def xf(self, args):
        if (args[0], args[1]) not in device_font_map:
            raise ParseError('We don\'t support that device font yet')
        self.device_font = device_font_map[(args[0], args[1])]
        return ''

    def f(self, args):
        self.font = args[0]
        return ''

    def s(self, args):
        if self.font_size and self.font_size != args[0]:
            raise ParseError('switching font size not yet supported')
        self.font_size = args[0]
        return ''

    def V(self, args):
        if args[0] % self.vert_motion != 0:
            raise ParseError('can only move multiples of vert_motion')
        prev_line = self.line
        self.line = args[0]
        return '\n'*((args[0] // self.vert_motion) -
            (prev_line // self.vert_motion))

    def xX(self, args):
        if args[0] in ('devtag:.col 1\n', 'devtag:.eo.h\n'):
            self.reset_column = True
        return ''

    def xs(self, args):
        raise StopIteration()


if __name__ == '__main__':
    import sys
    with open('wget_groff', 'rb') as fd:
        for x in TextOutput(fd):
            sys.stdout.write(x)
        #print(''.join([x for x in Output(fd)]))
        #for thing in Output(fd):
        #    print(thing)
