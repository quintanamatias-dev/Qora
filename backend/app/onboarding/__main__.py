"""`uv run python -m app.onboarding <spec.yaml|json> [--dry-run]`

Parses a spec file into OnboardingSpec and calls the same
`app.onboarding.service.run_onboarding` the admin endpoint calls, against
`Settings().database_url`. Prints the checklist as JSON to stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import yaml

from app.core.config import Settings
from app.core.database import create_engine_and_session
from app.onboarding.service import run_onboarding
from app.onboarding.spec import OnboardingSpec


def _load_spec_dict(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


async def _main(spec_path: Path, dry_run: bool) -> None:
    spec = OnboardingSpec(**_load_spec_dict(spec_path))

    settings = Settings()
    _, session_factory = create_engine_and_session(settings.database_url)

    async with session_factory() as session:
        result = await run_onboarding(spec, session, dry_run=dry_run, settings=settings)
        if not dry_run:
            await session.commit()

    print(json.dumps(result.model_dump(), indent=2))


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    positional = [a for a in args if a != "--dry-run"]
    if not positional:
        print("Usage: python -m app.onboarding <spec.yaml|json> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_main(Path(positional[0]), dry_run))


if __name__ == "__main__":
    main()
