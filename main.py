import json
import random
import re
import sys
import time
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from client import get_client, get_model
from observability import Timer, estimate_cost, estimate_tokens, log_call

# Sampling settings, recorded under Inputs in SPEC.md.
TEMPERATURE = 0.7
MAX_TOKENS = 2000

# Retry policy, from SPEC.md.
MAX_ERROR_ATTEMPTS = 3   # error: 3 attempts in total
MAX_DELAY_SECONDS = 8    # no wait is ever longer than this


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# Each option must be 1 to 100 characters, as the prompt and SPEC.md promise.
Option = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class Question(BaseModel):
    question: str = Field(min_length=10, max_length=300)
    options: list[Option] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    difficulty: Literal["easy", "medium", "hard"]

    @model_validator(mode="after")
    def validate_answer_index(self):
        # Cross-field validation:
        # answer_index must refer to one of the supplied options.
        if self.answer_index >= len(self.options):
            raise ValueError("answer_index does not point to an existing option")
        return self


class GeneratedResponse(BaseModel):
    topic: str
    questions: list[Question] = Field(min_length=5, max_length=5)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_topic(topic: str) -> bool:
    topic = topic.strip()
    return 3 <= len(topic) <= 200


# ---------------------------------------------------------------------------
# Refusal detection
# ---------------------------------------------------------------------------

def is_refusal(text: str) -> bool:
    lowered = text.lower()

    refusal_phrases = [
        "i'm sorry, but i can't help",
        "i'm sorry, but i cannot help",
        "i can't help with that",
        "i cannot help with that",
        "i'm unable to help",
        "i am unable to help",
        "i can't generate",
        "i cannot generate",
    ]

    return any(phrase in lowered for phrase in refusal_phrases)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def extract_json(text: str) -> str:
    """
    Extract a JSON object from:
      1. Plain JSON
      2. Markdown ```json ... ``` fences
      3. A preamble followed by JSON
    """

    text = text.strip()

    if not text:
        raise ValueError("empty model response")

    # Case 1 / 2:
    # Extract content from a Markdown code fence if present.
    fence_match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if fence_match:
        text = fence_match.group(1).strip()

    # Case 1:
    # Response is already plain JSON.
    if text.startswith("{") and text.endswith("}"):
        return text

    # Case 3:
    # A preamble or other text appears before the JSON object.
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or start >= end:
        raise ValueError("no JSON object found in model response")

    return text[start:end + 1]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(topic: str) -> str:
    return f"""
Generate exactly 5 multiple-choice questions about the topic "{topic}".

Return exactly one JSON object with this structure:

{{
  "topic": "{topic}",
  "questions": [
    {{
      "question": "question text",
      "options": [
        "option 1",
        "option 2",
        "option 3",
        "option 4"
      ],
      "answer_index": 0,
      "difficulty": "easy"
    }}
  ]
}}

Requirements:
- Exactly 5 questions.
- Exactly 4 options for every question.
- answer_index must be 0, 1, 2, or 3.
- difficulty must be exactly one of: easy, medium, hard.
- Each question must be between 10 and 300 characters.
- Each option must be between 1 and 100 characters.
- Return JSON only.
- Do not add explanations before or after the JSON.
""".strip()


def build_repair_prompt(topic: str) -> str:
    # Used for the one repair retry after an invalid_output reply.
    return (
        build_prompt(topic)
        + "\n\nYour previous reply could not be used: it was not valid JSON "
        "in the structure above. Reply again with only the JSON object."
    )


# ---------------------------------------------------------------------------
# Reply classification
# ---------------------------------------------------------------------------

def classify_reply(content):
    """Turn the model's text into (status, validated).

    status is ok, invalid_output or refused. validated is the parsed
    GeneratedResponse when status is ok, otherwise None.
    """
    if not content or not content.strip():
        print("Model returned an empty response", file=sys.stderr)
        return "invalid_output", None

    if is_refusal(content):
        return "refused", None

    try:
        json_text = extract_json(content)
    except ValueError as exc:
        print(f"JSON extraction failed: {exc}", file=sys.stderr)
        return "invalid_output", None

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return "invalid_output", None

    try:
        validated = GeneratedResponse.model_validate(data)
    except ValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return "invalid_output", None

    return "ok", validated


