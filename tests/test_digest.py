"""Digest builder: dummy signals and dummy holdings only (no personal data)."""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import digest  # noqa: E402


def _fixture(tmp_path):
    docs = tmp_path / "docs"
    priv = tmp_path / "priv"
    docs.mkdir()
    priv.mkdir()
    alerts = [{"evidence": "strong", "feed": "US short interest", "ticker": f"T{i}", "name": f"Co {i}",
               "detail": "Short interest 20% of shares"} for i in range(8)]
    alerts.append({"evidence": "good", "feed": "Southbound", "ticker": "0001.HK", "name": "A & B",
                   "detail": "Unusual mainland buying <test>"})
    sig = {"generated_at": "2026-01-03T00:30:00Z", "alerts": alerts,
           "us_short": {"market": {"avg_si_pct": 5.0, "pctile_3y": 80, "date": "2025-12-15"}},
           "hk": {"sb_est_net_flow_hkd_bn": -1.5, "sb_etf_net_flow_hkd_bn": 2.0,
                  "sb_period": {"from": "2025-12-26", "to": "2026-01-02"}},
           "data_status": {"feed_a": {"ok": True, "as_of": "2026-01-02"}, "feed_b": {"ok": False}}}
    (docs / "signals.json").write_text(json.dumps(sig))
    (priv / "holdings_signals.json").write_text(json.dumps(
        [{"ticker": "AAA", "alert_count": 1}, {"ticker": "BBB", "alert_count": 0}]))
    (priv / "holdings_alerts.json").write_text(json.dumps(
        [{"holding": "AAA", "holding_name": "Fund A", "evidence": "strong", "name": "Market", "detail": "x"}]))
    return docs, priv


def test_digest(tmp_path):
    docs, priv = _fixture(tmp_path)
    d = digest.build(docs, priv)
    md = digest.to_markdown(d)
    assert "9 alerts: 8 strong, 1 good, 0 context" in md
    assert "sold a net HK$1.50bn" in md and "HK$2.00bn into index ETFs" in md
    assert "**`AAA`**" in md and "No alert: `BBB`." in md and "`T0` Co 0" in md
    assert "…and 2 more on the dashboard." in md          # 8 US alerts, 6 listed
    assert "Failed this week: feed_b." in md

    h = digest.to_html(md)
    assert "<b><code>AAA</code></b>" in h and "&lt;test&gt;" in h and "A &amp; B" in h

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.err = [], []

        def handle_starttag(self, tag, attrs):
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.err.append(tag)

    p = P()
    p.feed(h)
    assert p.stack == [] and p.err == []
    assert "**" not in digest.to_text(md) and "`" not in digest.to_text(md)


def test_digest_without_holdings(tmp_path):
    docs, _ = _fixture(tmp_path)
    md = digest.to_markdown(digest.build(docs, None))
    assert "No alert touches your holdings this week." in md
