import os

import scrape_manuals_conf as conf

def get_path(release, package, version, locale, section):
    cache_dir = conf.CACHE_DIR + '/' + '/'.join((release, package, version,
        locale, section))

    try:
        os.makedirs(cache_dir)
    except OSError:
        pass

    return cache_dir
