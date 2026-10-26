import os
import re
import sqlite3
import urllib.request
import urllib.error
import datetime
import time
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DB = os.environ.get("DB_PATH", "/data/boatrace_ev.sqlite3")

VENUES = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}

FEMALE_TITLE_KEYWORDS = (
    "オールレディース",
    "ヴィーナスシリーズ",
    "ヴィーナスＳ",
    "レディースチャンピオン",
    "レディースオールスター",
    "レディースチャレンジカップ",
    "クイーンズクライマックス",
)

BASE = "https://www.boatrace.jp/owpc/pc/race/racelist"


class PageParser(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self.title_parts = []
        self.title_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if self.title_depth > 0:
            if tag not in self.VOID_TAGS:
                self.title_depth += 1
            return

        classes = (
            attrs.get("class", "")
            .strip()
            .split()
        )

        if any(
            "heading2_title" in cls
            for cls in classes
        ):
            self.title_depth = 1

    def handle_data(self, data):
        text = data.strip()

        if not text:
            return

        self.parts.append(text)

        if self.title_depth > 0:
            self.title_parts.append(text)

    def handle_endtag(self, tag):
        if self.title_depth > 0:
            self.title_depth -= 1

    def get_text(self):
        return " ".join(self.parts)

    def get_event_title(self):
        return " ".join(
            self.title_parts
        ).strip()


def parse_page(html):
    parser = PageParser()
    parser.feed(html)

    return (
        parser.get_text(),
        parser.get_event_title(),
    )


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 boatrace-ev-research/1.0",
            "Accept-Language":
                "ja-JP,ja;q=0.9",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=20,
    ) as res:
        charset = (
            res.headers.get_content_charset()
            or "utf-8"
        )

        return res.read().decode(
            charset,
            errors="replace",
        )


def normalize_title(title):
    return (
        title
        .replace(" ", "")
        .replace("　", "")
        .upper()
    )


def detect_category(event_title):
    title = normalize_title(event_title)

    if not title:
        return "mixed"

    if (
        title.startswith("ＡＬ・")
        or title.startswith("AL・")
    ):
        return "female"

    for keyword in FEMALE_TITLE_KEYWORDS:
        normalized_keyword = (
            normalize_title(keyword)
        )

        if normalized_keyword in title:
            return "female"

    return "mixed"


def extract_deadlines(text):
    m = re.search(
        r"締切予定時刻\s+"
        r"((?:\d{1,2}:\d{2}\s*){12})",
        text,
    )

    if not m:
        return []

    return re.findall(
        r"\d{1,2}:\d{2}",
        m.group(1),
    )


def init_db():
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS race_pages (
                race_date TEXT NOT NULL,
                venue_code TEXT NOT NULL,
                venue_name TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                category TEXT NOT NULL,
                deadline TEXT,
                fetched_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                raw_html TEXT NOT NULL,
                PRIMARY KEY (
                    race_date,
                    venue_code,
                    race_no,
                    fetched_at
                )
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS collector_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                race_date TEXT NOT NULL,
                active_venues INTEGER DEFAULT 0,
                pages_saved INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0
            )
            """
        )


def save_page(
    race_date,
    venue_code,
    venue_name,
    race_no,
    category,
    deadline,
    fetched_at,
    url,
    html,
):
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            INSERT INTO race_pages (
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline,
                fetched_at,
                source_url,
                raw_html
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline,
                fetched_at,
                url,
                html,
            ),
        )


def collect(race_date=None):
    now = datetime.datetime.now(JST)

    if race_date is None:
        race_date = now.strftime("%Y%m%d")

    started_at = now.isoformat()

    with sqlite3.connect(DB) as con:
        cur = con.execute(
            """
            INSERT INTO collector_runs (
                started_at,
                race_date
            )
            VALUES (?, ?)
            """,
            (
                started_at,
                race_date,
            ),
        )

        run_id = cur.lastrowid

    active_venues = 0
    pages_saved = 0
    error_count = 0

    for venue_code, venue_name in VENUES.items():

        check_url = (
            f"{BASE}?hd={race_date}"
            f"&jcd={venue_code}"
            f"&rno=1"
        )

        try:
            html = fetch(check_url)

            (
                text,
                event_title,
            ) = parse_page(html)

            if (
                "締切予定時刻" not in text
                or "出走表" not in text
            ):
                print(
                    "SKIP",
                    venue_name,
                )
                continue

            active_venues += 1

            category = detect_category(
                event_title
            )

            deadlines = extract_deadlines(
                text
            )

            print(
                "ACTIVE",
                venue_code,
                venue_name,
                category,
                "TITLE=",
                event_title,
            )

            for race_no in range(1, 13):
                url = (
                    f"{BASE}?hd={race_date}"
                    f"&jcd={venue_code}"
                    f"&rno={race_no}"
                )

                try:
                    race_html = fetch(url)

                    fetched_at = (
                        datetime.datetime
                        .now(JST)
                        .isoformat()
                    )

                    deadline = None

                    if len(deadlines) >= race_no:
                        deadline = deadlines[
                            race_no - 1
                        ]

                    save_page(
                        race_date=race_date,
                        venue_code=venue_code,
                        venue_name=venue_name,
                        race_no=race_no,
                        category=category,
                        deadline=deadline,
                        fetched_at=fetched_at,
                        url=url,
                        html=race_html,
                    )

                    pages_saved += 1

                    print(
                        "SAVED",
                        venue_name,
                        f"{race_no}R",
                        deadline,
                        category,
                    )

                    time.sleep(0.5)

                except Exception as e:
                    error_count += 1

                    print(
                        "ERROR",
                        venue_name,
                        f"{race_no}R",
                        repr(e),
                    )

        except urllib.error.HTTPError:
            continue

        except Exception as e:
            error_count += 1

            print(
                "VENUE_ERROR",
                venue_name,
                repr(e),
            )

        time.sleep(0.5)

    finished_at = (
        datetime.datetime
        .now(JST)
        .isoformat()
    )

    with sqlite3.connect(DB) as con:
        con.execute(
            """
            UPDATE collector_runs
            SET finished_at=?,
                active_venues=?,
                pages_saved=?,
                error_count=?
            WHERE id=?
            """,
            (
                finished_at,
                active_venues,
                pages_saved,
                error_count,
                run_id,
            ),
        )

    print(
        "COLLECTOR_DONE",
        "date=",
        race_date,
        "venues=",
        active_venues,
        "pages=",
        pages_saved,
        "errors=",
        error_count,
    )


if __name__ == "__main__":
    init_db()
    collect()
