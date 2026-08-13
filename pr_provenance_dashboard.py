#!/usr/bin/env python3
"""Build a pull-request provenance dashboard from raw PR records.

Generic tool. It knows nothing about any particular repository, team, ticket
convention or branch layout: every one of those is supplied at run time by a
config file. Nothing organisation-specific is stored in this script.

    python3 pr_provenance_dashboard.py \\
        --config  org-config.json \\
        --raw     raw.json \\
        --template dashboard-template.html \\
        --out     dashboard.html

Provenance splits every PR three ways by WHO OPENED IT:
  * automation - the author account looks like a bot (config: botHints)
  * team       - the author is on the roster (config: roster)
  * outside    - anyone else

CONFIG (all organisation-specific input lives here, never in this file):
    repo          "owner/name", shown on the page
    repoTotalPrs  total PRs in the repo, for the "N of M" figure
    urlTemplate   fallback PR link, "{n}" is replaced by the number
    routineUrl    optional; linked as "Refresh now"
    categories    {automation|team|outside: display label}
    botHints      substrings that mark an author account as automation
    roster        {login: real name} - decides team vs outside
    names         {login: real name} - display only, no effect on provenance
    signals       [{key,label,field,pattern,flags,query}] - field is
                  title|head|base; pattern is a Python/JS-compatible regex,
                  flags "i" for case-insensitive. `query` documents the GitHub
                  search that finds it and is not used by this script.
    copy          every user-visible string on the page

RAW INPUT (list, or {"prs":[...]}), one object per (PR x matching query):
    {"number":123,"matched":["<signal key>"],"title":"...",
     "author":"some-github-login","state":"MERGED"|"OPEN"|"CLOSED",
     "isDraft":false,"createdAt":"2026-01-02T...","mergedAt":null,
     "url":"...","headRefName":"...","baseRefName":"...",
     "additions":0,"deletions":0,"changedFiles":0,"labels":[]}

`number`, `createdAt` and `state` are required; everything else is optional and
omitting a key is always safer than guessing a value. `matched` carries the
signal key of the query that returned the PR: trust it in addition to
re-deriving from the fields, because a search qualifier is evaluated
server-side and may match even when the API does not hand back the field it
matched on. Duplicates of the same PR number are MERGED, not overwritten.
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
from collections import Counter


def load_config(path):
    cfg = json.load(io.open(path, encoding="utf-8"))
    missing = [k for k in ("repo", "signals", "copy") if k not in cfg]
    if missing:
        sys.exit("config %s is missing required key(s): %s" % (path, ", ".join(missing)))
    compiled = []
    for s in cfg["signals"]:
        for k in ("key", "label", "field", "pattern"):
            if k not in s:
                sys.exit("config signal %r is missing %r" % (s.get("key", s), k))
        if s["field"] not in ("title", "head", "base"):
            sys.exit("config signal %r: field must be title, head or base (got %r)"
                     % (s["key"], s["field"]))
        flags = re.IGNORECASE if "i" in (s.get("flags") or "") else 0
        try:
            rx = re.compile(s["pattern"], flags)
        except re.error as e:
            sys.exit("config signal %r has an invalid pattern: %s" % (s["key"], e))
        compiled.append((s["key"], s["field"], rx))
    cfg["_compiled"] = compiled
    cfg["_labels"] = {s["key"]: s["label"] for s in cfg["signals"]}
    return cfg


def derive_signals(cfg, title, head, base):
    """Which configured signals match this PR's own fields."""
    values = {"title": title or "", "head": head or "", "base": base or ""}
    return sorted({key for key, field, rx in cfg["_compiled"]
                   if rx.search(values[field])})


def provenance(cfg, login):
    lu = (login or "").lower()
    for hint in cfg.get("botHints") or []:
        if hint.lower() in lu:
            return "automation"
    return "team" if login in (cfg.get("roster") or {}) else "outside"


def norm_state(state, is_draft, merged_at=None):
    """Merged wins over closed.

    GitHub's SEARCH api reports a merged pull request as state "closed"; the only
    discriminator is a non-null merged_at. Trusting `state` alone therefore files
    every merged PR as "closed unmerged". A caller that supplies a real MERGED
    state still works, so both shapes are handled.
    """
    s = (state or "").upper()
    if s == "MERGED" or merged_at:
        return "merged"
    if s == "OPEN":
        return "draft" if is_draft else "open"
    return "closed"


