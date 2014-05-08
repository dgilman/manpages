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
from cache import get_path

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

# this maps countries to the encodings that they use
# it is highly probable that there will be duplicates, but we do want to
# preserve the ordering from the SUPPORTED file so we use a list
encodings = {'DEFAULT_LOCALE': set(('',))}
# add the special cases from above
for lang in langs:
    if lang[0] not in encodings:
        encodings[lang[0]] = []
    encodings[lang[0]].append(lang[1])

with open('/usr/share/i18n/SUPPORTED') as fd:
    for line in fd:
        lang, encoding = line.strip().split(' ')
        # ignore the country (the US part of en_US)
        lang = lang.split('_')[0]
        langs.add((lang, encoding))

        if lang not in encodings:
            encodings[lang] = []
        encodings[lang].append(encoding)

        # see iso-8859-1 note above
        if encoding == 'ISO-8859-1':
            langs.add((lang, 'ISO8859-1'))
            encodings[lang].append('ISO8859-1')

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
    '(?P<manpage>.+)[.]'
    '(?P=section)(?P<extrasection>.*?)[.]gz$'.format(locale_re))

SIMPLE_MAN_REGEX = re.compile('/man(?!ual)(?P<section>[^/]+)/'
            '(?P<manpage>.+)[.](?!Debian)(?P<section2>[^.]+?)[.]gz$', flags=re.I)

APROPOS_REGEX = re.compile('^-: "(?P<page>.*?) - (?P<desc>.*)"$')

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

class AproposException(Exception): pass

def get_apropos(contents, manpage, locale):
    """
    contents: bytestring of a manpage (can be gzipped).
    manpage: name of the manpage you are looking for
    locale: not a real locale (en_US) but just a country code
    Will be fed into lexgrog to get apropos output.
    Raises AproposException if anything goes wrong."""
    # note - universal_newlines turns on encoding for both stdin
    # and stdout which is most definitely not what we want - most of our
    # stdins are going to be gzipped.
    # so, we need to decode stdout manually.
    # unfortunately, we don't know what the encoding is - manpages are
    # kept in folders with languages only. chardet is no help here because
    # it's probabilistic and these are short snips.  the only alternative
    # is to parse the SUPPORTED locales file and see every encoding that a
    # given lang uses and hope that decodes right
    apropos_popen = subprocess.Popen(('lexgrog', '-'),
        stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    stdout, stderr = apropos_popen.communicate(input=contents)
    orig = stdout

    if locale == 'DEFAULT_LOCALE':
        # hope this works
        try:
            stdout = stdout.decode()
        except:
            raise AproposException('Unable to decode in DEFAULT_LOCALE')
    elif locale in encodings:
        decoded = None
        for encoding in encodings[locale]:
            try:
                decoded = stdout.decode(encoding)
                break
            except:
                continue
        if decoded == None:
            # http://i.imgur.com/pekaDQI.gif
            import pdb; pdb.set_trace()
            raise AproposException("None of the country's encodings worked")
        stdout = decoded
    else:
        raise AproposException("I don't know anything about lang {0}"\
            .format(locale))

    for line in stdout.splitlines():
        match = APROPOS_REGEX.search(line)
        if not match:
            continue

        if match.group('page') == manpage:
            #logging.info((manpage, match.group('desc')))
            return match.group('desc')
    raise AproposException('Unable to find anything for page {0}'\
        .format(manpage))

def iter_package_contents(package_path):
    dpkg_deb_popen = subprocess.Popen(('dpkg-deb', '--fsys-tarfile',
        package_path), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tar_popen = subprocess.Popen(('tar', 'tf', '-'),
        stdin=dpkg_deb_popen.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, universal_newlines=True)
    dpkg_deb_popen.stdout.close() # allow for pushing a SIGPIPE upstream
    for line in tar_popen.stdout:
        yield line

def get_package_file(package_path, filename):
    dpkg_deb_popen = subprocess.Popen(('dpkg-deb', '--fsys-tarfile',
        package_path), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tar_popen = subprocess.Popen(('tar', '-Oxf', '-', filename),
        stdin=dpkg_deb_popen.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    dpkg_deb_popen.stdout.close() # allow for pushing a SIGPIPE upstream
    return tar_popen.communicate()[0]

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
    section_cache = DBCache(conn.cursor(), 'sections', 'section')
    for release, package in iter_packages():
        release_id = release_cache[release]
        package_id = package_cache[package['Package']]

        package_path = conf.MIRROR + '/' + package['Filename']
        if not os.path.exists(package_path):
            logging.error('File not found for package {0} ({1})'\
                .format(package['Package'], package['Filename']))
            continue

        for line in iter_package_contents(package_path):
            match = MAN_REGEX.search(line)
            simple_match = SIMPLE_MAN_REGEX.search(line)
            if simple_match and not match:
                logging.info('Simple regex matched line but fancy didn\'t: '
                    '{0}'.format(line))
            if not match:
                continue

            section = match.group('section') + \
                match.group('extrasection')
            section_id = section_cache[section]

            name = match.group('manpage')
            if '/' in name:
                logging.error('Invalid manpage name in package {0}.'\
                    .format(package['Package']))
                continue

            if match.group('locale'):
                # strip leading /
                locale = match.group('locale')[1:]
            else:
                locale = 'DEFAULT_LOCALE'
            locale_id = locale_cache[locale]

            contents = get_package_file(package_path, line.strip())
            if len(contents) == 0:
                logging.error('Didn\'t find {0} in {1}'.format(line.strip(),
                    package_path))
                continue

            try:
                apropos = get_apropos(contents, name, locale)
            except AproposException as e:
                #logging.info('Apropos error {0} for {1} ({2})'\
                #    .format(e.args, package['Package'], line.strip()))
                apropos = None

            if conf.COPY_MANPAGES:
                # cache the troff file and save its path
                cache_dir = get_path(release, package['Package'],
                    package['Version'], locale, section)
                path = cache_dir + '/' + name + '.gz'
                with open(path, 'wb') as fd:
                    fd.write(contents)
            else:
                # save the deb
                path = package['Filename']
            try:
                c.execute('INSERT INTO manpages '
                    '(id, release, section, package, name, path, version, '
                    'locale) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)',
                    (release_id, section_id, package_id, name, path,
                    package['Version'], locale_id))
                manpage_id = c.lastrowid
            except sqlite3.IntegrityError as e:
                logging.error('Duplicate primary key: '
                    '(release: {0}, section: {1}, package: {2}, '
                    'name: {3}, locale: {4})'.format(release, section_id,
                    package['Package'], name, locale))
                continue

            c.execute('INSERT INTO aproposes (docid, apropos) VALUES (?, ?)',
                (manpage_id, apropos))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    import cProfile
    prof = cProfile.Profile()
    prof.enable()

    main()

    prof.disable()
    prof.dump_stats('profile.stats')
