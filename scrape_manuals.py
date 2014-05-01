import os
import bz2
import subprocess
import re
import sqlite3
import logging

logging.basicConfig(format='%(levelname)s:%(lineno)d:%(message)s',
    level=logging.INFO, filename='scraper.log')

from debian import deb822

import scrape_manuals_conf as conf

# set up some locale stuff

if not os.path.exists('/usr/share/i18n/SUPPORTED'):
    raise Exception('Can\'t find the file with localizations in it.')

# according to debian packaging standards, only the language code is
# allowed in the manpath.  currently portuguese and chinese have an exception
# so add them in manually
langs = set((('pt_BR', 'UTF-8'), ('pt_BR', 'ISO-8859-1'),
                # for unknown reasons, iso-8859-1 is sometimes called
                # iso8859-1 in the filename.  throw that in there too
                ('pt_BR', 'ISO8859-1'),
            ('pt_PT', 'UTF-8'), ('pt_PT', 'ISO-8859-1'),
                ('pt_PT', 'ISO8859-1'),
            ('zh_CN', 'UTF-8'), ('zh_CN', 'GB18030'), ('zh_CN', 'GBK'),
                ('zh_CN', 'GB2312'),
            ('zh_TW', 'UTF-8'), ('zh_TW', 'EUC-TW'), ('zh_TW', 'BIG5')))

with open('/usr/share/i18n/SUPPORTED') as fd:
    for line in fd:
        lang, encoding = line.strip().split(' ')
        # ignore the country (the US part of en_US)
        lang = lang.split('_')[0]
        langs.add((lang, encoding))
        # see iso-8859-1 note above
        if encoding == 'ISO-8859-1':
            langs.add((lang, 'ISO8859-1'))

# a lang folder can look like /lang.ENCODING/ or just /lang/
# so this is a regex that matches all possible localizations :)
# the trailing / is matched outside this group

# first, base langs.  this looks like en|jp|fr|...
locale_re = '|'.join(['/' + x[0] for x in langs])
locale_re += '|'

# langs + encodings
locale_re += '|'.join(['/' + x[0] + '.' + x[1] for x in langs])

# this lets us match the empty string, which is the case when there is no
# localization for the encoding
locale_re += '|'

# note that manpages sometimes look like
# man1/wc1posix.gz
# so there is an extra .*? before the [.]gz to account for this junk
MAN_REGEX = re.compile('(?P<locale>{0})/'
    'man(?P<section>[1-9])/'
    '(?P<manpage>.+)[.](?P=section).*?[.]gz$'.format(locale_re))

SIMPLE_MAN_REGEX = re.compile('/man(?!ual)(?P<section>[^/]+)/'
            '(?P<manpage>.+)[.](?!Debian)(?P<section2>[^.]+?)[.]gz$', flags=re.I)

release_cache = {}

class DBCache(object):
    # make sure that 'table' and 'column' are not
    # input from the user as they are not escaped!
    # but it shouldn't be a big problem
    def __init__(self, cursor, table, column):
        self.cache = {}
        self.c = cursor
        self.select = 'SELECT id FROM {0} WHERE {1} = ?'.format(table, column)
        self.insert = 'INSERT INTO {0} (id, {1}) ' \
            'VALUES (NULL, ?)'.format(table, column)

    def __getitem__(self, key):
        if key not in self.cache:
            self.c.execute(self.select, (key,))
            rval = self.c.fetchall()
            if rval:
                self.cache[key] = rval[0][0]
            else:
                self.c.execute(self.insert, (key,))
                self.cache[key] = self.c.lastrowid
        return self.cache[key]

def iter_packages():
    for release in conf.RELEASES:
        for packages_path in [conf.MIRROR + '/dists/' + release + '/' + \
            area + '/binary-' + conf.ARCH + '/Packages.bz2' \
            for area in conf.AREAS]:

            if not os.path.exists(packages_path):
                logging.error('Packages.bz2 file not found at {0}'\
                    .format(packages_path))
                continue

            with bz2.open(packages_path) as bz2fd:
                for package_obj in \
                    deb822.Packages.iter_paragraphs(sequence=bz2fd):
                    yield release, package_obj

def main():
    logging.info('Beginning cron job')
    conn = sqlite3.connect(conf.DSN)
    c = conn.cursor()

    release_cache = DBCache(conn.cursor(), 'releases', 'name')
    package_cache = DBCache(conn.cursor(), 'packages', 'name')
    locale_cache = DBCache(conn.cursor(), 'locales', 'name')
    for release, package in iter_packages():
        release_id = release_cache[release]
        package_id = package_cache[package['Package']]

        package_path = conf.MIRROR + '/' + package['Filename']
        if not os.path.exists(package_path):
            logging.error('File not found for package {0} ({1})'\
                .format(package['Package'], package['Filename']))
            continue

        dpkg_deb_popen = subprocess.Popen(('dpkg-deb', '--fsys-tarfile',
            package_path), stdout=subprocess.PIPE)
        tar_popen = subprocess.Popen(('tar', 'tf', '-'),
            stdin=dpkg_deb_popen.stdout, stdout=subprocess.PIPE)
        dpkg_deb_popen.stdout.close() # allow for pushing a SIGPIPE upstream
        for line in tar_popen.communicate()[0].decode().splitlines():
            matches = MAN_REGEX.search(line)
            simple_match = SIMPLE_MAN_REGEX.search(line)
            if simple_match and not matches:
                logging.info('Simple regex matched line but fancy didn\'t: '
                    '{0}'.format(line))
            if matches:
                section = int(matches.group('section'))
                name = matches.group('manpage')
                if matches.group('locale'):
                    # strip leading /
                    locale = matches.group('locale')[1:]
                else:
                    locale = 'DEFAULT_LOCALE'
                locale_id = locale_cache[locale]

                if conf.COPY_MANPAGES:
                    # cache the troff file and save its path
                    raise NotImplemented
                else:
                    # save the deb
                    path = package['Filename']
                try:
                    c.execute('INSERT INTO manpages '
                        '(release, section, package, name, path, version, '
                        'locale) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (release_id, section, package_id, name, path,
                        package['Version'], locale_id))
                except sqlite3.IntegrityError as e:
                    logging.error('Duplicate primary key: '
                        '(release: {0}, section: {1}, package: {2}, '
                        'name: {3}, locale: {4})'.format(release, section,
                        package['Package'], name, locale))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    import cProfile
    prof = cProfile.Profile()
    prof.enable()

    main()

    prof.disable()
    prof.dump_stats('profile.stats')
