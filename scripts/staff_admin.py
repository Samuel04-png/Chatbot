"""Owner tool for one-time setup and data mapping (owner connection to observer_control, not the web app).
Day-to-day staff management (invite, approve, suspend, roles, facilities) is done by admins in staff.html.

  facility-add   --account A --facility F --name "Display name"
  bootstrap-admin --email E --name N --firebase-uid UID --scope A:F [--scope ...]   (first admin only)
  map-referrals  --rules deploy/facility_rules.json [--execute]   phones whose referrals match exactly one facility
  map-csv        --file mappings.csv [--execute]                  owner-provided phone,account,facility rows
  map-remaining  --account A --facility F [--execute]             every still-unmapped phone -> one holding facility
  pending                                                          verified sign-ins awaiting approval
  suspend        --email E                                         emergency suspension (takes effect next request)
All changes run in one transaction and append to observer_control.staff_admin_events with --actor.
Dry runs print counts only (no phone numbers).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._env import load_env  # noqa: E402
from rudo.auth import FIREBASE_ISSUER_PREFIX  # noqa: E402
from rudo.db import Database  # noqa: E402

PHONES = 'SELECT phone FROM public.users UNION SELECT phone FROM public.messages'


def event(conn, actor, action, target, detail):
    conn.execute('INSERT INTO observer_control.staff_admin_events(actor,action,target,detail) VALUES(%s,%s,%s,%s)',
                 (actor, action, target, Jsonb(detail)))


def unmapped(conn, source):
    return [r[0] for r in conn.execute(f'''SELECT p.phone FROM ({PHONES}) p WHERE NOT EXISTS(
        SELECT 1 FROM observer_control.source_mappings m WHERE m.source_id=%s AND m.phone=p.phone) ORDER BY 1''', (source,))]


def insert_mappings(conn, source, rows, method, actor, execute):
    known = {(r[0], r[1]) for r in conn.execute('SELECT account_id,facility_id FROM observer_control.facilities WHERE source_id=%s', (source,))}
    missing = sorted({(a, f) for _, a, f in rows} - known)
    if missing:
        raise SystemExit(f'Unknown facilities (add them first): {missing}')
    summary = {'mode': 'execute' if execute else 'dry-run', 'method': method, 'phones': len(rows),
               'per_facility': {f'{a}:{f}': sum(1 for _, x, y in rows if (x, y) == (a, f)) for a, f in sorted({(a, f) for _, a, f in rows})}}
    if execute:
        for phone, account, facility in rows:
            conn.execute('''INSERT INTO observer_control.source_mappings(source_id,phone,account_id,facility_id,approved,method,approved_by)
                            VALUES(%s,%s,%s,%s,true,%s,%s) ON CONFLICT DO NOTHING''', (source, phone, account, facility, method, actor))
        event(conn, actor, 'map_phones', source, {k: v for k, v in summary.items() if k != 'mode'})
    else:
        conn.rollback()
    return summary


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['facility-add', 'bootstrap-admin', 'map-referrals', 'map-csv', 'map-remaining', 'pending', 'suspend'])
    parser.add_argument('--actor')
    parser.add_argument('--account')
    parser.add_argument('--facility')
    parser.add_argument('--name')
    parser.add_argument('--email')
    parser.add_argument('--firebase-uid')
    parser.add_argument('--scope', action='append', default=[])
    parser.add_argument('--rules')
    parser.add_argument('--file')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    env = env if env is not None else load_env()
    dsn = env.get('RUDO_CONTROL_ADMIN_DATABASE_URL', '')
    Database(allow_remote=env.get('RUDO_STAFF_ADMIN_ALLOW_REMOTE') == 'true').check_target(dsn)
    source = env.get('RUDO_OBSERVER_SOURCE_ID', '')
    if not source:
        raise SystemExit('RUDO_OBSERVER_SOURCE_ID is required')
    if args.command not in ('pending',) and not args.actor:
        raise SystemExit('--actor is required')
    with psycopg.connect(dsn) as conn:
        if args.command == 'pending':
            rows = [dict(zip(('provider', 'email', 'email_verified', 'last_seen'), r)) for r in conn.execute(
                '''SELECT r.provider,r.email,r.email_verified,r.last_seen FROM observer_control.identity_requests r
                   WHERE NOT EXISTS(SELECT 1 FROM observer_control.staff_identities i WHERE i.issuer=r.issuer AND i.subject=r.subject)
                   ORDER BY r.last_seen DESC''')]
            print(json.dumps(rows, indent=2, default=str))
            return rows
        if args.command == 'facility-add':
            if not (args.account and args.facility and args.name):
                raise SystemExit('facility-add requires --account, --facility and --name')
            conn.execute('INSERT INTO observer_control.facilities(source_id,account_id,facility_id,display_name) VALUES(%s,%s,%s,%s)',
                         (source, args.account, args.facility, args.name))
            event(conn, args.actor, 'facility_add', f'{args.account}:{args.facility}', {'name': args.name})
        elif args.command == 'bootstrap-admin':
            if not (args.email and args.firebase_uid and args.scope):
                raise SystemExit('bootstrap-admin requires --email, --firebase-uid and at least one --scope ACCOUNT:FACILITY')
            if conn.execute("SELECT 1 FROM observer_control.staff WHERE role='admin' AND status='active'").fetchone():
                raise SystemExit('An active admin already exists; invite further admins from the staff page')
            issuer = FIREBASE_ISSUER_PREFIX + env['FIREBASE_PROJECT_ID']
            sid = conn.execute("INSERT INTO observer_control.staff(email,display_name,role,created_by) VALUES(lower(%s),%s,'admin',%s) RETURNING id",
                               (args.email, args.name, args.actor)).fetchone()[0]
            conn.execute("INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by) "
                         "VALUES(%s,%s,'firebase',%s,lower(%s),'bootstrap',%s)", (issuer, args.firebase_uid, sid, args.email, args.actor))
            for scope in args.scope:
                account, _, facility = scope.partition(':')
                conn.execute("INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by) VALUES(%s,%s,%s,%s,%s)",
                             (sid, source, account, facility, args.actor))
            event(conn, args.actor, 'bootstrap_admin', str(sid), {'scopes': args.scope})
            print(json.dumps({'staff_id': str(sid)}))
            return str(sid)
        elif args.command == 'map-referrals':
            rules = json.loads(Path(args.rules).read_text())
            compiled = [(re.compile(r['pattern'], re.I), r['account'], r['facility']) for r in rules]
            candidates = {}
            for phone, text in conn.execute('SELECT phone,source FROM public.referrals'):
                for pattern, account, facility in compiled:
                    if pattern.search(text or ''):
                        candidates.setdefault(phone, set()).add((account, facility))
                        break
            todo = set(unmapped(conn, source))
            rows = [(p, *next(iter(f))) for p, f in sorted(candidates.items()) if len(f) == 1 and p in todo]
            summary = insert_mappings(conn, source, rows, 'referral_rules', args.actor, args.execute)
            summary['ambiguous_phones_skipped'] = sum(1 for f in candidates.values() if len(f) > 1)
            print(json.dumps(summary, indent=2))
            return summary
        elif args.command == 'map-csv':
            with open(args.file, newline='') as handle:
                rows = [(r['phone'].strip(), r['account'].strip(), r['facility'].strip()) for r in csv.DictReader(handle)]
            summary = insert_mappings(conn, source, rows, 'owner_csv', args.actor, args.execute)
            print(json.dumps(summary, indent=2))
            return summary
        elif args.command == 'map-remaining':
            if not (args.account and args.facility):
                raise SystemExit('map-remaining requires --account and --facility')
            if not conn.execute('SELECT 1 FROM observer_control.facilities WHERE source_id=%s AND account_id=%s AND facility_id=%s',
                                (source, args.account, args.facility)).fetchone():
                raise SystemExit(f'Unknown facilities (add them first): {[(args.account, args.facility)]}')
            rows = [(p, args.account, args.facility) for p in unmapped(conn, source)]
            summary = insert_mappings(conn, source, rows, 'holding_facility', args.actor, args.execute)
            print(json.dumps(summary, indent=2))
            return summary
        else:
            changed = conn.execute("UPDATE observer_control.staff SET status='suspended',updated_at=now() WHERE lower(email)=lower(%s) RETURNING id",
                                   (args.email,)).fetchone()
            if not changed:
                raise SystemExit('No such staff member')
            event(conn, args.actor, 'suspend', str(changed[0]), {'via': 'owner_cli'})
    print('ok')


if __name__ == '__main__':
    main()
