#!/usr/bin/env bash
set -euo pipefail

# Skip if no staged changes
if git diff --cached --quiet; then
  exit 0
fi

REVIEW_PROMPT="$(cat .claude/commands/review.md)

IMPORTANT: After your review, your final line must be exactly one of:
- RESULT:PASS
- RESULT:FAIL"

OUTPUT=$(claude -p "$REVIEW_PROMPT" --allowedTools "Bash(git diff:*)" "Read" "Grep" 2>&1) || true

echo "$OUTPUT"

if echo "$OUTPUT" | grep -q "RESULT:FAIL"; then
  echo ""
  echo "Code review found MUST FIX issues. Please address them before committing."
  exit 1
fi

exit 0
