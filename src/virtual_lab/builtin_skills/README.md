# virtual_lab's built-in skills

Each folder here with a `SKILL.md` is a skill that comes with the lab, in the format of the Agent Skills standard (agentskills.io). It is general practice for kinds of analysis where a number is easy to get wrong: reading the sign of dependency scores, enrichment analysis, sample ids and PCA, multiple-testing corrections in small panels, variant call statistics, what a tool's function computes, and a checklist for any question that asks for a number from data.

The server reads them after the workspace's own skills and those in `~/.agents/skills`, so a skill of the same name that you put in takes the place of one of these. They cannot be deleted from the Skills page, but a person can turn any of them off there, or leave it out of one conversation. A meeting, which has no skills, is offered them as know-how documents (see `builtin_know_how` in `virtual_lab/resources.py`).

A skill's `description` is what the lead reads of it in every request, cut to 250 characters in the list it is given, so it says when to use the skill, in the words a task would use, within that. Write practice that holds for any data of the kind, and leave out answers to particular questions and particular datasets. A skill's name is its folder's, in lowercase letters, digits, and hyphens.

This file is not a skill, since it is not a `SKILL.md`.
