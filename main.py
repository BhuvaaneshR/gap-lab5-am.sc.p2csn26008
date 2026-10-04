import json
import re
import sys
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from client import get_client, get_model


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Question(BaseModel):
    question: str = Field(min_length=10, max_length=300)
    options: list[str] = Field(min_length=4, max_length=4)
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

    prompt = build_prompt(topic)

    # ---------------------------------------------------------------
    # One model call through the supplied client.py
    # ---------------------------------------------------------------
    try:
        client = get_client()
        model = get_model()

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

    except Exception as exc:
        print(f"Model call failed: {exc}", file=sys.stderr)
        print("error")
        return 1

    # ---------------------------------------------------------------
    # Obtain the model's text response
    # ---------------------------------------------------------------
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        print("Model response did not contain message content", file=sys.stderr)
        print("invalid_output")
        return 1

    if not content or not content.strip():
        print("Model returned an empty response", file=sys.stderr)
        print("invalid_output")
        return 1

    # ---------------------------------------------------------------
    # Refusal detection
    # ---------------------------------------------------------------
    if is_refusal(content):
        print("refused")
        return 1

    # ---------------------------------------------------------------
    # Extract JSON
    # ---------------------------------------------------------------
    try:
        json_text = extract_json(content)
    except ValueError as exc:
        print(f"JSON extraction failed: {exc}", file=sys.stderr)
        print("invalid_output")
        return 1

    # ---------------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------------
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        print("invalid_output")
        return 1

    # ---------------------------------------------------------------
    # Pydantic validation
    # ---------------------------------------------------------------
    try:
        validated = GeneratedResponse.model_validate(data)
    except ValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        print("invalid_output")
        return 1

    # ---------------------------------------------------------------
    # Successful result
    # ---------------------------------------------------------------
    print(json.dumps(validated.model_dump(), indent=2))
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())