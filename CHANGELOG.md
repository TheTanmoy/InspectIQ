# Changelog

## 1.1.1 - 2026-11-20

### Changed
- The AI model and data-source status box in the sidebar is shown only to IT Support & FinOps.
- Report headers say "AI-assisted" instead of naming the AI model for plant roles (inspector, line supervisor,
  quality manager, compliance officer, plant quality head).

## 1.1.0 - 2026-11-20

### Added
- Quality Cost page for the Plant Quality Head: cost of poor quality from the plant's own history.
  - Weekly scrap and rework cost by line (each lot's sampled defect rate applied to the full lot).
  - Every open issue costed from the day it started (excess over the line's normal rate), with a weekly trend.
  - Projected monthly saving if issues are resolved, one-time fix cost, payback and 12-month net; savings are
    capped at the plant's pre-issue cost level.
  - Editable assumptions (part values, rework cost, scrap share by severity, fix costs), audited.

### Changed
- Plant Quality Head no longer sees AI Cost & Ops or the software business case.
- Cost-Benefit renamed Solution ROI; viewable by IT Support and the Quality Manager, editable by IT Support.
- Deck: new Plant Quality Head quality-cost slide; video cost scene now shows the Quality Cost page.

## 1.0.1 - 2026-11-20

### Changed
- All costs are now in US dollars. AI token cost, support & maintenance run cost and the cost-benefit
  assumptions are stored and calculated in USD (former rupee defaults converted at INR 84 = USD 1),
  so token and run costs add up directly. The USD-to-INR setting is removed.
- Product journey deck, overview video and screenshots regenerated with dollar figures.

## 1.0.0 - 2026-11-20

First release of InspectIQ - AI quality inspection reports (Prompt Syndicates, AI Friday Season 3).

### Reports and AI
- Standardized report (template QIR-STD-01) generated from computed facts; Gemini writes the text, guardrails verify numbers, part serials and claims.
- Purpose & scope section on every report.
- Primary / fallback model: `gemini-3.8-flash`, falling back to `gemini-3.5-flash-lite` after `LLM_PRIMARY_TIMEOUT` seconds or on an error.

### Data and analytics
- Synthetic 3-line plant: measurements, camera detections, manual checks, gauges, maintenance.
- Raw-material traceability: every lot linked to a material heat with its mill certificate; planted off-spec L3 heat.
- Pattern detection: shift spikes, drift, raw-material links (consistent across shifts), gauge calibration.

### Workflow and compliance
- Approval chain Inspector -> Line Supervisor -> Quality Manager, plus Plant Quality Head release for high-risk reports.
- Segregation of duties: each sign-off by a different person.
- Versioned rulebook with 13 synthetic rules, including R-013 raw-material certificate.

### Operations
- AI Cost & Ops page for IT: per-call token logging, cost, forecast, support & maintenance run cost.
- Cost-Benefit page for the Plant Quality Head: payback, ROI, benefit vs run cost.
- Dark, premium UI theme with gradient sidebar.

### Docs
- `docs/InspectIQ_Product_Journey.pptx` - product journey deck for newcomers.
- `docs/InspectIQ_Overview.mp4` - 2-minute narrated problem + product video.
