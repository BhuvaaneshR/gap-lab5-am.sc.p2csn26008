# What it does

<!-- One paragraph. Someone outside this course should understand it. -->
The application accepts a topic from the command line input and asks a language model to generate five multiple-choice questions about that topic. Each question contains the question text, exactly four answer options, the index of the correct option, and a difficulty level. The application extracts JSON from the model response even when the response contains a Markdown code fence or a short preamble, parses the JSON, validates it with Pydantic, and reports whether the response was accepted, unusable, refused, or failed.

# Inputs

<!-- Every input. Type, constraints, and what happens if it is absent. -->
The application takes one required command-line input: topic.

topic is a string between 5 and 50 characters after removing leading and trailing whitespace(if any). A topic containing only whitespace, an absent topic, or a topic outside this length range is rejected before any model call and exits with code 2.

The model configuration is read from .env through client.py using LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL.

# Outputs

<!-- The exact shape. If it is JSON, the actual keys. -->
A successful response contains the following JSON structure:

topic: string containing the requested topic.

questions: a list containing exactly 5 question objects.

Each question object contains:

question: a string between 10 and 500 characters.

options: a list containing exactly 4 answer strings, each between 1 and 50 characters.

answer_index: an integer from 0 to 3 identifying the correct option in options.

difficulty: one of easy, medium, or hard.

The program may print the generated questions or other useful information, but the last non-empty stdout line must be exactly ok, invalid_output, refused, or error.


# Failure cases

<!-- What can go wrong, and what the program does about each one.
     Each one must be something you can make happen on purpose. -->
An invalid or missing topic is rejected before any model call and exits with code 2.

A model response that is empty, malformed JSON, or valid JSON that fails the defined schema or validation rules is reported as invalid_output and exits with code 1.

A response containing an explicit refusal to generate questions is reported as refused and exits with code 1.

A model or client failure that prevents completion of the request is reported as error and exits with code 1.

A valid response enclosed in a Markdown JSON code fence or preceded by a short explanatory preamble is accepted after JSON extraction and validation.

The answer_index must point to an existing option, and each question must contain exactly four options.

# Acceptance checks

<!-- How someone else proves it works, without asking you anything.
     Each one a command they can run and a result they can see. -->
python main.py <topic> with a working provider must produce a valid response and end with ok and exit code 0.

The application must accept the supplied valid sample response and reject the supplied invalid sample response.

The stub modes stub:ok, stub:fenced, and stub:preamble must end with ok and exit code 0.

The stub modes stub:malformed, stub:badshape, and stub:empty must end with invalid_output and exit code 1.

The stub mode stub:refused must end with refused and exit code 1.

The stub mode stub:error must end with error and exit code 1.

An empty topic must exit with code 2 without making a model call.

The complete implementation must pass python check.py ..

# Out of scope

<!-- What you are deliberately not building. -->
The application does not provide a web or graphical interface, store questions in a database, authenticate users, maintain question history across executions, or guarantee that questions are unique across separate runs.