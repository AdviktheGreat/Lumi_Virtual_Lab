# Virtual Lab web interface

The interface for talking to the head of a lab, built with Next.js, React, Tailwind, and shadcn/ui, and exported as
static pages. The server (`virtual-lab-server`, in `src/virtual_lab/server`) serves those pages itself, along with the
API they talk to, so there is nothing to run but the server.

## Layout

| Path | What is there |
| --- | --- |
| `src/app` | The pages: `/` starts a conversation, `/chat?id=…` is one |
| `src/components` | What the pages are made of; `ui/` is shadcn's |
| `src/lib` | The API client, the stream of a conversation's events, and the transcript they add up to: what the lead said, each call it made, the code that ran, what a team did when the lead brought it in, and the notes left for it; and the files that go with a message, the files of a conversation, and the way a turn is steered; and how the list of conversations is searched and put in days; and what the settings say, the keys, and the scientists; and what there is to set up for code in Docker, and the jobs that build and fetch it |
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

## The list of conversations

The sidebar lists every conversation under the day it was last at work (Today, Yesterday, Previous 7 days, Earlier, by
the reader's own calendar), the latest first, and looks again every few seconds and whenever the page is shown. With
eight or more there is a search box, which finds the titles that have all the words typed, in any order and whatever
their case; Escape empties it.

The options of a conversation are in the menu at the end of its row, which shows when the row is pointed at or reached by
keyboard, and always on a screen that is touched. Rename changes the title where it is read: Enter or leaving the box
keeps it, Escape gives it up, and one with nothing in it, or the one it had, changes nothing. The server keeps a title
with its words one space apart, cut to 80 characters (`src/lib/history.ts` does the same before asking), and tells the
conversation that is open, whose heading follows. Delete asks first, and removes the conversation with its messages and
its files, stopping it if it is at work; if it is the one that is open, the page goes to the home page. One that is gone
already is as good as deleted.

## Settings

The gear at the foot of the sidebar opens the settings, in four parts. What is set is what conversations started from then
on begin with; one already begun keeps what it began with.

- **Model** has the model, which is chosen from those the server can reach, grouped by whose they are, or named when it is
  not one of them ("Another model…"). A model whose key is not set says so, with a button that goes to the keys. It also
  has the most one conversation may spend, in dollars (empty for no limit), and whether replies show as they are written.
- **Keys** has a box for each key the server can take, which says whether it is set and never shows it. A key is kept by
  the server until it stops, and is sent from the box once, as a password; Remove takes one away, including one the server
  was started with.
- **Code** has where the lab runs code. In a Docker container it has the image, whether the code can reach the network,
  the data lake (for Biomni's images), and which keys the code can read. On this computer it warns that nothing holds the
  code back, and has the Python to run it with.
- **Scientists** has the library the lead draws on. The lab's own cannot be deleted; editing one keeps your own version
  under its title, and deleting that gives the lab's back. A new scientist cannot take the title of one that exists.

Save changes sends only what was changed (`PATCH /api/settings`), so a setting changed meanwhile by another page is not
undone, and shows what the server refuses beside the button. Closing with something changed and not saved asks first,
and a scientist that is half written counts as not saved. A conversation that cannot start because its model's key is not set says which key,
and offers to go and set it (`src/lib/errors.ts` tells those from other errors by the server's `missing_keys` code).

## Setting up for code in Docker

The container icon in the sidebar, beside the gear, opens the setup, in three parts. Building and fetching go on in the
server, so they go on when the setup is closed, the icon shows a dot while one does, and the setup shows them again
when it is opened.

- **Overview** is the checklist the server draws up (`GET /api/setup`): Docker, the image, and the key for the model,
  and the data lake if it is wanted, each marked done, to do, in progress, or waiting. Each stage of the image shows
  whether it is built, with a button to build it where Docker can, its progress, and what it printed; a build that failed
  says why. Where the computer is not the one the image is made for, it says the image will run slowly. Check again asks
  Docker again.
- **Data lake** lists the files of Biomni's data lake and which are there, with a search and a way to show only those
  that are not. It offers to fetch all that are missing, or only those that may be used commercially, and asks first,
  saying about how much that is (the server cannot say of a file it has not got, so 11 GB is a figure kept in
  `src/lib/setup.ts`) and warning when the disk has less room than that. A file can be fetched on its own.
- **Jobs** lists what has been built or fetched since the server started, the latest first. A job at work has a Stop
  button, which says Stopping until the server has stopped it, and a job can show what it printed.

A job is followed by asking for the jobs every second while one is at work, and when the page is shown again (the page
may have been hidden for hours). What a job printed is asked for from the line after the last that is held
(`?log_from=`), so only what is new is sent, and the page keeps the last 2000 lines, as the server does. When a job
finishes, what it changed (the steps, the images, the files) is asked for again. A conversation that cannot start because
Docker or the image is not ready (the server's `setup_needed` code) offers a Set up button that opens the setup.

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

The Files button in the header opens the conversation's files: what was attached and what the code made, in folders,
with a search once there are more than a few. A file opens beside the conversation (over it on a narrow screen) as an
image, a table, or text, whichever it is. Only the first 200 KB of a file is read to show it, a table
shows its first 200 rows and 40 columns, and a file that is not text is offered for download instead. The list is read
again when a turn makes or changes a file, once the stream has been quiet for a moment.

## Saving a conversation

The Save button in the header saves the conversation as a document: a web page (HTML) that opens in any browser with its
figures in it, or a PDF. The server lays it out (`GET /api/chats/{id}/export?format=html|pdf`, from
`virtual_lab.export_chat`, as the Python package saves a conversation), and the page fetches it, and then hands it to the
browser to save under the name the server gave it, from the title (`src/lib/export.ts`). It is fetched, and not a link
that downloads, so that what the server says when it cannot make the document is shown above the composer, and is not
saved as a file. A PDF needs WeasyPrint and the Pango library on the machine that runs the server (see the root README);
without them the server answers `pdf_unavailable`, and the page says to save the web page and print that. There is
nothing to save until the conversation has a turn, so the button waits for one. A conversation that is still going is
saved as far as it has got. Only one document is made at a time, and one that is still being made when the conversation
is left is not saved.

## A team in the conversation

When the lead brings the team in (`convene_team`) or asks one scientist (`consult`), the call that did it opens to what
the session is: who is in it, what it is for (under "Agenda"), and who said what in each round, with the code a scientist
ran and the files it made where they did it. While it goes on, what a scientist is writing shows as they write it. The
session is open while it runs, and as the researcher left it afterwards; one that was over before the page was opened stays
closed, which is told by the page having been sent every event the conversation had when it was opened
(`last_event_id`), since until then a call may only seem to be going on. One the researcher stopped is shown as cut short,
not as an error, which is how `src/lib/lab.ts` tells a stop (the `failed` event of the kind `ChatStopped`) from a failure.

## End-to-end tests

The tests run the real server with the built pages and a script where the model would be
(`e2e/scripted_server.py`), so they need no key and give the same answers every time. They need the Python that has
`virtual-lab[server]` installed: it is `python3` unless `VIRTUAL_LAB_PYTHON` says otherwise. `E2E_PORT` changes the
port, which is 8799. The scripted server takes 20 KiB as the most for a file, so that the tests of the limit need only
small files; `--max-upload-bytes` changes it.

The tests of the settings, the keys, and the scientists (`e2e/own-server`) change what every conversation is made with, so
they run in a project of their own, against a second scripted server on the next port (8800). Each file of them puts
back what it changed before each test, and neither touches what the other does. They run in order within a file, and a
test that needs a key puts it there itself, since the server keeps none.

The tests of the setup (`e2e/setup`) have a third scripted server, on the port after that (8801), which is given stand-ins
for Docker and for the place the data lake is fetched from, so that nothing is built or downloaded: a Docker that says
what a test tells it, and files of 10 KB for every file of the data lake. A test arranges them through a small server on
the port after (8802, `--setup-control-port`; `e2e/setup/state.ts` is the client, and `FakeSetup.control` in
`e2e/scripted_server.py` lists what it can be told), for instance to hold a download so that its progress and stopping can
be seen. These run in a project of their own (`--project=setup`), one test at a time, and put the stand-ins back as they
were before each test.

The scripted model answers a question with a short reply that repeats it. What else a message makes it do depends on
a word in it:

| In the message | The scripted lead |
| --- | --- |
| `slow:` | Writes a long reply, slowly, which a test can follow or stop |
| `fail:` | Fails |
| `markdown:` | Answers with a page of Markdown, including what a page must not trust: a script, a tracking image, an address that runs code |
| `wide:` | Answers with a table and lines of code that run past the width of the page, for what scrolls in a reply |
| `code:hello`, `error`, `two`, `plot`, `long`, `big`, `slow` | Runs code in the conversation's session first, as the word says, and answers once it has run |
| `code:files` | Runs code that writes one of each kind of file the panel shows differently: a long table, a wide one, a long log, a file that is not text, and an empty one |
| `tool:unknown`, `tool:resources` | Calls a tool it does not have, or looks for resources |
| `pdf:unavailable` | Has saving the conversation as a PDF fail, as it does where WeasyPrint is not installed (the PDF is otherwise made by a stand-in that needs no WeasyPrint) |
| `lab:team` | Brings in the team for a round of discussion, in which the scientists answer as the script says |
| `lab:consult` | Asks one scientist, reviewed by the critic |
| `lab:code` | Asks one scientist, who runs code in the session before they reply |
| `lab:slow` | Asks one scientist, who writes a long reply, slowly |

Code runs on this machine, so a test that wants it makes its conversation through the server with `code: {where:
"local"}`, as `askWhereCodeRuns` in `e2e/fixtures.ts` does. `e2e/replay.spec.ts` replaces a conversation's event stream
with events written in the test, for what the scripted lead does not do, such as a turn that is cut short.

## How the pages look, and who can use them

`e2e/appearance.spec.ts` goes through the pages in both themes, at the width of a desktop and of a phone: the home page,
replies, a team's session, an error, the menu for saving, the files and what is shown of them, the conversations, the
settings, and the setup. At each it runs [axe](https://github.com/dequelabs/axe-core) (`e2e/axe.ts`), which checks the page
against the rules for being usable without a mouse or good eyes (contrast, names, landmarks, and what can be reached from
the keyboard), and looks for the page going past its edge. It also holds what is being got, so as to look at what is shown
meanwhile. A rule is left out only where the page is not what is wrong: the order of headings in what a model writes, and
what a menu that is open puts behind it.

What scrolls, such as output, code, a table, or a file, is a `ScrollBox` (`src/components/scroll-box.tsx`). The arrow
keys scroll only what has the focus, so it can be reached from the keyboard while what is in it is more than it shows, and
is not one more stop in the order of the page when it is not. It looks again as the window changes and as what is in it
changes, which does not always make it draw itself again. Anything new that scrolls is made with it, which axe says when
it is not.

## Notes

- The pages hold nothing the server does not give them. The token in the link the server prints is kept by the browser
  in a cookie the pages cannot read, and the API wants it from every request.
- Nothing may need a Node server at run time, so there are no server actions, rewrites, redirects, or dynamic routes.
