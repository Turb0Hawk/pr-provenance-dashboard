# pr-provenance-dashboard

Builds a self-contained HTML dashboard of a repository's pull requests, split by
**who opened them**: automation, a named roster, or everyone else.

The tool is generic. It hardcodes no repository, team, ticket prefix, branch
convention or person — all of that is supplied at run time in a config file.

## Use

    python3 pr_provenance_dashboard.py \
        --config   my-config.json \
        --raw      raw.json \
        --template dashboard-template.html \
        --out      dashboard.html \
        --min-prs  100

`--raw` is a JSON array of pull-request records, one entry per (PR × matching
discovery query); duplicates of the same PR number are merged. See the module
docstring for the accepted shape and which fields are required.

`--config` describes your repo, roster, signals and page copy. Start from
`config.example.json`.

## Config

| key | meaning |
|---|---|
| `repo` | `owner/name`, shown on the page |
| `repoTotalPrs` | total PRs in the repo, for the "N of M" figure |
| `urlTemplate` | fallback PR link; `{n}` becomes the number |
| `routineUrl` | optional; rendered as a "Refresh now" link |
| `categories` | display labels for automation / team / outside |
| `botHints` | substrings that mark an author account as automation |
| `roster` | `{login: name}` — decides team vs outside |
| `names` | `{login: name}` — display only |
| `signals` | `[{key,label,field,pattern,flags,query}]`; `field` is `title`, `head` or `base` |
| `copy` | every user-visible string on the page |

A signal fires when its regex matches the named field. A record may also carry
`matched: ["<signal key>"]`, which is trusted in addition to re-deriving from the
fields — a search qualifier is evaluated server-side and can match even when the
API does not return the field it matched on.

## Keep your config out of this repo

If your config names a private repository, internal ticket conventions or real
people, it is organisation data. Supply it at run time and store it wherever that
data is allowed to live — not here.

## Notes

- Python 3, standard library only. No network access, no git: it consumes `--raw`.
- Refuses to build rather than emit something misleading: it exits non-zero on an
  empty result, on fewer than `--min-prs`, or when no record carries a date.
- Provenance keys off the author account, never the PR title.
- The three category colours are slots 1–3 of a colourblind-validated categorical
  palette, checked in both light and dark mode on the strict all-pairs list.
  Colour never carries meaning alone; every hue is paired with a text label.
