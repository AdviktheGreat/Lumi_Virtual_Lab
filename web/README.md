# Virtual Lab web interface

The interface for talking to the head of a lab, built with Next.js, React, Tailwind, and shadcn/ui, and exported as
static pages. The server (`virtual-lab-server`, in `src/virtual_lab/server`) serves those pages itself, along with the
API they talk to, so there is nothing to run but the server.

## Layout

| Path | What is there |
| --- | --- |
| `src/app` | The pages: `/` starts a conversation, `/chat?id=…` is one |
| `src/components` | What the pages are made of; `ui/` is shadcn's |
| `src/lib` | The API client, the stream of a conversation's events, and the transcript they add up to: what the lead said, each call it made, the code that ran, and the notes left for it; and the files that go with a message and the way a turn is steered |
| `e2e` | Playwright tests, and the scripted server they run against |

A conversation is named in the query of an address, not in its path, because the pages are exported as they are and
there is no page to make for each conversation there will be.

## Commands

Everything is run from this directory, with Node 22 or later.

```bash
npm install
npx playwright install chromium   # once, for the end-to-end tests

npm run lint
npm run typecheck
npm test                  # unit tests of src/lib
npm run test:e2e          # builds the pages, starts the scripted server, and drives a browser through them

npm run build             # the pages, in out/
npm run package           # the pages, in src/virtual_lab/server/static, which the server serves once installed
```

To use the interface while changing it, build it and point the server at the build:

```bash
npm run build
virtual-lab-server --static-dir out
```

The server turns away any page that is not its own, so `next dev` on another port cannot talk to it: rebuild instead,
which takes seconds.

## Steering a turn

While the lead is at work, the box in the composer takes a note instead of a message, and the lead reads it before its
next step. Pause holds the turn once the step that is running is done, Resume lets it go on, and Stop ends it. The
buttons follow the state the server reports (`idle`, `running`, `pausing`, `paused`, `stopping`), as
`src/lib/steering.ts` lays out. A note stays marked as waiting until the conversation says it was read, or that it came
too late.

## Files

A file is attached with the paperclip, by dropping it on the composer, or by pasting it. With a conversation to send it
to, it goes at once, with its progress shown, and can be retried or removed; on the home page, where there is no
conversation yet, files wait until the first message makes one. The message is sent with the names the server gave the
files. A message cannot be sent while a file is on its way or has failed, and up to 100 files go with one message.

The most that one file may be is the server's `max_upload_bytes` (4 GiB unless `serve` is told otherwise), which the
pages learn from `/settings`, so they turn a larger file away before sending it.

## End-to-end tests

The tests run the real server with the built pages and a script where the model would be
(`e2e/scripted_server.py`), so they need no key and give the same answers every time. They need the Python that has
`virtual-lab[server]` installed: it is `python3` unless `VIRTUAL_LAB_PYTHON` says otherwise. `E2E_PORT` changes the
port, which is 8799. The scripted server takes 20 KiB as the most for a file, so that the tests of the limit need only
small files; `--max-upload-bytes` changes it.

The scripted model answers a question with a short reply that repeats it. What else a message makes it do depends on
a word in it:

| In the message | The scripted lead |
| --- | --- |
| `slow:` | Writes a long reply, slowly, which a test can follow or stop |
| `fail:` | Fails |
| `markdown:` | Answers with a page of Markdown, including what a page must not trust: a script, a tracking image, an address that runs code |
| `code:hello`, `error`, `two`, `plot`, `long`, `big`, `slow` | Runs code in the conversation's session first, as the word says, and answers once it has run |
| `tool:unknown`, `tool:resources` | Calls a tool it does not have, or looks for resources |

Code runs on this machine, so a test that wants it makes its conversation through the server with `code: {where:
"local"}`, as `askWhereCodeRuns` in `e2e/fixtures.ts` does. `e2e/replay.spec.ts` replaces a conversation's event stream
with events written in the test, for what the scripted lead does not do, such as a turn that is cut short.

## Notes

- The pages hold nothing the server does not give them. The token in the link the server prints is kept by the browser
  in a cookie the pages cannot read, and the API wants it from every request.
- Nothing may need a Node server at run time, so there are no server actions, rewrites, redirects, or dynamic routes.
