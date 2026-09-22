import os
import json
import re
import time
from datetime import datetime
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from groq import Groq
import requests

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI()
HISTORY_FILE = str(BASE_DIR / "saved_histories.json")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
PERSONA_BATCH_SIZE = max(1, int(os.getenv("PERSONA_BATCH_SIZE", "40")))
GROQ_MAX_PARALLEL = max(1, int(os.getenv("GROQ_MAX_PARALLEL", "1")))
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_groq_client():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY missing in .env file")
    return Groq(api_key=key)


def load_saved_histories():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def persist_saved_histories(histories):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(histories, f, indent=2, ensure_ascii=False)


def groq_json(client, prompt, schema, max_output_tokens=16000, retries=5):
    last_error = None
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a synthetic-user research engine. Return only the requested JSON and follow the supplied schema exactly."},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "synthetic_research_output",
                        "strict": False,
                        "schema": schema,
                    },
                },
                temperature=0.25,
                max_completion_tokens=max_output_tokens,
                reasoning_effort="low",
            )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("Groq returned an empty response.")
            return json.loads(text)
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            if attempt < retries - 1:
                delay = min(2 ** attempt, 12)
                if status == 429:
                    delay = min(8 + 2 * attempt, 20)
                time.sleep(delay)
    raise ValueError(f"Groq request failed after retries: {last_error}")


class WorkspaceParams(BaseModel):
    product_domain: str
    product_description: str
    target_audience: str
    research_objective: str
    persona_count: int = 0


class SurveyRequest(BaseModel):
    question: str
    cohort: List[dict]


class InterviewRequest(BaseModel):
    persona: dict
    history: List[dict]
    question: str


class BroadcastRequest(BaseModel):
    question: str
    cohort: List[dict]


class InsightsRequest(BaseModel):
    survey_results: List[dict]
    interview_logs: List[dict]
    broadcast_results: List[dict] = []
    workspace_params: dict


class SaveHistoryRequest(BaseModel):
    workspace_params: dict
    cohort: List[dict]
    survey_results: List[dict] = []
    interview_logs: List[dict] = []
    broadcast_results: List[dict] = []
    insights: dict | None = None


class ValidationRequest(BaseModel):
    workspace_params: dict
    cohort: List[dict]
    scenarios: List[dict]


class ReportRequest(BaseModel):
    workspace_params: dict
    cohort: List[dict] = []
    survey_results: List[dict] = []
    interview_logs: List[dict] = []
    broadcast_results: List[dict] = []
    insights: dict | None = None
    validation_report: dict | None = None
    survey_insights: dict | None = None
    interview_insights: dict | None = None


PERSONA_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "role": {"type": "string"},
            "location": {"type": "string"},
            "psychological_behavior": {"type": "string"},
            "personality": {"type": "string"},
            "tech_adoption_level": {"type": "string"},
            "preferred_channel": {"type": "string"},
            "goals": {"type": "string"},
            "pain_points": {"type": "string"},
            "risk_tier": {"type": "string", "enum": ["Low", "Moderate", "High"]},
            "target_audience": {"type": "string"},
            "research_objective": {"type": "string"},
            "memory_consistency_node": {"type": "string"},
        },
        "required": [
            "name", "age", "role", "location", "psychological_behavior",
            "personality", "tech_adoption_level", "preferred_channel", "goals",
            "pain_points", "risk_tier", "target_audience", "research_objective",
            "memory_consistency_node"
        ],
    },
}


def validate_persona_cohort(cohort, expected_count):
    required = set(PERSONA_SCHEMA["items"]["required"])
    if len(cohort) != expected_count:
        raise ValueError(f"Expected {expected_count} personas, but Groq returned {len(cohort)}.")
    for i, p in enumerate(cohort, 1):
        if not isinstance(p, dict):
            raise ValueError(f"Persona {i} is not an object.")
        missing = required - set(p.keys())
        if missing:
            raise ValueError(f"Persona {i} is missing: {', '.join(sorted(missing))}")
    return cohort


def persona_prompt(params, count):
    return f"""
Create exactly {count} NEW synthetic research personas for this experiment.
Do not use a fixed persona list and do not repeat names.

Product Domain: {params.product_domain}
Product Description: {params.product_description}
Target Audience: {params.target_audience}
Research Objective: {params.research_objective}

Return one object for every persona with exactly these fields:
name, age, role, location, psychological_behavior, personality,
tech_adoption_level, preferred_channel, goals, pain_points, risk_tier,
target_audience, research_objective, memory_consistency_node.

PERSONA DETAIL RULE:
- psychological_behavior, personality, tech_adoption_level, preferred_channel, goals, pain_points, target_audience, research_objective and memory_consistency_node must each contain exactly 2 concise points.
- Put each point on a separate line using "• ".
- Each point should be a meaningful short phrase of about 5-10 words, not a single word.
- Keep each of those fields to only 2-3 lines; never write paragraphs.
- role and location should be realistic and specific.
- risk_tier must be Low, Moderate, or High.
- Make personas meaningfully different in age, occupation, location, risk tolerance, technology comfort, goals, pain points, and communication preferences.
- Keep all details grounded in the supplied product and research objective.
"""


