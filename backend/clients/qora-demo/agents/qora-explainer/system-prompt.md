# qora-explainer System Prompt

The active Qora demo prompt is currently seeded in the database by `seed_qora_demo()`.

This file reserves the intended product file structure:

```text
backend/clients/qora-demo/agents/qora-explainer/
├── system-prompt.md
└── skills/
```

When prompt storage is moved back to filesystem-backed agent configuration, this file should become the source of truth for the Qora explainer agent prompt.
