# Measurement protocol: did the change work?

Load this before designing a test, choosing what to watch after a change, or
telling a client that something "worked". It turns the plugin's
falsifiability rule into a procedure with fixed decision rules, so two people
reading the same data reach the same verdict.

Credit: the layered-latency framing, holdout groups and the four-verdict
vocabulary are adapted from ideas in aaron-he-zhu/seo-geo-claude-skills
(Apache-2.0). The wording, thresholds and implementation here are this
project's own.

## 1. Four latency layers

A change propagates through layers that respond on very different clocks.
Judge each change at the layer it can actually move within the horizon, and
never claim a lagging-layer result from a leading-layer change on a short
clock.

| Layer | What it captures | Visible after | Instrument | Indicator type |
|---|---|---|---|---|
| 1. Crawler access | Can search and AI crawlers fetch the page (robots.txt, CDN/WAF rules, managed robots, meta robots) | Immediately once deployed | `geo-crawlers`, `aeo.crawler_access`, `seo-drift` | Leading, binary |
| 2. Readiness | Is the page shaped to be cited: front-loaded answers, attributed statistics, self-contained passages, schema | Immediately, but only as a **proxy** | `citability_scorer.py`, `aeo.*` scores | Leading proxy; says nothing about outcomes |
| 3. AI surfacing | Is the brand mentioned or cited in AI answers; do assistants send visits | Days to weeks (index refresh, retrieval changes) | `geo-share-of-voice` (`ai.*`), `ai_referrals.py` (`ga4.ai_*`) | Outcome, noisy |
| 4. Rankings and clicks | Organic positions, impressions, clicks, key events | Weeks to months (recrawl, re-ranking, 2-3 day GSC lag) | `rank_tracker.py`, `gsc.*`, `ga4.organic_*`, `leads.*` | Lagging outcome |

Consequences:

- A layer-1 fix (unblocking a crawler) is verified the same day by re-running
  the access check. It does not need a holdout; it needs a before/after check.
- A layer-2 improvement is never reported as a result on its own. A higher
  citability score is a reason to expect layer-3 movement, not evidence of it.
- Layer-3 and layer-4 claims need a pre-registered horizon and, wherever a
  comparable group exists, a control group.

## 2. Designing a holdout test

1. **Write the hypothesis** as one sentence naming the change, the metric and
   the direction: "Adding answer-first summaries to comparison pages improves
   their GSC average position by at least 1 within 28 days."
2. **Pick treatment and control sets** before anything ships:
   - same layer of metric (keywords for rankings, prompts for AI visibility);
   - similar starting band and intent (do not pair page-1 treatment keywords
     with page-3 controls);
   - controls untouched by the change and not linked to from changed pages
     (spillover makes the control move too);
   - at least 6 measurable keywords per group (a two-sided sign test cannot
     reach p < 0.05 with fewer); 10+ is better, and the control group should be
     at least as large as the treatment group.
3. **Tag them**: `rank_tracker.py add --tag treatment:<name>` and
   `--tag control:<name>`; for AI prompts use the profile prompt panel's
   `treatment` / `control` groups. A keyword carrying both tags is flagged and
   contaminates the result.
4. **Pre-register** in the project profile so the plan cannot drift after the
   data arrives:
   ```bash
   python3 scripts/seo_project.py note example.com "TEST faq-summaries: start 2026-09-01, \
   horizon 28d, metric GSC avg position, min effect 1.0, alpha 0.05, \
   treatment:faq vs control:faq" --approved-by user
   ```
5. **Choose the horizon by layer**: layer 1, 1-7 days; layer 3, 14-28 days
   with at least 5 runs per prompt; layer 4, 28-56 days. Rankings need the
   longer end: Google must recrawl, re-rank, and GSC must catch up.
6. **Name the leading indicator** you will watch during the horizon (crawler
   hits in logs, `aeo.citability`, impressions before clicks) so the team is
   not tempted to peek at the outcome metric.

## 3. Measuring

`rank_tracker.py experiment --treatment T --control C --start D --horizon H`:

- pre window = the H days before D; post window = the H days from D
  (truncated to available data, which ends `--lag` days before `--as-of`);
- per keyword: delta = pre position - post position (positive = improved);
  GSC keywords need `--min-impressions` (default 10) in both windows, others
  are listed as excluded;
- control-adjusted delta = treatment delta - median(control deltas), which
  removes movement shared by both groups (a core update, seasonality);
- sign test on the adjusted deltas, ignoring changes smaller than 0.5
  positions (noise in averaged positions).

AI-visibility tests use the same vocabulary; `geo-share-of-voice` compares
paired prompts across periods with a sign test and Holm adjustment across
engines or prompt groups.

## 4. Verdicts and decision rules

Defaults: alpha = 0.05, minimum effect = 1.0 position. Change them only in
the pre-registration note, never after seeing data.

| Verdict | Rule (evaluated in this order) | What to do |
|---|---|---|
| **Keep-testing** | The pre-registered horizon has not been reached. | Report interim numbers as interim. No decision, no client claim. |
| **Unproven** | Horizon reached, and any of: no measurable control keywords; fewer than 6 measurable treatment keywords. | Say the test could not decide. Re-register with more keywords. |
| **Promote** | Horizon reached, adjusted median delta >= +min effect, and adjusted sign-test p < alpha. | Roll the change out to similar pages; keep watching the control. |
| **Rollback** | Horizon reached, adjusted median delta <= -min effect, and adjusted sign-test p < alpha. | Revert the change on treatment pages; check `seo-drift` for side effects. |
| **Unproven** | Horizon reached and neither Promote nor Rollback holds. | Do not extend this test to "wait for significance". Re-register a larger or longer one if the idea is still worth it. |

Why no extension: stopping when a result first looks significant inflates
false positives. A new test with a new pre-registration is the honest way to
look longer.

Caveats the script raises and the write-up must repeat: the control group
moved significantly on its own (site-wide movement; the adjustment only
removes its median); the control group is smaller than treatment (its median
is noisy); keywords in both groups.

## 5. Falsifiability rule

Every recommendation this plugin emits carries four parts. For tested changes
they map directly onto the protocol:

| Part | In a holdout test |
|---|---|
| Observation it rests on | The CONFIRMED finding that motivated the change (tool output, quoted) |
| Dependency | What must be true first (e.g. crawler access verified at layer 1) |
| How we would know it failed | The Rollback / Unproven condition, stated before launch |
| Leading indicator | The layer 1-3 metric watched during the horizon |

A verdict is CONFIRMED only as a statement about the measured groups ("treatment
keywords improved a median 1.8 positions more than controls, p = 0.02"). Any
explanation of why is INFERRED and should list competing explanations.

## 6. Confounders checklist

Check before writing up any verdict:

- Google updates during the window: `python3 scripts/seo_updates.py --since <yyyy-mm>`.
- Site-wide deploys or template changes: `seo-drift history`.
- SERP layout changes (an AI Overview appearing lowers CTR without a rank change).
- Seasonality: compare with the same weeks last year in GSC when available.
- Spillover: internal links or shared templates between treatment and control.
- Measurement changes: GSC property switch, GA4 channel rules, a new AI source
  table version in `ai_referrals.py`.

## 7. Before/after without a control

Some changes have no comparable control (a site-wide migration). Then the
best available evidence is a before/after comparison at every layer with the
same windows, plus the confounders checklist. Report it as Unproven-by-design:
the direction and size are CONFIRMED observations; attribution to the change
is INFERRED.
