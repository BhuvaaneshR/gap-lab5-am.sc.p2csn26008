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



## 2026-10-04 - Model: gpt-oss-20b instead of llama-3.1-8b-instant

I first set LLM_MODEL=llama-3.1-8b-instant, because it is a plain instruct model and a good fit for five short questions. My first real call returned a 404 model_not_found ("does not exist or you do not have access to it"). I switched to openai/gpt-oss-20b; two real runs ("laptop" and "photosynthesis") both returned five valid questions and ok. I considered openai/gpt-oss-120b, which costs twice as much per token for a task. The cost of my choice is that gpt-oss is a reasoning model, so hidden reasoning tokens may add cost and latency. I will measure that in run_log.jsonl instead of assuming it.


## 2026-10-04 - All errors are retried the same way

I chose to retry every error up to 3 attempts in total, without trying to tell temporary failures such as a 429 from permanent ones such as the 404 I hit on llama-3.1-8b-instant. I considered not retrying permanent failures, but rejected that, because stub:error raises a generic exception that carries no signal to classify, and the lab's check expects 2 or 3 log lines for it. The cost is that a permanent error wastes about three attempts and a few seconds of backoff before it is reported.