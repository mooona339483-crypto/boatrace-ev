"""Result evidence/settlement local candidate. No HTTP or automatic migrations.
Pure parsing/accounting plus explicit caller-owned SQLite ingestion helpers.
Input is selected official DOM table text, NOT the undocumented bc_rs2 layout.
URL/hash are provenance references, not independent authentication of the contents.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class MarketOutcome:
    bet_type: str
    state: str  # SETTLED / VOID / UNKNOWN
    winner: str | None = None
    payout_per_100: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class RaceOutcome:
    race_id: str
    markets: tuple[MarketOutcome, ...]
    refund_boats: tuple[int, ...] | None  # None = completeness unknown
    source_url: str
    source_sha256: str
    observed_at: str

    @property
    def legacy_safe(self):
        return _consistent_markets(self.markets) and self.refund_boats == () and all(m.state == "SETTLED" for m in self.markets)


def valid_selection(selection, bet_type):
    count = {"2T": 2, "3T": 3}.get(bet_type)
    if count is None or not isinstance(selection, str):
        return False
    parts = selection.split("-")
    return len(parts) == count and len(set(parts)) == count and all(p in "123456" and len(p) == 1 for p in parts)


def _consistent_markets(markets):
    if len(markets) != 2 or {m.bet_type for m in markets} != {"2T", "3T"}:
        return False
    for m in markets:
        if m.state == "SETTLED":
            if not valid_selection(m.winner, m.bet_type) or type(m.payout_per_100) is not int or m.payout_per_100 <= 0:
                return False
        elif m.state == "VOID":
            if m.winner is not None or type(m.payout_per_100) is not int or m.payout_per_100 != 100:
                return False
        elif m.state != "UNKNOWN" or m.winner is not None or m.payout_per_100 is not None:
            return False
    two, three = (next(m for m in markets if m.bet_type == bet) for bet in ("2T", "3T"))
    if two.state == "VOID" and three.state == "SETTLED":
        return False
    return not (two.state == three.state == "SETTLED" and two.winner != "-".join(three.winner.split("-")[:2]))


def _market(block, bet_type):
    tokens = block.split()
    # Explicit void marker AND full unit refund. Missing winner or payout=100
    # alone is never interpreted as a refund.
    if tokens == ["不成立", "¥100"] or tokens == ["不成立", "￥100"]:
        return MarketOutcome(bet_type, "VOID", None, 100, "EXPLICIT_OFFICIAL_VOID")
    if len(tokens) != 3 or not valid_selection(tokens[0], bet_type):
        return MarketOutcome(bet_type, "UNKNOWN", reason="UNSUPPORTED_OR_MISSING_RESULT")
    payout = re.fullmatch(r"[¥￥]([1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)", tokens[1])
    if not payout or not re.fullmatch(r"[1-9]\d*", tokens[2]):
        return MarketOutcome(bet_type, "UNKNOWN", reason="INVALID_PAYOUT_OR_POPULARITY")
    return MarketOutcome(bet_type, "SETTLED", tokens[0], int(payout[1].replace(",", "")))


def parse_official_observation(observation, expected_race_id):
    """Parse the observed official DOM text contract strictly; never scrape/fetch.
    Caller must independently establish page/content identity. Unsupported layouts
    stay UNKNOWN and are not admissible to legacy saves.
    """
    match = re.fullmatch(r"(\d{8})-(\d{2})-(\d{2})", expected_race_id)
    if not match:
        raise ValueError("invalid expected race identity")
    day, venue, race = match.groups()
    datetime.strptime(day, "%Y%m%d")
    if not 1 <= int(venue) <= 24 or not 1 <= int(race) <= 12:
        raise ValueError("invalid expected race identity")
    url = urlparse(observation["url"])
    q = parse_qs(url.query, keep_blank_values=True)
    if (url.scheme != "https" or url.netloc != "www.boatrace.jp"
            or url.path != "/owpc/pc/race/raceresult" or url.fragment
            or q != {"hd": [day], "jcd": [venue], "rno": [str(int(race))]}):
        raise ValueError("source identity mismatch")
    observed = datetime.fromisoformat(observation["checked_at_jst"])
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("aware observed timestamp required")
    tables = observation["tables"]
    if not isinstance(tables, list) or not all(isinstance(t, str) for t in tables) or len(tables) > 10 or sum(map(len, tables)) > 65536:
        raise ValueError("invalid or oversized table evidence")
    canonical = json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    source_hash = hashlib.sha256(canonical).hexdigest()
    payout_tables = [t for t in tables if t.splitlines() and t.splitlines()[0].split() == ["勝式", "組番", "払戻金", "人気"]]
    blocks = {}
    if len(payout_tables) == 1:
        text = payout_tables[0]
        labels = list(re.finditer(r"(?m)^(3連単|3連複|2連単|2連複|拡連複|単勝|複勝)(?=\s|$)", text))
        for i, label in enumerate(labels):
            blocks.setdefault(label[1], []).append(text[label.end(): labels[i+1].start() if i+1 < len(labels) else len(text)])
    markets = []
    for label, bet in (("2連単", "2T"), ("3連単", "3T")):
        entries = blocks.get(label, [])
        markets.append(_market(entries[0], bet) if len(entries) == 1 else MarketOutcome(bet, "UNKNOWN", reason="MISSING_OR_DUPLICATE_MARKET"))
    refund_tables = [t for t in tables if t.splitlines() and t.splitlines()[0].strip() == "返還"]
    refunds = None
    if len(refund_tables) == 1:
        tokens = "\n".join(refund_tables[0].splitlines()[1:]).split()
        if tokens == ["なし"]:
            refunds = ()
        elif tokens and len(tokens) == len(set(tokens)) and all(t in list("123456") for t in tokens):
            refunds = tuple(sorted(map(int, tokens)))
    if refunds == () and any("返還艇あり" in table for table in tables):
        refunds = None  # Explicit remark contradicts an empty refund list.
    if refunds is not None:
        markets = [MarketOutcome(m.bet_type, "UNKNOWN", reason="WINNER_REFUND_CONFLICT")
                   if m.winner and set(map(int, m.winner.split("-"))) & set(refunds) else m for m in markets]
    if not _consistent_markets(markets):
        markets = [MarketOutcome(bet, "UNKNOWN", reason="CONTRADICTORY_MARKETS") for bet in ("2T", "3T")]
    return RaceOutcome(expected_race_id, tuple(markets), refunds, observation["url"], source_hash, observation["checked_at_jst"])


def settle_ticket(outcome, bet_type, selection, stake):
    """Pure paper accounting only; does not persist or authorize any wager."""
    if not valid_selection(selection, bet_type) or type(stake) is not int or stake <= 0 or stake % 100:
        raise ValueError("invalid ticket or stake")
    pending = {"state": "PENDING", "stake": stake, "payout": None, "profit": None}
    if not _consistent_markets(outcome.markets):
        return pending
    if outcome.refund_boats is not None and (not isinstance(outcome.refund_boats, tuple)
            or any(type(b) is not int or b not in range(1, 7) for b in outcome.refund_boats)
            or len(set(outcome.refund_boats)) != len(outcome.refund_boats)):
        return pending
    market = next((m for m in outcome.markets if m.bet_type == bet_type), None)
    state, payout = "PENDING", None
    if market and market.state == "VOID" and market.winner is None and market.payout_per_100 == 100:
        state, payout = "REFUND", stake
    elif market and market.state == "SETTLED" and outcome.refund_boats is not None:
        if not valid_selection(market.winner, bet_type) or type(market.payout_per_100) is not int or market.payout_per_100 <= 0:
            raise ValueError("invalid normalized market")
        if set(map(int, market.winner.split("-"))) & set(outcome.refund_boats):
            return {"state": "PENDING", "stake": stake, "payout": None, "profit": None}
        if set(map(int, selection.split("-"))) & set(outcome.refund_boats):
            state, payout = "REFUND", stake
        elif selection == market.winner:
            state, payout = "WIN", stake // 100 * market.payout_per_100
        else:
            state, payout = "LOSS", 0
    return {"state": state, "stake": stake, "payout": payout, "profit": None if payout is None else payout - stake}


# Optional explicit-migration persistence. Never CREATE/ALTER from application code.
TABLE = "race_result_resolutions"


def table_exists(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone() is not None


def settlement_evidence_column_exists(con):
    return any(row[1] == "result_source_sha256" for row in con.execute("PRAGMA table_info(settlement_records)"))


def is_terminal(outcome):
    return (isinstance(outcome, RaceOutcome) and _consistent_markets(outcome.markets)
            and all(m.state in ("SETTLED", "VOID") for m in outcome.markets)
            and (outcome.refund_boats is not None or all(m.state == "VOID" for m in outcome.markets)))


def load_resolution_index(con):
    """A present but invalid record blocks fallback to legacy results."""
    if not table_exists(con):
        return {}
    index = {}
    for row in con.execute("SELECT race_id, observation_json, source_sha256 FROM race_result_resolutions"):
        race_id, raw, digest = row[0], row[1], row[2]
        index[race_id] = None
        try:
            if not isinstance(raw, str) or len(raw) > 131072:
                continue
            outcome = parse_official_observation(json.loads(raw), race_id)
            if outcome.source_sha256 == digest and is_terminal(outcome):
                index[race_id] = outcome
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            continue
    return index


def store_official_observation(con, observation, expected_race_id):
    """Explicit local/approved ingestion; caller owns transaction and commit.
    No HTTP or DDL. Immutable/idempotent; conflicting evidence needs manual review.
    This function is NOT automatically called by the production collector.
    """
    if not table_exists(con) or not settlement_evidence_column_exists(con):
        raise ValueError("explicit result-resolution migration required")
    outcome = parse_official_observation(observation, expected_race_id)
    if not is_terminal(outcome):
        raise ValueError("result/refund evidence incomplete; keep pending")
    raw = json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = con.execute("SELECT observation_json, source_sha256 FROM race_result_resolutions WHERE race_id=?", (expected_race_id,)).fetchone()
    if existing is not None:
        if existing[0] != raw or existing[1] != outcome.source_sha256:
            raise ValueError("conflicting immutable resolution; manual review required")
        return False
    # This is a separate append: never REPLACE/UPDATE a result or a settlement.
    con.execute("INSERT INTO race_result_resolutions(race_id, observation_json, source_sha256, recorded_at) VALUES(?,?,?,?)",
                (expected_race_id, raw, outcome.source_sha256, datetime.now().astimezone().isoformat()))
    return True


def settle_selections(outcome, bet_type, selections):
    """All-or-pending aggregate; never partially account a malformed ticket list."""
    if not isinstance(selections, list) or not selections:
        return None
    seen, tickets = set(), []
    for item in selections:
        if not isinstance(item, dict) or not valid_selection(item.get("selection"), bet_type) or item["selection"] in seen:
            return None
        seen.add(item["selection"])
        try:
            ticket = settle_ticket(outcome, bet_type, item.get("selection"), item.get("stake"))
        except (ValueError, TypeError):
            return None
        if ticket["state"] == "PENDING":
            return None
        tickets.append(ticket)
    stake = sum(t["stake"] for t in tickets)
    payout = sum(t["payout"] for t in tickets)
    return {"total_stake": stake, "total_payout": payout, "profit": payout - stake,
            "hits": sum(t["state"] == "WIN" for t in tickets),
            "refund_stake": sum(t["stake"] for t in tickets if t["state"] == "REFUND"),
            "refund_tickets": sum(t["state"] == "REFUND" for t in tickets),
            "has_decision": any(t["state"] in ("WIN", "LOSS") for t in tickets),
            "result_source_sha256": outcome.source_sha256}


def _bc_sections(body):
    if not isinstance(body, str) or len(body) > 65536 or '\ufffd' in body or body.lstrip().startswith('<'):
        raise ValueError('invalid result text')
    lines = body.splitlines()
    if not lines:
        raise ValueError('empty result text')
    header = lines[0].split('\t')
    sections, current = [], []
    for line in lines[1:]:
        if not line.strip():
            if current:
                sections.append(current); current = []
        else:
            current.append(line.split('\t'))
    if current:
        sections.append(current)
    return header, sections


def exception_hint(body):
    """Only triggers extra verification, never declares refund/status from a code."""
    try:
        header, sections = _bc_sections(body)
    except ValueError:
        return False
    return ((len(header) >= 3 and bool(header[2].strip()))
            or any('不成立' in cell for i in (0, 2) if i < len(sections) for row in sections[i] for cell in row))


def supported_bc_exception(body):
    """Observed numeric layout only. Header codes are not interpreted as statuses.
    Refund membership is accepted only after independent official-HTML agreement.
    """
    header, sections = _bc_sections(body)
    if len(header) != 3 or header[:2] != ['1', '1'] or not re.fullmatch(r'[1-6]+', header[2]) or len(set(header[2])) != len(header[2]):
        raise ValueError('unsupported result header; no status-code inference')
    if len(sections) < 3:
        raise ValueError('missing result sections')
    markets = []
    for index, bet in ((0, '2T'), (2, '3T')):
        if len(sections[index]) != 1:
            raise ValueError('multiple/unknown winning rows')
        row = [value.strip() for value in sections[index][0]]
        if len(row) != 6:
            raise ValueError('unsupported result row width')
        if row == ['', '', '', '', '不成立', '']:
            markets.append(MarketOutcome(bet, 'VOID'))  # refund amount not inferred here
            continue
        winner = '-'.join((row[0], row[2])) if bet == '2T' else '-'.join(row[:3])
        if (not valid_selection(winner, bet) or (bet == '2T' and row[1] != '-')
                or not re.fullmatch(r'[1-9]\d*', row[3]) or row[4] != '円'
                or not re.fullmatch(r'[1-9]\d*', row[5])):
            raise ValueError('unsupported result row')
        markets.append(MarketOutcome(bet, 'SETTLED', winner, int(row[3])))
    return tuple(markets), tuple(sorted(map(int, header[2])))


def official_observation_from_html(html, source_url, expected_race_id, observed_at):
    """Strict selected-table HTML adapter, validated against one real fixture.
    Navigation identity + venue image + unique table headers are required.
    Scripts are never executed. Unknown/malformed structure fails closed.
    """
    from html.parser import HTMLParser
    from urllib.parse import urljoin
    if not isinstance(html, str) or len(html) > 524288 or '\ufffd' in html:
        raise ValueError('invalid official HTML')
    class Tables(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.tables=[]; self.table=None; self.row=None; self.cell=None
            self.links=[]; self.images=[]; self.hidden=0; self.spans={}
        def handle_starttag(self, tag, attrs):
            a=dict(attrs)
            if tag in ('script','style'):
                self.hidden += 1
            if tag=='a' and 'href' in a:self.links.append(a['href'])
            if tag=='img' and 'src' in a:self.images.append(a['src'])
            if tag=='table':
                if self.table is not None:raise ValueError('nested result tables unsupported')
                self.table=[]; self.spans[id(self.table)]=[]
            elif self.table is not None and tag=='tr':
                if self.row is not None:raise ValueError('malformed result rows')
                self.row=[]
            elif self.row is not None and tag in ('th','td'):
                if self.cell is not None:raise ValueError('malformed result cells')
                self.cell=[]
                self.spans[id(self.table)].append((len(self.table),len(self.row),tag,a.get('rowspan','1'),a.get('colspan','1')))
        def handle_data(self,data):
            if self.cell is not None and not self.hidden:self.cell.append(data)
        def handle_endtag(self,tag):
            if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
            if tag in ('td','th') and self.cell is not None:
                text=' '.join(''.join(self.cell).split())
                text=re.sub(r'\s*-\s*','-',text)
                self.row.append(text); self.cell=None
            elif tag=='tr' and self.row is not None:
                if self.cell is not None:raise ValueError('unclosed result cell')
                self.table.append(self.row);self.row=None
            elif tag=='table' and self.table is not None:
                if self.row is not None:raise ValueError('unclosed result row')
                self.tables.append(self.table);self.table=None
    parser=Tables();parser.feed(html);parser.close()
    if parser.table is not None or parser.row is not None or parser.cell is not None:
        raise ValueError('unclosed official table')
    match=re.fullmatch(r'(\d{8})-(\d{2})-(\d{2})',expected_race_id)
    if not match:raise ValueError('invalid race identity')
    day,venue,race=match.groups()
    expected={'hd':[day],'jcd':[venue],'rno':[str(int(race))]}
    for page in ('racelist','beforeinfo'):
        matches=[link for link in parser.links if urlparse(urljoin(source_url,link)).scheme=='https'
                 and urlparse(urljoin(source_url,link)).netloc=='www.boatrace.jp'
                 and urlparse(urljoin(source_url,link)).path=='/owpc/pc/race/'+page
                 and parse_qs(urlparse(urljoin(source_url,link)).query)==expected]
        if len(matches)!=1:raise ValueError('official current-race navigation mismatch')
    if parser.images.count('/static_extra/pc/images/text_place2_'+venue+'.png')!=1:
        raise ValueError('official venue identity mismatch')
    selected=[]
    for header in (['勝式','組番','払戻金','人気'],['返還'],['備考']):
        tables=[t for t in parser.tables if t and t[0]==header]
        if len(tables)!=1:raise ValueError('missing/duplicate official result table')
        table=tables[0]
        spans={(r,c):(tag,rs,cs) for r,c,tag,rs,cs in parser.spans[id(table)]}
        if any(spans.get((0,c)) != ('th','1','1') for c in range(len(header))):
            raise ValueError('unsupported result header spans')
        if len(header)==4:
            cursor=1
            for label, rowspan in (('3連単',2),('3連複',2),('2連単',2),('2連複',2),('拡連複',5),('単勝',2),('複勝',3)):
                if cursor>=len(table) or len(table[cursor])!=4 or table[cursor][0]!=label:
                    raise ValueError('unsupported result row structure')
                if spans.get((cursor,0)) != ('td',str(rowspan),'1') or any(spans.get((cursor,c)) != ('td','1','1') for c in (1,2,3)):
                    raise ValueError('unsupported result cell spans')
                for offset in range(1,rowspan):
                    r=cursor+offset
                    if r>=len(table) or len(table[r])!=3 or any(spans.get((r,c)) != ('td','1','1') for c in range(3)):
                        raise ValueError('unsupported continuation row')
                cursor+=rowspan
            if cursor!=len(table):raise ValueError('extra result rows')
        elif len(table)!=2 or len(table[1])!=1 or spans.get((1,0))!=('td','1','1'):
            raise ValueError('unsupported refund/remark structure')
        selected.append('\n'.join('\t'.join(row) for row in table))
    observation={'url':source_url,'checked_at_jst':observed_at,'tables':selected,
                 'official_html_sha256':hashlib.sha256(html.encode('utf-8')).hexdigest()}
    # Same validator also checks final URL, date/race ranges and aware timestamp.
    outcome=parse_official_observation(observation,expected_race_id)
    if not is_terminal(outcome):raise ValueError('official evidence not terminal/complete')
    return observation


def corroborated_exception_observation(body, body_url, official_observation, expected_race_id, observed_at):
    match=re.fullmatch(r'(\d{8})-(\d{2})-(\d{2})',expected_race_id)
    if not match:raise ValueError('invalid race identity')
    day,venue,race=match.groups()
    expected=f'https://race.boatcast.jp/m_txt/{venue}/bc_rs2_{day}_{venue}_{race}.txt'
    if body_url != expected:raise ValueError('result source identity mismatch')
    parsed, header_boats=supported_bc_exception(body)
    official=parse_official_observation(official_observation,expected_race_id)
    if not is_terminal(official) or official.refund_boats != header_boats:
        raise ValueError('official refund evidence disagrees with source header')
    for source in parsed:
        target=next(m for m in official.markets if m.bet_type==source.bet_type)
        if source.state != target.state or source.winner != target.winner:
            raise ValueError('official/source market disagreement')
        if source.state=='SETTLED' and source.payout_per_100 != target.payout_per_100:
            raise ValueError('official/source payout disagreement')
        if source.state=='VOID' and target.payout_per_100 != 100:
            raise ValueError('official full refund not confirmed')
    observed=datetime.fromisoformat(observed_at)
    if observed.tzinfo is None or observed.utcoffset() is None:raise ValueError('aware source timestamp required')
    observation=dict(official_observation)
    observation['boatcast_corroboration']={'url':body_url,'observed_at':observed_at,
        'sha256_utf8':hashlib.sha256(body.encode('utf-8')).hexdigest(),'body_utf8':body}
    return observation
