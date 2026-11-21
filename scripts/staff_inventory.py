"""READ-ONLY staff account inventory (Firebase Auth vs approved staff records).

Requires: FIREBASE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS (a NEW, rotated key file, gitignored),
RUDO_CONTROL_ADMIN_DATABASE_URL (owner connection to observer_control). Writes no hashes. Prints counts;
the detailed list (emails/UIDs of staff only) goes to the gitignored .local/ directory.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._env import load_env  # noqa: E402
from rudo.staff_migration import LinkStore, assert_no_secrets, classify, firebase_overview  # noqa: E402


def export_firebase_users(project):
    import firebase_admin
    from firebase_admin import auth, credentials
    app = firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': project}, name='rudo-inventory')
    return list(auth.list_users(app=app).iterate_all())


def main(argv=None, env=None, firebase_users=None):
    env = env if env is not None else load_env()
    project = env.get('FIREBASE_PROJECT_ID')
    if not project or not env.get('GOOGLE_APPLICATION_CREDENTIALS'):
        sys.exit('FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS are required')
    if '--firebase-only' in (argv if argv is not None else sys.argv[1:]):
        # No staff database needed: produces the worksheet for the owner-approved staff/facility map.
        report = assert_no_secrets(firebase_overview(firebase_users if firebase_users is not None else export_firebase_users(project)))
        out = Path('.local/firebase-accounts-worksheet.json')
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + '\n')
        out.chmod(0o600)
        print(json.dumps({k: v for k, v in report.items() if k != 'accounts'}, indent=2))
        print(f'Worksheet written to {out} (gitignored, owner-only). Mark approved staff, roles and facilities.')
        return report
    store = LinkStore(env.get('RUDO_CONTROL_ADMIN_DATABASE_URL', ''), allow_remote=env.get('RUDO_STAFF_ADMIN_ALLOW_REMOTE') == 'true')
    report = assert_no_secrets(classify(export_firebase_users(project), store.staff_rows(), project))
    out = Path('.local/staff-inventory.json')
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}, indent=2))
    print(f'Detailed staff-only inventory written to {out} (gitignored). Review it before any import.')


if __name__ == '__main__':
    main()
