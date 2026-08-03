## Summary

Describe the user-visible or technical change and its scope.

## Verification

- [ ] `python -m pytest -q`
- [ ] `python -m compileall -q app tests`
- [ ] JavaScript syntax checks run if frontend code changed
- [ ] Documentation links checked if Markdown changed

## LineageShield safety

- [ ] No `.env`, token, credential, secret-bearing log, virtual environment, cache, database, or downloaded dependency is included
- [ ] Analysis and preview remain read-only; `DATAHUB_MUTATIONS_ENABLED` stays false in tracked files
- [ ] Live metadata is not fabricated, and inferred criticality remains labeled `inferred`
- [ ] Risk policy and decisions remain deterministic, or policy changes are explicitly reviewed and tested
- [ ] Generated safeguards are described as review-only; no SQL execution is claimed
- [ ] Any write-back change remains root-only, snapshot-backed, explicitly confirmed, and idempotent

