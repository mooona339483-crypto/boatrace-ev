import os, sqlite3, json, datetime, argparse
from zoneinfo import ZoneInfo
JST=ZoneInfo('Asia/Tokyo')
DB=os.getenv('DB_PATH','ev.sqlite3')
SCHEMA='''CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY, venue INTEGER NOT NULL CHECK(venue BETWEEN 1 AND 24), race_date TEXT NOT NULL, race_no INTEGER NOT NULL CHECK(race_no BETWEEN 1 AND 12), bet_type TEXT NOT NULL CHECK(bet_type IN ('2T','3T')), selection TEXT NOT NULL, stake INTEGER NOT NULL CHECK(stake>0 AND stake%100=0), odds REAL NOT NULL CHECK(odds>1), probability REAL NOT NULL CHECK(probability>0 AND probability<1), ev REAL NOT NULL CHECK(ev>0), deadline TEXT NOT NULL, recorded_at TEXT NOT NULL, source TEXT NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', payout INTEGER, UNIQUE(venue,race_date,race_no,bet_type,selection));'''
def conn():
 c=sqlite3.connect(DB); c.execute(SCHEMA); return c
def now():return datetime.datetime.now(JST)
def record(args):
 t=now(); deadline=datetime.datetime.fromisoformat(args.deadline)
 if deadline.tzinfo is None: raise ValueError('deadline must have timezone offset')
 if t>=deadline.astimezone(JST): raise ValueError('Race deadline has passed')
 if not args.verified: raise ValueError('Model must be validated; pass --verified only with documented out-of-sample calibration')
 if not args.source:raise ValueError('Timestamped odds source required')
 if args.probability*args.odds<=1:raise ValueError('EV is not positive')
 if args.stake>10000:raise ValueError('Stake exceeds per-type budget')
 digits=args.selection.split('-')
 if len(digits)!=(2 if args.type=='2T' else 3) or len(set(digits))!=len(digits) or any(d not in '123456' or len(d)!=1 for d in digits):raise ValueError('Invalid selection')
 with conn() as c:
  total=c.execute('SELECT COALESCE(SUM(stake),0) FROM bets WHERE venue=? AND race_date=? AND race_no=? AND bet_type=?',(args.venue,args.date,args.race,args.type)).fetchone()[0]
  if total+args.stake>10000:raise ValueError('Per-type race budget exceeded')
  c.execute('INSERT INTO bets(venue,race_date,race_no,bet_type,selection,stake,odds,probability,ev,deadline,recorded_at,source,model_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(args.venue,args.date,args.race,args.type,args.selection,args.stake,args.odds,args.probability,args.probability*args.odds-1,deadline.isoformat(),t.isoformat(),args.source,args.model))
 print('Recorded immutable pre-race bet')
def settle(args):
 with conn() as c:
  bet=c.execute('SELECT status,stake,selection FROM bets WHERE id=?',(args.id,)).fetchone()
  if not bet or bet[0]!='pending':raise ValueError('Unknown or already settled bet')
  if args.payout<0:raise ValueError('Invalid payout')
  c.execute('UPDATE bets SET status=?,payout=? WHERE id=?',('settled',args.payout,args.id))
 print('Settled')
def report():
 with conn() as c:
  for typ in ('2T','3T'):
   rows=c.execute("SELECT stake,payout,probability FROM bets WHERE bet_type=? AND status='settled'",(typ,)).fetchall()
   n=len(rows); st=sum(x[0] for x in rows);pay=sum(x[1] for x in rows); hits=sum(x[1]>0 for x in rows)
   print(json.dumps({'type':typ,'settled_bets':n,'stake':st,'payout':pay,'roi_percent':round(pay/st*100,2) if st else None,'hit_rate':hits/n if n else None,'predicted_hit_rate':sum(x[2] for x in rows)/n if n else None,'brier':sum((x[2]-(1 if x[1]>0 else 0))**2 for x in rows)/n if n else None},ensure_ascii=False))
p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
a=sub.add_parser('record');a.add_argument('--venue',type=int,required=True);a.add_argument('--date',required=True);a.add_argument('--race',type=int,required=True);a.add_argument('--type',choices=['2T','3T'],required=True);a.add_argument('--selection',required=True);a.add_argument('--stake',type=int,required=True);a.add_argument('--odds',type=float,required=True);a.add_argument('--probability',type=float,required=True);a.add_argument('--deadline',required=True);a.add_argument('--source',required=True);a.add_argument('--model',required=True);a.add_argument('--verified',action='store_true')
b=sub.add_parser('settle');b.add_argument('--id',type=int,required=True);b.add_argument('--payout',type=int,required=True)
sub.add_parser('report')
args=p.parse_args(); {'record':record,'settle':settle,'report':lambda _:report()}[args.cmd](args)
