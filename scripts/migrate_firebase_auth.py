"""Full Firebase Auth -> Supabase Auth account migration (every account; importing never grants access).

Subcommands (all DRY RUN / read-only unless --execute):
  export     Read every Firebase Auth account (your own Google login via ADC) and save it ENCRYPTED
             (AES-256-GCM) to ~/.rudo-migration/; key in ~/.config/rudo/migration.key. Firebase is not changed.
  plan       Decide one outcome per account from an export. Writes a secret-free worksheet; changes nothing.
  import     --execute --confirm-project <ref> (and RUDO_AUTH_IMPORT_ALLOWED_REF=<ref>) creates the accounts.
             Start with --only-uid <uid> or --limit 1. Re-runs are idempotent.
  reconcile  Compare the export, the ledger and Supabase Auth; every account must have a terminal outcome.
  rollback   Delete ONLY Supabase users this migration created (ledger id + Firebase marker). --execute needed.
  export-data     Read every Firestore document (all collections and sub-collections), encrypted export.
  plan-data       Counts per collection and owning application from a data export. Changes nothing.
  import-data     --execute --confirm-project <ref>: upsert into firebase_import.documents (separate from Rudo tables).
  reconcile-data  Every exported document path and content hash must be present in Supabase.

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
from rudo import firestore_migration as fsm  # noqa: E402
from rudo.staff_migration import HashParams, project_ref  # noqa: E402


def firebase_export(project):
    import firebase_admin
    from firebase_admin import auth, credentials
    app = firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': project}, name='rudo-export')
    records = [fm.export_record(u) for u in auth.list_users(app=app).iterate_all()]
    # Owning application from the shared Firestore profile (user/{uid}.role): Mother -> dawamom, Doctor -> dawaclinician.
    from google.cloud import firestore
    roles = {d.id: (d.to_dict() or {}).get('role') for d in firestore.Client(project=project).collection('user').stream()}
    for record in records:
        record['owner_app'] = fsm.account_owner(roles.get(record['uid']))
    return records


def firestore_export(project):
    from google.cloud import firestore
    return fsm.export_documents(firestore.Client(project=project))


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def main(argv=None, env=None, admin=None, ledger=None, firebase_records=None, firestore_records=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=('export', 'plan', 'import', 'reconcile', 'rollback', 'export-data', 'plan-data', 'import-data', 'reconcile-data'))
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
                   'by_owner_app': fm.owner_counts(records), **fm.summarise_accounts([fm.account_facts(r) for r in records])}
        print(json.dumps(fm.assert_no_secrets(summary), indent=2))
        return summary

    if args.command == 'export-data':
        docs, phantom = firestore_records if firestore_records is not None else firestore_export(args.project)
        path, digest = fm.encrypt_export(docs, fm.OUT_DIR / f'firestore-{args.project}-{stamp()}.enc.json')
        summary = {'export_sha256': digest, 'file': str(path), 'phantom_parents_traversed': phantom, **fsm.summarise(docs)}
        print(json.dumps(summary, indent=2))
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
    if ledger is None and (args.execute or args.command in ('reconcile', 'rollback', 'reconcile-data')):
        raise SystemExit('RUDO_MIGRATOR_DATABASE_URL is required (ledger)')

    if args.command.endswith('-data'):
        if args.command == 'plan-data':
            summary = {'mode': 'dry_run', 'export_sha256': digest, **fsm.summarise(records)}
        elif args.command == 'import-data':
            if not args.execute:
                summary = {'mode': 'dry_run', 'export_sha256': digest, 'would_upsert': len(records), **fsm.summarise(records)}
            else:
                run_id = ledger.start(args.project, digest, 'execute', args.actor)
                written = fsm.import_documents(records, args.project, ledger, run_id)
                summary = {'mode': 'execute', 'run_id': run_id, 'upserted': written, **fsm.summarise(records)}
                ledger.finish(run_id, summary)
        else:
            summary = fsm.reconcile_documents(records, args.project, ledger)
        print(json.dumps(summary, indent=2, default=str))
        return summary

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