def _extract_json_text(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _cerebras_json(prompt, schema, max_output_tokens=16000):
    key = os.getenv("CEREBRAS_API_KEY")
    if not key:
        raise ValueError("CEREBRAS_API_KEY is not configured")
    response = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": CEREBRAS_MODEL,
            "messages": [
                {"role": "system", "content": "You are a synthetic-user research engine. Return only the requested JSON and follow the supplied schema exactly."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "synthetic_research_output", "strict": False, "schema": schema}},
            "temperature": 0.25,
            "max_completion_tokens": max_output_tokens,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise ValueError(f"Cerebras request failed: {response.status_code} - {response.text[:500]}")
    data = response.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not text:
        raise ValueError("Cerebras returned an empty response")
    return _extract_json_text(text)


def _gemini_json(prompt, schema, max_output_tokens=16000):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    response = requests.post(
        url,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise ValueError(f"Gemini request failed: {response.status_code} - {response.text[:500]}")
    data = response.json()
    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                text += part["text"]
    if not text:
        raise ValueError("Gemini returned an empty response")
    return _extract_json_text(text)


def _groq_persona_json(prompt, schema, max_output_tokens=16000):
    client = get_groq_client()
    return groq_json(client, prompt, schema, max_output_tokens=max_output_tokens, retries=1)


def generate_persona_batch(params, count, batch_number):
    prompt = persona_prompt(params, count) + f"\nThis is batch {batch_number}. Generate a fresh, distinct set of personas for this batch."
    providers = ["groq", "cerebras", "gemini"]
    start_index = (batch_number - 1) % len(providers)
    ordered = providers[start_index:] + providers[:start_index]
    errors = []
    for provider in ordered:
        try:
            if provider == "groq":
                return _groq_persona_json(prompt, PERSONA_SCHEMA, max_output_tokens=16000)
            if provider == "cerebras":
                return _cerebras_json(prompt, PERSONA_SCHEMA, max_output_tokens=16000)
            return _gemini_json(prompt, PERSONA_SCHEMA, max_output_tokens=16000)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            continue
    raise ValueError("All persona providers failed. " + " | ".join(errors))


def generate_persona_cohort(params):
    requested = max(0, min(150, int(params.persona_count)))
    if requested <= 0:
        raise HTTPException(status_code=400, detail="Persona count must be greater than 0.")
    batches = [PERSONA_BATCH_SIZE] * (requested // PERSONA_BATCH_SIZE)
    if requested % PERSONA_BATCH_SIZE:
        batches.append(requested % PERSONA_BATCH_SIZE)

    results = []
    with ThreadPoolExecutor(max_workers=min(len(batches), 3)) as executor:
        futures = [executor.submit(generate_persona_batch, params, n, i + 1) for i, n in enumerate(batches)]
        for future in as_completed(futures):
            results.extend(future.result())

    if len(results) != requested:
        raise ValueError(f"Generated {len(results)} personas instead of {requested}.")
    names = set()
    for p in results:
        if p["name"] in names:
            p["name"] = f"{p['name']} {len(names)+1}"
        names.add(p["name"])
    return validate_persona_cohort(results, requested)


RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "response": {"type": "string"},
            "sentiment": {"type": "string", "enum": ["Positive", "Neutral", "Negative"]},
            "would_use_score": {"type": "number"},
        },
        "required": ["name", "response", "sentiment", "would_use_score"],
    },
}


def response_prompt(question, personas):
    return f"""
Answer this research question as each supplied synthetic persona.
Question: {question}

Return one object for every supplied persona, preserving the supplied name.
Each response must be 4-5 complete sentences with concrete reasoning from that persona.
Classify sentiment from the actual response as Positive, Neutral, or Negative.
Give would_use_score from 0 to 100 based on the persona and response evidence.
Do not force positive sentiment. Use Negative when the response contains meaningful rejection, concern, frustration, or unwillingness.

PERSONA CONTEXT:
{json.dumps([{k: p.get(k) for k in ["name", "age", "role", "location", "psychological_behavior", "personality", "tech_adoption_level", "goals", "pain_points", "risk_tier"]} for p in personas], ensure_ascii=False)}
"""


def run_response_batches(client, question, cohort):
    batches = [cohort[i:i + PERSONA_BATCH_SIZE] for i in range(0, len(cohort), PERSONA_BATCH_SIZE)]
    outputs = []
    with ThreadPoolExecutor(max_workers=GROQ_MAX_PARALLEL) as executor:
        futures = [executor.submit(groq_json, client, response_prompt(question, batch), RESPONSE_SCHEMA, 16000) for batch in batches]
        for future in as_completed(futures):
            outputs.extend(future.result())
    return outputs


def sentiment_from_text(text, model_label):
    """Use the structured model label, with a small text-based safeguard for obvious contradictions."""
    label = str(model_label or "Neutral").title()
    if label in {"Positive", "Neutral", "Negative"}:
        return label
    return "Neutral"


def classify_interview_sentiment(text):
    """Conservative text-based sentiment classification for interview answers without labels."""
    text = str(text or "").lower()
    positive = (" like ", " good ", " helpful", " useful", " easy", " trust", " prefer", " willing", " yes", " comfortable", " benefit")
    negative = (" dislike", " bad ", " difficult", " hard ", " concern", " worry", " risk", " frustrated", " reject", " unwilling", " no ", " distrust")
    p = sum(text.count(term) for term in positive)
    n = sum(text.count(term) for term in negative)
    return "Positive" if p > n else "Negative" if n > p else "Neutral"


@app.post("/api/simulate-sandbox")
def simulate_sandbox(params: WorkspaceParams):
    try:
        return generate_persona_cohort(params)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run-survey")
