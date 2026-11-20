# Changelog

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
