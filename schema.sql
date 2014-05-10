CREATE TABLE packages(
    id INTEGER PRIMARY KEY,
    name TEXT
    );

CREATE TABLE releases(
    id INTEGER PRIMARY KEY,
    name TEXT
    );

CREATE TABLE locales(
    id INTEGER PRIMARY KEY,
    name TEXT
    );

CREATE TABLE sections(
    id INTEGER PRIMARY KEY,
    section TEXT
    );

CREATE TABLE manpages(
    id INTEGER PRIMARY KEY,
    release INTEGER REFERENCES releases(id),
    section INTEGER REFERENCES sections(id),
    package INTEGER REFERENCES packages(id),
    name TEXT NOT NULL,
    locale INTEGER REFERENCES locales(id),
    path TEXT NOT NULL, -- can be a .deb or a troff file
    version TEXT NOT NULL,
    UNIQUE (release, section, package, name, locale)
    );

CREATE VIRTUAL TABLE aproposes USING fts4(apropos, tokenize=unicode61);

CREATE TABLE symlinks(
    link_release INTEGER REFERENCES releases(id),
    link_section INTEGER REFERENCES sections(id),
    link_name TEXT NOT NULL,
    link_locale INTEGER REFERENCES locales(id),

    target_release INTEGER REFERENCES releases(id),
    target_section INTEGER REFERENCES sections(id),
    target_name TEXT NOT NULL,
    target_locale INTEGER REFERENCES locales(id)
    );

-- used for the day-to-day querying
CREATE INDEX manpages_release_section_name ON manpages (release, section, name);
