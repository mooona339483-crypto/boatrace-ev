
import re
import time
import urllib.error
import urllib.request

BASE = "https://race.boatcast.jp"
TIMEOUT = 20
MAX_RETRIES = 3


def normalize_date(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 8:
        raise ValueError("date must be YYYYMMDD")
    return digits


def build_url(kind, race_date, venue_code, race_no):
    race_date = normalize_date(race_date)
    venue_code = str(venue_code).zfill(2)
    race_no = str(int(race_no)).zfill(2)

    if kind not in ("tkz", "stt"):
        raise ValueError("unknown preview kind")

    filename = (
        f"bc_j_{kind}_{race_date}_"
        f"{venue_code}_{race_no}.txt"
    )
    return f"{BASE}/hp_txt/{venue_code}/{filename}"


def fetch_text_result(url):
    failure = "FETCH_FAILED"
    headers = {
        "User-Agent": "boatrace-ev/1.0",
        "Accept": "text/plain,*/*",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        request = urllib.request.Request(
            url,
            headers=headers,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT,
            ) as response:
                status = response.status
                content_type = response.headers.get(
                    "Content-Type", ""
                )
                raw = response.read()

            body = raw.decode(
                "utf-8",
                errors="replace",
            )

            if (
                "text/html" in content_type.lower()
                or body.lstrip().startswith("<")
            ):
                print(
                    "FETCH_INVALID_CONTENT",
                    "status=", status,
                    "content_type=", content_type,
                    "url=", url,
                    flush=True,
                )
                return None, "INVALID_CONTENT"

            if not body.strip():
                print(
                    "FETCH_EMPTY",
                    "url=", url,
                    flush=True,
                )
                return None, "EMPTY_BODY"

            print(
                "FETCH_OK",
                "bytes=", len(raw),
                "url=", url,
                flush=True,
            )
            return body, "OK"

        except urllib.error.HTTPError as error:
            code = error.code

            print(
                "FETCH_HTTP_ERROR",
                "status=", code,
                "attempt=", attempt,
                "url=", url,
                "reason=", str(error.reason),
                flush=True,
            )

            if code in (401, 403):
                print(
                    "FETCH_ACCESS_DENIED",
                    "status=", code,
                    "url=", url,
                    flush=True,
                )
                return None, "ACCESS_DENIED"

            if code == 404:
                print(
                    "FETCH_NOT_FOUND",
                    "url=", url,
                    flush=True,
                )
                return None, "NOT_FOUND"

            if code not in (
                408, 429, 500, 502, 503, 504
            ):
                return None, "HTTP_ERROR"

            failure = "RATE_LIMITED" if code == 429 else "HTTP_ERROR"
            if code == 429:
                retry_after = error.headers.get(
                    "Retry-After", ""
                )
                print(
                    "FETCH_RATE_LIMIT",
                    "retry_after=", retry_after,
                    flush=True,
                )

        except (
            urllib.error.URLError,
            TimeoutError,
        ) as error:
            failure = "CONNECTION_ERROR"
            print(
                "FETCH_CONNECTION_ERROR",
                "attempt=", attempt,
                "url=", url,
                "error=", str(error),
                flush=True,
            )

        if attempt < MAX_RETRIES:
            time.sleep(attempt * 2)

    print("FETCH_FAILED", url, flush=True)
    return None, failure


def fetch_text(url):
    """Preserve the existing body-or-None interface for other callers."""
    return fetch_text_result(url)[0]


def preview_format_valid(body):
    if not isinstance(body, str):
        return False
    lines = body.splitlines()
    return len(lines) >= 2 and lines[0].lstrip().startswith("data=")


def empty_values_reason(body, kind):
    """Classify zero extracted values; placeholders do not prove publication state.

    Mirror only the rows/columns consumed by the existing parser. Never provide
    replacement values or interpret the tkz trailing timing section as courses.
    """
    if not preview_format_valid(body):
        return "PARSE_INVALID"
    rows = [line for line in body.splitlines()[2:] if line.strip()]
    if kind == "tkz":
        rows = rows[:6]
    if not rows:
        return "EMPTY_DATA"
    placeholders = ("", "-", "－")
    for row in rows:
        columns = row.split("\t")
        if kind == "tkz":
            if len(columns) < 2:
                return "PARSE_INVALID"
            value = columns[1].strip()
            if value not in placeholders:
                number = to_float(value)
                if number is None or not 5.0 <= number <= 10.0:
                    return "PARSE_INVALID"
                # Caller has no extracted values; a valid value is inconsistent.
                return "PARSE_INVALID"
        elif kind == "stt":
            if len(columns) < 5:
                return "PARSE_INVALID"
            for value in columns[:2]:
                value = value.strip()
                if value in placeholders:
                    continue
                try:
                    number = int(value)
                except ValueError:
                    return "PARSE_INVALID"
                if not 1 <= number <= 6:
                    return "PARSE_INVALID"
            if all(value.strip() not in placeholders for value in columns[:2]):
                return "PARSE_INVALID"
        else:
            return "PARSE_INVALID"
    return "VALUES_NOT_READY"


def to_float(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    if value.startswith("."):
        value = "0" + value

    try:
        return float(value)
    except ValueError:
        return None


def parse_tkz(body):
    if not body:
        return None, {}

    lines = body.splitlines()

    if not lines or not lines[0].lstrip().startswith(
        "data="
    ):
        return None, {}

    if len(lines) < 2:
        return None, {}

    status = lines[1].split("\t")[0].strip()

    rows = [
        line
        for line in lines[2:]
        if line.strip()
    ][:6]

    exhibition = {}

    for boat_number, row in enumerate(rows, start=1):
        columns = row.split("\t")

        if len(columns) < 2:
            continue

        value = to_float(columns[1])

        if value is not None and 5.0 <= value <= 10.0:
            exhibition[boat_number] = value

    return status, exhibition


def parse_start_timing(value, flag):
    if not value:
        return None

    flag = (flag or "").strip().upper()

    if flag == "L":
        return None

    value = value.strip()

    if value.startswith("."):
        value = "0" + value

    try:
        number = float(value)
    except ValueError:
        return None

    if flag == "F":
        number = -number

    return number


def parse_stt(body):
    if not body:
        return {}, {}

    lines = body.splitlines()

    if not lines or not lines[0].lstrip().startswith(
        "data="
    ):
        return {}, {}

    courses = {}
    start_timing = {}

    for row in lines[2:]:
        if not row.strip():
            continue

        columns = row.split("\t")

        if len(columns) < 5:
            continue

        try:
            course = int(columns[0].strip())
            boat_number = int(columns[1].strip())
        except ValueError:
            continue

        if not (
            1 <= course <= 6
            and 1 <= boat_number <= 6
        ):
            continue

        courses[boat_number] = course

        flag = columns[5] if len(columns) > 5 else ""

        start_timing[boat_number] = parse_start_timing(
            columns[4],
            flag,
        )

    return courses, start_timing


def fetch_preview(race_date, venue_code, race_no):
    tkz_url = build_url(
        "tkz",
        race_date,
        venue_code,
        race_no,
    )

    stt_url = build_url(
        "stt",
        race_date,
        venue_code,
        race_no,
    )

    tkz_body, tkz_failure = fetch_text_result(tkz_url)

    if tkz_body is None:
        return {
            "status": "SKIP",
            "reason": "TKZ_" + tkz_failure,
            "exhibition": {},
            "courses": {},
            "start_timing": {},
        }

    if not preview_format_valid(tkz_body):
        return {"status": "SKIP", "reason": "TKZ_PARSE_INVALID",
                "exhibition": {}, "courses": {}, "start_timing": {}}
    tkz_status, exhibition = parse_tkz(tkz_body)
    print("PREVIEW_DATA_STATUS", "kind=tkz", "status=", tkz_status,
          "exhibition_count=", len(exhibition),
          "exhibition_state=", "VALUES_PRESENT" if exhibition else empty_values_reason(tkz_body, "tkz"),
          "url=", tkz_url, flush=True)

    if tkz_status != "1":
        return {
            "status": "SKIP",
            "reason": "TKZ_NOT_READY",
            "exhibition": exhibition,
            "courses": {},
            "start_timing": {},
        }

    stt_body, stt_failure = fetch_text_result(stt_url)

    if stt_body is None:
        return {
            "status": "SKIP",
            "reason": "STT_" + stt_failure,
            "exhibition": exhibition,
            "courses": {},
            "start_timing": {},
        }

    if not preview_format_valid(stt_body):
        return {"status": "SKIP", "reason": "STT_PARSE_INVALID",
                "exhibition": exhibition, "courses": {}, "start_timing": {}}
    courses, start_timing = parse_stt(stt_body)
    print("PREVIEW_DATA_STATUS", "kind=stt", "course_count=", len(courses),
          "url=", stt_url, flush=True)

    common = set(exhibition) & set(courses)

    if len(common) not in (5, 6):
        return {
            "status": "SKIP",
            "reason": ("TKZ_" + empty_values_reason(tkz_body, "tkz")
                       if not exhibition else
                       "STT_" + empty_values_reason(stt_body, "stt")
                       if not courses else "INCOMPLETE_PREVIEW"),
            "exhibition": exhibition,
            "courses": courses,
            "start_timing": start_timing,
        }

    return {
        "status": "READY",
        "reason": "BOATCAST_PREVIEW_READY",
        "exhibition": exhibition,
        "courses": courses,
        "start_timing": start_timing,
    }


if __name__ == "__main__":
    print("BOATCAST_PREVIEW_READY")
