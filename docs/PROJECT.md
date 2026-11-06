# Project record

## Objective

Maintainers of many repositories cannot tell at a glance which ones lack a license, tests, CI or a security policy. repo-health scores any local checkout offline, with documented weights, without running repository code, so gaps are visible and CI can gate on a minimum score.

## Scope

- In scope: ten weighted offline checks (DOC001-004, TST001, CI001-002, SEC001-002, MNT001), the `repo_health` public API, and the `python -m repo_health` command line interface with text or JSON output and a `--min-score` gate.
- Out of scope: hosting APIs, coverage measurement, linting, network access, and any runtime dependency.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 471144 / 67954 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.6633 |

## Factory run u083 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2469 | 55648 | 0 | 4246 | 0.2811 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 234 | 5621 | 24585 | 0.0189 |
| fix-2 | claude-sonnet-5-5 | no | 6 | 459 | 6154 | 39940 | 0.0240 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 1434 | 15559 | 74746 | 0.0607 |
| fix-4 | claude-sonnet-5-5 | no | 8 | 825 | 6846 | 55670 | 0.0309 |
| audit | claude-sonnet-5-5 | no | 12 | 4806 | 44296 | 143176 | 0.1731 |
| docs | claude-haiku-5-5 | no | 126274 | 4548 | 0 | 0 | 0.0745 |

Total: $0.6633. Prices: Anthropic list prices.
