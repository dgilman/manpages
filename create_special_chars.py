# use this to create special_chars.py
# run it as cat uniglyph_*.cpp | python create_special_chars.py > special_chars.py

# note that uniglyph.cpp is from the groff source code and is licensed under
# gpl3 or later.  you can find the file at src/libs/libgroff/uniglyph.cpp

# if you update this file, change the name to reflect the git commit ID of
# the new version of uniglyph.cpp

# for more information on what this is about, see man 7 groff_char


import re
import sys

#MATCHER = re.compile('\s+[\][[](..)[]]\s+.*?u(\S+) .*$')
#MATCHER = re.compile(r'^\s+.\s+\\[[](..)[]]\s+\S+\s+u(\S+?)\s+')

MATCHER = re.compile(r'^.*[{] "(.*?)", "(.*?)" [}],.*$')

def main():
    print('# this file is licensed under the gplv3 or later, '
        'see the licence for uniglyph.cpp')
    print()
    print('# this file created with create_special_chars.py')
    print('# do not edit it manually')
    print('# recreate it with:')
    print('# $ cat uniglyph_*.cpp | python create_special_chars.py > '
        'special_chars.py')
    print('chars = {')
    # these are special chars sometimes emitted, see
    # DESCRIPTION in groff_char(7)
    # `\\', `\´', `\`', `\-', `\.', and `\e'
    print("'\\\\\\\\': '\\\\',")
    print("'\\\\´': '´',")
    print("'\\\\`': '`',")
    print("'\\\\-': '-',")
    print("'\\\\.': '.',")
    print("'\\\\e': '\\\\',")
    for line in sys.stdin:
        if line[0:2] == '//':
            continue
        match = MATCHER.search(line)
        if match:
            char_str = ''
            for char in match.groups()[0].split('_'):
                char_str += '\\u{0}'.format(char)
            escaped_code = match.groups()[1].replace("'", "\\'")
            output = "'{0}': '{1}',".format(escaped_code, char_str)
            print(output)
    print('}')

if __name__ == '__main__':
    main()
