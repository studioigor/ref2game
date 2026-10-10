# ref2game: OpenAI plugin packaging proposal

This additive package preserves studioigor authorship and the original edition.
It contains a root portable `plugin.json`, `skills/ref2game/SKILL.md` and the
edition's bundled resources. The first section of the packaged skill binds
runtime-specific examples to capabilities actually available on the surface.

Source edition: `codex/`. The original source files are unchanged.
Keep packaged resources in sync with that edition when updating this proposal.

## Build an upload archive

From this directory, run:

```sh
python3 build.py --output /tmp/ref2game-openai-plugin.zip
```

The archive has one plugin root. Build output belongs outside the repository.
The builder validates identity, skill frontmatter, resources and package paths.

## Review status

This is a draft packaging proposal, not a published or approved plugin.
Static packaging checks do not prove skill activation or successful production.
Before submission, test direct, indirect, incomplete, negative and unavailable-
capability prompts in fresh ChatGPT/Codex sessions; run representative project,
capture and QA workflows. Add author-approved listing artwork and review metadata.
studioigor's Claude-specific autopilot launcher is not a portable scheduler;
this package uses bounded current-session steps until that adapter exists.

Packaging reference: https://developers.openai.com/plugins/build/plugins
Skill reference: https://developers.openai.com/plugins/build/skills
