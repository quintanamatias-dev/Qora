# [Skill Name]
# File naming: {capability}.agent-skill.md — e.g., product-pricing.agent-skill.md
# This file is KNOWLEDGE ONLY. No personality, no style instructions, no behavioral rules.
# The agent reads this file when it needs facts about this topic. Keep it scannable.
# Delete these comments before deploy.

## What this covers

[One sentence: what knowledge domain this skill provides.]
Example: "Pricing structure, payment options, and discount tiers for [PRODUCT]."

## [Main Content Section — rename to match the domain]

[The actual facts, organized for quick scanning. Use sub-sections for distinct sub-topics.
Write in neutral, factual prose. Avoid markdown formatting that won't survive spoken output.
Sub-sections are fine here since the agent reads this, not speaks it directly.]

### [Sub-topic 1]

[Facts about this sub-topic.]

### [Sub-topic 2]

[Facts about this sub-topic.]

## [Additional Content Section — add as many as needed]

[More domain facts. Keep each section tightly scoped to one sub-topic.]

## Recommended Responses

[Suggested spoken responses for the most common questions about this topic.
These are starting points — the agent adapts them to the conversation flow.
The agent does NOT read these verbatim. They show the expected tone and spoken form.]

If the user asks about [COMMON_QUESTION_1]:
"[Suggested spoken response — 1-2 sentences, spoken form, no markdown.]"

If the user asks about [COMMON_QUESTION_2]:
"[Suggested spoken response.]"

If the user asks about [COMMON_QUESTION_3]:
"[Suggested spoken response.]"

## Limits

[What this skill does NOT cover. This is critical — it helps the agent know when to stop
and say "I don't have that information" instead of hallucinating.]

- This skill does not cover [TOPIC_OUTSIDE_SCOPE_1].
- This skill does not cover [TOPIC_OUTSIDE_SCOPE_2].
- For [RELATED_TOPIC], see [OTHER_SKILL_NAME] if available, or tell the user you don't have that information.
- Do not infer or extrapolate beyond the facts listed here.
