# Architecture & Pricing Brief — Partner Review

*Prepared: 2026-06-10 | Sources: verified June 2026 AWS/Anthropic published rates, internal deployment logs, industry pricing analyses*

---

## 1. Architecture: Today vs. Proposed

| | **Today** | **Proposed** |
|---|---|---|
| Pipeline | 5 steps: upload → AWS OCR (Textract) → poll every 10s → chop text into chunks → AI, one chunk at a time | 2 steps: upload → AI reads PDF directly (via AWS Bedrock) |
| Speed (50-page doc) | 7+ minutes | 2–3 minutes |
| Documents at once | 1 | 15–25 (expandable to 100+) |
| Vendors touching PHI | 2 (AWS + AI vendor) | 1 (AWS only — existing BAA covers Bedrock) |
| Database | Self-managed container on one server; script-based backups | Managed AWS RDS: automatic backups, encryption, patching |
| Server | Single t3.small — has crashed under load once already | Same or smaller; heavy lifting moves to AWS |
| Code maintained | ~80k lines incl. ~1,700-line OCR polling chain (top failure source) | ~15–20% of codebase deleted, not rewritten |
| Migration risk | — | Runs behind a feature flag alongside old path; reversible at any point |

## 2. Cost: Today vs. Proposed

| | **Today** | **Proposed** |
|---|---|---|
| Per document (20-pg avg) | ~12¢ | ~13¢ (full-speed lane 21¢; half-price batch lane 11¢) |
| Per page (scanned) | ~0.65¢ | ~1.1¢ full speed / ~0.55¢ batch — **budget 1¢/page** |
| Infrastructure /month | ~$23 | ~$59 (delta is the managed database) |
| Total @ 1,000 docs/mo | ~$143 | ~$184 |
| Total @ 5,000 docs/mo | ~$630 — **cannot keep up (serial queue)** | ~$684 — works with headroom |
| Heavy user (1,500 pages/day ≈ 33k pages/mo) | Not serviceable | $200–340/mo cost to us |

**Net: ~$40/mo more at current volume; buys 2–3x speed, 20x+ capacity, managed PHI backups, one fewer vendor.**

## 3. Competitor Pricing (closest three)

| Competitor | Model | Reported Rates |
|---|---|---|
| **readabl.ai** (direct competitor) | Per page/month + mandatory startup fee; private cloud per customer | Quote-only; enterprise-scale minimums |
| **Wisedocs** | Per page / per case | ~$40–150 per case ≈ **5–15¢/page** |
| **Tennr** | Volume-based enterprise | **$2k–5k/mo** small practice; $10k–50k implementation; $20k+/mo at scale |

Adjacent data points: Casemark $25–80/doc · Supio $2k–3.5k/seat/mo · DigitalOwl $250k+/yr floor.
**No competitor publishes pricing or offers self-serve. The small-practice segment is unserved.**

## 4. Our Pricing Recommendation

| | **Standard Seat** | **Power Seat** |
|---|---|---|
| Price | $149/user/mo | $499/user/mo |
| Included pages | 2,500/mo | 20,000/mo |
| Overage | 3¢/page | 3¢/page (2¢ above 50k) |

**Heavy-user economics** (33k pages/mo on Power seat): revenue ~$889/mo · our cost ~$340 worst case · **gross margin 62–75%** · customer saves ~90% vs. human abstraction ($10k+/mo equivalent labor).

**Position:** 3¢/page sits below Wisedocs' implied 5–15¢; published self-serve pricing is a structural wedge competitors can't follow without breaking their enterprise sales model.

## 5. Decision Asks

1. Approve migration (config + deletion work behind a feature flag; product unchanged)
2. Approve managed database move (~$35/mo — automated, encrypted PHI backups)
3. Approve pricing structure: seat + page allowance + metered overage
4. Security remediation (credential rotation) proceeds immediately regardless of the above
