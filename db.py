"""SQLite persistence layer -- the single source of truth for the dashboard.

Nothing about a run's outcome lives only in Streamlit session state: every
job, every one-of-five candidate, every reviewer action, and every run's
progress is written here first. This means the dashboard can be closed and
reopened, or opened from another machine pointed at the same file, and
still show exactly where a run stands.
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    source_file TEXT,
    started_at REAL,
    ended_at REAL,
    status TEXT DEFAULT 'running',
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    current_item TEXT,
    current_stage TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    food_name TEXT,
    normalized_name TEXT,
    category TEXT,
    excel_rows TEXT,              -- JSON list of source-row numbers sharing this job
    status TEXT,                  -- AUTO_APPROVED / HUMAN_REVIEW / HUMAN_APPROVED / REJECTED / ERROR / NOT_FOUND
    error_type TEXT,
    error_message TEXT,
    best_score REAL,
    selected_source TEXT,
    selected_candidate_id INTEGER,
    retry_count INTEGER DEFAULT 0,
    drive_link TEXT,
    description TEXT,
    rejection_reason TEXT,
    reviewer TEXT,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    attempt INTEGER DEFAULT 1,     -- 1 = first pass, 2+ = Search Again rounds
    source TEXT,
    availability TEXT,             -- FOUND / SOURCE_NO_RESULT / SOURCE_ERROR
    url TEXT,
    local_path TEXT,
    query TEXT,
    author TEXT,
    license TEXT,
    attribution_url TEXT,
    width INTEGER,
    height INTEGER,
    file_size_kb REAL,
    technical_score REAL,
    ai_score REAL,
    composition_score REAL,
    color_quality_score REAL,
    resolution_score REAL,
    final_score REAL,
    rank INTEGER,
    ai_json TEXT,
    reason TEXT,
    warnings TEXT,
    retrieved_at REAL
);

CREATE TABLE IF NOT EXISTS review_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    reviewer TEXT,
    action TEXT,                  -- Approve / Reject / Search Again / Select Another / Retry / Manual Upload / Mark Resolved
    reason TEXT,
    old_score REAL,
    new_score REAL,
    timestamp REAL
);
"""


def _row_to_dict(cursor, row):
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL;")  # allows dashboard + batch runner to share the file safely
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Adds columns introduced after a database file was first created,
        so existing agent_data.db files don't need to be deleted/recreated
        when the code is upgraded."""
        try:
            self.conn.execute("ALTER TABLE candidates ADD COLUMN color_quality_score REAL")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    @contextmanager
    def cursor(self):
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        finally:
            cur.close()

    # ---------- runs ----------
    def create_run(self, source_file: str, total_items: int) -> str:
        run_id = uuid.uuid4().hex[:10]
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (run_id, source_file, started_at, status, total_items, processed_items) "
                "VALUES (?,?,?,?,?,0)",
                (run_id, source_file, time.time(), "running", total_items),
            )
        return run_id

    def update_run_progress(self, run_id, processed_items=None, current_item=None, current_stage=None, status=None):
        fields, values = [], []
        for col, val in (("processed_items", processed_items), ("current_item", current_item),
                          ("current_stage", current_stage), ("status", status)):
            if val is not None:
                fields.append(f"{col}=?")
                values.append(val)
        if not fields:
            return
        values.append(run_id)
        with self.cursor() as cur:
            cur.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id=?", values)

    def finish_run(self, run_id, status="completed"):
        with self.cursor() as cur:
            cur.execute("UPDATE runs SET status=?, ended_at=? WHERE run_id=?", (status, time.time(), run_id))

    def get_runs(self, limit=20):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def get_run(self, run_id):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
            r = cur.fetchone()
            return _row_to_dict(cur, r) if r else None

    # ---------- jobs ----------
    def find_job_by_normalized_name(self, run_id, normalized_name):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE run_id=? AND normalized_name=?", (run_id, normalized_name))
            r = cur.fetchone()
            return _row_to_dict(cur, r) if r else None

    def create_job(self, run_id, food_name, normalized_name, category, excel_rows) -> int:
        now = time.time()
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (run_id, food_name, normalized_name, category, excel_rows, status, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, food_name, normalized_name, category, json.dumps(excel_rows),
                 "PROCESSING", now, now),
            )
            return cur.lastrowid

    def update_job(self, job_id, **fields):
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))

    def get_job(self, job_id):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            r = cur.fetchone()
            return _row_to_dict(cur, r) if r else None

    def get_jobs(self, run_id=None, status=None, limit=500):
        q = "SELECT * FROM jobs WHERE 1=1"
        params = []
        if run_id:
            q += " AND run_id=?"
            params.append(run_id)
        if status:
            if isinstance(status, (list, tuple)):
                q += f" AND status IN ({','.join('?' * len(status))})"
                params.extend(status)
            else:
                q += " AND status=?"
                params.append(status)
        q += " ORDER BY job_id DESC LIMIT ?"
        params.append(limit)
        with self.cursor() as cur:
            cur.execute(q, params)
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def count_jobs_by_status(self, run_id=None):
        q = "SELECT status, COUNT(*) c FROM jobs"
        params = []
        if run_id:
            q += " WHERE run_id=?"
            params.append(run_id)
        q += " GROUP BY status"
        with self.cursor() as cur:
            cur.execute(q, params)
            return {r["status"]: r["c"] for r in cur.fetchall()}

    # ---------- candidates ----------
    def add_candidate(self, job_id, **fields) -> int:
        fields["job_id"] = job_id
        fields.setdefault("retrieved_at", time.time())
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" for _ in fields)
        with self.cursor() as cur:
            cur.execute(f"INSERT INTO candidates ({cols}) VALUES ({marks})", list(fields.values()))
            return cur.lastrowid

    def get_candidates(self, job_id, attempt=None):
        q = "SELECT * FROM candidates WHERE job_id=?"
        params = [job_id]
        if attempt is not None:
            q += " AND attempt=?"
            params.append(attempt)
        q += " ORDER BY attempt, rank"
        with self.cursor() as cur:
            cur.execute(q, params)
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def get_candidate(self, candidate_id):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,))
            r = cur.fetchone()
            return _row_to_dict(cur, r) if r else None

    def all_candidates(self, limit=2000):
        with self.cursor() as cur:
            cur.execute(
                "SELECT candidates.*, jobs.food_name, jobs.status as job_status FROM candidates "
                "JOIN jobs ON jobs.job_id = candidates.job_id ORDER BY candidates.candidate_id DESC LIMIT ?",
                (limit,),
            )
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    # ---------- review actions ----------
    def log_action(self, job_id, reviewer, action, reason=None, old_score=None, new_score=None):
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO review_actions (job_id, reviewer, action, reason, old_score, new_score, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, reviewer, action, reason, old_score, new_score, time.time()),
            )

    def get_actions(self, job_id):
        with self.cursor() as cur:
            cur.execute("SELECT * FROM review_actions WHERE job_id=? ORDER BY timestamp", (job_id,))
            return [_row_to_dict(cur, r) for r in cur.fetchall()]
