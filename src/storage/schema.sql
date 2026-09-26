-- Схема хранилища собранных документов.
-- Написана так, чтобы без правок применяться и к SQLite, и к PostgreSQL:
-- только общие типы, без AUTOINCREMENT и без SERIAL.

CREATE TABLE IF NOT EXISTS documents (
    source_id    TEXT PRIMARY KEY,          -- "openalex:W123" или "arxiv:2609.00001"
    query        TEXT,                      -- по какому запросу документ нашли
    title        TEXT NOT NULL,
    abstract     TEXT,
    url          TEXT,
    published    DATE,
    source_type  TEXT,                      -- научная публикация, препринт, патент, медиа
    language     TEXT,                      -- язык оригинала
    venue        TEXT,
    authors      TEXT,                      -- имена через " | "
    orgs         TEXT,                      -- организации через " | "
    domain       TEXT,
    trust        TEXT,                      -- высокий, средний, низкий
    translated   INTEGER DEFAULT 0,         -- 1, если текст получен автопереводом
    ru_summary   TEXT,                      -- русское резюме зарубежного материала
    collected_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_query     ON documents (query);
CREATE INDEX IF NOT EXISTS idx_documents_published ON documents (published);
CREATE INDEX IF NOT EXISTS idx_documents_domain    ON documents (domain);

-- Кандидаты, которые система выделила по запросу. Нужны для вкладки
-- «Отклонено»: там показываем, что и почему не попало в ТОП-15.
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id  TEXT PRIMARY KEY,
    query         TEXT NOT NULL,
    technology    TEXT NOT NULL,
    area          TEXT,
    score         REAL,
    verdict       TEXT,                     -- сигнал / отклонено
    reject_reason TEXT,                     -- зрелая / хайп / шум
    payload       TEXT,                     -- полная карточка кандидата в JSON
    created_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_query ON candidates (query);
