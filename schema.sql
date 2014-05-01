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

CREATE TABLE manpages(
    release INTEGER REFERENCES releases(id),
    section INTEGER NOT NULL,
    package INTEGER REFERENCES packages(id),
    name TEXT NOT NULL,
    locale INTEGER REFERENCES locales(id),
    path TEXT NOT NULL, -- can be a .deb or a troff file
    version TEXT NOT NULL,
    PRIMARY KEY (release, section, package, name, locale)
    );

-- used for the day-to-day querying
CREATE INDEX manpages_release_section_name ON manpages (release, section, name);