def coerce(cfg, raw):
    """Normalise raw records, tolerating field-name variants, and MERGE duplicates."""
    if isinstance(raw, dict) and "prs" in raw:
        raw = raw["prs"]
    if not isinstance(raw, list):
        sys.exit("raw input must be a list of PRs or {'prs':[...]}")

    known = set(cfg["_labels"])
    url_tpl = cfg.get("urlTemplate") or ""
    out = {}

    for pr in raw:
        num = pr.get("number") or pr.get("n")
        if not num:
            continue
        author = pr.get("author") or pr.get("login") or pr.get("user") or ""
        if isinstance(author, dict):
            author = author.get("login") or ""
        title = pr.get("title") or pr.get("t") or ""
        head = pr.get("headRefName") or pr.get("head") or pr.get("headRef") or ""
        base = pr.get("baseRefName") or pr.get("base") or pr.get("baseRef") or ""
        labels = [l.get("name") if isinstance(l, dict) else l
                  for l in (pr.get("labels") or [])]
        created = (pr.get("createdAt") or pr.get("created_at") or pr.get("c") or "")[:10]
        merged = (pr.get("mergedAt") or pr.get("merged_at") or pr.get("m")
                  or (pr.get("pull_request") or {}).get("merged_at") or "")
        merged = merged[:10] if merged else ""
        url = pr.get("url") or pr.get("html_url") or url_tpl.replace("{n}", str(num))

        matched = pr.get("matched") or pr.get("_signals") or []
        if isinstance(matched, str):
            matched = [matched]
        matched = [s for s in matched if s in known]

        rec = {
            "n": num, "t": title, "u": author or "(unknown)",
            "p": provenance(cfg, author),
            "st": norm_state(pr.get("state"),
                             pr.get("isDraft") or pr.get("draft"),
                             merged),
            "c": created, "m": merged,
            "a": int(pr.get("additions") or pr.get("a") or 0),
            "d": int(pr.get("deletions") or pr.get("d") or 0),
            "f": int(pr.get("changedFiles") or pr.get("changed_files") or pr.get("f") or 0),
            "hb": head, "bb": base,
            "lb": [x for x in labels if x],
            "sg": sorted(set(derive_signals(cfg, title, head, base)) | set(matched)),
            "url": url,
        }

        prev = out.get(num)
        if prev is None:
            out[num] = rec
            continue
        # One record arrives per matching query. Union the signals - overwriting
        # would keep only the last query's - and never let a later record with a
        # blank field erase a value an earlier one supplied.
        prev["sg"] = sorted(set(prev["sg"]) | set(rec["sg"]))
        for key in ("t", "u", "c", "m", "hb", "bb", "url", "a", "d", "f"):
            if not prev.get(key) and rec.get(key):
                prev[key] = rec[key]
        if not prev.get("lb") and rec.get("lb"):
            prev["lb"] = rec["lb"]
        prev["p"] = provenance(cfg, prev["u"])
        prev["sg"] = sorted(set(prev["sg"])
                            | set(derive_signals(cfg, prev["t"], prev["hb"], prev["bb"])))
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="organisation config JSON")
    ap.add_argument("--raw", required=True, help="raw PR records JSON")
    ap.add_argument("--template", required=True, help="page template with __DATA__")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--data-out", default="data.json")
    ap.add_argument("--generated", default=None, help="stamp; defaults to now (UTC)")
    ap.add_argument("--min-prs", type=int, default=1,
                    help="refuse to build with fewer than this many PRs")
    args = ap.parse_args()

    cfg = load_config(args.config)
    rows = coerce(cfg, json.load(io.open(args.raw, encoding="utf-8")))

    dropped = [r["n"] for r in rows if not r["sg"]]
    if dropped:
        sys.stderr.write("WARNING: %d PRs matched no signal, dropping: %s\n"
                         % (len(dropped), dropped[:20]))
        rows = [r for r in rows if r["sg"]]
    if not rows:
        sys.exit("no PRs after processing - refusing to build an empty dashboard")
    if len(rows) < args.min_prs:
        sys.exit("only %d PRs, below --min-prs %d - refusing to build (this usually "
                 "means a search truncated)" % (len(rows), args.min_prs))

    dated = [r for r in rows if r["c"]]
    if not dated:
        sys.exit("no PR has a createdAt date - the search must return createdAt; "
                 "refusing to build a dashboard with no timeline")
    if len(dated) < len(rows):
        sys.stderr.write("WARNING: %d of %d PRs lack createdAt and will be absent "
                         "from the timeline\n" % (len(rows) - len(dated), len(rows)))

    rows.sort(key=lambda r: r["c"], reverse=True)

    names = dict(cfg.get("names") or {})
    names.update(cfg.get("roster") or {})
    gen = args.generated or datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y-%m-%d %H:%M UTC")

    meta = {
        "repo": cfg["repo"],
        "generated": gen,
        "total": len(rows),
        "repoTotalPrs": cfg.get("repoTotalPrs") or 0,
        "first": min(r["c"] for r in dated),
        "last": max(r["c"] for r in dated),
        "provCounts": dict(Counter(r["p"] for r in rows)),
        "stateCounts": dict(Counter(r["st"] for r in rows)),
        "categories": cfg.get("categories") or {
            "automation": "Automation", "team": "Team", "outside": "Everyone else"},
        "roster": cfg.get("roster") or {},
        "bots": sorted({r["u"] for r in rows if r["p"] == "automation"}),
        "names": names,
        "signalLabels": cfg["_labels"],
        "authorCount": len({r["u"] for r in rows if r["p"] != "automation"}),
        "routineUrl": cfg.get("routineUrl") or "",
        "copy": cfg["copy"],
    }

    payload = json.dumps({"meta": meta, "rows": rows},
                         ensure_ascii=False, separators=(",", ":"))
    io.open(args.data_out, "w", encoding="utf-8").write(payload)

    tpl = io.open(args.template, encoding="utf-8").read()
    if "__DATA__" not in tpl:
        sys.exit("template %s has no __DATA__ placeholder" % args.template)
    doc_title = (cfg["copy"].get("docTitle") or "Pull request provenance")
    html = tpl.replace("__TITLE__", doc_title) \
              .replace("__DATA__", payload.replace("</", "<\\/"))
    if "__TITLE__" in tpl and doc_title not in html:
        sys.exit("failed to substitute __TITLE__")
    io.open(args.out, "w", encoding="utf-8").write(html)

    print("built: %d PRs | provenance=%s | span %s..%s"
          % (len(rows), meta["provCounts"], meta["first"], meta["last"]))
    print("wrote %s (%d bytes)" % (args.out, os.path.getsize(args.out)))


if __name__ == "__main__":
    main()
