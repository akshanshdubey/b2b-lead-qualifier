# Use case, ICP and qualification criteria

## Use case
A B2B technology consulting firm sells **cloud solutions, data analytics and AI automation**. Its sales team needs a
short, reviewable list of companies that probably need those services. The system takes a list of companies, researches
public information, scores each company against an Ideal Customer Profile (ICP), explains the score with quoted evidence,
and hands a shortlist to a human. **It never contacts anyone.**

## Ideal Customer Profile (default, editable in the dashboard)
Mid-size to large **B2B** organisations in industries that run large operations and data but are typically not technology
vendors themselves, so they buy cloud/data/AI help rather than build it:

| Field | Default |
|---|---|
| Target industries | fintech, banking, healthcare, logistics, manufacturing, retail, education |
| Excluded (disqualified) | restaurant, gambling, data analytics, artificial intelligence (the last two are our competitors) |
| Size | 100 - 5,000 employees (half credit within 50% below / 2x above) |
| Regions | United States, Canada, United Kingdom, Germany |
| Business model | B2B |
| Need-for-services keywords | cloud, digital transformation, modernization, migration, automation, analytics, machine learning, AI, legacy, hiring, expansion |

These are *assumptions* chosen for this exercise; change them in the ICP tab or `data/icp_default.json`.

## Criteria and scoring (total 100, computed by plain Python in `leadgen/scoring.py`)
| Criterion (PDF criterion it maps to) | Points |
|---|---|
| Industry fit (industry & business relevance) | 25 |
| Need for services (potential need for our services: verified cloud/data/AI/modernisation/growth signals) | 35 |
| Company size (scale, where available) | 15 |
| Region (geographic fit) | 15 |
| Business model | 10 |
| **Evidence quality** (quality & reliability of evidence) | not a point category - shown as High/Medium/Low and gates the decision |

Only facts with a **verbatim quote re-found in a page that was really fetched** earn points. Unverified or missing facts
earn 0 and are flagged.

## What the score means
| Decision | Meaning |
|---|---|
| Qualified | score ≥ 70 and ≥ 50% of the points rest on verified evidence → a good candidate **for a human to review** |
| Needs Review | score 45-69, or high score with thin evidence |
| Not Qualified | score < 45, or an excluded industry |
| Insufficient Data | low score and little verified data - research more before judging |

**The score supports human review. It is not proof that a company is ready to buy.** Every lead starts as
*Pending review* and a person approves or rejects it.
