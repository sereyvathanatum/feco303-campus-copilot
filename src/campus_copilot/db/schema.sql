-- Campus database schema (docs/implementation-plan.md §8.5).
-- Every row is synthetic and produced by the deterministic seed in data/seed/.

CREATE TABLE accounts (
    id            TEXT PRIMARY KEY,          -- A0001 ...
    display_name  TEXT NOT NULL,
    cohort        TEXT NOT NULL
);

CREATE TABLE courses (
    code     TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    credits  INTEGER NOT NULL
);

CREATE TABLE enrollments (
    account_id   TEXT NOT NULL REFERENCES accounts(id),
    course_code  TEXT NOT NULL REFERENCES courses(code),
    PRIMARY KEY (account_id, course_code)
);

CREATE TABLE rooms (
    id             TEXT PRIMARY KEY,         -- building-number, for example B-204
    building       TEXT NOT NULL,
    capacity       INTEGER NOT NULL,
    has_projector  INTEGER NOT NULL CHECK (has_projector IN (0, 1)),
    has_pcs        INTEGER NOT NULL CHECK (has_pcs IN (0, 1))
);

CREATE TABLE sessions (
    course_code  TEXT NOT NULL REFERENCES courses(code),
    weekday      TEXT NOT NULL CHECK (weekday IN ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')),
    start        TEXT NOT NULL,              -- HH:MM
    "end"        TEXT NOT NULL,
    room_id      TEXT NOT NULL REFERENCES rooms(id),
    kind         TEXT NOT NULL CHECK (kind IN ('lecture', 'lab'))
);

CREATE TABLE room_bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     TEXT NOT NULL REFERENCES rooms(id),
    date        TEXT NOT NULL,               -- YYYY-MM-DD
    start       TEXT NOT NULL,
    "end"       TEXT NOT NULL,
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    purpose     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled'))
);

CREATE TABLE books (
    isbn          TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    authors       TEXT NOT NULL,
    year          INTEGER NOT NULL,
    copies_total  INTEGER NOT NULL
);

CREATE TABLE loans (
    isbn        TEXT NOT NULL REFERENCES books(isbn),
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    due_date    TEXT NOT NULL,
    returned    INTEGER NOT NULL DEFAULT 0 CHECK (returned IN (0, 1))
);

CREATE TABLE holds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    isbn        TEXT NOT NULL REFERENCES books(isbn),
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'fulfilled'))
);

CREATE TABLE assignments (
    course_code  TEXT NOT NULL REFERENCES courses(code),
    title        TEXT NOT NULL,
    due_at       TEXT NOT NULL,              -- YYYY-MM-DD HH:MM
    weight       REAL NOT NULL
);

CREATE TABLE events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    date      TEXT NOT NULL,
    start     TEXT,
    "end"     TEXT,
    location  TEXT,
    kind      TEXT NOT NULL CHECK (kind IN ('holiday', 'exam', 'seminar', 'deadline', 'event')),
    source    TEXT NOT NULL DEFAULT 'seed' CHECK (source IN ('seed', 'image', 'manual'))
);

CREATE INDEX idx_sessions_room ON sessions(room_id, weekday);
CREATE INDEX idx_bookings_room ON room_bookings(room_id, date);
CREATE INDEX idx_loans_account ON loans(account_id);
