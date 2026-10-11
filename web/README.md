# Virtual Lab web interface

The interface for talking to the head of a lab, built with Next.js, React, Tailwind, and shadcn/ui, and exported as
static pages. The server (`virtual-lab-server`, in `src/virtual_lab/server`) serves those pages itself, along with the
API they talk to, so there is nothing to run but the server.

## Layout

| Path | What is there |
| --- | --- |
| `src/app` | The pages: `/` starts a conversation, `/chat?id=…` is one |
| `src/components` | What the pages are made of; `ui/` is shadcn's |
| `src/lib` | The API client, the stream of a conversation's events, and the transcript they add up to |
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

## End-to-end tests

The tests run the real server with the built pages and a script where the model would be
(`e2e/scripted_server.py`), so they need no key and give the same answers every time. They need the Python that has
`virtual-lab[server]` installed: it is `python3` unless `VIRTUAL_LAB_PYTHON` says otherwise. `E2E_PORT` changes the
port, which is 8799.

The scripted model answers a question with a short reply that repeats it. A message with `slow:` in it is answered with
a long reply, written slowly, which a test can follow or stop. A message with `fail:` in it makes the model fail.

## Notes

- The pages hold nothing the server does not give them. The token in the link the server prints is kept by the browser
  in a cookie the pages cannot read, and the API wants it from every request.
- Nothing may need a Node server at run time, so there are no server actions, rewrites, redirects, or dynamic routes.