# ---------------------------------------------------------------------------
# One logged model call
# ---------------------------------------------------------------------------

def read_usage(response, prompt, content):
    """Return (prompt_tokens, completion_tokens, tokens_estimated).

    Uses the provider's counts when it reports them. When usage is missing,
    has a None count, or is zeroed, both counts are estimated instead.
    """
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)

    missing = prompt_tokens is None or completion_tokens is None
    zeroed = prompt_tokens == 0 and completion_tokens == 0

    if missing or zeroed:
        return estimate_tokens(prompt), estimate_tokens(content or ""), True

    return prompt_tokens, completion_tokens, False


def get_retry_after(exc):
    """Seconds the provider asked us to wait, or None if it did not say.

    Looks for a retry_after attribute (the stub's rate-limit error), then
    for a Retry-After header on the error's HTTP response (the OpenAI SDK).
    """
    value = getattr(exc, "retry_after", None)
    if value is None:
        headers = getattr(getattr(exc, "response", None), "headers", None)
        if headers is not None:
            value = headers.get("retry-after")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def call_model(client, model, prompt, attempt):
    """Make one model call: time it, classify the result, write one log line.

    Returns (status, validated, retry_after). retry_after is only set when
    the call failed and the provider said how long to wait. Every call
    writes exactly one line to run_log.jsonl, whatever the status.
    """
    try:
        with Timer() as timer:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
    except Exception as exc:
        print(f"Model call failed: {exc}", file=sys.stderr)
        # The call never completed, so tokens and cost are unknown: null.
        log_call("error", model, None, None, timer.ms, None, attempt=attempt)
        return "error", None, get_retry_after(exc)

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        print("Model response did not contain message content", file=sys.stderr)
        content = None

    status, validated = classify_reply(content)
    prompt_tokens, completion_tokens, estimated = read_usage(
        response, prompt, content
    )

    log_call(
        status,
        getattr(response, "model", None) or model,
        prompt_tokens,
        completion_tokens,
        timer.ms,
        estimate_cost(prompt_tokens, completion_tokens),
        tokens_estimated=estimated,
        attempt=attempt,
    )
    return status, validated, None


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

def backoff_delay(next_attempt, retry_after):
    """Seconds to wait before attempt number next_attempt.

    (2 ** n) plus up to 1 second of jitter. If the provider's Retry-After is
    longer, wait that instead. Never more than MAX_DELAY_SECONDS.
    """
    delay = (2 ** next_attempt) + random.uniform(0, 1)
    if retry_after is not None and retry_after > delay:
        delay = retry_after
    return min(delay, MAX_DELAY_SECONDS)


def run_with_retries(client, model, topic):
    """Call the model under the retry policy. Returns (status, validated).

    - ok: stop.
    - refused: never retried.
    - invalid_output: one repair retry, which is not itself retried.
    - error: up to MAX_ERROR_ATTEMPTS attempts in total, with backoff. An
      error on the repair retry ends the run.
    """
    prompt = build_prompt(topic)
    attempt = 0
    errors = 0
    repaired = False

    while True:
        attempt += 1
        status, validated, retry_after = call_model(client, model, prompt, attempt)

        if status in ("ok", "refused"):
            return status, validated

        if status == "invalid_output":
            if repaired:
                return status, None
            repaired = True
            prompt = build_repair_prompt(topic)
            print("Reply unusable, making one repair retry", file=sys.stderr)
            continue

        # status == "error"
        errors += 1
        if repaired or errors >= MAX_ERROR_ATTEMPTS:
            return status, None
        delay = backoff_delay(attempt + 1, retry_after)
        print(f"Retrying in {delay:.1f}s", file=sys.stderr)
        time.sleep(delay)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main() -> int:
    # The assignment specifies the topic as the first command-line argument.
    if len(sys.argv) < 2:
        return 2

    topic = sys.argv[1].strip()

    # Input gate: reject before making any model call.
    if not validate_topic(topic):
        return 2

    try:
        client = get_client()
        model = get_model()
    except Exception as exc:
        print(f"Could not create the model client: {exc}", file=sys.stderr)
        print("error")
        return 1

    status, validated = run_with_retries(client, model, topic)

    if status != "ok":
        print(status)
        return 1

    print(json.dumps(validated.model_dump(), indent=2))
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())