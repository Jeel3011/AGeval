"""
api/redteam.py

Red Teaming & Security API.

Runs a real, defensive adversarial probe (see api/redteam_engine.py) against a
model the caller controls, and returns an honest security scorecard derived from
the model's actual responses — not a fabricated grade.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging

from api.deps import verify_api_key
from api.redteam_engine import run_red_team

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/redteam",
    tags=["Red Teaming"],
    dependencies=[Depends(verify_api_key)],
)


class AttackRequest(BaseModel):
    agent_id: str
    attack_vectors: list[str] = [
        "prompt_injection",
        "roleplay_jailbreak",
        "data_exfiltration",
        "dow",
    ]
    model: str = "gpt-4o-mini"
    system_prompt: str | None = None


@router.post("/run")
def run_attack_simulation(req: AttackRequest, user_id: str = Depends(verify_api_key)):
    """
    Synchronously run the adversarial probe library against `model` and return a
    real scorecard. This sends each canned attack prompt through the caller's
    OpenAI key and reports which guardrails held.
    """
    log.info(
        f"Red-team run by {user_id} | agent={req.agent_id} | "
        f"model={req.model} | vectors={req.attack_vectors}"
    )
    try:
        scorecard = run_red_team(
            vectors=req.attack_vectors,
            model=req.model,
            system_prompt=req.system_prompt,
        )
    except RuntimeError as exc:
        # Missing OPENAI_API_KEY etc. — honest 400, not a fake result.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "completed",
        "agent_id": req.agent_id,
        "scorecard": scorecard,
    }
