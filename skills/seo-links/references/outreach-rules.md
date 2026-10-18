# Outreach rules

`scripts/link_outreach.py` enforces the rules marked **(enforced)**. The rest are judgment rules for whoever writes the draft.

## Never

- **(enforced)** Offer or mention payment, sponsorship, link exchanges, swapped or reciprocal links, guest-post fees, or "dofollow". The lint rejects: pay, payment, paid, sponsor, sponsored, sponsorship, link exchange, swap links, reciprocal, guest post fee, dofollow, do-follow.
- **(enforced)** Link to anything except the brief's `asset_url`, `client_home`, `contact_path` or the prospect's own evidence pages.
- **(enforced)** Send without a named approver, or contact a domain marked `do_not_contact`.
- Claim a client, result, award or number that is not in the brief's `allowed_claims`. If proof is thin, offer expertise, not portfolio.
- Pretend to be a reader, a fan or a mutual connection.
- Scrape or guess personal email addresses. Use the site's public contact page, or the address a person published for this purpose.

## Format

- **(enforced)** Subject of at most 90 characters; body of at most 150 words; neither empty.
- One ask, stated plainly in the last two sentences.
- The first line says why this page fits *their* readers, quoting the evidence (the page title or URL that links to a competitor).
- Plain text. No attachments. A signature with the sender's real name and role.

## Cadence

- **(enforced)** One follow-up at most, at least 7 days after first contact, with its own approval.
- **(enforced)** `lost` and `no_reply` start a 90-day cooldown before the domain can be re-added.
- Stop immediately on any opt-out, and mark `do_not_contact`.

## Compliance

- Follow the anti-spam law of the sender's and the recipient's country: identify the sender, give a working reply address, and honor opt-outs.
- Keep a record. The `events` table logs every status change with its actor and time.
