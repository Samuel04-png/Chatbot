"""Regression: verify_backup_restore must parse the Supabase CLI JSON strictly and report errors clearly."""
import json
from types import SimpleNamespace

import pytest

from scripts import verify_backup_restore as v

OK = json.dumps({'boundary': 'b', 'rows': [{'c': {'public.users': 916}}], 'warning': 'untrusted'}, indent=2)  # agent format
TERMINAL = json.dumps([{'c': {'public.users': 916}}], indent=2)  # plain terminal format (the KeyError/'keys: [c]' case)
ERR = json.dumps({'_tag': 'Error', 'error': {'code': 'LegacyDbQueryUnexpectedStatusError',
                                             'message': 'unexpected status 400: {"message":"Failed to run sql query: ERROR:  42501: permission denied for table secrets"}'}})


def test_both_success_formats_return_rows():
    assert v.parse_cli_rows(0, OK, 'Initialising login role...\n') == [{'c': {'public.users': 916}}]
    assert v.parse_cli_rows(0, TERMINAL, 'Initialising login role...\n') == [{'c': {'public.users': 916}}]
    assert v.parse_cli_rows(0, '[]', '') == []
    assert v.parse_cli_rows(0, 'Notice text before json\n' + OK, '') == [{'c': {'public.users': 916}}]


@pytest.mark.parametrize('code,stdout,stderr,expected', [
    (1, ERR, 'Initialising login role...', 'LegacyDbQueryUnexpectedStatusError'),
    (0, ERR, '', 'permission denied'),                                    # error envelope even with exit 0
    (1, '', 'failed to connect to ' + 'postgres' + '://u:' + 'hunter2' + '@db.example:5432/postgres', 'exited 1'),  # synthetic
    (0, '', 'Initialising login role...', 'no JSON'),
    (0, json.dumps({'boundary': 'b', 'warning': 'w'}), '', 'no "rows" list'),  # the original KeyError: 'rows'
    (0, json.dumps({'rows': {'c': 1}}), '', 'no "rows" list'),
    (0, json.dumps({'c': 1}), '', 'no "rows" list'),                       # a bare row object is not a result set
    (0, json.dumps([1, 2]), '', 'not JSON objects'),
    (0, '[{"c": 1', '', 'no JSON'),                                        # truncated output
])
def test_error_shapes_raise_meaningful_errors(code, stdout, stderr, expected):
    with pytest.raises(v.CliQueryError, match=expected) as exc:
        v.parse_cli_rows(code, stdout, stderr)
    assert 'hunter2' not in str(exc.value) and 'postgres://' not in str(exc.value)


def runner(*responses):
    calls = []
    def run(args, **kwargs):
        calls.append(open(args[5]).read())
        return responses[min(len(calls), len(responses)) - 1]
    run.calls = calls
    return run


def test_linked_query_is_read_only_retries_transient_and_checks_row_shape(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda s: None)
    transient = SimpleNamespace(returncode=1, stdout=json.dumps({'_tag': 'Error', 'error': {'code': 'X', 'message': 'unexpected status 503'}}), stderr='')
    ok = SimpleNamespace(returncode=0, stdout=OK, stderr='')
    run = runner(transient, ok)
    assert v.linked_query('SELECT 1 AS c', runner=run) == {'public.users': 916}
    assert v.linked_query('SELECT 1 AS c', runner=runner(SimpleNamespace(returncode=0, stdout=TERMINAL, stderr=''))) == {'public.users': 916}
    assert len(run.calls) == 2 and run.calls[0].startswith('BEGIN READ ONLY; ') and run.calls[0].endswith('; ROLLBACK;')
    with pytest.raises(v.CliQueryError, match='permission denied'):
        v.linked_query('SELECT 1 AS c', runner=runner(SimpleNamespace(returncode=1, stdout=ERR, stderr='')))
    two_rows = SimpleNamespace(returncode=0, stdout=json.dumps({'rows': [{'c': 1}, {'c': 2}]}), stderr='')
    with pytest.raises(v.CliQueryError, match='one row'):
        v.linked_query('SELECT 1 AS c', runner=runner(two_rows))
