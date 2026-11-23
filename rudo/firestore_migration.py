"""Firestore -> Supabase landing (schema firebase_import), kept separate from Rudo's own tables.

Every document in every collection and sub-collection becomes one row keyed by its full original path,
with original id, parent path, create/update times, owning application and typed JSON data. Exports are
encrypted (same AES-256-GCM key as the account export). Import is an idempotent upsert; reconciliation
compares every path and content hash with the export.
"""
import base64
import collections
import datetime as dt
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

# Owning application per top-level collection (sub-collections inherit). Owner-confirmed on 2026-11-23:
# dawaMom and dawaClinician data land in Rudo's project but stay separate from Rudo's tables.
OWNERS = {
    'mother': 'dawamom', 'mobile_chats': 'dawamom', 'weeks_of_pregenancy': 'dawamom',
    'doctor': 'dawaclinician', 'clinic': 'dawaclinician', 'encounter': 'dawaclinician',
    'first_encounter': 'dawaclinician', 'parity': 'dawaclinician',
    'user': 'dawa_shared_profiles',
    'whatsapp_chats': 'rudo_or_unknown', 'chatbot_users': 'rudo_or_unknown', 'analytics': 'rudo_or_unknown',
    'users': 'dawamom',  # users/{uid}/period_tracker_settings, daily_notes (dawaMom features)
}
ROLE_OWNERS = {'mother': 'dawamom', 'doctor': 'dawaclinician'}


def owner_for(path, owners=None):
    return (owners or OWNERS).get(path.split('/', 1)[0], 'unknown')


def account_owner(role):
    return ROLE_OWNERS.get((role or '').strip().lower(), 'rudo_or_unknown')


def encode(value):
    """Firestore value -> JSON, keeping types that JSON lacks as tagged objects."""
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and value != value:
            return {'__type': 'nan'}
        return value
    if isinstance(value, dt.datetime):
        return {'__type': 'timestamp', 'value': value.astimezone(dt.timezone.utc).isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {'__type': 'bytes', 'base64': base64.b64encode(bytes(value)).decode()}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if hasattr(value, 'latitude') and hasattr(value, 'longitude'):
        return {'__type': 'geopoint', 'latitude': value.latitude, 'longitude': value.longitude}
    if hasattr(value, 'path') and hasattr(value, 'id'):  # DocumentReference
        return {'__type': 'reference', 'path': value.path}
    return {'__type': 'unknown', 'repr': type(value).__name__}


def content_sha256(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _iso(value):
    return value.astimezone(dt.timezone.utc).isoformat() if isinstance(value, dt.datetime) else None


def export_documents(client, workers=16):
    """Walk every collection recursively. Phantom parents (no fields, only sub-collections) are traversed
    and counted but are not documents in Firestore, so they are not exported as rows."""
    records, phantom = [], 0

    def walk(collection_ref, parent_path):
        nonlocal phantom
        present = {}
        for snap in collection_ref.stream():
            data = encode(snap.to_dict() or {})
            present[snap.id] = True
            records.append({'path': snap.reference.path, 'collection_id': collection_ref.id,
                            'collection_path': (collection_ref.parent.path + '/' if collection_ref.parent else '') + collection_ref.id,
                            'doc_id': snap.id, 'parent_path': parent_path, 'data': data,
                            'create_time': _iso(snap.create_time), 'update_time': _iso(snap.update_time),
                            'content_sha256': content_sha256(data)})
        refs = list(collection_ref.list_documents())  # Includes phantom parents.
        with ThreadPoolExecutor(workers) as pool:
            children = list(pool.map(lambda r: (r, list(r.collections())), refs))
        for ref, subs in children:
            if ref.id not in present and subs:
                phantom += 1
            for sub in subs:
                walk(sub, ref.path)

    for top in client.collections():
        walk(top, None)
    return records, phantom


def summarise(records, owners=None):
    by_collection = collections.Counter()
    by_owner = collections.Counter()
    for r in records:
        group = r['collection_path'].split('/', 1)[0] + ('' if '/' not in r['collection_path'] else '/*/' + r['collection_id'])
        by_collection[group] += 1
        by_owner[owner_for(r['path'], owners)] += 1
    return {'documents': len(records), 'by_collection': dict(sorted(by_collection.items())), 'by_owner_app': dict(sorted(by_owner.items()))}


def import_documents(records, project, ledger, run_id, owners=None, batch=500):
    rows = [(project, r['path'], r['collection_id'], r['collection_path'], r['doc_id'], r['parent_path'], owner_for(r['path'], owners),
             json.dumps(r['data'], ensure_ascii=False), r['create_time'], r['update_time'], r['content_sha256'], run_id) for r in records]
    written = 0
    for i in range(0, len(rows), batch):
        written += ledger.upsert_documents(rows[i:i + batch])
    return written


def reconcile_documents(records, project, ledger):
    landed = ledger.document_hashes(project)
    source = {r['path']: r['content_sha256'] for r in records}
    missing = sorted(set(source) - set(landed))
    changed = sorted(p for p in set(source) & set(landed) if source[p] != landed[p])
    extra = sorted(set(landed) - set(source))
    return {'source_documents': len(source), 'landed_documents': len(landed), 'missing': len(missing), 'content_mismatch': len(changed),
            'not_in_this_export': len(extra), 'coverage_complete': not missing and not changed,
            'sample_missing': missing[:20], 'sample_mismatch': changed[:20]}
