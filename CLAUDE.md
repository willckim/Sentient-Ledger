# Sentient Ledger

## What this is
Autonomous GL validation pipeline built on the Claude API. Personal project.
Runs on Raspberry Pi 5 with AI Hat+ (Hailo NPU). Local inference via Ollama.
ChromaDB for RAG. Telegram for autonomous notifications.
Migrating from OpenClaw to PicoClaw as local AI agent framework.

## Architecture
- Lead agent orchestrates sub-agents
- Sub-agents: gl-validator, tax-checker, anomaly-detector
- RAG: ChromaDB indexed against IRS publications and IRC sections
- Notifications: Telegram
- Always-on: systemd service on Pi

## Rules

**Plan first.** Before touching any code, write the plan in TASKS.md. If something goes wrong mid-task, stop and re-plan. Never push through a broken state.

**Subagents.** For complex work, spawn a subagent rather than polluting the main context. Keep the main session clean.

**Self-improvement loop.** Every time I correct you or you make a mistake, add a lesson to .claude/lessons.md. Format: "- [date] lesson learned"

**Verification standard.** Never tell me a task is complete without proving it works. Run the app, check the logs, confirm the output. Ask yourself: would a staff engineer approve this?

**Demand elegance.** For any non-trivial change, pause and ask if there is a more elegant solution before implementing. If a fix feels hacky, flag it and rebuild it properly.

**Autonomous bug fixing.** When given a bug, just fix it. Go to the logs, find the root cause, resolve it. Don't ask me what to do — show me what you did.

**Git discipline.** Commit at logical checkpoints with meaningful messages. Never push to main without confirming the branch first.

**Task tracking.** Before starting any new feature or fix, add it to TASKS.md under "In Progress". Move it to "Completed" when verified working. Never start work without a TASKS.md entry.

## Hard Rules
- Never suggest cloud hosting — this runs locally on the Pi for privacy
- Never suggest LangChain or LangGraph — keep dependencies minimal
- If AI is needed, use claude-sonnet-4-6 via API or local Ollama models only
