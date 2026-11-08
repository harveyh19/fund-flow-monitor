"""Write the weekly digest from docs/ (public signals) and the private holdings
output, in three forms: Markdown for Notion, HTML and plain text for email.

    python tools/digest.py --docs docs --private OUT --dest OUT/digest

Only reads the private folder; never writes personal data back into the repo.
"""
import argparse
import html
import json
from pathlib import Path

DASHBOARD = "https://claude.ai/artifact/5nXsSpzdvskAo2VDUTp8KC"
REPO = "https://github.com/harveyh19/fund-flow-monitor"
EVIDENCE = {
    "strong": "Strong: short interest, which research links to later underperformance.",
    "good": "Good: mainland Southbound flows, which research links to short-term HK returns.",
    "context": "Context: 13F filings, futures positioning and sector ETF flows; background only.",
}
FEED_ORDER = ["US short interest", "HK short positions", "UK short positions",
              "Southbound", "Sector ETF flows", "Futures positioning", "13F (hedge funds)"]
PER_FEED = 6  # alerts listed per feed in the digest; the dashboard has the rest


def _load(p, default):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def _fmt(v, nd=2, sign=False):
    if v is None:
        return "n/a"
    s = f"{float(v):+,.{nd}f}" if sign else f"{float(v):,.{nd}f}"
    return s


def build(docs, private):
    docs = Path(docs)
    sig = _load(docs / "signals.json", {})
    alerts = sig.get("alerts") or []
    us = (sig.get("us_short") or {}).get("market") or {}
    hk = sig.get("hk") or {}
    sbp = hk.get("sb_period") or {}
    tf = (sig.get("thirteen_f") or {}).get("hedge") or {}
    hold = _load(Path(private) / "holdings_signals.json", []) if private else []
    hold_alerts = _load(Path(private) / "holdings_alerts.json", []) if private else []

    gen = (sig.get("generated_at") or "")[:10]
    counts = {e: sum(a.get("evidence") == e for a in alerts) for e in EVIDENCE}
    sb = hk.get("sb_est_net_flow_hkd_bn")
    sbe = hk.get("sb_etf_net_flow_hkd_bn")

    take = []
    if us.get("avg_si_pct") is not None:
        take.append(f"US short interest (S&P 1500 average) is {_fmt(us['avg_si_pct'])}% of shares, "
                    f"percentile {_fmt(us.get('pctile_3y'), 0)} of the last 3 years "
                    f"(FINRA settlement {us.get('date') or 'n/a'}).")
    if sb is not None:
        verb = "sold" if sb < 0 else "bought"
        line = (f"Mainland investors {verb} a net HK${_fmt(abs(sb))}bn of single HK stocks "
                f"({sbp.get('from', '?')} to {sbp.get('to', '?')})")
        if sbe is not None:
            line += f" and moved HK${_fmt(abs(sbe))}bn {'out of' if sbe < 0 else 'into'} index ETFs"
        take.append(line + ".")

    by_feed = {}
    for a in alerts:
        by_feed.setdefault(a.get("feed") or "Other", []).append(a)
    feeds = [f for f in FEED_ORDER if f in by_feed] + [f for f in by_feed if f not in FEED_ORDER]

    status = sig.get("data_status") or {}
    bad = [k for k, v in status.items() if isinstance(v, dict) and v.get("ok") is False]
    asof = {k: v.get("as_of") for k, v in status.items() if isinstance(v, dict) and v.get("as_of")}

    return dict(gen=gen, counts=counts, take=take, by_feed=by_feed, feeds=feeds, hold=hold,
                hold_alerts=hold_alerts, bad=bad, asof=asof, tf=tf, n_alerts=len(alerts))


def _code(t):
    """Tickers go in backticks: Notion would otherwise turn 0700.HK into a web link."""
    return f"`{t}`" if t else ""


def _alert_line(a):
    who = _code(a.get("ticker"))
    name = a.get("name") or ""
    head = f"{who} {name}".strip()
    return f"[{a.get('evidence')}] {head}: {a.get('detail')}"


