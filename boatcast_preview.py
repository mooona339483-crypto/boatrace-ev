
import re
import urllib.error
import urllib.request


BASE = "https://race.boatcast.jp"


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

    return (
        f"{BASE}/hp_txt/"
        f"{venue_code}/{filename}"
    )


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 boatrace-ev/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            raw = response.read()
            body = raw.decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as error:
        print(
            "FETCH_HTTP_ERROR",
            error.code,
            url,
            "reason=", str(error.reason),
            "headers=", dict(error.headers),
            flush=True,
        )
        return None

    except urllib.error.URLError as error:
        print(
            "FETCH_URL_ERROR",
            str(error.reason),
            url,
            flush=True,
        )
        return None

    except TimeoutError:
        print(
            "FETCH_TIMEOUT",
            url,
            flush=True,
        )
        return None

    if body.lstrip().startswith("<"):
        print(
            "FETCH_HTML_RESPONSE",
            url,
            flush=True,
        )
        return None

    return body


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

    if (
        not lines
        or not lines[0].lstrip().startswith("data=")
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

    if (
        not lines
        or not lines[0].lstrip().startswith("data=")
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

        flag = (
            columns[5]
            if len(columns) > 5
            else ""
        )

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

    tkz_body = fetch_text(tkz_url)
    stt_body = fetch_text(stt_url)

    if tkz_body is None:
        return {
            "status": "SKIP",
            "reason": "TKZ_NOT_FOUND",
            "exhibition": {},
            "courses": {},
            "start_timing": {},
        }

    tkz_status, exhibition = parse_tkz(tkz_body)

    if tkz_status != "1":
        return {
            "status": "SKIP",
            "reason": "TKZ_NOT_READY",
            "exhibition": exhibition,
            "courses": {},
            "start_timing": {},
        }

    if stt_body is None:
        return {
            "status": "SKIP",
            "reason": "STT_NOT_FOUND",
            "exhibition": exhibition,
            "courses": {},
            "start_timing": {},
        }

    courses, start_timing = parse_stt(stt_body)

    common = set(exhibition) & set(courses)

    if len(common) not in (5, 6):
        return {
            "status": "SKIP",
            "reason": "INCOMPLETE_PREVIEW",
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
