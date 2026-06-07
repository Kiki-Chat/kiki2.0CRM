"""Shared in-memory fakes for the Stripe billing unit tests (no network, no DB).

FakeDB mimics the supabase-py query builder we use (select/insert/update/eq/…),
records inserts/updates, applies updates to its canned rows, and can enforce a
UNIQUE column to simulate the call_id / stripe_event_id idempotency guarantees.
"""

from __future__ import annotations

from typing import Any


class _Res:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, db: "FakeDB", table: str):
        self.db = db
        self.table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[tuple] = []
        self._count = None

    def select(self, *a, **k):
        self._op = "select"
        self._count = k.get("count")
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, c, v):
        self._filters.append(("eq", c, v))
        return self

    def neq(self, c, v):
        self._filters.append(("neq", c, v))
        return self

    def gte(self, c, v):
        self._filters.append(("gte", c, v))
        return self

    def lte(self, c, v):
        self._filters.append(("lte", c, v))
        return self

    def ilike(self, c, v):
        return self

    def in_(self, c, v):
        self._filters.append(("in", c, v))
        return self

    def is_(self, c, v):
        self._filters.append(("is", c, v))
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def _match(self, row: dict) -> bool:
        for op, c, v in self._filters:
            rv = row.get(c)
            if op == "eq" and str(rv) != str(v):
                return False
            if op == "neq" and str(rv) == str(v):
                return False
            if op == "in" and rv not in v:
                return False
            if op == "is" and v in (None, "null") and rv is not None:
                return False
        return True

    def execute(self):
        t = self.table
        if self._op == "insert":
            return self.db._insert(t, self._payload)
        if self._op == "update":
            rows = [r for r in self.db.canned.get(t, []) if self._match(r)]
            for r in rows:
                r.update(self._payload)
            self.db.updates.append((t, self._payload, list(self._filters)))
            return _Res(rows)
        if self._op == "delete":
            kept = [r for r in self.db.canned.get(t, []) if not self._match(r)]
            self.db.canned[t] = kept
            self.db.deletes.append((t, list(self._filters)))
            return _Res([])
        rows = [r for r in self.db.canned.get(t, []) if self._match(r)]
        if self._count == "exact":
            return _Res(rows, count=len(rows))
        return _Res(rows)


class FakeDB:
    def __init__(self, canned: dict | None = None, unique: dict | None = None):
        # deep-ish copy so tests don't share mutable rows
        self.canned = {k: [dict(r) for r in v] for k, v in (canned or {}).items()}
        self.unique = unique or {}        # table -> column that must be unique
        self.inserts: list[tuple] = []
        self.updates: list[tuple] = []
        self.deletes: list[tuple] = []
        self._idc = 0
        self._seen: dict[str, set] = {}

    def table(self, name):
        return _Query(self, name)

    def _insert(self, table, payload):
        uc = self.unique.get(table)
        if uc:
            val = payload.get(uc)
            seen = self._seen.setdefault(table, set())
            if val in seen:
                raise RuntimeError(
                    f'duplicate key value violates unique constraint "{table}_{uc}_key" '
                    "(SQLSTATE 23505)"
                )
            seen.add(val)
        self._idc += 1
        row = dict(payload, id=payload.get("id") or f"{table}-{self._idc}")
        self.inserts.append((table, payload))
        self.canned.setdefault(table, []).append(row)
        return _Res([row])

    # convenience accessors for assertions
    def inserts_to(self, table):
        return [p for (t, p) in self.inserts if t == table]

    def updates_to(self, table):
        return [p for (t, p, _f) in self.updates if t == table]
