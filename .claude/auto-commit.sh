#!/usr/bin/env bash
# Auto-commit hook for Claude Code (wired in .claude/settings.json → Stop event).
#
# Triggered after every Claude turn. Stages tracked + untracked changes and
# creates ONE commit covering everything Claude touched this turn.
#
# Behavior:
#   - No-op if not inside a git repo (cwd-safe across worktrees)
#   - No-op if there's nothing to commit (clean tree → silent exit)
#   - Skips files matching gitignore (we use `git add -A` so gitignore is honored)
#   - Commit message: "chore(auto): <N> files (<top file>, ...)" — short but
#     identifying. Full file list goes in the commit body.
#   - Trailer marks the commit as agent-authored so `git log --grep` finds them
#
# Failure isolation: any error is logged to .claude/auto-commit.log and the
# script exits 0 — a broken hook must NEVER block the Claude turn.

set -u  # unset vars = error, but no -e: we handle failures explicitly

LOG="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/auto-commit.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

log() {
    # Best-effort logging — drop on failure rather than crash the hook
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null || true
}

# Bail if not a git repo (e.g. someone clones to a non-git location)
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "skip: not a git repo"
    exit 0
fi

# Bail if nothing changed
if [[ -z "$(git status --porcelain)" ]]; then
    exit 0
fi

# Build a short subject from the changed file list. Use printf|while instead
# of mapfile so we stay compatible with bash 3.2 (macOS default).
CHANGED_LIST=$(git status --porcelain | awk '{print $NF}')
COUNT=$(printf '%s\n' "$CHANGED_LIST" | sed '/^$/d' | wc -l | tr -d ' ')
FIRST=$(printf '%s\n' "$CHANGED_LIST" | sed -n '1p' | xargs basename 2>/dev/null || echo "files")

if [[ "$COUNT" == "1" ]]; then
    SUBJECT="chore(auto): ${FIRST}"
else
    SUBJECT="chore(auto): ${COUNT} files (${FIRST}, ...)"
fi

# Full file list as body — useful for grepping later
BODY="$CHANGED_LIST"

# Stage + commit. Use --no-verify so heavy pre-commit hooks (e.g. running
# the test suite) don't fan out into the Stop hook path.
if ! git add -A 2>>"$LOG"; then
    log "ERROR: git add failed"
    exit 0
fi

if ! git commit -m "$SUBJECT" -m "$BODY" -m "Auto-committed-by: claude-code" --no-verify >>"$LOG" 2>&1; then
    log "ERROR: git commit failed (subject: $SUBJECT)"
    exit 0
fi

log "committed: $SUBJECT"
exit 0
