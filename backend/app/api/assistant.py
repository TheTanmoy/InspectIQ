"""Ask Quality AI: chat grounded in plant data, with input guardrails and role-based context."""
import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import require
from app.core import audit, config, guardrails as g, prompts, security
from app.core.llm import LLMError, chat_stream, get_usage, last_model, reset_usage
from app.core.rag import DocIndex
from app.schemas import ChatRequest
from app.services import ai, analytics, reports
from app.services.inspection_source import get_store

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def build_context(user: dict, question: str) -> str:
    store = get_store()
    ov = analytics.overview(store, 30)
    ctx = {"last_30_days_kpis": ov["kpis"], "pareto": ov["pareto"][:6],
           "features": [{k: f[k] for k in ("line", "feature", "mean", "lsl", "usl", "cpk", "out_of_spec")}
                        for f in ov["features"]],
           "insights": [{"title": i["title"], "detail": i["detail"]} for i in ov["insights"]],
           "shift_comparison": ov["shift_comparison"],
           "raw_material_lots": [{k: m[k] for k in ("material_lot", "line", "supplier", "heat_number", "incoming_result",
                                                     "deviations", "parts", "per_100", "top_defect")}
                                 for m in ov.get("materials", [])[:12]]}
    reps = reports.list_reports()[:15]
    if security.can(user["role"], "compliance:view"):
        ctx["recent_reports"] = reps
    else:  # inspectors see report status but not compliance details
        ctx["recent_reports"] = [{k: r[k] for k in ("id", "lot", "status", "defect_rate_pct")} for r in reps]
    index = DocIndex()
    for name, text in store.legacy_reports():
        index.add(name, text)
    legacy = index.context_for(question, k=2)
    text = json.dumps(ctx, default=str)
    if legacy:
        clean, _ = g.sanitize_untrusted(legacy)
        text += "\n\nOLD REPORTS (inconsistent legacy formats):\n" + g.wrap_untrusted("legacy_reports", clean)
    return g.cap_text(text, 30_000)


def _mock_answer(question: str, user: dict) -> str:
    ins = analytics.detect_patterns(get_store())
    lines = [f"**[Template mode - no LLM key set]** Here is what the data shows for: _{question[:120]}_", ""]
    lines += [f"- **{i['title']}** - {i['detail']}" for i in ins[:4]]
    lines += ["", "Set `LLM_PROVIDER` and `LLM_API_KEY` in `backend/.env` for full natural-language answers."]
    return "\n".join(lines)


@router.post("/chat")
def chat(req: ChatRequest, user=Depends(require("assistant:use"))):
    question = req.messages[-1].content
    allowed, reason = g.check_question(question)
    if not allowed:
        audit.log(user, "assistant.blocked", "assistant", "", meta={"reason": reason, "question": question[:200]})
        return StreamingResponse(iter([f"🛡️ {reason}"]), media_type="text/plain; charset=utf-8")
    if not ai.limiter.allow(user["username"]):
        return StreamingResponse(iter(["⏳ Too many AI requests - please wait a minute."]),
                                 media_type="text/plain; charset=utf-8")
    masked_q, _ = g.mask_pii(question)
    history = [m.model_dump() for m in req.messages[-8:]]
    history[-1]["content"] = masked_q

    if ai.is_mock():
        return StreamingResponse(iter([_mock_answer(question, user)]), media_type="text/plain; charset=utf-8")

    system = prompts.ASSISTANT_SYSTEM.format(role=security.ROLES[user["role"]], context=build_context(user, question))

    def gen():
        t0, ok, err, out = time.perf_counter(), True, "", []
        reset_usage()
        try:
            for chunk in chat_stream(history, system=system):
                out.append(chunk)
                yield chunk
        except LLMError as e:
            ok, err = False, str(e)
            yield f"\n\n⚠️ The AI service is unavailable right now ({str(e)[:150]})."
        _, hits = g.scrub_claims("".join(out))
        if hits:
            yield "\n\n> 🛡️ Note: compliance and approval decisions are made by authorised staff, not by the assistant."
        audit.log_llm_call(user["username"], "assistant.chat", config.LLM_PROVIDER,
                           last_model() if ok else config.LLM_MODEL, config.PROMPT_VERSION,
                           int((time.perf_counter() - t0) * 1000), ok, {"claims_flagged": len(hits)}, err,
                           usage=get_usage())

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
