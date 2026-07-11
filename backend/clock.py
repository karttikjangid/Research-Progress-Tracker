"""Single source of truth for time (H2).

Every stored datetime is tz-aware UTC. The IST civil calendar (Asia/Kolkata)
is applied ONLY at day-boundary comparisons and for display — never stored.

Named `clock` and NOT `time`: `time` is a CPython built-in module, so a local
`time.py` on sys.path is either shadowed (unimportable) or a footgun for the
stdlib `import time` in llm.py. `clock` sidesteps that entirely. (deviation from
the fix brief's literal "time.py", documented in decisions.md.)
"""
import datetime as dt
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Kolkata")  # server civil timezone (IST, +05:30)


def now_utc() -> dt.datetime:
    """The one 'now': tz-aware UTC."""
    return dt.datetime.now(dt.timezone.utc)


def to_local(when: dt.datetime) -> dt.datetime:
    """Render a UTC (or naive-assumed-UTC) instant in IST. Used only at
    day-boundary comparisons and display."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(LOCAL_TZ)


def today_local() -> str:
    """The local (IST) calendar date as YYYY-MM-DD — independent of the host's
    system timezone, so day boundaries are correct even if the box runs UTC."""
    return to_local(now_utc()).date().isoformat()


def local_date_of(when: dt.datetime) -> str:
    """The IST calendar date of a stored UTC instant (e.g. an FSRS due date).
    'due today' == local_date_of(due) <= today_local()."""
    return to_local(when).date().isoformat()
