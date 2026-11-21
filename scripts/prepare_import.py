"""No live exporter or remote importer; accepted input is an approved private export."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rudo.importer import plan,apply_local,reconcile_local

parser=argparse.ArgumentParser()
parser.add_argument('--input',required=True)
mode=parser.add_mutually_exclusive_group()
mode.add_argument('--apply-local',action='store_true')
mode.add_argument('--dry-run',action='store_true',help='Default: validate only, no network or writes')
parser.add_argument('--facility')
parser.add_argument('--account')
args=parser.parse_args()
try:
    records,counts=plan(json.loads(Path(args.input).read_text()))
    print(json.dumps(counts))  # Aggregate counts only, never keys or record contents.
    if args.apply_local:
        if counts['quarantined'] or not args.facility or not args.account:
            raise ValueError('preflight_failed')
        dsn=os.getenv('RUDO_IMPORT_DATABASE_URL','')
        print(json.dumps(apply_local(dsn,records,args.facility,args.account)))
        verification=reconcile_local(dsn,records)
        print(json.dumps(verification))
        if verification['mismatched']:raise ValueError('reconciliation_failed')
except Exception:
    raise SystemExit('Import preparation failed; no record contents are logged.') from None
