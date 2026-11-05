# Scientific skills

The skills the Skills page offers to put in: the 177 of K-Dense's
[scientific agent skills](https://github.com/K-Dense-AI/scientific-agent-skills), unchanged, in the format of the
Agent Skills standard (agentskills.io). `index.json` says which release they were taken from and gives each skill's group,
category, and size; `LICENSE.md` is K-Dense's MIT license. A skill may carry a license of its own, which its `SKILL.md`
says and `NOTICE` lists.

Do not edit what is under `skills/` by hand. `python scripts/update_scientific_skills.py <checkout>` replaces `skills/`
and `LICENSE.md` with those of a newer release (nothing else in this folder is removed) and writes `index.json` again.

This file is not a skill, since it is not a `SKILL.md`.