def to_markdown(d):
    L = [f"Week of {d['gen']}. {d['n_alerts']} alerts: {d['counts']['strong']} strong, "
         f"{d['counts']['good']} good, {d['counts']['context']} context.", ""]
    L += ["## Market takeaway"] + [f"- {t}" for t in d["take"]] + [""]
    L += ["## Your holdings"]
    if d["hold_alerts"]:
        for h in d["hold_alerts"]:
            L.append(f"- **{_code(h['holding'])}** ({h.get('holding_name') or ''}): [{h['evidence']}] "
                     f"{h.get('name') or ''}: {h.get('detail')}")
    else:
        L.append("- No alert touches your holdings this week.")
    quiet = [h["ticker"] for h in d["hold"] if not h.get("alert_count")]
    if quiet:
        L.append(f"- No alert: {', '.join(_code(q) for q in quiet)}.")
    L.append("")
    L += ["## Top alerts by feed"]
    for f in d["feeds"]:
        rows = d["by_feed"][f]
        L.append(f"### {f} ({len(rows)})")
        L += [f"- {_alert_line(a)}" for a in rows[:PER_FEED]]
        if len(rows) > PER_FEED:
            L.append(f"- …and {len(rows) - PER_FEED} more on the dashboard.")
    L.append("")
    L += ["## Data status"]
    L.append("- All feeds downloaded." if not d["bad"] else f"- Failed this week: {', '.join(d['bad'])}.")
    L.append("- Data as of: " + "; ".join(f"{k} {v}" for k, v in d["asof"].items()) + ".")
    if d["tf"].get("period"):
        L.append(f"- 13F quarter: {d['tf']['period']} vs {d.get('tf', {}).get('prev_period')}.")
    L.append("")
    L += ["## Evidence key"] + [f"- {v}" for v in EVIDENCE.values()] + [""]
    L += [f"Dashboard: {DASHBOARD}", f"Code and public data: {REPO}",
          "", "Not investment advice; signals are statistical tendencies, not forecasts for any one stock."]
    return "\n".join(L)


def to_text(md):
    out = []
    for line in md.splitlines():
        if line.startswith("### "):
            line = line[4:].upper()
        elif line.startswith("## "):
            line = "\n" + line[3:].upper()
        line = line.replace("**", "").replace("`", "")
        if line.startswith("- "):
            line = "  * " + line[2:]
        out.append(line)
    return "\n".join(out)


def to_html(md):
    out, in_list = [], False
    for line in md.splitlines():
        esc = html.escape(line)
        # restore bold markers after escaping
        while "**" in esc:
            esc = esc.replace("**", "<b>", 1).replace("**", "</b>", 1)
        while "`" in esc:
            esc = esc.replace("`", "<code>", 1).replace("`", "</code>", 1)
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{esc[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith(("Dashboard: ", "Code and public data: ")):
            label, url = line.split(": ", 1)
            out.append(f'<p>{html.escape(label)}: <a href="{html.escape(url)}">{html.escape(url)}</a></p>')
        elif line.strip():
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    return "<div style=\"font-family:Arial,sans-serif;font-size:14px\">" + "\n".join(out) + "</div>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--private", default=None)
    ap.add_argument("--dest", required=True)
    a = ap.parse_args()
    d = build(a.docs, a.private)
    md = to_markdown(d)
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "digest.md").write_text(md)
    (dest / "digest.txt").write_text(to_text(md))
    (dest / "digest.html").write_text(to_html(md))
    (dest / "subject.txt").write_text(
        f"Fund Flow Monitor, week of {d['gen']}: {d['counts']['strong']} strong alerts, "
        f"{len(d['hold_alerts'])} touching your holdings")
    print(json.dumps({"alerts": d["n_alerts"], "holding_alerts": len(d["hold_alerts"]), "dest": str(dest)}))


if __name__ == "__main__":
    main()
