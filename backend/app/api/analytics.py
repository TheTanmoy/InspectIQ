import json

from fastapi import APIRouter, Depends, Query

from app.api.deps import require
from app.core import guardrails as g, prompts
from app.services import ai, analytics
from app.services.inspection_source import get_store

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
VIEW = Depends(require("analytics:view"))


@router.get("/overview")
def overview(days: int = Query(30, ge=1, le=120), line: str = "", user=VIEW):
    return analytics.overview(get_store(), days, line)


@router.get("/spc")
def spc(line: str, feature: str, days: int = Query(60, ge=5, le=120), user=VIEW):
    return analytics.spc_series(get_store(), line, feature, days)


@router.post("/insights/explain")
def explain(user=VIEW):
    """AI explanation of the detected patterns (numbers verified against the computed insights)."""
    insights = analytics.detect_patterns(get_store())
    facts = [{"title": i["title"], "detail": i["detail"], "metrics": i["metrics"],
              "possible_cause": i.get("possible_cause")} for i in insights]
    if ai.is_mock() or not insights:
        lines = [f"- **{i['title']}**: {i['detail']}" + (f" Likely cause: {i['possible_cause']}" if i.get("possible_cause") else "")
                 for i in insights] or ["- No significant patterns detected in the last 14 days."]
        text, mode = "\n".join(lines), "template"
    else:
        raw, meta = ai.call("insights.explain", user, [{"role": "user", "content": "FACTS:\n" + json.dumps(facts, default=str)}],
                            prompts.INSIGHTS_SYSTEM)
        if raw is None:
            lines = [f"- **{i['title']}**: {i['detail']}" for i in insights]
            text, mode = "\n".join(lines), "fallback"
        else:
            text, mode = raw, "llm"
    text, hits = g.scrub_claims(text)
    return {"text": text, "mode": mode, "insights": insights,
            "guardrails": [g.verify_numbers(text, facts),
                           g.check("No unsupported claims", g.WARN if hits else g.PASS,
                                   f"{len(hits)} claim(s) removed." if hits else "No absolute claims.", hits)]}
