"""Resumability store — SQLite keyed on (example_id, candidate_index).

Persists:
  - setup_cache   : SetupBundle per example_id (JSON blob)
  - candidates    : ExecResult + JudgeVerdict per (example_id, cand_index)
  - pairs         : emitted DPO pairs, to avoid re-writing on resume

An interrupted run can resume by checking get_candidate() before calling
the setup agent and runner — skips LLM calls and CloverDX executions for
already-processed (example_id, cand_index) pairs.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional


class ForgeState:

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS setup_cache (
                    example_id  TEXT PRIMARY KEY,
                    bundle_json TEXT NOT NULL,
                    created_at  TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    example_id   TEXT    NOT NULL,
                    cand_index   INTEGER NOT NULL,
                    exec_level   TEXT,
                    run_status   TEXT,
                    verdict_json TEXT,
                    is_rejected  INTEGER,
                    is_correct   INTEGER,
                    created_at   TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (example_id, cand_index)
                );
                CREATE TABLE IF NOT EXISTS pairs (
                    example_id TEXT    NOT NULL,
                    pair_index INTEGER NOT NULL,
                    pair_json  TEXT    NOT NULL,
                    created_at TEXT    DEFAULT (datetime('now')),
                    PRIMARY KEY (example_id, pair_index)
                );
            """)

    # ------------------------------------------------------------------
    # Setup cache
    # ------------------------------------------------------------------

    def get_setup_bundle(self, example_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT bundle_json FROM setup_cache WHERE example_id = ?",
            (example_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_setup_bundle(self, example_id: str, bundle_data: dict):
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO setup_cache (example_id, bundle_json) VALUES (?, ?)",
                (example_id, json.dumps(bundle_data)),
            )

    # ------------------------------------------------------------------
    # Candidate results
    # ------------------------------------------------------------------

    def get_candidate(self, example_id: str, cand_index: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT exec_level, run_status, verdict_json, is_rejected, is_correct "
            "FROM candidates WHERE example_id = ? AND cand_index = ?",
            (example_id, cand_index),
        ).fetchone()
        if not row:
            return None
        return {
            "exec_level":  row[0],
            "run_status":  row[1],
            "verdict":     json.loads(row[2]) if row[2] else None,
            "is_rejected": bool(row[3]),
            "is_correct":  bool(row[4]),
        }

    def save_candidate(
        self,
        example_id: str,
        cand_index: int,
        exec_level: str,
        run_status: str,
        verdict_data: Optional[dict],
        is_rejected: bool,
        is_correct: bool,
    ):
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO candidates
                   (example_id, cand_index, exec_level, run_status,
                    verdict_json, is_rejected, is_correct)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    example_id, cand_index, exec_level, run_status,
                    json.dumps(verdict_data) if verdict_data else None,
                    int(is_rejected), int(is_correct),
                ),
            )

    def candidates_done(self, example_id: str, total: int) -> bool:
        """True if all `total` candidates for this example are already stored."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE example_id = ?",
            (example_id,),
        ).fetchone()[0]
        return count >= total

    # ------------------------------------------------------------------
    # Pairs
    # ------------------------------------------------------------------

    def pairs_exist(self, example_id: str) -> bool:
        count = self._conn.execute(
            "SELECT COUNT(*) FROM pairs WHERE example_id = ?",
            (example_id,),
        ).fetchone()[0]
        return count > 0

    def save_pairs(self, example_id: str, pairs_data: list[dict]):
        with self._conn:
            for i, pair in enumerate(pairs_data):
                self._conn.execute(
                    "INSERT OR IGNORE INTO pairs (example_id, pair_index, pair_json) "
                    "VALUES (?, ?, ?)",
                    (example_id, i, json.dumps(pair)),
                )

    # ------------------------------------------------------------------

    def close(self):
        self._conn.close()
