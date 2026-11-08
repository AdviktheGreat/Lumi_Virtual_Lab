# PaperAgents

[Back to the README](../README.md). A PaperAgent is one paper, with the code that came with it, made into something the lab can use.

This is built one step at a time. For now an agent is the record of what it is to be made from: which paper it is of, and where its code is. Reading the paper, setting up its code, and building tools from it are not done yet, and each step of an agent says so (`pending`) until it is. Reading many papers at once, for the tasks, databases, and software they share, is a different thing, the [surveys](papers-and-functions.md#growing-the-toolset-from-papers), and is still there as the other part of the same page.

## Making an agent

The web interface's PaperAgents page (`/papers`) lists the agents, the latest first, and makes one. An agent is of one paper, given in one of three ways:

- **A DOI**, such as `10.1038/s41586-020-2649-2`. `doi:10.…` and a `https://doi.org/10.…` link are accepted, and the DOI is kept in lower case.
- **A link** to the paper on the web, which begins with `http://` or `https://`. A link to `doi.org` is kept as the DOI it holds. The host is kept in lower case, and a fragment, a closing slash, and the port that the scheme has by itself (80 for http, 443 for https) are dropped.
- **A file** that is uploaded to the agent after it is made: a PDF, or a text, Markdown, or LaTeX file, up to the upload limit (at most 100,000,000 bytes, which the page says as 95 MB). It is kept with the agent, and may be uploaded again to replace it, or taken away.

An agent may also say where its code is: the address of a project at github.com, gitlab.com, bitbucket.org, or codeberg.org, such as `https://github.com/owner/name`. A longer address, to a branch or a file, is cut down to the project. Nothing is fetched from it yet.

An agent is called by its title. For a DOI or a link the title may be left out, and the DOI, or where the link leads, is used. For a file it is needed, since there is nothing else to call it by.

One paper is one agent. A DOI or a link that an agent has already, or a file with the contents of one an agent has (which is told by its SHA-256), is refused with the agent that has it (`exists`, 409), and the page links to it. At most 200 agents can be kept. Two links are one paper only if they are the same once written as above, so `http` and `https` addresses, or the same query in another order, are two links.

An agent's page (`/papers?agent=...`) shows its paper (a DOI or a link opens in a new tab), its code, and how far each step has got. It says again what the agent is called and where its code is, uploads or removes the paper of an agent whose paper is a file, and deletes the agent, after asking, with the paper that was uploaded to it.

## What is kept

Each agent is a directory of its own in `paperagents/` in the workspace, named from its title:

```
paperagents/<id>/
    agent.json    schema, title, created_at, paper, repo, steps
    paper/        the paper that was uploaded, if the paper is a file
```

`agent.json` is written all at once, so that it is never half written, and says which version of the record it is (`schema`), so that a later version can read what an earlier one wrote. A directory without a valid `agent.json` is not an agent and is not listed, nor is one whose file was edited to hold a DOI, a link, or an address of code that would not be taken when it is given, nor is a directory that is a link to another. Later steps will keep what they make in directories beside these, and nothing in the workspace is sent anywhere.

## The API

All of it needs the server's token, like the rest of the API.

| Request | What it does |
| --- | --- |
| `GET /api/paperagents` | The agents, the latest first, and what a page needs to make one: `max_agents`, `max_paper_bytes`, `suffixes`, and `repo_hosts`. |
| `POST /api/paperagents` | Makes an agent from `{"title": ..., "paper": {...}, "repo": ...}`, where `paper` is `{"kind": "doi", "doi": ...}`, `{"kind": "url", "url": ...}`, or `{"kind": "file"}`, and `title` and `repo` may be left out as above. Answers 201 with the agent. |
| `GET /api/paperagents/{id}` | One agent: `id`, `title`, `created_at`, `paper`, `repo` (or `null`), and `steps`, which says `pending`, `running`, `done`, `failed`, or `skipped` for each of `reading`, `repository`, `environment`, `data`, and `tools`. |
| `PATCH /api/paperagents/{id}` | Says again `title` and `repo`, at least one of them. What is left out is left as it was, and an empty `repo` takes the code away. |
| `DELETE /api/paperagents/{id}` | Deletes the agent and its paper, and answers with the list. |
| `POST /api/paperagents/{id}/paper?name=...` | Gives an agent whose paper is a file its paper, as the body, in place of one it had. Answers 201 with the agent, as the upload of a paper to a survey does. A file that is not a paper, or is over the limit, is refused (422, 413). |
| `DELETE /api/paperagents/{id}/paper` | Takes the uploaded paper away. |

A request that is not fit is refused with 422 (`invalid`) and says what is wrong; an agent that is not there is 404. A paper that is uploaded to an agent whose paper is a DOI or a link is refused with 409 (`invalid`), and a 201st agent with 409 (`too_many`).

## What it does not do yet

- It does not read the paper, find its claims, or fetch, set up, or run its code.
- It does not check a link or a DOI, or fetch the paper from it: the agent holds only what it was told.
- It does not make tools for the lead, and an agent is not yet something a conversation can use.
- It does not refuse a link to this machine or to a private address, since nothing is fetched from a link yet. The step that fetches will.

The paper and its code are data, not instructions, so what an agent reads from them will never be taken as something to do.
