import os
import math
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from result_resolution import (
    load_resolution_index, is_terminal, valid_selection, exception_hint,
    supported_bc_exception, official_observation_from_html,
    corroborated_exception_observation, store_official_observation,
    table_exists, settlement_evidence_column_exists,
)

from backtest_engine import (
    init_db,
    record_result,
)


JST = ZoneInfo("Asia/Tokyo")

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

BASE = "https://race.boatcast.jp"

LOOKBACK_DAYS = 3
MAX_FETCHES = 30
GRACE_MINUTES = 3
MAX_EXCEPTION_VERIFY_FETCHES = 1


def connect():
    con = sqlite3.connect(
        DB,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    return con


def make_race_id(
    race_date,
    venue_code,
    race_no,
):
    return (
        f"{race_date}-"
        f"{str(venue_code).zfill(2)}-"
        f"{int(race_no):02d}"
    )


def deadline_datetime(
    race_date,
    deadline,
):
    if not deadline:
        return None

    try:
        value = datetime.strptime(
            f"{race_date}{deadline}",
            "%Y%m%d%H:%M",
        )
    except ValueError:
        return None

    return value.replace(
        tzinfo=JST
    )


def build_result_url(
    race_date,
    venue_code,
    race_no,
):
    venue = str(
        venue_code
    ).zfill(2)

    race = f"{int(race_no):02d}"

    return (
        f"{BASE}/m_txt/"
        f"{venue}/"
        f"bc_rs2_"
        f"{race_date}_"
        f"{venue}_"
        f"{race}.txt"
    )


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "boatrace-ev/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            if response.status != 200 or response.geturl() != url:
                print("RESULT_FETCH_UNAVAILABLE", "url=", url,
                      "reason=UNEXPECTED_RESPONSE_IDENTITY", flush=True)
                return None
            raw = response.read(65537)
            if len(raw) > 65536:
                print("RESULT_FETCH_UNAVAILABLE", "url=", url,
                      "reason=BODY_TOO_LARGE", flush=True)
                return None
            body = raw.decode("utf-8", errors="strict")

    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        UnicodeDecodeError,
    ) as error:
        print("RESULT_FETCH_UNAVAILABLE", "url=", url, "error_type=",
              type(error).__name__, "http_status=",
              getattr(error, "code", None), flush=True)
        return None

    if body.lstrip().startswith("<"):
        print("RESULT_FETCH_UNAVAILABLE", "url=", url,
              "reason=HTML_RESPONSE", flush=True)
        return None

    return body


def to_int(value):
    if value is None:
        return None

    cleaned = re.sub(
        r"[^\d]",
        "",
        str(value),
    )

    if not cleaned:
        return None

    try:
        return int(cleaned)

    except ValueError:
        return None


def split_sections(body):
    if not body:
        return []

    lines = body.splitlines()

    if lines:
        first = (
            lines[0]
            .split("\t")[0]
            .strip()
        )

        if first in (
            "0",
            "1",
        ):
            lines = lines[1:]

    sections = []
    current = []

    for line in lines:

        if not line.strip():
            if current:
                sections.append(
                    current
                )
                current = []

            continue

        current.append(
            line.split("\t")
        )

    if current:
        sections.append(
            current
        )

    return sections


def valid_boat(value):
    return str(value).strip() in (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    )


def parse_2t(row):
    if len(row) < 4:
        return None, None

    first = row[0].strip()
    second = row[2].strip()

    if not (
        valid_boat(first)
        and valid_boat(second)
        and first != second
    ):
        return None, None

    payout = to_int(
        row[3]
    )

    if payout is None:
        return None, None

    return (
        f"{first}-{second}",
        payout,
    )


def parse_3t(row):
    if len(row) < 4:
        return None, None

    first = row[0].strip()
    second = row[1].strip()
    third = row[2].strip()

    if not all(
        valid_boat(value)
        for value in (
            first,
            second,
            third,
        )
    ):
        return None, None

    if len({
        first,
        second,
        third,
    }) != 3:
        return None, None

    payout = to_int(
        row[3]
    )

    if payout is None:
        return None, None

    return (
        f"{first}-{second}-{third}",
        payout,
    )


