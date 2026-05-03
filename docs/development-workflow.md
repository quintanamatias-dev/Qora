# Development Workflow

This project keeps feature work traceable through GitHub issues, branches, PRs, and merges.

## Feature tracking checklist

For each feature or analysis metric:

1. Start from a GitHub issue that describes the expected behavior.
2. Create a dedicated branch from `main`.
3. Implement the change with tests before or alongside the feature work.
4. Open a pull request that references the issue with `Closes #<issue>`.
5. Merge the PR into `main` before considering the issue complete.
6. Confirm the issue is closed and the PR is merged.

## Analysis metric rule

Universal analysis metrics must stay generic. Do not introduce client-specific or industry-specific taxonomy unless the issue explicitly asks for it.

When an issue defines categories or output values, treat them as authoritative. Do not rename, split, or reinterpret them during implementation without an explicit product decision.

## Cleanup rule

If a commit reaches `main` through another PR, close any stale duplicate PRs with a note explaining that the code is already merged. Then close the corresponding issue only after verifying the commit is present in `main`.
