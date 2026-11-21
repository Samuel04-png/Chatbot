"""Split a `supabase db dump --data-only --use-copy` file for restore verification. Prints COUNTS ONLY.

Writes <out>/restorable.sql: session settings, COPY blocks and sequence setvals for application schemas.
Platform schemas (auth, storage, supabase_functions) are version-dependent, so they are not restored
locally; their COPY row counts are reported for comparison with production instead.
Usage: python -I scripts/backup_split.py <data.sql> <out_dir>   -> prints JSON {restorable:{..}, platform:{..}}
"""
import json
import re
import sys
from pathlib import Path

PLATFORM = {'auth', 'storage', 'supabase_functions'}
COPY = re.compile(r'^COPY "?([A-Za-z0-9_]+)"?\."?([A-Za-z0-9_]+)"? .* FROM stdin;$')
SETVAL = re.compile(r"""setval\('"?([A-Za-z0-9_]+)"?\.""")


def split(data_path, out_dir):
    counts = {'restorable': {}, 'platform': {}}
    out = Path(out_dir) / 'restorable.sql'
    with open(data_path, encoding='utf-8') as source, open(out, 'w', encoding='utf-8') as target:
        block, keep = None, True
        for line in source:
            if block is None:
                match = COPY.match(line.rstrip('\n'))
                if match:
                    schema, table = match.groups()
                    block, keep = f'{schema}.{table}', schema not in PLATFORM
                    counts['restorable' if keep else 'platform'][block] = 0
                    if keep:
                        target.write(line)
                    continue
                setval = SETVAL.search(line)
                if setval and setval.group(1) in PLATFORM:
                    continue
                if not line.startswith(('COPY ', 'INSERT ')):
                    target.write(line)  # SET statements, setvals for application schemas, comments.
                continue
            if line.rstrip('\n') == '\\.':
                if keep:
                    target.write(line)
                block = None
                continue
            counts['restorable' if keep else 'platform'][block] += 1
            if keep:
                target.write(line)
    if block is not None:
        raise SystemExit('Truncated dump: unterminated COPY block')
    return counts


if __name__ == '__main__':
    print(json.dumps(split(sys.argv[1], sys.argv[2]), sort_keys=True))
