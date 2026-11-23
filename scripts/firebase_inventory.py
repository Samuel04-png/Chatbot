"""READ-ONLY inventory of the whole Firebase project used by Rudo (Auth, Firestore, Realtime Database,
Storage, registered apps, enabled services). Nothing is written to Firebase or Supabase.

Credentials: your own Google account through Application Default Credentials (short-lived, revocable):
    gcloud auth application-default login
    gcloud auth application-default set-quota-project dawa-ca263
Never a downloaded service-account key, and never the exposed key 43a1573c...

Output:
  stdout                                  aggregate counts only (no emails, UIDs, hashes or document data)
  ~/.rudo-migration/inventory-<ts>.json   per-account worksheet and per-collection detail, mode 0600,
                                          outside the Git repository; contains emails/UIDs, no hashes.
Usage: .venv/bin/python scripts/firebase_inventory.py --project dawa-ca263 [--skip-data] [--id-scan-limit 20000]
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rudo.firebase_migration import OUT_DIR, account_facts, secure_write, summarise_accounts  # noqa: E402

SCOPES = ['https://www.googleapis.com/auth/cloud-platform', 'https://www.googleapis.com/auth/firebase',
          'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/firebase.database']
EXPOSED_KEY_PREFIX = '43a1573c'


def credentials(project):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    keyfile = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if keyfile and Path(keyfile).expanduser().exists():
        if json.loads(Path(keyfile).expanduser().read_text()).get('private_key_id', '').startswith(EXPOSED_KEY_PREFIX):
            sys.exit('Refusing the exposed, compromised service-account key.')
    try:
        creds, _ = google.auth.default(scopes=SCOPES, quota_project_id=project)
    except google.auth.exceptions.DefaultCredentialsError:
        sys.exit('No Google login found. Run: gcloud auth application-default login (see docs/auth-migration/FULL_MIGRATION.md)')
    return creds, AuthorizedSession(creds)


def section(name, fn, report):
    try:
        report[name] = fn()
    except Exception as exc:  # One unavailable service must not hide the others.
        status = getattr(getattr(exc, 'response', None), 'status_code', None) or getattr(exc, 'code', None)
        report[name] = {'error': type(exc).__name__, 'status': str(status) if status else None}


def get_json(session, url, **params):
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def apps(session, project):
    base = f'https://firebase.googleapis.com/v1beta1/projects/{project}'
    project_info = get_json(session, base)
    out = {'project': {k: project_info.get(k) for k in ('projectId', 'projectNumber', 'displayName', 'state')}}
    for kind, id_field in (('webApps', None), ('androidApps', 'packageName'), ('iosApps', 'bundleId')):
        items = get_json(session, f'{base}/{kind}', pageSize=100).get('apps', [])
        out[kind] = [{'displayName': a.get('displayName'), 'appId': a.get('appId'), 'state': a.get('state'),
                      **({id_field: a.get(id_field)} if id_field else {})} for a in items]
    return out


def services(session, project):
    data = get_json(session, f'https://serviceusage.googleapis.com/v1/projects/{project}/services', filter='state:ENABLED', pageSize=200)
    names = sorted(s['config']['name'] for s in data.get('services', []))
    interesting = ('firestore', 'firebasedatabase', 'storage', 'cloudfunctions', 'firebasehosting', 'fcm', 'firebaseremoteconfig',
                   'identitytoolkit', 'run.googleapis', 'pubsub', 'cloudscheduler', 'firebaseextensions', 'firebaseappcheck')
    return {'enabled_count': len(names), 'relevant': [n for n in names if any(i in n for i in interesting)]}


def auth_config(session, project):
    cfg = get_json(session, f'https://identitytoolkit.googleapis.com/admin/v2/projects/{project}/config')
    sign_in = cfg.get('signIn', {})
    idps = get_json(session, f'https://identitytoolkit.googleapis.com/admin/v2/projects/{project}/defaultSupportedIdpConfigs').get('defaultSupportedIdpConfigs', [])
    return {'email_enabled': sign_in.get('email', {}).get('enabled'), 'password_required': sign_in.get('email', {}).get('passwordRequired'),
            'phone_enabled': sign_in.get('phoneNumber', {}).get('enabled'), 'anonymous_enabled': sign_in.get('anonymous', {}).get('enabled'),
            'allow_duplicate_emails': sign_in.get('allowDuplicateEmails'),
            'hash_algorithm': (sign_in.get('hashConfig') or {}).get('algorithm'),  # Parameters themselves are never printed.
            'idps': sorted((i.get('name', '').rsplit('/', 1)[-1], bool(i.get('enabled'))) for i in idps),
            'mfa_state': (cfg.get('mfa') or {}).get('state'), 'multi_tenant': bool((cfg.get('multiTenant') or {}).get('allowTenants'))}


def auth_users(project):
    import firebase_admin
    from firebase_admin import auth, credentials as fb_credentials
    app = firebase_admin.initialize_app(fb_credentials.ApplicationDefault(), {'projectId': project}, name='rudo-inventory')
    users = list(auth.list_users(app=app).iterate_all())
    tenants = []
    try:
        from firebase_admin import tenant_mgt
        tenants = [t.tenant_id for t in tenant_mgt.list_tenants(app=app).iterate_all()]
    except Exception:
        pass  # Identity Platform tenants not enabled.
    return users, tenants


def firestore_inventory(session, project, id_scan_limit, uids):
    from google.cloud import firestore
    dbs = get_json(session, f'https://firestore.googleapis.com/v1/projects/{project}/databases').get('databases', [])
    out = []
    for db in dbs:
        db_id = db['name'].rsplit('/', 1)[-1]
        client = firestore.Client(project=project, database=db_id)
        entry = {'database': db_id, 'type': db.get('type'), 'location': db.get('locationId'), 'collections': []}
        sub_ids = set()
        for col in client.collections():
            count = col.count().get()[0][0].value
            ids, fields = [], collections.Counter()
            for i, doc in enumerate(col.select([]).limit(id_scan_limit).stream()):
                ids.append(doc.id)
            for doc in col.limit(25).stream():  # Field names only (schema shape), never values.
                fields.update((doc.to_dict() or {}).keys())
                sub_ids.update(c.id for c in doc.reference.collections())
            entry['collections'].append({'path': col.id, 'documents': count, 'doc_ids_matching_auth_uid': len(set(ids) & uids),
                                         'scanned_ids': len(ids), 'top_fields': [f for f, _ in fields.most_common(25)]})
        entry['subcollection_groups'] = [{'group': g, 'documents': client.collection_group(g).count().get()[0][0].value}
                                         for g in sorted(sub_ids)]
        out.append(entry)
    return out


def rtdb_inventory(session, project):
    instances = get_json(session, f'https://firebasedatabase.googleapis.com/v1beta/projects/{project}/locations/-/instances').get('instances', [])
    out = []
    for inst in instances:
        url = inst.get('databaseUrl')
        entry = {'instance': inst.get('name', '').rsplit('/', 1)[-1], 'type': inst.get('type'), 'state': inst.get('state'), 'top_level': []}
        root = get_json(session, f'{url}/.json', shallow='true') or {}
        for key in sorted(root) if isinstance(root, dict) else []:
            child = get_json(session, f'{url}/{key}.json', shallow='true')
            entry['top_level'].append({'key': key, 'children': len(child) if isinstance(child, dict) else (0 if child is None else 1)})
        out.append(entry)
    return out


def storage_inventory(project):
    from google.cloud import storage
    client = storage.Client(project=project)
    names = {b.name for b in client.list_buckets()} | {f'{project}.appspot.com'}
    out = []
    for name in sorted(names):
        try:
            prefixes = collections.defaultdict(lambda: {'objects': 0, 'bytes': 0, 'types': collections.Counter()})
            for blob in client.list_blobs(name):
                p = prefixes[blob.name.split('/', 1)[0] if '/' in blob.name else '(root)']
                p['objects'] += 1; p['bytes'] += blob.size or 0; p['types'][blob.content_type or 'unknown'] += 1
            out.append({'bucket': name, 'objects': sum(p['objects'] for p in prefixes.values()),
                        'bytes': sum(p['bytes'] for p in prefixes.values()),
                        'prefixes': {k: {**v, 'types': dict(v['types'].most_common(5))} for k, v in sorted(prefixes.items())}})
        except Exception as exc:
            out.append({'bucket': name, 'error': type(exc).__name__})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only Firebase project inventory')
    parser.add_argument('--project', required=True)
    parser.add_argument('--skip-data', action='store_true', help='Auth and project metadata only')
    parser.add_argument('--id-scan-limit', type=int, default=20000)
    args = parser.parse_args(argv)
    if args.project != 'dawa-ca263':
        sys.exit('Rudo uses Firebase project dawa-ca263 (js/rudo-auth.js); refusing another project.')
    _, session = credentials(args.project)
    report = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'firebase_project': args.project}
    section('apps', lambda: apps(session, args.project), report)
    section('services', lambda: services(session, args.project), report)
    section('auth_config', lambda: auth_config(session, args.project), report)
    users, tenants = auth_users(args.project)
    facts = [account_facts(u) for u in users]
    report['auth'] = {**summarise_accounts(facts), 'tenants': len(tenants)}
    uids = {f['uid'] for f in facts}
    if not args.skip_data:
        section('firestore', lambda: firestore_inventory(session, args.project, args.id_scan_limit, uids), report)
        section('realtime_database', lambda: rtdb_inventory(session, args.project), report)
        section('storage', lambda: storage_inventory(args.project), report)
    detail = {**report, 'accounts': facts}
    path = secure_write(OUT_DIR / f"inventory-{report['generated_at'][:19].replace(':', '')}.json", json.dumps(detail, indent=2, default=str))
    printable = json.loads(json.dumps(report, default=str))
    for db in printable.get('firestore', []) if isinstance(printable.get('firestore'), list) else []:
        for col in db['collections']:
            col.pop('top_fields', None)  # Field names stay in the 0600 file.
    print(json.dumps(printable, indent=2))
    print(f'\nPer-account worksheet (emails/UIDs, no hashes): {path}')


if __name__ == '__main__':
    main()
