## Summary

<!-- What changes and why, in the words of GLOSSARY.md. A diagram, call tree or diff sketch beats prose.
     Reference the ticket: `Closes #N` (the ticket says `Part of #<spec>`) or `Spec: #<spec>`. A `feat` PR
     without a spec by a trusted author is not reviewed: the review compares the result with the spec. -->

## Checks

<!-- Tick what you ran. CI runs `mise run verify` on every push; paste the proof for what it cannot see. -->

- [ ] `mise run verify` is green (locally or in CI)
- [ ] API change: `api/main.tsp` changed first, `mise run generate` run, `frontend/src/api` not edited by hand
- [ ] New or changed behavior has a test (a bug fix has one that fails without the fix)
- [ ] Browser check: `mise run browser-check:verify -- <PR>` says OK for the current head (a `feat` PR brings an `@main` scenario)
- [ ] `GLOSSARY.md` / `docs/adr/` updated if a term or a decision changed
- [ ] No secrets, tokens or `.env*` in the diff

**Evidence:** <!-- before / after: test output, screenshot, request and response -->

## Risk

**Door:** <!-- one-way (data, public contract, released behavior) or two-way -->

**Blast radius:** <!-- one word: who or what breaks if this is wrong (guests, owner, CI, deploy, data) -->

<!-- Optional: what could go wrong and how you would notice. -->

## Rollback

<!-- How to undo it: `git revert` of this commit, a flag to turn off, a data fix. For a one-way door say what stays behind (migrated data, published tag) and how to repair it. -->
