# Outreach rules

`scripts/link_outreach.py` enforces the rules marked **(enforced)**. The rest are judgment rules for whoever writes the draft.

## Never

- **(enforced)** Offer or mention payment, sponsorship, link exchanges, swapped or reciprocal links, guest-post fees, compensation, or "dofollow". The lint normalizes the text first (Unicode compatibility forms, invisible characters, dashes and underscores read as spaces), then rejects whole-word forms of: pay (pays, paying, payment, payout), paid, sponsor (sponsored, sponsorship, sponsors), link exchange and "exchange links", swap links and "link swap", reciprocal, guest post fee, dofollow / do-follow / "do follow", compensat… . "PayPal", "payroll", "repay" and "unpaid" pass. "do follow" as two ordinary words is also rejected: rephrase.
- **(enforced)** Link to anything except the brief's `asset_url`, `client_home`, `contact_path` or the prospect's own evidence pages. URLs are found with or without `https://`, with or without `www.`, in any letter case, and as a bare host (`evil.com`) or host with a path. A name that looks like a domain (`ASP.NET`) is read as one: rephrase.
- **(enforced)** Put an email address in the draft. Contact is by the public contact page or the sender's own email tool.
- **(enforced)** Approve a draft that was checked against an older brief: `approve` refuses until `save-draft` is run again with the current brief hash.
- **(enforced)** Send without a named approver, or contact a domain marked `do_not_contact`. Do-not-contact covers the whole organization: `blog.example.org` and `example.org` are one registrable domain.
- Claim a client, result, award or number that is not in the brief's `allowed_claims`. If proof is thin, offer expertise, not portfolio.
- Pretend to be a reader, a fan or a mutual connection.
- Scrape or guess personal email addresses. Use the site's public contact page, or the address a person published for this purpose.

## Format

- **(enforced)** Subject of at most 90 characters; body of at most 150 words; neither empty.
- One ask, stated plainly in the last two sentences.
- The first line says why this page fits *their* readers, quoting the evidence (the page title or URL that links to a competitor).
- Plain text. No attachments. A signature with the sender's real name and role.

## Cadence

- **(enforced)** One follow-up at most, at least 7 days after first contact, with its own approval. If the prospect replies while a follow-up draft is waiting, record the real outcome (won, lost, no_reply); never mark a follow-up contacted that was not sent.
- **(enforced)** `lost` and `no_reply`, and `skipped` or `do_not_contact` after first contact, start a 90-day cooldown before the domain can be re-added. The cooldown, and any active prospect, apply to the whole organization (all subdomains).
- **(enforced)** A skipped prospect is not re-added unless `add --include-skipped` is used (the cooldown still applies).
- Stop immediately on any opt-out, and mark `do_not_contact`.

## Compliance

- Follow the anti-spam law of the sender's and the recipient's country: identify the sender, give a working reply address, and honor opt-outs.
- Keep a record. The `events` table logs every status change with its actor and time.
