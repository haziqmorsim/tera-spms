from __future__ import annotations

from sqlalchemy import text
from app.db.session import engine


def print_rows(title: str, sql: str) -> None:
    print(f"\n===== {title} =====")

    with engine.connect() as conn:
        conn.execute(text("SET statement_timeout = '10s'"))
        rows = conn.execute(text(sql)).mappings().all()

    if not rows:
        print("No rows returned.")
        return

    for row in rows:
        print(dict(row))


def main() -> None:
    print("Checking database activity...")

    print_rows(
        "Current activity",
        """
        SELECT
            pid,
            usename,
            application_name,
            state,
            wait_event_type,
            wait_event,
            now() - query_start AS running_for,
            LEFT(query, 300) AS query
        FROM pg_stat_activity
        WHERE datname = current_database()
        ORDER BY query_start ASC
        LIMIT 50
        """,
    )

    print_rows(
        "Locks on job_runs",
        """
        SELECT
            a.pid,
            a.usename,
            a.application_name,
            a.state,
            a.wait_event_type,
            a.wait_event,
            now() - a.query_start AS running_for,
            l.locktype,
            l.mode,
            l.granted,
            LEFT(a.query, 300) AS query
        FROM pg_locks l
        JOIN pg_stat_activity a
            ON a.pid = l.pid
        WHERE l.relation = 'job_runs'::regclass
        ORDER BY l.granted ASC, a.query_start ASC
        """,
    )

    print_rows(
        "Blocked sessions",
        """
        SELECT
            blocked_activity.pid AS blocked_pid,
            blocked_activity.state AS blocked_state,
            blocked_activity.wait_event_type,
            blocked_activity.wait_event,
            now() - blocked_activity.query_start AS blocked_for,
            LEFT(blocked_activity.query, 300) AS blocked_query,
            blocking_activity.pid AS blocking_pid,
            blocking_activity.state AS blocking_state,
            now() - blocking_activity.query_start AS blocking_for,
            LEFT(blocking_activity.query, 300) AS blocking_query
        FROM pg_catalog.pg_locks blocked_locks
        JOIN pg_catalog.pg_stat_activity blocked_activity
            ON blocked_activity.pid = blocked_locks.pid
        JOIN pg_catalog.pg_locks blocking_locks
            ON blocking_locks.locktype = blocked_locks.locktype
           AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
           AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
           AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
           AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
           AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
           AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
           AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
           AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
           AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
           AND blocking_locks.pid != blocked_locks.pid
        JOIN pg_catalog.pg_stat_activity blocking_activity
            ON blocking_activity.pid = blocking_locks.pid
        WHERE NOT blocked_locks.granted
        ORDER BY blocked_activity.query_start ASC
        LIMIT 50
        """,
    )

    print("Done.")


if __name__ == "__main__":
    main()