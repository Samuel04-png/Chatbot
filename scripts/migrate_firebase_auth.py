"""Full Firebase Auth -> Supabase Auth account migration (every account; importing never grants access).

Subcommands (all DRY RUN / read-only unless --execute):
  export     Read every Firebase Auth account (your own Google login via ADC) and save it ENCRYPTED
             (AES-256-GCM) to ~/.rudo-migration/; key in ~/.config/rudo/migration.key. Firebase is not changed.
  plan       Decide one outcome per account from an export. Writes a secret-free worksheet; changes nothing.
  import     --execute --confirm-project <ref> (and RUDO_AUTH_IMPORT_ALLOWED_REF=<ref>) creates the accounts.
             Start with --only-uid <uid> or --limit 1. Re-runs are idempotent.
  reconcile  Compare the export, the ledger and Supabase Auth; every account must have a terminal outcome.
  rollback   Delete ONLY Supabase users this migration created (ledger id + Firebase marker). --execute needed.

Environment (.env, never printed): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RUDO_MIGRATOR_DATABASE_URL,
RUDO_MIGRATOR_ALLOW_REMOTE, FIREBASE_SIGNER_KEY / FIREBASE_SALT_SEPARATOR / FIREBASE_ROUNDS / FIREBASE_MEM_COST.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._env import load_env  # noqa: E402
from rudo import firebase_migration as fm  # noqa: E402
from rudo.staff_migration import HashParams, project_ref  # noqa: E402


def firebase_export(project):
    import firebase_admin
    from firebase_admin import auth, credentials
    app = firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': project}, name='rudo-export')
    return [fm.export_record(u) for u in auth.list_users(app=app).iterate_all()]


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def main(argv=None, env=None, admin=None, ledger=None, firebase_records=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=('export', 'plan', 'import', 'reconcile', 'rollback'))
    parser.add_argument('--project', default='dawa-ca263')
    parser.add_argument('--export', help='Encrypted export file (from the export command)')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-project')
    parser.add_argument('--only-uid')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--exclusions', help='Owner-approved JSON {uid: reason}; excluded accounts are still reported')
    parser.add_argument('--no-oauth-links', action='store_true')
    parser.add_argument('--actor', default='owner')
    args = parser.parse_args(argv)
    env = env if env is not None else load_env()

    if args.command == 'export':
        records = firebase_records if firebase_records is not None else firebase_export(args.project)
        path, digest = fm.encrypt_export(records, fm.OUT_DIR / f'firebase-auth-{args.project}-{stamp()}.enc.json')
        summary = {'exported_accounts': len(records), 'export_sha256': digest, 'file': str(path),
                   **fm.summarise_accounts([fm.account_facts(r) for r in records])}
        print(json.dumps(fm.assert_no_secrets(summary), indent=2))
        return summary

    if not args.export:
        raise SystemExit('--export <encrypted export file> is required')
    records, digest = fm.decrypt_export(args.export)
    url = env.get('SUPABASE_URL', '')
    if args.execute:
        allowed = env.get('RUDO_AUTH_IMPORT_ALLOWED_REF')
        if not allowed or args.confirm_project != project_ref(url) or allowed != project_ref(url):
            raise SystemExit('Refusing --execute: --confirm-project and RUDO_AUTH_IMPORT_ALLOWED_REF must both equal the SUPABASE_URL project ref')
    admin = admin or fm.AuthAdmin(url, env.get('SUPABASE_SERVICE_ROLE_KEY', ''))
    if ledger is None and env.get('RUDO_MIGRATOR_DATABASE_URL'):
        ledger = fm.Ledger(env['RUDO_MIGRATOR_DATABASE_URL'], allow_remote=env.get('RUDO_MIGRATOR_ALLOW_REMOTE') == 'true')
    if ledger is None and (args.execute or args.command in ('reconcile', 'rollback')):
        raise SystemExit('RUDO_MIGRATOR_DATABASE_URL is required (ledger)')

    if args.command in ('plan', 'import'):
        exclusions = json.loads(Path(args.exclusions).read_text()) if args.exclusions else None
        params = HashParams.from_env(env)
        summary, decisions = fm.execute_plan(records, args.project, digest, admin, ledger, url, params, args.actor,
                                             execute=args.command == 'import' and args.execute, only_uid=args.only_uid,
                                             limit=args.limit, exclusions=exclusions, link_oauth=not args.no_oauth_links)
        worksheet = fm.secure_write(fm.OUT_DIR / f'plan-{args.project}-{stamp()}.json',
                                    json.dumps(fm.assert_no_secrets({'summary': summary, 'decisions': decisions}), indent=2, default=str))
        summary = {**summary, 'export_sha256': digest, 'worksheet': str(worksheet)}
    elif args.command == 'reconcile':
        summary = fm.reconcile(records, args.project, admin, ledger)
        summary.pop('problem_detail') if not summary['problems'] else None
    else:
        summary = fm.rollback_users(args.project, admin, ledger, execute=args.execute)
    print(json.dumps(fm.assert_no_secrets(summary), indent=2, default=str))
    return summary


if __name__ == '__main__':
    main()
