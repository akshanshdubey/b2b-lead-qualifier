# Test cases and observations

Run: `python cli.py --input data\sample_companies_demo.csv --mode demo` (all companies below are **fictional** demo data),
and `python -m pytest -v` (120 automated tests).

| # | Company | Type | Score | Decision | Evidence quality | Observation |
|---|---|---|---|---|---|---|
| 1 | Brightbyte Payments | Strong fit (UK fintech, 85 staff, legacy modernisation + cloud migration) | 92.5 | Qualified | High | Size is slightly under the range → half credit, correctly explained. |
| 2 | Titan Steelworks | Strong fit (US manufacturer, 4,500 staff, digital-transformation programme) | 90 | Qualified | High (90%) | Business model unclear on its pages → flagged, no points, not guessed. |
| 3 | Nimbus Freight Software | Good fit (logistics, Netherlands) | 85 | Qualified | High | Region (Netherlands) is not a target, yet it still scores high on signals → good example of why a human must review. |
| 4 | Cobalt Secure | Partial fit + **prompt injection** on its page | 53 | Needs Review | High | Page text asks for "100/100"; it is ignored. Score comes only from verified facts. |
| 5 | Lumora Analytics | Competitor (data analytics vendor) | 75 | Not Qualified | High | Disqualified by the exclusion list despite a high raw score; the reason is stated. |
| 6 | Harvest Table Bistro | Wrong industry (restaurant) | 15 | Not Qualified | High | Excluded industry. |
| 7 | **Mystery Startup Ltd** | **Incomplete record** (almost no information) | 0 | Insufficient Data | Low (35%) | Industry, size, region, model all flagged "missing or unverified"; nothing invented. |
| 8 | **Zephyr Unlisted Corp** | **Unknown company** (no data at all) | 0 | Insufficient Data | Low (0%) | No pages retrieved → every criterion flagged; no facts fabricated. |

## Automated checks (examples)
- A fabricated quote that is not in the fetched page is rejected and earns 0 points.
- A bad/missing API key, rate limit, timeout or malformed LLM JSON never stops the batch (falls back to rules).
- Private/local addresses and non-http(s) URLs are blocked; robots.txt is honoured.
- CSV export neutralises spreadsheet-formula injection (`=HYPERLINK(...)` company names).
- Invalid ICP (weights ≠ 100, bad thresholds) is rejected with a clear message.

## Consistency review
Running the demo twice gives identical scores (scoring is deterministic). Rankings match common sense: strong-fit
non-vendor companies on top, competitors and wrong industries excluded, incomplete records never rated "Qualified".

## Known limitations
- Demo data is fictional; **Live mode must be tried on real companies** (`data/sample_companies_live.csv`) - many real
  sites hide employee counts or render with JavaScript, so expect more *Needs Review* / *Insufficient Data*.
- Keyword rules are simple (e.g. "cloud" can appear in marketing text without a real initiative) - hence human review.
- Region of the Netherlands/EU countries outside the target list scores 0 even if a good fit; edit the ICP to change this.
