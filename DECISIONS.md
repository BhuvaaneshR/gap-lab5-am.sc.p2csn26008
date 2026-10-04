# Decisions

<!--
One entry per decision, written when the decision happened, not at the end.
A decision has an alternative you rejected. "Used Python because it's popular"
is not a decision. "Fixed a bug in main.py" is a commit message.

Format:

## YYYY-MM-DD - short title

What I found.
What I changed it to.
What else I considered, and why I did not do that.
-->

## 2026-09-20 - Question format and response schema

I chose to generate exactly five multiple-choice questions for each topic. Each question contains exactly four options, an `answer_index`, and a `difficulty` value of `easy`, `medium`, or `hard`. I chose `answer_index` instead of storing the correct answer as text because the index gives a fixed relationship between the answer and the options and is straightforward to validate. I considered using short-answer questions or allowing a variable number of options, but rejected those alternatives because they would make the response structure less consistent and validation less precise.

## 2026-09-20 - JSON extraction strategy

I chose to implement an `extract_json` function that extracts the JSON object from the model response and handles both Markdown code fences and explanatory text before the JSON. I considered requiring the model to return perfectly formatted JSON and passing the response directly to `json.loads()`, but rejected that approach because a model can return valid JSON surrounded by formatting or a short preamble. Handling these cases in the application makes the parser more tolerant without changing the required response schema.

## 2026-09-20 - Refusal detection

I chose to detect explicit refusal language before attempting JSON parsing. I considered treating every unparseable prose response as `invalid_output`, but rejected that approach because the application contract distinguishes a model refusal from other unusable responses. The application therefore checks for explicit refusal phrases and reports `refused` when they are detected. The trade-off is that phrase-based detection may produce a false positive if a legitimate response contains one of the selected refusal phrases.