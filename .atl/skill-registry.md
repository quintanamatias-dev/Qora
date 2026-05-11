# Skill Registry — Qora
# Updated: 2026-05-11

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

---

## User Skills

| Trigger | Skill | Path |
|---------|-------|------|
| create skill, add agent instructions, document AI workflow patterns | skill-creator | /Users/mati/Desktop/Qora/skills/skill-creator/SKILL.md |
| create client, configure agent, ElevenLabs setup, voice demo routing | qora-client-agent-setup | /Users/mati/Desktop/Qora/skills/qora-client-agent-setup/SKILL.md |
| Dashboard, admin panel, SaaS app, tool, settings page | interface-design | /Users/mati/.agents/skills/interface-design/SKILL.md |
| Final quality pass before shipping, polish alignment/spacing | polish | /Users/mati/.agents/skills/polish/SKILL.md |
| Remotion, video creation in React | remotion-best-practices | /Users/mati/.agents/skills/remotion-best-practices/SKILL.md |
| "judgment day", "review adversarial", "dual review", "juzgar" | judgment-day | /Users/mati/.config/opencode/skills/judgment-day/SKILL.md |
| Creating a GitHub issue, reporting a bug, requesting a feature | issue-creation | /Users/mati/.config/opencode/skills/issue-creation/SKILL.md |
| Creating a pull request, opening a PR, preparing for review | branch-pr | /Users/mati/.config/opencode/skills/branch-pr/SKILL.md |
| Creating a new skill, adding agent instructions | skill-creator | /Users/mati/.config/opencode/skills/skill-creator/SKILL.md |
| Go tests, Bubbletea TUI testing | go-testing | /Users/mati/.config/opencode/skills/go-testing/SKILL.md |

---

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### interface-design
- Scope: dashboards, admin panels, SaaS apps, tools — NOT landing pages or marketing
- Answer before coding: who is the user, what must they accomplish, what should it feel like
- Every choice must be explainable — never default to "clean and modern"
- Typography, navigation, and data are design decisions, not infrastructure
- Token names must evoke the product world (--ink, --parchment) not generic scales (--gray-700)
- If another AI would produce the same output, you have failed — design from specific intent
- No placeholder lorem ipsum or generic icons without justification

### polish
- Only polish functionally complete work — polish is last, not first
- Check pixel-perfect alignment with grid overlay
- All spacing must use design tokens — no arbitrary values (no random 13px gaps)
- Every interactive element needs all states: default, hover, focus, active, disabled
- Contrast ratios must meet WCAG — all text readable
- Never put gray text on colored backgrounds — use a shade of that color
- Test at multiple viewport sizes before declaring done

### remotion-best-practices
- Load specific rule files from ./rules/ for each domain (3d, animations, audio, captions, etc.)
- Use Mediabunny for video/audio duration, frame extraction, and decode checking
- Captions: load rules/subtitles.md for timing and styling details
- FFmpeg: use only for trimming or silence detection, load rules/ffmpeg.md
- Audio visualization: load rules/audio-visualization.md for spectrum/waveform patterns

### judgment-day
- Launch TWO independent blind judge sub-agents in parallel via delegate (never sequential)
- Neither judge knows about the other — no cross-contamination
- Orchestrator synthesizes: Confirmed (both found) / Suspect A / Suspect B / Contradiction
- Classify every WARNING as real (can a normal user trigger it?) or theoretical (contrived scenario)
- Theoretical warnings → INFO only, do NOT fix, do NOT block
- Fix Agent runs only if confirmed CRITICALs or real WARNINGs exist
- Re-judge both in parallel after fixes — max 2 iterations before escalation
- Resolve skill registry BEFORE launching judges and inject compact rules into both

### issue-creation
- MUST use a template (bug report or feature request) — blank issues are disabled
- Every issue gets status:needs-review automatically on creation
- A maintainer MUST add status:approved before any PR can be opened
- Questions go to Discussions, not issues
- Required fields: pre-flight checks, description, steps to reproduce, expected vs actual behavior

### branch-pr
- Every PR MUST link an approved issue (status:approved) — no exceptions
- Branch naming: type/description — lowercase, only a-z0-9._- (e.g. feat/user-login)
- Valid types: feat, fix, chore, docs, style, refactor, perf, test, build, ci, revert
- PR body MUST contain Closes #N (or Fixes/Resolves)
- Every PR MUST have exactly one type:* label
- Run shellcheck on modified scripts before opening PR
- Automated checks must pass before merge

### skill-creator
- Project developer skills live at `skills/{skill-name}/SKILL.md` and are loaded by coding agents.
- Runtime/product agent skills live at `backend/clients/{client-id}/agents/{agent-slug}/skills/` and must NOT be named `SKILL.md`.
- Create skills only for repeated project workflows, conventions, or complex decision trees.
- Frontmatter must include `name`, one-line quoted `description` with Trigger words, `license`, `metadata.author`, and `metadata.version`.
- Put templates/schemas/examples in `assets/`; put long local references in `references/`.
- Register project skills in `AGENTS.md` and update this registry after changes.

### qora-client-agent-setup
- Treat `client_id` as the tenant boundary; never reuse another client's Custom LLM URL.
- Runtime agent files belong under `backend/clients/{client-id}/agents/{agent-slug}/`.
- ElevenLabs Custom LLM server URL is `https://{ngrok}/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions`.
- ElevenLabs initiation webhook is `https://{ngrok}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}`.
- Store the ElevenLabs `agent_id` on the matching Qora Agent row.
- If `/calls/{conversation_id}/end` returns 404 after custom LLM error, debug Custom LLM firing first; the session was never created.

### go-testing
- Use standard go test with -race flag for concurrency tests
- Table-driven tests preferred — use []struct{name, input, want} pattern
- Bubbletea TUI: use teatest.NewTestModel(), send msgs via tm.Send(), assert with tm.FinalOutput()
- Mock interfaces, not concrete types
- Test file naming: foo_test.go in same package for white-box, foo_test package for black-box

---

## Qora Project Standards

### Python + FastAPI Conventions
- Use `pyproject.toml` for project configuration
- Use `pytest` for backend testing.
- Async-first: all I/O operations MUST be async
- Type hints required on all public functions
- Pydantic v2 for request/response models

### Architecture Patterns
- Channel abstraction: agents communicate through ChannelAdapter interface
- Event-driven: conversation completion emits events for async processing
- SQLite for MVP, PostgreSQL-ready schema design
- Each agent has a configurable system prompt per client
- ElevenLabs Conversational AI Custom LLM URL for tenant routing uses `/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions` in the Custom LLM UI.
- Qora demo client id is `qora-demo`; never route Qora demo traffic through `quintana-seguros`.

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| AGENTS.md | /Users/mati/Desktop/Qora/AGENTS.md | Index for Qora project developer skills vs client-scoped runtime agent skills |
| skills architecture | /Users/mati/Desktop/Qora/docs/skills-architecture.md | Explains root `skills/`, `backend/clients/{client}/agents/{agent}/skills/`, and `Plugin/` separation |
