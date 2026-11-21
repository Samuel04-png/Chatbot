"""Staff-only Firebase Auth -> Supabase Auth import. DRY RUN unless --execute.

--execute additionally requires --confirm-project equal to the SUPABASE_URL project ref AND to
RUDO_AUTH_IMPORT_ALLOWED_REF. Start with --only-uid on a dedicated test account. Production use needs
separate written approval; nothing here changes Firebase, so Firebase sign-in keeps working.
Requires FIREBASE_SIGNER_KEY/SALT_SEPARATOR/ROUNDS/MEM_COST, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
GOOGLE_APPLICATION_CREDENTIALS and RUDO_CONTROL_ADMIN_DATABASE_URL from the environment or .env.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._env import load_env  # noqa: E402
from scripts.staff_inventory import export_firebase_users  # noqa: E402
from rudo.staff_migration import (HashParams, LinkStore, SupabaseAdmin, assert_no_secrets, classify,  # noqa: E402
                                  project_ref, run_import)


def main(argv=None, env=None, firebase_users=None, admin=None, links=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-project')
    parser.add_argument('--only-uid')
    parser.add_argument('--actor', required=True, help='Approving administrator (recorded in the link audit)')
    args = parser.parse_args(argv)
    env = env if env is not None else load_env()
    url, project = env.get('SUPABASE_URL', ''), env.get('FIREBASE_PROJECT_ID', '')
    if args.execute:
        allowed = env.get('RUDO_AUTH_IMPORT_ALLOWED_REF')
        if not allowed or args.confirm_project != project_ref(url) or allowed != project_ref(url):
            raise SystemExit('Refusing --execute: --confirm-project and RUDO_AUTH_IMPORT_ALLOWED_REF must both match SUPABASE_URL')
    params = HashParams.from_env(env)
    links = links or LinkStore(env.get('RUDO_CONTROL_ADMIN_DATABASE_URL', ''), allow_remote=env.get('RUDO_STAFF_ADMIN_ALLOW_REMOTE') == 'true')
    admin = admin or SupabaseAdmin(url, env.get('SUPABASE_SERVICE_ROLE_KEY', ''))
    firebase_users = firebase_users if firebase_users is not None else export_firebase_users(project)
    report = classify(firebase_users, links.staff_rows(), project)
    results = run_import(report, firebase_users, params, admin, links, url, args.actor,
                         execute=args.execute, only_uid=args.only_uid)
    summary = assert_no_secrets({'mode': 'execute' if args.execute else 'dry-run', 'held': report['held'], 'results': results})
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    main()