def parse_result(body):
    sections = split_sections(
        body
    )

    # bc_rs2:
    # 0 = 2連単
    # 1 = 2連複
    # 2 = 3連単
    if len(sections) < 3:
        return None

    if (
        not sections[0]
        or not sections[2]
    ):
        return None

    (
        winning_2t,
        payout_2t,
    ) = parse_2t(
        sections[0][0]
    )

    (
        winning_3t,
        payout_3t,
    ) = parse_3t(
        sections[2][0]
    )

    if (
        winning_2t is None
        or payout_2t is None
        or winning_3t is None
        or payout_3t is None
    ):
        return None

    return {
        "winning_2t":
            winning_2t,
        "winning_3t":
            winning_3t,
        "payout_2t":
            payout_2t,
        "payout_3t":
            payout_3t,
    }


def pending_parse_details(body):
    """Bounded diagnostic only; no guessed void/refund status or partial save."""
    sections = split_sections(body)
    two = parse_2t(sections[0][0]) if sections and sections[0] else (None, None)
    three = parse_3t(sections[2][0]) if len(sections) > 2 and sections[2] else (None, None)
    return {
        "sections": len(sections),
        "2T_normal_fields": all(value is not None for value in two),
        "3T_normal_fields": all(value is not None for value in three),
    }


class ExceptionVerifyBudgetExceeded(ValueError):
    pass


def resolve_supported_exception(body, body_url, race_id, row, fetch_budget=None):
    """One official public GET; no retries, redirects, guessed flags or auto-DDL."""
    supported_bc_exception(body)  # reject unknown layouts before any extra HTTP
    with connect() as con:
        if not table_exists(con) or not settlement_evidence_column_exists(con):
            raise ValueError("explicit result-resolution migration required")
        resolutions = load_resolution_index(con)
        if race_id in resolutions:
            if is_terminal(resolutions[race_id]):
                return True
            raise ValueError("existing resolution requires manual review")
    official_url = ("https://www.boatrace.jp/owpc/pc/race/raceresult"
                    f"?rno={int(row['race_no'])}&jcd={str(row['venue_code']).zfill(2)}&hd={row['race_date']}")
    # Reject redirects rather than follow another host/path automatically.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    if fetch_budget is None:
        fetch_budget = [0]
    if fetch_budget[0] >= MAX_EXCEPTION_VERIFY_FETCHES:
        raise ExceptionVerifyBudgetExceeded("official fetch budget exhausted")
    fetch_budget[0] += 1  # count real attempts, not unsupported rows
    with opener.open(official_url, timeout=10) as response:
        if response.status != 200 or response.geturl() != official_url:
            raise ValueError("unexpected official response identity")
        raw = response.read(524289)
        if len(raw) > 524288:
            raise ValueError("oversized official result")
        html = raw.decode("utf-8", errors="strict")
    observed_at = datetime.now(JST).isoformat()
    observation = official_observation_from_html(html, official_url, race_id, observed_at)
    observation = corroborated_exception_observation(body, body_url, observation, race_id, observed_at)
    with connect() as con:
        inserted = store_official_observation(con, observation, race_id)
    print("RESULT_RESOLVED_NONSTANDARD", race_id,
          "inserted=", inserted, "source=official_and_boatcast", flush=True)
    return True


def get_existing_results():
    init_db()

    with connect() as con:
        rows = con.execute(
            """
            SELECT race_id, winning_2t, winning_3t, payout_2t, payout_3t
            FROM race_results
            """
        ).fetchall()
        resolutions = load_resolution_index(con)

    # A present but invalid resolution is not complete and never falls back.
    legacy = {row["race_id"] for row in rows
              if all(valid_selection(row["winning_"+bet.lower()], bet)
                     and isinstance(row["payout_"+bet.lower()], (int, float))
                     and not isinstance(row["payout_"+bet.lower()], bool)
                     and math.isfinite(row["payout_"+bet.lower()])
                     and row["payout_"+bet.lower()] >= 0 for bet in ("2T", "3T"))
              and row["winning_2t"] == "-".join(row["winning_3t"].split("-")[:2])} - set(resolutions)
    return legacy | {race_id for race_id, value in resolutions.items() if is_terminal(value)}


