"""Streamlit dashboard: AI-Powered B2B Lead Qualification (public data only, no outreach)."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from leadgen.config import DATA_DIR, load_settings
from leadgen.exporter import (DISCLAIMER, REVIEW_STATUSES, results_to_csv, results_to_dataframe,
                              results_to_json)
from leadgen.icp import CRITERIA, CRITERIA_LABELS, ICP, ICPError
from leadgen.llm import LLMError
from leadgen.pipeline import run_pipeline
from leadgen.scoring import DECISIONS
from leadgen.validation import (ValidationError, limit_companies, parse_company_lines, parse_csv)

st.set_page_config(page_title="B2B Lead Qualification", page_icon="🎯", layout="wide")
settings = load_settings()

DECISION_ICON = {"Qualified": "🟢", "Needs Review": "🟡", "Not Qualified": "🔴", "Insufficient Data": "⚪"}

# ------------------------------------------------------------------ session state
if "icp" not in st.session_state:
    st.session_state.icp = ICP.load(DATA_DIR / "icp_default.json")
if "results" not in st.session_state:
    st.session_state.results = []
if "companies" not in st.session_state:
    st.session_state.companies = []
if "reviews" not in st.session_state:
    st.session_state.reviews = {}
if "input_notes" not in st.session_state:
    st.session_state.input_notes = []

icp: ICP = st.session_state.icp

# ------------------------------------------------------------------ header
st.title("🎯 B2B Lead Qualification Dashboard")
st.caption("Researches **public** company information, scores it against your ICP, and shows the "
           "evidence behind every point. It never contacts prospects and never invents sources.")
st.info("**A score supports human review. It is not proof that a company is ready to buy.** "
        "Every lead needs a person to approve or reject it in the *Human review* section of the Results tab.")

with st.sidebar:
    st.header("Run settings")
    mode_label = st.radio(
        "Research mode",
        ["Demo (offline, fictional companies)", "Live (public web + Wikipedia)"], key="mode_label",
        help="Demo needs no internet or API key. Live fetches public pages, honouring robots.txt.")
    mode = "demo" if mode_label.startswith("Demo") else "live"
    extractor_options = {"Auto (LLM if API key set)": "auto", "LLM only": "llm", "Rules only (free)": "rules"}
    extractor_label = st.selectbox("Extractor", list(extractor_options), key="extractor_label")
    extractor = extractor_options[extractor_label]
    if settings.has_api_key:
        st.success(f"API key loaded from .env · model `{settings.model}`")
    else:
        st.warning("No API key found. Rules-only extraction will be used.\n\n"
                   "Add `ANTHROPIC_API_KEY` to your `.env` file to enable the LLM.")
    st.caption(f"Max {settings.max_companies} companies per run.")
    st.divider()
    st.caption(DISCLAIMER)

tab_in, tab_icp, tab_res, tab_how = st.tabs(["1 · Companies", "2 · ICP settings", "3 · Results & export", "How it works"])

# ------------------------------------------------------------------ tab 1: input
with tab_in:
    method = st.radio("Input method", ["Type company names", "Upload CSV", "Load a sample file"],
                      horizontal=True, key="method")
    parsed, notes = None, []
    try:
        if method == "Type company names":
            text = st.text_area(
                "One company per line. Optional website after `|` or a comma.", height=170, key="names_text",
                placeholder="HubSpot | hubspot.com\nOkta\nAcme Corp, acme.com")
            parsed, notes = parse_company_lines(text)
        elif method == "Upload CSV":
            up = st.file_uploader("CSV with a `company_name` column (and optional `website`)",
                                  type=["csv"], key="csv_upload")
            if up is not None:
                parsed, notes = parse_csv(up.getvalue())
        else:
            choice = st.selectbox("Sample file", ["Demo sample (fictional - use Demo mode)",
                                                  "Live sample (real public companies - use Live mode)"],
                                  key="sample_choice")
            fname = "sample_companies_demo.csv" if choice.startswith("Demo") else "sample_companies_live.csv"
            parsed, notes = parse_csv((DATA_DIR / fname).read_bytes())
    except ValidationError as exc:
        st.error(str(exc))

    if parsed is not None:
        parsed, limit_note = limit_companies(parsed, settings.max_companies)
        if limit_note:
            notes.append(limit_note)
        st.session_state.companies = parsed
    else:
        st.session_state.companies = []
    for n in notes:
        st.warning(n)

    companies = st.session_state.companies
    if companies:
        st.write(f"**{len(companies)} valid companies ready**")
        st.dataframe(pd.DataFrame([{"Company": c.name, "Website": c.website or "(not provided)"}
                                   for c in companies]), hide_index=True)
    else:
        st.info("Add at least one valid company to continue.")

    if mode == "live" and companies:
        st.info("Live mode makes a few HTTP requests per company (about 1 second apart) and, if "
                "enabled, one small LLM call per company.")

    if st.button("▶ Run research & scoring", type="primary", disabled=not companies, key="run_btn"):
        bar = st.progress(0.0, text="Starting…")

        def on_progress(done: int, total: int, name: str) -> None:
            bar.progress(done / max(total, 1), text=f"Researching {name}…" if name != "done" else "Finished")

        try:
            st.session_state.results = run_pipeline(companies, icp, settings, mode=mode,
                                                    extractor=extractor, progress=on_progress)
            st.success(f"Done - {len(st.session_state.results)} companies processed. Open the Results tab.")
        except (LLMError, ICPError, ValueError) as exc:
            st.error(f"Could not run: {exc}")
        finally:
            bar.empty()

# ------------------------------------------------------------------ tab 2: ICP
with tab_icp:
    st.subheader("Ideal Customer Profile")
    st.caption("Change the criteria, then press **Apply ICP**. Weights must add up to 100.")
    with st.form("icp_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("ICP name", icp.name)
        model = c2.selectbox("Target business model", ["B2B", "B2C"], index=0 if icp.target_business_model == "B2B" else 1)
        t_ind = c1.text_area("Target industries (one per line)", "\n".join(icp.target_industries), height=130)
        x_ind = c2.text_area("Excluded industries (one per line)", "\n".join(icp.excluded_industries), height=130)
        regions = c1.text_area("Target regions / countries (one per line)", "\n".join(icp.target_regions), height=110)
        sigs = c2.text_area("Buying-signal keywords (one per line)", "\n".join(icp.buying_signal_keywords), height=110)
        e1, e2 = st.columns(2)
        min_e = e1.number_input("Min employees", 0, 10_000_000, icp.min_employees, step=10)
        max_e = e2.number_input("Max employees", 0, 10_000_000, icp.max_employees, step=50)
        st.markdown("**Scoring weights (must total 100)**")
        wcols = st.columns(len(CRITERIA))
        weights = {k: int(wc.number_input(CRITERIA_LABELS[k], 0, 100, icp.weights[k], step=5, key=f"w_{k}"))
                   for k, wc in zip(CRITERIA, wcols)}
        t1, t2, t3, t4 = st.columns(4)
        q_thr = t1.number_input("Qualified at ≥", 0, 100, icp.qualified_threshold)
        r_thr = t2.number_input("Needs review at ≥", 0, 100, icp.review_threshold)
        cov = t3.slider("Min verified data coverage", 0.0, 1.0, float(icp.min_coverage), 0.05)
        unk = t4.slider("Credit for unknown data", 0.0, 0.5, float(icp.unknown_credit), 0.05,
                        help="0 = unknown criteria earn nothing (strict, recommended).")
        submitted = st.form_submit_button("Apply ICP", type="primary")
    if submitted:
        try:
            st.session_state.icp = ICP.from_dict({
                "name": name, "target_business_model": model, "target_industries": t_ind,
                "excluded_industries": x_ind, "target_regions": regions, "buying_signal_keywords": sigs,
                "min_employees": min_e, "max_employees": max_e, "weights": weights,
                "qualified_threshold": q_thr, "review_threshold": r_thr, "min_coverage": cov,
                "unknown_credit": unk})
            st.success("ICP applied. Re-run research to rescore.")
            icp = st.session_state.icp
        except ICPError as exc:
            st.error(str(exc))
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ Download ICP (JSON)", json.dumps(icp.to_dict(), indent=2),
                       "icp.json", "application/json", key="dl_icp")
    icp_up = d2.file_uploader("Load ICP JSON", type=["json"], key="icp_upload", label_visibility="collapsed")
    if icp_up is not None:
        try:
            st.session_state.icp = ICP.from_dict(json.loads(icp_up.getvalue().decode("utf-8")))
            st.success("ICP loaded - values above update after the next interaction.")
        except (ICPError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            st.error(f"Invalid ICP file: {exc}")
    if d3.button("Reset to default", key="reset_icp"):
        st.session_state.icp = ICP.load(DATA_DIR / "icp_default.json")
        st.rerun()

# ------------------------------------------------------------------ tab 3: results
with tab_res:
    results = st.session_state.results
    if not results:
        st.info("No results yet. Add companies and press **Run research & scoring**.")
    else:
        counts = {d: sum(1 for r in results if r.score and r.score.decision == d) for d in DECISIONS}
        errors = sum(1 for r in results if r.status == "error")
        cols = st.columns(len(DECISIONS) + 1)
        cols[0].metric("Companies", len(results))
        for col, d in zip(cols[1:], DECISIONS):
            col.metric(f"{DECISION_ICON[d]} {d}", counts[d])
        if errors:
            st.error(f"{errors} companies failed - see their rows below.")

        df = results_to_dataframe(results, st.session_state.reviews)
        f1, f2 = st.columns([2, 1])
        shown = f1.multiselect("Show decisions", list(DECISIONS) + ["Error"], default=list(DECISIONS) + ["Error"], key="flt_dec")
        min_score = f2.slider("Minimum score", 0, 100, 0, key="flt_score")
        view = df[df["Decision"].isin(shown) & (df["Score"].fillna(0) >= min_score)]
        st.dataframe(
            view[["Company", "Score", "Decision", "Data Coverage %", "Industry", "Employees", "HQ Region",
                  "Evidence Quality", "Business Model", "Buying Signals", "Review Status", "Explanation"]],
            hide_index=True,
            column_config={"Score": st.column_config.ProgressColumn("Score /100", min_value=0, max_value=100, format="%.0f"),
                           "Data Coverage %": st.column_config.NumberColumn("Verified data %", format="%d%%")})
        if not view.empty:
            st.bar_chart(view.set_index("Company")["Score"])

        st.subheader("Human review (required before any outreach)")
        st.caption("Approve or reject each lead and add a note. Nothing is ever sent to a prospect - "
                   "the output is a reviewable shortlist.")
        rv = pd.DataFrame([{"Company": r.name,
                            "Decision": r.score.decision if r.score else "Error",
                            "Review Status": st.session_state.reviews.get(r.name, {}).get("status", REVIEW_STATUSES[0]),
                            "Reviewer Notes": st.session_state.reviews.get(r.name, {}).get("notes", "")}
                           for r in results])
        edited = st.data_editor(rv, hide_index=True, key="review_editor", disabled=["Company", "Decision"],
                                column_config={"Review Status": st.column_config.SelectboxColumn(
                                    "Review Status", options=list(REVIEW_STATUSES), required=True)})
        st.session_state.reviews = {row["Company"]: {"status": row["Review Status"],
                                                     "notes": str(row["Reviewer Notes"] or "")[:500]}
                                    for _, row in edited.iterrows()}

        st.subheader("Company details & evidence")
        by_name = {r.name: r for r in results}
        for name in view["Company"]:
            r = by_name[name]
            label = f"{DECISION_ICON.get(r.score.decision, '❌') if r.score else '❌'} {r.name} — " + \
                    (f"{r.score.total:g}/100 · {r.score.decision}" if r.score else "Error")
            with st.expander(label):
                if r.status == "error":
                    st.error(r.error)
                    continue
                st.write(r.score.summary)
                st.markdown("**Score breakdown**")
                st.dataframe(pd.DataFrame([{"Criterion": c.label, "Weight": c.weight, "Points": c.points,
                                            "Status": c.status, "Why": c.explanation} for c in r.score.criteria]),
                             hide_index=True)
                st.markdown("**Evidence (verbatim quotes confirmed in the retrieved pages)**")
                rows = [{"Fact": k, "Value": str(v.value), "Quote": v.evidence, "Source": v.source_url}
                        for k, v in (("Industry", r.facts.industry), ("Employees", r.facts.employee_count),
                                     ("HQ region", r.facts.region), ("Business model", r.facts.business_model))
                        if v.verified]
                rows += [{"Fact": "Buying signal", "Value": str(s.value), "Quote": s.evidence, "Source": s.source_url}
                         for s in r.facts.buying_signals if s.verified]
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
                        "Source": st.column_config.LinkColumn("Source URL")})
                else:
                    st.caption("No verified evidence was found.")
                if r.flags:
                    st.markdown("**⚠ Flags - missing or unverified information**")
                    for fl in r.flags:
                        st.markdown(f"- {fl.replace('<', '&lt;')}")
                st.markdown("**Sources retrieved**")
                if r.sources:
                    st.dataframe(pd.DataFrame([s.public_dict() for s in r.sources])[["url", "kind", "title", "fetched_at"]],
                                 hide_index=True)
                else:
                    st.caption("No pages were retrieved - nothing to cite.")
                with st.popover("Research log"):
                    st.code("\n".join(r.research_log) or "(empty)")
                st.caption(f"Extractor: {r.facts.extractor} · Researched {r.researched_at}")

        st.subheader("Export")
        approved = [r for r in results if st.session_state.reviews.get(r.name, {}).get("status") == "Approved"]
        st.caption(f"{len(approved)} lead(s) approved by a human reviewer.")
        st.download_button("⬇ Download approved shortlist (CSV)",
                           results_to_csv(approved, st.session_state.reviews).encode("utf-8-sig"),
                           "approved_shortlist.csv", "text/csv", key="dl_short", disabled=not approved)
        x1, x2 = st.columns(2)
        x1.download_button("⬇ Download CSV", results_to_csv(results, st.session_state.reviews).encode("utf-8-sig"),
                           "lead_qualification_results.csv", "text/csv", key="dl_csv")
        x2.download_button("⬇ Download JSON (full evidence)", results_to_json(results, icp, st.session_state.reviews),
                           "lead_qualification_results.json", "application/json", key="dl_json")

# ------------------------------------------------------------------ tab 4: how it works
with tab_how:
    st.markdown("""
**Pipeline:** input → validation → public-source research → fact extraction (LLM or rules) →
**evidence verification** → transparent scoring → explanation → CSV/JSON export.

**Scoring (out of 100)** uses the weights in your ICP: industry, company size, region, business model
and *need for services* (cloud / data / AI initiatives and growth signals). **Evidence quality** (High / Medium / Low)
shows how much of the score rests on verified quotes and also gates the decision. Scoring is plain Python - the LLM never decides the score.

**Anti-fabrication rules**
- Every fact needs a *verbatim quote* that is re-checked against the page text that was actually fetched.
- Quotes that cannot be found are rejected, flagged, and earn **0 points**.
- Unknown data is never guessed. It is flagged and, by default, earns nothing.
- Page text is treated as untrusted data (prompt-injection text on pages is ignored).
- Sources shown are only pages that were really retrieved. Failed fetches appear in the research log.

**Decisions:** *Qualified* (score ≥ threshold and enough verified data) · *Needs Review* ·
*Not Qualified* (low score or excluded industry) · *Insufficient Data*.

**Safety:** public pages only, robots.txt respected, private/local addresses blocked, no emails or
messages are ever sent.
""")
