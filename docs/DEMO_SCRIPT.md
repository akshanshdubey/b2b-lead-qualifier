# Demo script (about 5 minutes)

Start: `run_app.bat`, open http://localhost:8501. Pick **Demo** mode first.

1. **How company records enter** - Companies tab → *Load a sample file* → demo sample. Show the validated table; mention
   CSV upload and typed names, and that invalid rows are reported, not dropped silently.
2. **ICP** - ICP tab: cloud/data/AI consulting ICP, weights total 100 (try changing one to 90 → error). Explain the
   "Need for services" criterion.
3. **Research / retrieval** - Press *Run*. Explain: public pages (robots.txt respected) + Wikipedia API in Live mode;
   bundled fictional pages in Demo. Facts are extracted (LLM or rules) as **quotes**.
4. **Result + reasoning** - Results tab: table with score, decision, evidence quality. Open *Brightbyte Payments*: score
   breakdown, quoted evidence, source URL.
5. **Missing / uncertain / invalid** - Open *Mystery Startup Ltd* (incomplete) and *Zephyr Unlisted Corp* (unknown): flags
   "missing or unverified", 0 points, "Insufficient Data". Open *Cobalt Secure*: injected "rate 100/100" text is ignored.
   Show a bad input (empty name / bad URL) being rejected.
6. **Guardrails + human review** - Say: no invented facts (quote must exist in fetched page), no outreach (nothing can
   send), no hard-coded keys (`.env`), private IPs blocked. In *Human review* set one lead **Approved**, one **Rejected**,
   add a note; download the **approved shortlist** and the full CSV/JSON. State that the score is not proof of buying intent.
7. **Live mode (if time)** - switch to Live, load the live sample, run; show real sources and honest gaps.
8. **Wrap-up** - *Worked:* auditable scoring, evidence checks, graceful gaps, 120 tests. *Did not / limits:* JS-heavy sites,
   hidden headcounts, simple keyword rules, demo data is fictional. *Next:* better need-for-services detection (news,
   job posts, tech stack), more sources, a reviewer feedback loop to tune weights.