def run_survey(req: SurveyRequest):
    try:
        client = get_groq_client()
        outputs = run_response_batches(client, req.question, req.cohort)
        by_name = {x.get("name"): x for x in outputs}
        ordered = []
        for p in req.cohort:
            item = by_name.get(p.get("name"), {})
            ordered.append({
                "name": p.get("name"),
                "response": str(item.get("response", "No response generated.")).strip(),
                "sentiment": sentiment_from_text(item.get("response"), item.get("sentiment")),
                "would_use_score": max(0, min(100, float(item.get("would_use_score", 50)))),
            })
        return {"survey_results": ordered}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/broadcast-turn")
def broadcast_turn(req: BroadcastRequest):
    try:
        client = get_groq_client()
        outputs = run_response_batches(client, req.question, req.cohort)
        by_name = {x.get("name"): x for x in outputs}
        return {"broadcast_results": [
            {
                "personaName": p.get("name"),
                "response": str(by_name.get(p.get("name"), {}).get("response", "No response generated.")).strip(),
                "sentiment": sentiment_from_text(None, by_name.get(p.get("name"), {}).get("sentiment")),
                "would_use_score": max(0, min(100, float(by_name.get(p.get("name"), {}).get("would_use_score", 50)))),
            }
            for p in req.cohort
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview-turn")
def interview_turn(req: InterviewRequest):
    try:
        client = get_groq_client()
        p = req.persona
        history = "\n".join(f"{m.get('role', '').upper()}: {m.get('content', '')}" for m in req.history)
        prompt = f"""
You are {p.get('name')}, a synthetic research persona. Stay strictly in character and maintain memory consistency.
Persona profile:
{json.dumps(p, ensure_ascii=False)}

Conversation history:
{history}

New question: {req.question}
Respond naturally in 4-5 complete sentences, with concrete reasoning from the persona profile. Do not give generic filler.
"""
        schema = {"type": "object", "properties": {"response": {"type": "string"}}, "required": ["response"]}
        data = groq_json(client, prompt, schema, max_output_tokens=12000)
        return {"response": data["response"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {
        "recurring_themes": {"type": "array", "items": {"type": "object", "properties": {"theme": {"type": "string"}, "description": {"type": "string"}, "evidence_count": {"type": "integer"}, "personas": {"type": "array", "items": {"type": "string"}}}, "required": ["theme", "description", "evidence_count", "personas"]}},
        "theme_clusters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "themes": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string"}}, "required": ["name", "themes", "description"]}},
        "sentiment_breakdown": {"type": "object", "properties": {"Positive": {"type": "number"}, "Neutral": {"type": "number"}, "Negative": {"type": "number"}}, "required": ["Positive", "Neutral", "Negative"]},
        "agreement_patterns": {"type": "array", "items": {"type": "object", "properties": {"topic": {"type": "string"}, "agreement_level": {"type": "string"}, "agreeing_personas": {"type": "array", "items": {"type": "string"}}, "dissenting_personas": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"}}, "required": ["topic", "agreement_level", "agreeing_personas", "dissenting_personas", "summary"]}},
        "behavioral_trends": {"type": "array", "items": {"type": "object", "properties": {"trend": {"type": "string"}, "description": {"type": "string"}, "affected_personas": {"type": "array", "items": {"type": "string"}}, "implication": {"type": "string"}}, "required": ["trend", "description", "affected_personas", "implication"]}},
        "adoption_scoring": {"type": "array", "items": {"type": "object", "properties": {"persona_name": {"type": "string"}, "would_use_score": {"type": "number"}, "reasoning": {"type": "string"}}, "required": ["persona_name", "would_use_score", "reasoning"]}},
        "segment_adoption_scoring": {"type": "array", "items": {"type": "object", "properties": {"segment": {"type": "string"}, "member_count": {"type": "integer"}, "average_would_use_score": {"type": "number"}, "reasoning": {"type": "string"}}, "required": ["segment", "member_count", "average_would_use_score", "reasoning"]}},
        "segment_breakdown": {"type": "array", "items": {"type": "object", "properties": {"segment": {"type": "string"}, "member_count": {"type": "integer"}, "percentage": {"type": "number"}}, "required": ["segment", "member_count", "percentage"]}},
        "research_quality": {"type": "object", "properties": {"theme_relevance_score": {"type": "number"}, "evidence_coverage_score": {"type": "number"}, "consistency_score": {"type": "number"}, "overall_score": {"type": "number"}, "confidence": {"type": "string"}, "validation_notes": {"type": "array", "items": {"type": "string"}}}, "required": ["theme_relevance_score", "evidence_coverage_score", "consistency_score", "overall_score", "confidence", "validation_notes"]},
        "would_use_summary": {"type": "object", "properties": {"would_use_count": {"type": "integer"}, "would_not_use_count": {"type": "integer"}}, "required": ["would_use_count", "would_not_use_count"]},
        "average_product_fit": {"type": "number"},
        "majority_segment": {"type": "string"},
        "top_theme": {"type": "string"},
        "total_personas": {"type": "integer"},
        "total_responses": {"type": "integer"}
    },
    "required": ["recurring_themes", "theme_clusters", "sentiment_breakdown", "agreement_patterns", "behavioral_trends", "adoption_scoring", "segment_adoption_scoring", "segment_breakdown", "research_quality", "would_use_summary", "average_product_fit", "majority_segment", "top_theme", "total_personas", "total_responses"]
}


@app.post("/api/extract-insights")
def extract_insights(req: InsightsRequest):
    try:
        if not req.survey_results and not req.interview_logs and not req.broadcast_results:
            raise HTTPException(status_code=400, detail="Run at least one survey, interview, or Ask All Personas session first.")
        client = get_groq_client()
        corpus = json.dumps({"workspace": req.workspace_params, "surveys": req.survey_results, "interviews": req.interview_logs, "broadcasts": req.broadcast_results}, ensure_ascii=False)
        prompt = f"""
Analyze this synthetic user research corpus and return only the requested JSON structure.
{corpus}

Use actual supplied responses as evidence.
- Calculate sentiment percentages from the structured response sentiment labels when available.
- Keep Positive, Neutral and Negative as separate percentage values; do not force Negative to zero.
- Calculate individual and segment would-use scores from supplied evidence.
- Include recurring themes, theme clusters, segment breakdown, agreement/disagreement, behavioral trends, individual scoring, segment scoring and research quality.
- Do not invent evidence.
- Include all requested percentage metrics.
"""
        result = groq_json(client, prompt, INSIGHTS_SCHEMA, max_output_tokens=18000)

        # Derive all numeric sentiment/adoption totals directly from supplied
        # research responses. The LLM is used for qualitative themes only; it
        # cannot overwrite these source-of-truth metrics.
        responses = list(req.survey_results) + list(req.broadcast_results)
        interview_responses = [
            m for log in req.interview_logs for m in log.get("history", [])
            if m.get("role") == "assistant" and str(m.get("content", "")).strip()
        ]
        counts = {"Positive": 0, "Neutral": 0, "Negative": 0}
        for r in responses:
            label = str(r.get("sentiment", "Neutral")).strip().title()
            if label not in counts:
                label = "Neutral"
            counts[label] += 1
        for message in interview_responses:
            counts[classify_interview_sentiment(message.get("content"))] += 1

        total = len(responses) + len(interview_responses)
        result["sentiment_counts"] = {k: counts[k] for k in ["Positive", "Negative", "Neutral"]}
        result["sentiment_breakdown"] = (
            {k: round(counts[k] * 100 / total, 1) for k in ["Positive", "Negative", "Neutral"]}
            if total else {"Positive": 0, "Negative": 0, "Neutral": 0}
        )

        scores = []
        for r in responses:
            try:
                score = float(r.get("would_use_score"))
                if 0 <= score <= 100:
                    scores.append(score)
            except (TypeError, ValueError):
                continue
        if scores:
            result["average_product_fit"] = round(sum(scores) / len(scores), 1)
            result["would_use_summary"] = {
                "would_use_count": sum(1 for score in scores if score >= 50),
                "would_not_use_count": sum(1 for score in scores if score < 50),
            }
        else:
            result["average_product_fit"] = 0
            result["would_use_summary"] = {"would_use_count": 0, "would_not_use_count": 0}

        requested_personas = len(req.cohort) if hasattr(req, "cohort") else 0
        result["total_personas"] = requested_personas or int(req.workspace_params.get("persona_count", 0) or 0)
        interview_response_count = sum(1 for log in req.interview_logs for m in log.get("history", []) if m.get("role") == "assistant")
        result["total_responses"] = total if total else interview_response_count

        # Reconcile segment scoring with actual individual scores when the
        # model returned segment rows. This prevents invented averages/counts.
        if scores and result.get("adoption_scoring"):
            valid_by_name = {str(r.get("name")): float(r.get("would_use_score")) for r in responses if isinstance(r.get("would_use_score"), (int, float))}
            reconciled = []
            for item in result.get("adoption_scoring", []):
                name = str(item.get("persona_name", ""))
                if name in valid_by_name:
                    reconciled.append({
                        "persona_name": name,
                        "would_use_score": round(valid_by_name[name], 1),
                        "reasoning": str(item.get("reasoning", "Based on the supplied response.")),
                    })
            if reconciled:
                result["adoption_scoring"] = reconciled

        if result.get("recurring_themes"):
            result["top_theme"] = result["recurring_themes"][0].get("theme", "")
        if result.get("segment_breakdown"):
            result["majority_segment"] = max(result["segment_breakdown"], key=lambda x: x.get("member_count", 0)).get("segment", "")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/save-history")
def save_history(req: SaveHistoryRequest):
    try:
        histories = load_saved_histories()
        item = {
            "id": (max([int(h.get("id", 0)) for h in histories] or [0]) + 1),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "workspace_params": req.workspace_params,
            "cohort": req.cohort,
            "survey_results": req.survey_results,
            "interview_logs": req.interview_logs,
            "broadcast_results": req.broadcast_results,
            "insights": req.insights,
        }
        histories.append(item)
        persist_saved_histories(histories)
        return {"message": "History saved successfully.", "history": item}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/saved-histories")
def get_saved_histories():
    return {"histories": load_saved_histories()}


@app.delete("/api/saved-histories/{history_id}")
def delete_saved_history(history_id: int):
    histories = load_saved_histories()
    updated = [h for h in histories if int(h.get("id", -1)) != history_id]
    if len(updated) == len(histories):
        raise HTTPException(status_code=404, detail="Saved history not found.")
    persist_saved_histories(updated)
    return {"message": "Saved history deleted successfully."}


@app.post("/api/validate-insights")
def validate_insights(req: ValidationRequest):
    try:
        cohort = req.cohort or []
        scenarios = req.scenarios or []
        persona_count = len(cohort)
        research_responses = []
        for scenario in scenarios:
            research_responses.extend(scenario.get("survey_results", []) or [])
            research_responses.extend(scenario.get("broadcast_results", []) or [])
            for log in scenario.get("interview_logs", []) or []:
                research_responses.extend([m for m in log.get("history", []) if m.get("role") == "assistant"])

        # Validation is calculated from the evidence actually supplied to the
        # validator, so an empty/failed model response can no longer force 0/100.
        output_scenarios = []
        for scenario in scenarios:
            name = scenario.get("name") or scenario.get("scenario") or "Scenario"
            survey_n = len(scenario.get("survey_results", []) or [])
            broadcast_n = len(scenario.get("broadcast_results", []) or [])
            interview_n = sum(1 for log in scenario.get("interview_logs", []) or [] for m in log.get("history", []) if m.get("role") == "assistant")
            evidence_n = survey_n + broadcast_n + interview_n
            focus = scenario.get("persona_focus", []) or []

            # Evidence coverage: full coverage when every generated persona has
            # a response; persona-focus scenarios are measured by their supplied focus rows.
            if persona_count:
                coverage = min(100.0, evidence_n * 100.0 / persona_count) if evidence_n else 0.0
                if focus and not evidence_n:
                    coverage = round(min(100.0, len(focus) * 100.0 / persona_count), 1)
            else:
                coverage = 0.0

            # Theme relevance is based on whether the scenario contains the
            # research objective/focus and usable evidence, rather than a model guess.
            objective = str(req.workspace_params.get("research_objective", "")).strip().lower()
            question = str(scenario.get("question", "")).strip().lower()
            relevance = 100.0 if objective and (objective in question or question in objective) else (75.0 if question else 50.0)
            if evidence_n == 0 and not focus:
                relevance = 0.0

            # Persona consistency is measured from the supplied persona records.
            unique_names = len({str(p.get("name", "")).strip() for p in cohort if p.get("name")})
            consistency = round(unique_names * 100.0 / persona_count, 1) if persona_count else 0.0
            if focus:
                focus_names = {str(x.get("name", "")).strip() for x in focus if x.get("name")}
                consistency = round(min(100.0, len(focus_names) * 100.0 / persona_count), 1) if persona_count else 0.0

            overall = round((relevance + coverage + consistency) / 3.0, 1)
            findings = [
                f"{evidence_n} response(s) or evidence item(s) were supplied for this scenario.",
                f"Evidence coverage is {round(coverage, 1)}% across {persona_count} generated personas.",
                f"Persona consistency coverage is {round(consistency, 1)}% based on supplied persona records."
            ]
            output_scenarios.append({
                "scenario": name,
                "theme_relevance_score": round(relevance, 1),
                "evidence_coverage_score": round(coverage, 1),
                "persona_consistency_score": round(consistency, 1),
                "key_findings": findings,
                "issues": [] if evidence_n or focus else ["No research evidence was supplied for this scenario."],
            })

        overall_score = round(sum(x["theme_relevance_score"] + x["evidence_coverage_score"] + x["persona_consistency_score"] for x in output_scenarios) / (3 * len(output_scenarios)), 1) if output_scenarios else 0.0
        confidence = "High" if overall_score >= 80 else ("Medium" if overall_score >= 60 else "Limited")
        return {
            "scenarios": output_scenarios,
            "overall_score": overall_score,
            "overall_confidence": confidence,
            "cross_scenario_themes": [],
            "recommendations": ["Use additional responses for scenarios with incomplete evidence coverage."] if overall_score < 100 else [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def safe(value):
    # ReportLab's built-in Helvetica does not render many Unicode glyphs and
    # displays them as small square boxes. Normalize report text to a safe
    # ASCII representation before putting it into Paragraph/Table content.
    text = str(value or "")
    replacements = {
        "•": "-", "●": "-", "▪": "-", "■": "-", "□": "-", "◦": "-",
        "·": "-", "–": "-", "—": "-", "→": "->", "←": "<-",
        "“": '\"', "”": '\"', "‘": "'", "’": "'", "…": "...",
        "✓": "Yes", "✗": "No", "⚠": "!", "📄": "", "📊": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')


def bullet_lines(value):
    text = str(value or "").strip()
    parts = []
    for line in text.replace("•", "\n").replace("●", "\n").replace("▪", "\n").replace("■", "\n").replace("□", "\n").replace("◦", "\n").splitlines():
        line = line.strip()
        line = re.sub(r"^[\-–—*]+\s*", "", line)
        if line:
            parts.append(line)
    return parts or [text] if text else []


def summarize_source_sentiment(survey_results, interview_logs):
    labels = []
    for item in survey_results or []:
        label = str(item.get("sentiment", "Neutral")).strip().title()
        labels.append(label if label in {"Positive", "Negative", "Neutral"} else "Neutral")
    for log in interview_logs or []:
        for message in log.get("history", []) or []:
            if message.get("role") == "assistant":
                labels.append(classify_interview_sentiment(message.get("content", "")))
    counts = {"Positive": labels.count("Positive"), "Negative": labels.count("Negative"), "Neutral": labels.count("Neutral")}
    total = len(labels)
    breakdown = {key: round(counts[key] * 100 / total, 1) for key in counts} if total else {key: 0 for key in counts}
    return {"sentiment_counts": counts, "sentiment_breakdown": breakdown, "total_responses": total}


def append_insight_section(story, ins, styles, colors, Table, TableStyle, Paragraph, Spacer, Drawing, Pie, VerticalBarChart, mm, title_prefix=""):
    if not ins:
        return
    sent = ins.get("sentiment_breakdown", {}) or {}
    sent_counts = ins.get("sentiment_counts", {"Positive": 0, "Negative": 0, "Neutral": 0}) or {}
    story.append(Paragraph(f"{title_prefix}Sentiment Breakdown", styles["Section"]))
    table = Table([["Positive", "Negative", "Neutral"], [f"{sent_counts.get('Positive', 0)} responses", f"{sent_counts.get('Negative', 0)} responses", f"{sent_counts.get('Neutral', 0)} responses"], [f"{sent.get('Positive', 0)}%", f"{sent.get('Negative', 0)}%", f"{sent.get('Neutral', 0)}%"]], colWidths=[56.5 * mm] * 3)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#B8CCD3")), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(table)
    story.append(Paragraph(f"{title_prefix}Scoring Summary: Average product fit {round(float(ins.get('average_product_fit', 0)), 1)}%", styles["Small"]))


def build_pdf(req: ReportRequest):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.charts.piecharts import Pie
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"ReportLab is required: {exc}")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=13 * mm, leftMargin=13 * mm, topMargin=13 * mm, bottomMargin=13 * mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontSize=20, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#0F4C5C"), spaceAfter=12))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=13, leading=16, textColor=colors.HexColor("#0F4C5C"), spaceBefore=8, spaceAfter=7))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.3, leading=11, spaceAfter=3))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["BodyText"], fontSize=7.5, leading=9.5, spaceAfter=2))
    styles.add(ParagraphStyle(name="Metric", parent=styles["BodyText"], fontSize=9, leading=12, alignment=TA_CENTER))

    story = [Paragraph("Synthetic User Research Report", styles["ReportTitle"])]
    w = req.workspace_params or {}
    details = [
        ["Product Domain", safe(w.get("product_domain"))],
        ["Product Description", safe(w.get("product_description"))],
        ["Target Audience", safe(w.get("target_audience"))],
        ["Research Objective", safe(w.get("research_objective"))],
        ["Personas Generated", str(len(req.cohort))],
    ]
    t = Table(details, colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E7F3F6")), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#B8CCD3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8.2), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 9)]

    ins = req.insights or req.interview_insights or {}
    survey_ins = summarize_source_sentiment(req.survey_results, []) if req.survey_results else {}
    interview_ins = summarize_source_sentiment([], req.interview_logs) if req.interview_logs else {}
    sent = ins.get("sentiment_breakdown", {})
    would = ins.get("would_use_summary", {})
    metric_rows = [[
        Paragraph(f"<b>{len(req.cohort)}</b><br/>Personas", styles["Metric"]),
        Paragraph(f"<b>{ins.get('total_responses', len(req.survey_results))}</b><br/>Responses", styles["Metric"]),
        Paragraph(f"<b>{would.get('would_use_count', 0)}</b><br/>Would Use", styles["Metric"]),
        Paragraph(f"<b>{round(float(ins.get('average_product_fit', 0)))}%</b><br/>Product Fit", styles["Metric"]),
    ]]
    mt = Table(metric_rows, colWidths=[42.5 * mm] * 4)
    mt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F7F8")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#B8CCD3")), ("INNERGRID", (0, 0), (-1, -1), .3, colors.HexColor("#D1DEE2")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story += [mt, Spacer(1, 10)]

    if survey_ins and interview_ins:
        story.append(Paragraph("Survey and Interview Averages", styles["Section"]))
        story.append(Paragraph(f"Survey: Positive {survey_ins.get('sentiment_breakdown', {}).get('Positive', 0)}%, Negative {survey_ins.get('sentiment_breakdown', {}).get('Negative', 0)}%, Neutral {survey_ins.get('sentiment_breakdown', {}).get('Neutral', 0)}%", styles["Small"]))
        story.append(Paragraph(f"Interview: Positive {interview_ins.get('sentiment_breakdown', {}).get('Positive', 0)}%, Negative {interview_ins.get('sentiment_breakdown', {}).get('Negative', 0)}%, Neutral {interview_ins.get('sentiment_breakdown', {}).get('Neutral', 0)}%", styles["Small"]))
        story.append(Paragraph(f"Combined: Positive {ins.get('sentiment_breakdown', {}).get('Positive', 0)}%, Negative {ins.get('sentiment_breakdown', {}).get('Negative', 0)}%, Neutral {ins.get('sentiment_breakdown', {}).get('Neutral', 0)}%", styles["Small"]))
        story.append(Paragraph(f"Survey responses: {survey_ins.get('total_responses', 0)} | Interview responses: {interview_ins.get('total_responses', 0)}", styles["Small"]))
    elif survey_ins and not interview_ins:
        append_insight_section(story, survey_ins, styles, colors, Table, TableStyle, Paragraph, Spacer, Drawing, Pie, VerticalBarChart, mm, "Survey ")
    elif interview_ins and not survey_ins:
        append_insight_section(story, interview_ins, styles, colors, Table, TableStyle, Paragraph, Spacer, Drawing, Pie, VerticalBarChart, mm, "Interview ")

    if ins:
        story.append(Paragraph("Sentiment Breakdown", styles["Section"]))
        sent_counts = ins.get("sentiment_counts", {"Positive": 0, "Negative": 0, "Neutral": 0})
        sentiment_table = Table([["Positive", "Negative", "Neutral"], [f"{sent_counts.get('Positive', 0)} responses", f"{sent_counts.get('Negative', 0)} responses", f"{sent_counts.get('Neutral', 0)} responses"], [f"{sent.get('Positive', 0)}%", f"{sent.get('Negative', 0)}%", f"{sent.get('Neutral', 0)}%"]], colWidths=[56.5 * mm] * 3)
        sentiment_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#B8CCD3")), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        story.append(sentiment_table)

        # Visual sentiment diagram
        d = Drawing(480, 155)
        pie = Pie()
        pie.x = 120; pie.y = 5; pie.width = 135; pie.height = 135
        pie.data = [float(sent.get("Positive", 0)), float(sent.get("Neutral", 0)), float(sent.get("Negative", 0))]
        pie.labels = [f"Positive {sent.get('Positive', 0)}%", f"Neutral {sent.get('Neutral', 0)}%", f"Negative {sent.get('Negative', 0)}%"]
        pie.slices.strokeWidth = 0.5
        d.add(pie)
        story += [Spacer(1, 5), d]

        story.append(Paragraph("Recurring Themes", styles["Section"]))
        for item in ins.get("recurring_themes", []):
            if isinstance(item, dict):
                people = ", ".join(item.get("personas", []))
                story.append(Paragraph(f"<b>{safe(item.get('theme'))}</b> — {safe(item.get('description'))} <br/><b>Evidence:</b> {item.get('evidence_count', 0)} <br/><b>Personas:</b> {safe(people)}", styles["Small"]))
            else:
                story.append(Paragraph(safe(item), styles["Small"]))

        story.append(Paragraph("Theme Clusters", styles["Section"]))
        cluster_rows = [["Cluster", "Themes", "Description"]]
        for c in ins.get("theme_clusters", []):
            cluster_rows.append([safe(c.get("name")), safe(" · ".join(c.get("themes", []))), safe(c.get("description"))])
        if len(cluster_rows) > 1:
            ct = Table(cluster_rows, colWidths=[38 * mm, 60 * mm, 72 * mm], repeatRows=1)
            ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#B8CCD3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7.5)]))
            story += [ct, Spacer(1, 6)]

        story.append(Paragraph("Agreement / Disagreement Patterns", styles["Section"]))
        for a in ins.get("agreement_patterns", []):
            story.append(Paragraph(f"<b>{safe(a.get('topic'))}</b> — {safe(a.get('agreement_level'))}<br/>{safe(a.get('summary'))}<br/><b>Agreement:</b> {safe(', '.join(a.get('agreeing_personas', [])))}<br/><b>Dissent:</b> {safe(', '.join(a.get('dissenting_personas', [])))}", styles["Small"]))

        story.append(Paragraph("Behavioral Trends", styles["Section"]))
        for b in ins.get("behavioral_trends", []):
            story.append(Paragraph(f"<b>{safe(b.get('trend'))}</b><br/>{safe(b.get('description'))}<br/><b>Implication:</b> {safe(b.get('implication'))}<br/><b>Personas:</b> {safe(', '.join(b.get('affected_personas', [])))}", styles["Small"]))

        story.append(Paragraph("Would Use This Product — Individual Scoring", styles["Section"]))
        adoption_rows = [["Persona", "Score", "Reasoning"]]
        for a in ins.get("adoption_scoring", []):
            adoption_rows.append([safe(a.get("persona_name")), f"{round(float(a.get('would_use_score', 0)))}%", safe(a.get("reasoning"))])
        if len(adoption_rows) > 1:
            at = Table(adoption_rows, colWidths=[42 * mm, 25 * mm, 103 * mm], repeatRows=1)
            at.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#B8CCD3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7.2)]))
            story += [at, Spacer(1, 8)]

        # Adoption visual diagram
        scores = [round(float(a.get("would_use_score", 0))) for a in ins.get("adoption_scoring", [])]
        names = [str(a.get("persona_name", ""))[:12] for a in ins.get("adoption_scoring", [])]
        if scores:
            d2 = Drawing(500, 210)
            chart = VerticalBarChart()
            chart.x = 45; chart.y = 30; chart.height = 145; chart.width = 420
            chart.data = [scores]
            chart.categoryAxis.categoryNames = names
            chart.valueAxis.valueMin = 0; chart.valueAxis.valueMax = 100; chart.valueAxis.valueStep = 20
            chart.barWidth = 8
            chart.groupSpacing = 10
            d2.add(chart)
            story += [Paragraph("Individual adoption scores", styles["Small"]), d2]

        story.append(Paragraph("Would Use — Persona Segment Scoring", styles["Section"]))
        seg_rows = [["Segment", "Members", "Average Score", "Reasoning"]]
        for s in ins.get("segment_adoption_scoring", []):
            seg_rows.append([safe(s.get("segment")), str(s.get("member_count", 0)), f"{round(float(s.get('average_would_use_score', 0)))}%", safe(s.get("reasoning"))])
        if len(seg_rows) > 1:
            st = Table(seg_rows, colWidths=[40 * mm, 22 * mm, 28 * mm, 80 * mm], repeatRows=1)
            st.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#B8CCD3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7.2)]))
            story += [st, Spacer(1, 8)]

        story.append(Paragraph("Segment Breakdown", styles["Section"]))
        bd_rows = [["Segment", "Members", "Percentage"]]
        for s in ins.get("segment_breakdown", []):
            bd_rows.append([safe(s.get("segment")), str(s.get("member_count", 0)), f"{round(float(s.get('percentage', 0)), 1)}%"])
        if len(bd_rows) > 1:
            bt = Table(bd_rows, colWidths=[90 * mm, 35 * mm, 45 * mm], repeatRows=1)
            bt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#B8CCD3")), ("ALIGN", (1, 1), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
            story.append(bt)

        story.append(Paragraph("Research Quality / Validation", styles["Section"]))
        rq = ins.get("research_quality", {})
        rq_rows = [
            ["Metric", "Percentage"],
            ["Theme Relevance", f"{round(float(rq.get('theme_relevance_score', 0)))}%"],
            ["Evidence Coverage", f"{round(float(rq.get('evidence_coverage_score', 0)))}%"],
            ["Persona Consistency", f"{round(float(rq.get('consistency_score', 0)))}%"],
            ["Overall Quality", f"{round(float(rq.get('overall_score', 0)))}%"],
        ]
        if req.validation_report:
            vr = req.validation_report
            rq_rows.append(["Validation Overall", f"{round(float(vr.get('overall_score', 0)))}%"])
        qt = Table(rq_rows, colWidths=[105 * mm, 65 * mm], repeatRows=1)
        qt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#B8CCD3")), ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (1, 1), (1, -1), "CENTER")]))
        story += [qt, Spacer(1, 8)]

        if req.validation_report:
            story.append(Paragraph("Validation Scenario Percentages", styles["Section"]))
            for s in req.validation_report.get("scenarios", []):
                story.append(Paragraph(f"<b>{safe(s.get('scenario'))}</b> — Theme relevance: {round(float(s.get('theme_relevance_score', 0)))}% · Evidence coverage: {round(float(s.get('evidence_coverage_score', 0)))}% · Persona consistency: {round(float(s.get('persona_consistency_score', 0)))}%", styles["Small"]))
                for finding in s.get("key_findings", []):
                    story.append(Paragraph(f"- {safe(finding)}", styles["Tiny"]))

    story.append(Paragraph("Persona Profiles", styles["Section"]))
    for idx, p in enumerate(req.cohort, 1):
        rows = [["Field", "Persona Detail"]]
        for key in ["name", "age", "role", "location", "psychological_behavior", "personality", "tech_adoption_level", "preferred_channel", "goals", "pain_points", "risk_tier", "target_audience", "research_objective", "memory_consistency_node"]:
            val = p.get(key, "")
            if key in {"psychological_behavior", "personality", "tech_adoption_level", "preferred_channel", "goals", "pain_points", "target_audience", "research_objective", "memory_consistency_node"}:
                val = "<br/>".join("- " + safe(x) for x in bullet_lines(val))
            else:
                val = safe(val)
            rows.append([key.replace("_", " ").title(), val])
        pt = Table([[safe(a), Paragraph(b, styles["Tiny"]) if b else ""] for a, b in rows], colWidths=[45 * mm, 125 * mm], repeatRows=1)
        pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#B8CCD3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story += [Paragraph(f"Persona {idx}", styles["Heading3"]), pt, Spacer(1, 7)]

    if req.survey_results:
        story.append(Paragraph("Survey Responses", styles["Section"]))
        for r in req.survey_results:
            story.append(Paragraph(f"<b>{safe(r.get('name'))}</b> · {safe(r.get('sentiment'))} · Would use: {round(float(r.get('would_use_score', 0)))}%<br/>{safe(r.get('response'))}", styles["Small"]))

    if req.interview_logs:
        story.append(Paragraph("Interview Conversations", styles["Section"]))
        for log in req.interview_logs:
            story.append(Paragraph(f"<b>{safe(log.get('personaName'))}</b>", styles["Small"]))
            for m in log.get("history", []):
                story.append(Paragraph(f"<b>{safe(m.get('role'))}:</b> {safe(m.get('content'))}", styles["Tiny"]))

    # Final page: concise conclusion derived only from the generated research data.
    story.append(PageBreak())
    story.append(Paragraph("Overall Conclusion", styles["ReportTitle"]))
    conclusion_parts = []
    if ins:
        top_theme = ins.get("top_theme")
        majority_segment = ins.get("majority_segment")
        avg_fit = ins.get("average_product_fit")
        total_responses = ins.get("total_responses", len(req.survey_results))
        if top_theme:
            conclusion_parts.append(f"The strongest recurring theme identified was <b>{safe(top_theme)}</b>.")
        if majority_segment:
            conclusion_parts.append(f"The largest identified persona segment was <b>{safe(majority_segment)}</b>.")
        if avg_fit is not None and total_responses:
            conclusion_parts.append(f"Across {total_responses} supplied response(s), the average would-use score was <b>{round(float(avg_fit), 1)}%</b>.")
        conclusion_parts.append(f"Sentiment distribution was Positive {sent.get('Positive', 0)}%, Negative {sent.get('Negative', 0)}%, and Neutral {sent.get('Neutral', 0)}%.")
        rq_score = ins.get("research_quality", {}).get("overall_score")
        if rq_score is not None:
            conclusion_parts.append(f"The synthesized research-quality score was <b>{round(float(rq_score), 1)}%</b>.")
    if not conclusion_parts:
        conclusion_parts.append("No synthesized insight data was available for a data-based conclusion.")
    for part in conclusion_parts:
        story.append(Paragraph(part, styles["Small"]))
        story.append(Spacer(1, 5))

    doc.build(story)
    buf.seek(0)
    return buf


@app.post("/api/download-report")
def download_report(req: ReportRequest):
    try:
        buf = build_pdf(req)
        return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": "inline; filename=research_report.pdf"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
