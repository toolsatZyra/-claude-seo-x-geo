# Link-earning playbook

Every tactic below is white-hat. Each one earns a link because the target
site's readers benefit. None of them involves payment, swaps or link schemes.

| Prospect type | Tactic | What to offer (`asset_url`) | Effort |
|---|---|---|---|
| directory or review | Create or complete a genuine profile; ask real clients for reviews | Homepage or services hub | Low |
| partner or integration | Ask a vendor or partner you genuinely work with for a listing (LMS, tools, agencies) | The page that shows the integration or partnership | Low |
| resource page | Offer your most relevant, genuinely useful page for their list | A guide, template, checklist or calculator | Medium |
| event or podcast | Pitch a speaker, panel or guest slot with a specific angle | Speaker page or a relevant case study | Medium |
| association | Join, or get listed as a member; contribute to member resources | About page | Medium |
| community | Answer questions where you have expertise; links only when asked for | (none: participation, not outreach) | Medium |
| publication | Expert commentary on a trend, or an original data point; use source requests (Qwoted, Featured) | Data page, study or expert bio | High |
| blog (editorial) | Offer an expert contribution or point out an error or outdated fact; never paid | The page that answers the gap | High |
| unclassified | Look at the site manually first; most should be skipped | (none) | Medium |

## Choosing what to work on

1. **High-value prospects first.** Spend a personalized pitch on each one.
2. **Quick wins in batches.** Directories and partner pages need accurate, genuine profiles, not outreach copy.
3. **Leave the backlog alone** unless a prospect fits a campaign you are already running.

## Assets that earn links for B2B services

- **Original data:** a survey of your clients' buyers, or anonymized production benchmarks. Publish the method.
- **Practical tools:** a cost estimator, a brief template, a checklist.
- **Expert explainers** for questions that buyers search for. These match the topics in the profile.
- **Real case studies**, with client approval.
  - Never present third-party or placeholder work as your own.
  - If proof is thin, pitch expertise (commentary, data), not portfolio.

## Reclaiming unlinked mentions

If `geo-brand-mentions` or a search turns up pages that name the client without linking:

1. Import them: `link_sources.py import --format generic`, with the columns `domain`, `sample_url` and `title`.
2. Handle them as prospects with the tactic "Ask to add a link where you are already mentioned". This is low effort and has the highest acceptance rate.

## Measuring

- **Weekly:** `link_outreach.py verify`, then the KPIs, then `performance_tracker.py ingest`.
- **Monthly:** re-fetch the gap from the same source and compare `links.referring_domains`.