def get_candidate_races():
    with connect() as con:

        dates = con.execute(
            """
            SELECT DISTINCT race_date
            FROM race_pages
            ORDER BY race_date DESC
            LIMIT ?
            """,
            (
                LOOKBACK_DAYS,
            ),
        ).fetchall()

        race_dates = [
            row["race_date"]
            for row in dates
        ]

        if not race_dates:
            return []

        placeholders = ",".join(
            "?"
            for _ in race_dates
        )

        rows = con.execute(
            f"""
            SELECT
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline
            FROM race_pages
            WHERE race_date IN (
                {placeholders}
            )
              AND category != 'female'
            GROUP BY
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline
            ORDER BY
                race_date,
                venue_code,
                race_no
            """,
            race_dates,
        ).fetchall()

    return rows


def run():
    print(
        "RESULT_COLLECTOR_START",
        flush=True,
    )

    now = datetime.now(
        JST
    )

    existing = (
        get_existing_results()
    )

    candidates = (
        get_candidate_races()
    )

    targets = []

    for row in candidates:

        race_id = make_race_id(
            row["race_date"],
            row["venue_code"],
            row["race_no"],
        )

        if race_id in existing:
            continue

        deadline_dt = (
            deadline_datetime(
                row["race_date"],
                row["deadline"],
            )
        )

        if deadline_dt is None:
            continue

        ready_at = (
            deadline_dt
            + timedelta(
                minutes=GRACE_MINUTES
            )
        )

        if now < ready_at:
            continue

        targets.append(
            (
                race_id,
                row,
            )
        )

    targets = targets[
        :MAX_FETCHES
    ]

    saved = 0
    pending = 0
    errors = 0
    resolved_nonstandard = 0
    exception_verifications = [0]

    for race_id, row in targets:

        url = build_result_url(
            row["race_date"],
            row["venue_code"],
            row["race_no"],
        )

        try:
            body = fetch_text(
                url
            )

            if body is None:
                pending += 1
                print("RESULT_PENDING", race_id,
                      "reason=FETCH_UNAVAILABLE", flush=True)
                continue

            if exception_hint(body):
                try:
                    resolve_supported_exception(body, url, race_id, row, exception_verifications)
                    resolved_nonstandard += 1
                except ExceptionVerifyBudgetExceeded:
                    pending += 1
                    print("RESULT_PENDING", race_id,
                          "reason=EXCEPTION_VERIFY_BUDGET", flush=True)
                except (ValueError, TypeError, KeyError, urllib.error.HTTPError,
                        urllib.error.URLError, TimeoutError, UnicodeDecodeError) as error:
                    pending += 1
                    print("RESULT_PENDING", race_id, "reason=EXCEPTION_UNCONFIRMED",
                          "error_type=", type(error).__name__,
                          "http_status=", getattr(error, "code", None), flush=True)
                continue

            result = parse_result(
                body
            )

            if result is None:
                pending += 1
                print("RESULT_PENDING", race_id,
                      "reason=NORMAL_RESULT_FIELDS_INCOMPLETE",
                      pending_parse_details(body), flush=True)
                continue

            with connect() as con:
                resolution_present = race_id in load_resolution_index(con)
                legacy_present = con.execute("SELECT 1 FROM race_results WHERE race_id=?", (race_id,)).fetchone() is not None
            if resolution_present or legacy_present:
                pending += 1
                print("RESULT_PENDING", race_id,
                      "reason=EXISTING_RESULT_REVIEW_REQUIRED", flush=True)
                continue

            record_result(
                race_id=race_id,
                winning_2t=result[
                    "winning_2t"
                ],
                winning_3t=result[
                    "winning_3t"
                ],
                payout_2t=result[
                    "payout_2t"
                ],
                payout_3t=result[
                    "payout_3t"
                ],
            )

            saved += 1

            print(
                "RESULT_SAVED",
                row["venue_name"],
                f"{row['race_no']}R",
                result["winning_2t"],
                result["payout_2t"],
                result["winning_3t"],
                result["payout_3t"],
                flush=True,
            )

        except Exception as error:
            errors += 1

            print(
                "RESULT_ERROR",
                row["venue_name"],
                f"{row['race_no']}R",
                type(error).__name__,
                str(error)[:120],
                flush=True,
            )

    print(
        "RESULT_COLLECTOR_DONE",
        "targets=",
        len(targets),
        "saved=",
        saved,
        "pending=",
        pending,
        "errors=",
        errors,
        "resolved_nonstandard=",
        resolved_nonstandard,
        flush=True,
    )


if __name__ == "__main__":
    run()
