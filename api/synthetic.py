"""
api/synthetic.py

Synthetic Data Generation API.
Uses LLMs to bootstrap evaluation datasets from a few seed examples.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging
import os
import json

from api.deps import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/synthetic",
    tags=["Synthetic Data"],
    dependencies=[Depends(verify_api_key)],
)

class GenerationRequest(BaseModel):
    seed_examples: list[dict]
    num_examples_to_generate: int = 10
    dataset_name: str


def _extract_array(parsed: object) -> list:
    """OpenAI's json_object mode returns a top-level OBJECT, not a bare array.
    Models commonly wrap the list under a key like "examples"/"data"/"items".
    Pull out the first list value; if the response *is* a list, use it directly.
    """
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Prefer well-known keys, then fall back to the first list value.
        for key in ("examples", "data", "items", "results", "cases"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        for value in parsed.values():
            if isinstance(value, list):
                return value
    return []

@router.post("/generate")
def generate_synthetic_data(req: GenerationRequest):
    """
    Generates variations of the seed examples to build a robust golden dataset.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY must be set for synthetic generation")

    prompt = f"""
    You are an expert QA engineer. I will give you {len(req.seed_examples)} seed examples
    of inputs and expected outputs for an LLM agent.

    Seeds: {json.dumps(req.seed_examples, indent=2)}

    Please generate {req.num_examples_to_generate} NEW, highly varied, and challenging edge-case examples
    that follow the same structure. Ensure diversity in language, length, and complexity.

    Output strictly as a JSON array of objects.
    """

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        examples = _extract_array(parsed)
        return {
            "status": "success",
            "dataset_name": req.dataset_name,
            "requested_count": req.num_examples_to_generate,
            "generated_count": len(examples),   # the ACTUAL number returned
            "data": examples,
        }
    except json.JSONDecodeError as e:
        log.error(f"Generation returned invalid JSON: {e}")
        raise HTTPException(status_code=502, detail="Synthetic generation returned invalid JSON from the model")
    except Exception as e:
        # Surface the failure honestly instead of returning fake "success" data.
        log.error(f"Generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Synthetic generation failed: {e}")
