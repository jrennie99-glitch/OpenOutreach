# Rebrand spec — from fork to product

Status: DRAFT for owner sign-off. Nothing here is executed yet.
Legal basis: upstream `eracle/OpenOutreach` is Apache-2.0 (its own relicence,
commit 2a95839, merged in PR #2). Apache permits closed derivative + commercial
use. Obligations: keep the copyright notice, keep a NOTICE of the modification
history, don't reuse upstream's trademarks.

## What is already genuinely ours (the moat)

1. **No hub, no data pool, no telemetry.** Upstream's default build registers
   the install and (for non-EU/UK/CH operators) uploads every discovery page
   and every paid-resolved work email to `hub.openoutreach.app`, and its
   newsletter defaults ON outside protected jurisdictions. This build no-ops
   the hub client, refuses the hostname at DNS, blocks HF telemetry, verified
   by tests. This is a *documented, testable* claim — rare in outreach tools.
2. **Verified TLS on mailbox connections** (upstream: unverified for raw SMTP
   starttls and IMAP_SSL paths).
3. **Opt-out honoured before the model** (guard in `privacy.py`, repaired in
   PR #2 to survive the 0.1.88 sender refactor).
4. **The CybrMail play (to build):** one command provisions a warmed sending
   domain on CybrMail and the agent runs on it. Upstream requires users to
   bring their own SMTP — the #1 failure point of cold outreach. This is the
   integration he cannot copy without your platform.

## Name options (checked only against obvious collisions — verify before ship)

| Option | Positioning | Trade-off |
|---|---|---|
| **QuietLead** | Standalone: "your leads never become someone else's database." The privacy architecture IS the brand. | New brand from zero; domain/email likely taken variants — check. |
| **CybrReach** | Family: CybrMail + outreach as one stack, one subscription, one deliverability story. | Locked to CybrMail brand; strong if CybrMail is the flagship infra. |
| **LeadGod Agent** | Extends existing leadgod.net traffic; the agent *is* LeadGod's product. | "LeadGod" reads loud next to a privacy-first engineering story. |

Recommendation: **CybrReach** if the strategy is sell-the-stack (email +
outreach bundle = higher ARPU, defends CybrMail churn); **QuietLead** if the
strategy is own the "private outreach" niche on HN/GitHub where the fork
audience lives. Both can coexist: QuietLead as the open-source community
build, CybrReach as the paid integrated product.

## Rename execution (mechanical, ~1 day)

- Package: `openoutreach` → chosen name (pyproject, console_script, settings
  module paths); keep `outreach_*` env-var prefixes as a compat alias for one
  major version so upstream configs still run.
- `docs/NOTICE`: Apache §4 attribution — upstream copyright, "modified by AR
  Dynamics, changes in `openoutreach/privacy.py`, `wizard.py`, this file",
  link to eracle/OpenOutreach. README line: "Based on OpenOutreach by Antonio
  Ercole De Luca (Apache-2.0); hardened and integrated by AR Dynamics."
- Never say "built from scratch" or "100% proprietary" — your build standard
  bans unsupported capability claims and the git history is public.

## CybrMail integration milestones

- **M1 `cybrreach connect`** — provisions a CybrMail sending mailbox + domain
  (DKIM/SPF/DMARC auto-published), stores creds in the local SQLite, wires
  SMTP/IMAP through the existing verified-TLS path. Success: wizard completes
  with zero manual DNS.
- **M2 deliverability loop** — CybrMail-side warmup scheduler (staged send
  volume per domain), bounce/complaint events fed back from the existing
  `DeliveryEvent` rows into a reputation score shown in the run report.
- **M3 sending-pool manager** — multiple warmed domains per customer,
  round-robin with per-domain daily caps, suppression list shared across
  domains (server-side, never leaving CybrMail's control).
- Pricing to validate: CybrMail box + warm domain + agent = $X/mo flat vs
  upstream's "bring your own everything". Get 5 design-partner yeses before
  building M2/M3.

## Sync discipline (non-negotiable)

Upstream ships ~29 commits/month (verified Nov 2026). Monthly:
`git fetch upstream && git merge` → run tests → bump pins. The guard
rewrite is import-tolerant and CI-tested for exactly this.

## Open items for owner

- [ ] Pick the name (+ domains to grab: .com / .app, GitHub org repo, PyPI
      name — all manual registrations, I can check availability but you buy).
- [ ] Merge PR #2 (sync + guard repair). Fork stays private for now.
- [ ] Decide open-core: publish QuietLead build (attracts HN) or keep closed
      (agency-only)? Apache obliges nothing either way.
- [ ] Confirm M1 scope before code: which CybrMail API endpoints exist today
      for provisioning? (not verified yet — need to read cybrmail repo.)
