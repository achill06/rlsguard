"""
baseline_review.py

The "reasonable basic way to handle this task" comparator, per the
hackathon brief: one direct prompt, no tools, no sandbox, no verification.
This is deliberately not sophisticated. Its only job is to give the
advanced agent something honest to be measured against.

Supports either Anthropic or Gemini as the model provider, since only one
is needed and Gemini has a genuinely free tier.

Usage:
    python baseline_review.py path/to/schema.sql
    python baseline_review.py path/to/schema.sql --out results.json
    python baseline_review.py path/to/schema.sql --provider anthropic

Requires either GEMINI_API_KEY or ANTHROPIC_API_KEY in the environment,
matching whichever --provider you choose (default: gemini, since it's free).
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROMPT_TEMPLATE = """You are a database engineer doing a routine access-control \
configuration review. Read the Supabase/Postgres schema below and check \
whether each table's Row-Level Security setup correctly restricts data to \
its intended owner. For each table, note whether RLS is enabled, whether its \
policies reference the caller's identity, and whether INSERT/UPDATE policies \
have a WITH CHECK clause. Give a one-line note per table.

Schema:
{schema}
"""

# Fail fast instead of hanging indefinitely on a stuck connection.
REQUEST_TIMEOUT_SECONDS = 30


def review_with_anthropic(schema_text: str) -> str:
    import anthropic

    model = os.environ.get("RLSGUARD_MODEL", "claude-sonnet-5")
    client = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": PROMPT_TEMPLATE.format(schema=schema_text)}
            ],
        )
    except Exception as e:
        return f"[Anthropic API error: {e}]"

    return "".join(block.text for block in response.content if block.type == "text")


def review_with_gemini(schema_text: str) -> str:
    from google import genai
    from google.genai import types

    model = os.environ.get("RLSGUARD_MODEL", "gemini-3.5-flash-lite")
    # Timeout is in milliseconds. The SDK already retries transient
    # errors internally (via tenacity), so we don't add our own retry
    # loop on top of it -- that just multiplies worst-case wait time.
    client = genai.Client(
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_SECONDS * 1000)
    )
    safety_settings = [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
    ]

    try:
        response = client.models.generate_content(
            model=model,
            contents=PROMPT_TEMPLATE.format(schema=schema_text),
            config=types.GenerateContentConfig(safety_settings=safety_settings),
        )
    except Exception as e:
        return f"[Gemini API error: {e}]"

    if not response.text:
        candidate = response.candidates[0] if response.candidates else None
        finish_reason = getattr(candidate, "finish_reason", "unknown")
        return f"[No text returned. finish_reason={finish_reason}]"
    return response.text


PROVIDERS = {
    "anthropic": review_with_anthropic,
    "gemini": review_with_gemini,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_file", type=Path, help="Path to a .sql schema file")
    parser.add_argument(
        "--provider",
        choices=PROVIDERS.keys(),
        default="gemini",
        help="Which model provider to use (default: gemini)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional path to save raw output as JSON"
    )
    args = parser.parse_args()

    if not args.schema_file.exists():
        print(f"Schema file not found: {args.schema_file}", file=sys.stderr)
        sys.exit(1)

    key_var = "GEMINI_API_KEY" if args.provider == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_var):
        print(f"{key_var} is not set in the environment.", file=sys.stderr)
        sys.exit(1)

    schema_text = args.schema_file.read_text()
    raw_output = PROVIDERS[args.provider](schema_text)

    print(raw_output)

    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "schema_file": str(args.schema_file),
                    "provider": args.provider,
                    "raw_output": raw_output,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()