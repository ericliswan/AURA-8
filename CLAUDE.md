# Project Guidelines

## Git and GitHub

- Never add Claude attribution to anything git or GitHub related. No `Co-Authored-By: Claude` trailers, no "Generated with Claude Code" lines, no mention of Claude in commit messages, PR titles or descriptions, issues, comments, tags, or release notes.
- Commit often, in small logical units.
- Develop each feature on its own branch off `main` (e.g. `feature/<name>`).
- Break a feature into sub-features on sub-branches off the feature branch (e.g. `feature/<name>/<sub-feature>`), and merge them back into the feature branch.
- Before merging anything into `main`, run a code review. Fix the findings, then review again. Repeat until the review comes back clean. Only merge after a clean review.

## Code Style

- Write clean, self-documenting code: clear names and small focused functions over comments.
- Keep comments minimal. Only add a comment when a line has a non-obvious edge case or workaround.
- Do not write comments that explain what standard code is doing.
- Do not leave comments describing changes made during a session or prompt (e.g. "updated to…", "fixed…", "new:").
