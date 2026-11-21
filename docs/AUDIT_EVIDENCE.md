# Audit evidence and verification limits

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Date: 2026-11-20 (Africa/Lusaka). Work directory: `/Users/premierpluspawn/Downloads/chatbot`. The assignment stops at analysis/documentation. Existing application code, assets, requirements and logs were left unchanged.

## Evidence artifacts

| Artifact | Content |
|---|---|
| [SOURCE_INVENTORY.json](SOURCE_INVENTORY.json) | All 64 original file paths, byte sizes and whole-file SHA-256 digests; no source snippets, credentials or patient records |
| [REFERENCE_PROVENANCE.json](REFERENCE_PROVENANCE.json) | Public reference repository, pinned commit and inspected module hashes; source files held outside the project, not copied into application |
| [SYNTAX_CHECK_RESULTS.json](SYNTAX_CHECK_RESULTS.json) | Python parse result and all 18 individual JavaScript syntax check results |

Original-file hashes were captured before writing docs and compared after documentation preparation: **64/64 unchanged**. No Git repository exists in this supplied directory, so this is a filesystem integrity comparison, not a Git diff or history audit. Logs were inventoried and hashed as opaque bytes; their contents were not analyzed or reproduced. Image contents were not inspected. Original source still contains credentials because source remediation is outside this phase.

## Checks actually performed

| Check | Method | Observed result / scope |
|---|---|---|
| File discovery | Recursive local inventory including hidden paths; ancestor AGENTS.md checks | 64 original files; no applicable AGENTS.md found; no local Git/deployment/test/migration metadata |
| Route discovery | Python AST traversal of app.route decorators | Eight explicit routes; methods and line references recorded in CODEBASE_ANALYSIS |
| Python syntax | `ast.parse(Path('app.py').read_text())` | Pass; did not import or execute Flask, initialize providers or start server |
| Shared JS syntax | `node --check` on rudo-auth.js, admin-shell.js and risk-triage.js | 3/3 pass |
| Inline page script syntax | Extract nonempty inline script bodies from all 15 HTML pages into temporary JS files; `node --check` | 15/15 pass; no page scripts executed, no SDK/CDN/provider fetches |
| Auth bypass characterization | Execute only rudo-auth.js in isolated Node VM with synthetic localStorage/sessionStorage/location mocks, no Firebase or network API; await requireAuth | Forged active marker returns null without redirect; confirms fail-open UI behavior, not an approved security expectation |
| Triage characterization | Execute only risk-triage.js in isolated Node VM exposing a window object; call public functions with hand-authored synthetic text | 9/9 baseline assertions below match existing code; no patient content used |
| Local script graph | Parse HTML script src references and compare local files | analytics copy references absent js/script.min.js; twelve JS files have no direct supplied-page script reference |
| Duplicate dashboard check | Byte and line comparison | index/index2 are not byte-identical; only line 541 differs under replacement decoding; index.html contains a non-UTF-8 byte, so encoding needs explicit review before editing |
| Secrets in deliverables | Match known token-shaped source literals plus verification/PIN assignment literals against docs; output only pass/fail | No matched source credential values in prepared deliverables; this is a scoped scan, not a guarantee against every possible secret format |
| Public comparison | Read public GitHub tree/commit and selected raw modules without authentication | Pinned reference accessible; schema file referenced by README absent in tree; no production status established |
| Documentation links | Validate relative Markdown link targets after file creation | All document links required to resolve locally; external references are evidence links, not production endpoint probes |

The nine triage assertions observed:

1. Empty input returns no match.
2. A routine greeting returns no match.
3. Synthetic vaginal bleeding wording matches the existing URGENT rank.
4. Synthetic postpartum hemorrhage wording matches the existing HIGH-MODERATE rank.
5. An explicit bot-role risk phrase is excluded by assessConversation.
6. A risk phrase with no role is included by assessConversation.
7. A higher-ranked match wins over a lower-ranked match across a thread.
8. Repeated conversion of the same synthetic conversation key yields the same display ID; uniqueness is not proven.
9. A negated synthetic symptom phrase still matches, confirming lack of negation understanding.

Together with the auth assertion, **10/10 characterization assertions matched**. They intentionally document unsafe/limited behavior as well as ordinary behavior. They do not establish clinical validity, authorization correctness or migration readiness.

## Safe reproduction examples

From the repository root, these commands parse source without application startup:

```sh
python3 -c 'import ast,pathlib; ast.parse(pathlib.Path("app.py").read_text()); print("Python parse passed")'
node --check js/rudo-auth.js
node --check js/admin-shell.js
node --check js/risk-triage.js
```

The isolated triage characterization can be reproduced without network capabilities in the VM:

```js
// Run through node stdin from the project root; all inputs are synthetic.
const fs = require('fs');
const vm = require('vm');
const c = vm.createContext({ window: {} });
vm.runInContext(fs.readFileSync('js/risk-triage.js', 'utf8'), c);
const t = c.window.RiskTriage;
const checks = [
  t.assessText('') === null,
  t.assessText('Hello') === null,
  t.assessText('vaginal bleeding during pregnancy').priority === 'URGENT',
  t.assessText('postpartum hemorrhage').priority === 'HIGH-MODERATE',
  t.assessConversation([{ role: 'bot', message: 'vaginal bleeding during pregnancy' }]) === null,
  t.assessConversation([{ message: 'vaginal bleeding during pregnancy' }]).priority === 'URGENT',
  t.assessConversation([
    { role: 'user', message: 'postpartum hemorrhage' },
    { role: 'user', message: 'vaginal bleeding during pregnancy' }
  ]).priority === 'URGENT',
  t.toPatientId('conversation:260000000000') === t.toPatientId('conversation:260000000000'),
  t.assessText('I do not have vaginal bleeding during pregnancy') !== null
];
if (checks.some(ok => !ok)) throw new Error('Characterization changed');
console.log('9 existing-behavior assertions matched');
```

The auth characterization used mocked storage and location, not an actual browser/session or Firebase account. No application route was invoked with a provider credential. Future full tests need default-deny socket guards in addition to stubs; this audit did not add that test infrastructure or install dependencies.

## Public-source provenance and cautions

[Reference repository at inspected commit](https://github.com/Samuel04-png/rudo_medgemma/tree/af2545c92aea2cbcda5c6d717f67598b386a373d). Direct raw-file downloads were used for module line references; browser/search cached representations can differ, so provenance hashes identify the inspected bytes. Files inspected include main.py, db.py, requirements.txt, vercel.json, api/index.py, model/translation/language clients, guardrails, NLP endpoints and license. This was a targeted compatibility/security review, not exhaustive clinical/training-data or dependency verification. No training dataset was loaded into the local project.

The public README was treated as claimed intent and compared against code, not as deployment proof. Repository ownership, active deployment, actual schema, credentials, provider permissions, model behavior and data contents remain unverified.

## Not performed / not claimed

- No real WhatsApp send, callback probe, API-version compatibility test or webhook change.
- No Redis/Supabase/Firebase/Meta console access; no use of embedded credentials, production export or patient-data access.
- No SQL/RLS execution, data import/export, schema deployment, project creation or credential rotation.
- No full Flask request tests, browser execution/visual regression, dependency/CVE scan, performance/load test or end-to-end integration suite.
- No Mermaid rendering/visual verification; fenced diagrams were prepared as text.
- No production backup/restore, cutover or rollback rehearsal.
- No medical efficacy, regulatory compliance or deployed security conclusion.

Required future evidence and acceptance tests are in IMPLEMENTATION_CHECKLIST.md and DEPLOYMENT_RUNBOOK.md. Unchecked items are not implied successes.
