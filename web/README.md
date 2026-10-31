# Virtual Lab web interface

The interface for talking to the head of a lab, built with Next.js, React, Tailwind, and shadcn/ui, and exported as
static pages. The server (`virtual-lab-server`, in `src/virtual_lab/server`) serves those pages itself, along with the
API they talk to, so there is nothing to run but the server. To use the interface rather than change it, run
`python3 start.py` in the root of the repository, which builds the pages if they are not built and starts the server.

## Layout

| Path | What is there |
| --- | --- |
| `src/app` | The pages: `/` starts a conversation, `/chat?id=…` is one |
| `src/components` | What the pages are made of; `ui/` is shadcn's |
| `src/lib` | The API client, the stream of a conversation's events, and the transcript they add up to: what the lead said, each call it made, the code that ran, what a team did when the lead brought it in, and the notes left for it; and the files that go with a message, the files of a conversation, and the way a turn is steered; and how the list of conversations is searched and put in days; and what the settings say, the keys, the scientists, and the tools; and what there is to set up for code in Docker, and the jobs that build and fetch it; and the MCP servers, what a check of one found and whether it is signed in to, and what they and their tools ask of the researcher |
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

## Data

The sidebar has a link to each page besides the conversations, under New chat; the one that is open is marked as the
current page. The Data page (`/data`) is where the lab is given what it works on, in three parts.

- **Your data** is the files and folders the person gave the lab. A file is uploaded, and the lab keeps its own copy
  (up to the server's upload limit, and the form says what it is), or a file or folder is pointed to by its full path on
  the machine the server runs on, and is left where it is. Each has to say what it is, in words, since the lead reads that
  to know when to use it, and code finds a piece of data by its file name, so none can have the name of another: an upload
  with a name that is taken is refused where it is chosen. A piece of data shows where it came from, how big it is, and
  when it was changed. The eye shows the start of it (the first lines of a text file, or what is in a folder), the pencil
  changes what it is said to be, and the bin gives it up after asking, saying whether that deletes the lab's copy (an
  upload) or leaves the file where it is (a path). What was pointed to and has gone since is said to have gone, and the
  page looks again whenever it is shown, so that it is found out when the person comes back to its tab.
- **Your software** is a name and what it is for. The lab does not install it: it has to be where the code runs, which
  a conversation checks when its code first runs, and tells the lead if it is not.
- **Biomni's data lake** is the files of the data lake and the fetching of them, as the setup has it, with the progress
  of a fetch and the means to stop it. The jobs are the setup's, so a fetch begun in either is followed in both, and the
  page does not ask Docker anything (`useDataLake` in `src/lib/use-setup-data.ts` is the part of the setup's data that
  it needs).

What is given is in every conversation made from then on, and not in one that is already going (the page says so). The
server keeps it (`GET /api/own` and what changes it, in the main README), and every change gives back all of it as it
now is, which the page shows from then on. `src/lib/own.ts` checks what is written before it is sent, as the server
does, so that what is wrong is said where it is written.

## Papers

The Papers page (`/papers`) is where the lab reads papers, and writes functions from what they share. It lists the runs,
the latest first, each with where its papers come from and how far its reading has got, and makes one: from papers that are
uploaded to it afterwards, from a folder on the server's machine, or from bioRxiv (a period, a subject, and how many
preprints, which are checked where they are written, as the server checks them). A run is named in the address's query
(`/papers?id=...`), as a conversation is, and its page has four parts.

- **Papers** is where they are from. A run whose papers are uploaded shows them, with the means to remove one and to add
  more (several at once, each with how much of it has been sent, and one that is not a paper, is too big, or has a name that
  is taken is said so before it is sent). Reading asks for the most it may spend, which is always said, and may ask for the
  most one paper may spend; a run that was stopped carries on from where it was, and papers that failed are read again only
  if that is asked for. The progress of the job, and the way to stop it, are at the top of the run, and are the setup's jobs,
  so what is begun here is followed in the setup as well. Nothing else is done to a run while it is being read or has
  functions written for it. A stop is kept for the next paper: the one that is being read is not kept.
- **What was read** is each paper, whether it was read, was not to be had, or failed (and why), how many tasks, databases,
  and software were found in it, and what it cost.
- **What the papers share** is the tasks, databases, and software found in the most papers, each with a table to download.
- **Functions** are written for the tasks the papers share, for as much as is said it may spend, and as many as is asked for
  (the most common tasks first, and only those found in a number of papers). Each shows whether it was checked, what it uses,
  and its code, which is read from the server only when it is asked for, so that it can be read before it is relied on.
  Whether they are given to the conversations that are made from then on is a box that is ticked or not; one that is already
  going is not given them.

A model that has no key, or no price, and Docker where functions are checked in it, are refused with what to do about it, as
a conversation is. `src/lib/papers.ts` checks what is written before it is sent, as the server does.

## Benchmarks

The Benchmarks page (`/benchmarks`) is where the lab is scored on the questions Biomni is scored on. It has the files the
questions are in, which are about 4 MB and are fetched from the page once (a run cannot be made before they are there, and
the page says which are missing, or why those that are there cannot be read); the runs, the latest first, each with the
benchmark, who answers, and how far the answering has got; and the making of one: the benchmark (with how many questions
each has), which of its tasks, or which file of its questions, or whether to leave out those that refer to an image, who
answers (the lead alone, or the lead and the team, with the rounds of criticism or of discussion), and how many questions to
ask, the first ones, which is a way to try a run cheaply. A run keeps the model and where code runs as the settings have
them when it is made, which the form says. A run is named in the address's query (`/benchmarks?id=...`), as a conversation
is, and its page has these parts.

- **What is being done** is the answering that is going on, or how the last of it ended, with its progress and the way to
  stop it. It is the setup's job, so what is begun here is followed in the setup as well. Nothing else is done to a run while
  it is being answered. A stop ends the question that is being answered without keeping it, and what was answered is kept.
- **Answer the questions** asks for the most it may spend, which is always said, and may ask for the most one question may
  spend. A run that stopped carries on from where it was, and questions that failed are asked again only if that is asked
  for.
- **Scores** are the benchmark's own measures over what has been answered (accuracy, and for LAB-Bench how much was refused),
  and, where a benchmark has more than one task, how right the lead was in each.
- **Questions** is each question, with whether it was right, partly right, wrong, failed, or is not answered yet, and can be
  narrowed to a task and to how it was answered, a hundred at a time. Opening one reads it from the server, with what was
  asked, the answer that was read out of what was said, the right one, what it cost, and what was said in answering it, so
  that a score can be checked against it.

A model that has no key, or no price, and Docker where code runs in it, are refused with what to do about it, as a
conversation is. `src/lib/benchmarks.ts` checks what is written before it is sent, as the server does.

## Projects

The Projects page (`/projects`) is where the lead scientist is given a goal to carry out. It has the projects, the latest
first, each with how it stands (not started, working, finished, out of budget, out of rounds, stalled, stopped, failed, or
interrupted), how many rounds it took, how much of its plan is done, and what it has spent; and the making of one: its goal
(which may run over lines), a title (blank is the start of the goal), who works on it (the lead chooses the team, or the whole
lab is the team), how each step is told of what was found (the lead picks, the best matches, or every summary, and, for the
best matches, how many findings a step is given), the most scientists on the team, and the rounds of discussion in a meeting.
A project keeps the model, the lead, and where code runs as the settings have them when it is made, which the form says. A
project is named in the address's query (`/projects?id=...`), as a conversation is, and its page has these parts.

- **What is being done** is the work that is going on, or how the last of it ended, with the round it is in, what it has
  spent, and the way to stop it. It is the setup's job, so what is begun here is followed in the setup as well. Nothing else
  is done to a project while it is worked on. A stop is asked about before each round, and what was done is kept.
- **How it ended** says why a project that is not at work ended, what to do to carry it on, the answer the critic accepted (or
  the last one it did not, with what it objected to), why it failed if it did, and the report to save.
- **Work on it** asks for the most it may spend, which is always said and is over all the times the project is worked on, and
  may ask for the most rounds, and the most rounds in a row without more of the plan done. A project that stopped, or ran out,
  or failed, carries on from where it was, with the limit that ended it raised; one that has finished has nothing left to do.
- **Team and plan** is who is on the project, the lead and the critic among them, and the tasks the team made of the goal,
  with how far each has got.
- **Rounds** is what the lead decided each round (a meeting, code to write and run, a change to the team, or an answer put to
  the critic), why, and how it went.
- **Findings** is what the meetings and the code showed, each as a claim with what shows it, fifty at a time.
- **Steps** is each meeting and each run of code, with what it cost and how long it took. Opening one reads it from the
  server, with what it produced and what was said in it, or the code that was run and what it printed.

A model that has no key, or no price, and Docker where code runs in it, are refused with what to do about it, as a
conversation is. `src/lib/projects.ts` checks what is written before it is sent, as the server does.

## Settings

The gear at the foot of the sidebar opens the settings, in five parts. What is set is what conversations started from then
on begin with; one already begun keeps what it began with.

- **Model** has the model, which is chosen from those the server can reach, grouped by whose they are, or named when it is
  not one of them ("Another model…"). A model whose key is not set says so, with a button that goes to the keys. It also
  has the most one conversation may spend, in dollars (empty for no limit), and whether replies show as they are written.
- **Keys** has a box for each key the server can take, which says whether it is set and never shows it. A key is sent from
  the box once, as a password, and is kept in the server's keychain, so that it is there when the server is started again;
  beside each key that is set is where it is kept (in the keychain, until the server stops, or from the environment the
  server was started with). A box says where a key was kept as it is saved, and what went wrong if the keychain would not
  keep it, in which case it is kept until the server stops. "Keep keys in the keychain" can be unchecked, which this browser
  remembers (`src/lib/keys.ts`), and then a key is kept until the server stops and one kept before is forgotten. The
  keys of the MCP servers follow it. Where the server has no keychain, or could not read the one it has, the tab says so
  and why. Remove takes a key away, including one the server was started with, and from the keychain too.
- **Code** has where the lab runs code. In a Docker container it has the image, whether the code can reach the network,
  the data lake (for Biomni's images), and which keys the code can read. On this computer it warns that nothing holds the
  code back, and has the Python to run it with.
- **Scientists** has the library the lead draws on. The lab's own cannot be deleted; editing one keeps your own version
  under its title, and deleting that gives the lab's back. A new scientist cannot take the title of one that exists.
- **Tools** lists the library's tools by what they are for, each with a box. A box is kept as it is ticked
  (`PUT /api/tools`, which is sent the tools that are off, so that one the library gains later is on), and shows at once
  as it was ticked, whether or not the server has answered; changes are kept one after another, so two in quick succession
  do not undo each other, and the boxes (and the focus on them) are never disabled while one is kept. If the server refuses,
  the box goes back and the reason is shown. A conversation is given the tools that are on when it begins. The one tool that
  is only of use where code runs says so. Under them are the MCP servers (see [Servers, calls to allow, and
  questions](#servers-calls-to-allow-and-questions)).

Save changes sends only what was changed (`PATCH /api/settings`), so a setting changed meanwhile by another page is not
undone, and shows what the server refuses beside the button. Closing with something changed and not saved asks first,
and a scientist that is half written counts as not saved. Keys, scientists, and tools are kept as each is given. A conversation that cannot start because its model's key is not set says which key,
and offers to go and set it (`src/lib/errors.ts` tells those from other errors by the server's `missing_keys` code).

## Servers, calls to allow, and questions

An MCP server gives the lead more tools. The library's servers (Paperclip, Adaptyv, Proto) are listed at the foot of the
Tools settings, and a server of one's own is added there by what a config of any other tool says of it (`url`, or
`command` and `args`), with a warning that one that starts a program runs it on this computer. Each is kept as it is
chosen, as the tools are (`PATCH /api/mcp/servers/{name}`), and shows at once as it was chosen. A server that is signed in
to with a key takes it in a box, as the Keys settings do (the server only takes the keys of the library's own servers; a
key a server of one's own asks for is set where the server was started, which the row says), and one that can be signed in
to with an account says so, and which is chosen. A server that cannot work as it is says why on its row, and one of one's
own is removed after asking.

A server that can work as it is has **Check connection**, which connects to it as a conversation would and says how many
tools it gave and what some of them are, or why it could not (`POST /api/mcp/servers/{name}/check`, which a second check
of the same server is refused while the first is going, with `busy`). A check never opens a sign-in page, since nobody is
there to be sent to one, and never allows a call or answers a question: a server that is not signed in to says so, and that
the sign-in is asked for where a conversation uses the server. Its result stays until what it was of changes (a key, the
choice of key or account, or a sign-out), and one that comes back after that is dropped. A server signed in to with an
account says whether it is signed in (`signed_in` in `GET /api/mcp`; `null` where that does not apply or is not known), and
**Sign out** forgets the sign-in (`DELETE /api/mcp/servers/{name}/sign-in`), so the next conversation asks again.

A conversation is given the servers that are on when it begins, which `POST /api/chats` takes as `mcp` when it is to have
others, and connects to them when its first message is sent, since that is when the lead needs the tools. It keeps the
servers it was begun with while it is open, so one changed in the settings is for the conversations that begin after.
What happens around the lead's work is told in the conversation, so that it is on the page for whoever opens it, and is
answered from any window:

- **Connecting** is a line: Connecting to a server, then Connected to it with how many tools it gave. A server that cannot
  be connected to is a notice that says why, with a button to the settings; the turn ends without anything spent, and the
  next message tries again. A server that needs the researcher to sign in is a card with a link to its sign-in page, which
  opens in another tab; the lead goes on once they have. The link is only made of a web address.
- **A call to a tool that asks** (`approval` in the server's entry, and the library's servers that spend money or cannot be
  undone) is a card with the tool, what it is for, and what it is to be called with, and Allow and Decline
  (`POST /api/chats/{id}/approvals/{request}`). It waits for as long as the researcher does, and the badge in the header
  says "Waiting for you". Once answered it is a line, whoever answered it, and a call that was declined is not made, which
  the lead is told so that it does not make it again unchanged.
- **A question a server asks** while a tool runs is a form with a field for each thing it asks (text, numbers, yes or no,
  one choice, several, or a list), checked as it is sent, with what is wrong shown beside the field and the first taken
  to (`POST /api/chats/{id}/questions/{request}`). What was typed is never kept in the conversation. A question that is
  answered at a web page is a link to it and a button to say it was done.

Stopping a turn, or its ending in any other way, withdraws what still waits, and the cards become lines that say so
(`src/lib/transcript.ts`). `src/lib/asking.ts` reads a question's schema into a form and an answer back out of it.

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

## Commands

A slash at the start of the box opens a list of commands, which narrows as the name is written. The arrow keys choose,
Enter runs the one that is lit, Tab writes it out, and Escape puts the list away; the slash button beside the paperclip
opens it for touch. A command that cannot be run now is listed with why (`/stop` when nothing is running), and is not
sent to the lead in place of itself. A line that begins with a slash and is not one of the commands, such as the path of
a file, is a message. `src/lib/commands.ts` has the commands, where each is offered (a conversation, or the home page,
where `/budget` and `/model` set up the conversation to begin), and when each can be run; the box is in
`src/components/composer.tsx` and the list in `src/components/slash-menu.tsx`.

`/budget` opens the limits of the conversation: what it may spend, how many team sessions the lead may start in
answering a message, and how many rounds each may have. It works while the lead is at work, and a turn that was stopped
by the spending limit offers it as Raise the limit. The others stand for what the buttons do: `/model`, `/rename`,
`/export`, `/files`, `/new`, `/pause`, `/resume`, `/stop`, and `/help`.

`/ask`, `/plan`, `/search`, `/code`, `/plot`, `/review`, and `/lab` go with the message as a command (`directive` in
`POST /api/chats/{id}/messages`), which the transcript shows as a chip on the message. `/ask` and `/plan` answer
without tools, `/search` reads the literature first and cites what it found, `/code` and `/plot` run code, and `/review`
has the Critic go over the last answer. A command is a part of the message, so Retry and Edit send it again with it, and
the server holds the lead to it: an answer that did not do what was asked is shown with a note saying so. A command that
cannot be carried out, such as `/code` where code is turned off in the settings, is listed with why, and one the server
refuses puts the text back in the box. The rules are in `src/lib/commands.ts` and `src/lib/transcript.ts`.

`/lab` is a command whose choices are made in a panel (`src/components/lab-dialog.tsx`), which opens with what was
written after it as what the scientists are to work on. The researcher chooses a team that discusses it, with the lead
leading, or one scientist whom the Critic reviews, who takes part from the whole library of scientists (not only those
on the conversation's team: the server adds the others to it, when the lead is not at work), how many rounds, and
what they must answer. That is sent with the message as `lab` beside `directive: "lab"`, and the lead is given only
the tool that holds that session, with who and how many rounds set, so that it writes the agenda. The transcript
shows who was chosen beside the chip. A problem with a field is said once the field has been changed, Start waits
for the form to be right, a refusal by the server is shown in the panel, which stays open, and closing the panel puts
what was written back in the box as `/lab …`. Who and how many rounds are remembered for the next time
(`localStorage`, key `vl-lab`). The form's rules are in `src/lib/team-choice.ts`.

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
figures in it, a PDF, or a Jupyter notebook (`.ipynb`) whose code cells hold the code the lead ran, with what it printed and
the figures it drew as their outputs. The server lays it out (`GET /api/chats/{id}/export?format=html|pdf|ipynb`, from
`virtual_lab.export_chat` and `virtual_lab.export_notebook`, as the Python package saves a conversation), and the page fetches it, and then hands it to the
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

The tests of the settings, the keys, the scientists, the tools, and the data and software given to the lab (`e2e/own-server`) change what every conversation is made with, so
they run in a project of their own, against a second scripted server on the next port (8800). Each file of them puts
back what it changed before each test, and neither touches what the other does. They run in order within a file, and a
test that needs a key puts it there itself, since the server keeps none. The keys they give are kept in a keychain that is
a dictionary in the scripted server, the Test Keychain, and never in the machine's (`--no-keychain` has the server have
none, as one on a machine without a keychain does). `e2e/own-server/keychain.spec.ts` tests what the page shows of it.
It gives and takes away the same keys as the tests of the settings, so it has a project of its own (`--project=keychain`)
that begins when the others of the server are done, and a run of it runs them first (`--no-deps` leaves them out).

The tests of the setup (`e2e/setup`) have a third scripted server, on the port after that (8801), which is given stand-ins
for Docker and for the place the data lake is fetched from, so that nothing is built or downloaded: a Docker that says
what a test tells it, and files of 10 KB for every file of the data lake. A test arranges them through a small server on
the port after (8802, `--setup-control-port`; `e2e/setup/state.ts` is the client, and `FakeSetup.control` in
`e2e/scripted_server.py` lists what it can be told), for instance to hold a download so that its progress and stopping can
be seen. These run in a project of their own (`--project=setup`), one test at a time, and put the stand-ins back as they
were before each test. They include the data lake as the Data page shows it (`e2e/setup/data-page.spec.ts`).

The tests of the MCP servers (`e2e/mcp`) set servers up, and every conversation made without being told which to have is
given them, so they have a fourth scripted server, on the port after the setup's control port (8803), and run in a project of
their own (`--project=mcp`). The servers are real: the test server of the library's own tests (`tests/mcp_test_server.py`) is
started as a program for a conversation, or as a server over HTTP that is signed in to with OAuth, whose authorization
server signs anyone in at once. Nothing opens a browser; a test follows the sign-in link the page shows, as a person would,
and the sign-ins are kept in a folder of the scripted server's own. The tests of each file run in order, and name the
servers their conversations are given, since the files run beside each other. The check of a server, and its sign-in, are
tested there too (`e2e/mcp/check.spec.ts`), and `appearance.spec.ts` looks at what they show in the dark and on a phone.

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
| `tool:files` | Looks at the file attached to the conversation, `counts.csv`, with the library's own tools for that |
| `tool:offered` | Answers with the names of the tools the model was offered, which is how a test sees what the settings gave it |
| `mcp:echo`, `count`, `both`, `order`, `confirm`, `signed`, `gated` | Calls the tools of the test server that the tests of `e2e/mcp` set up as `genes` (or `vault`, for `signed`, and `gate`, for `gated`): `echo`, `count`, `count` and then `echo`, `order` (which asks what to order), and `confirm` (which asks yes or no) |
| `pdf:unavailable` | Has saving the conversation as a PDF fail, as it does where WeasyPrint is not installed (the PDF is otherwise made by a stand-in that needs no WeasyPrint) |
| `lab:team` | Brings in the team for a round of discussion, in which the scientists answer as the script says |
| `lab:consult` | Asks one scientist, reviewed by the critic |
| `lab:code` | Asks one scientist, who runs code in the session before they reply |
| `lab:slow` | Asks one scientist, who writes a long reply, slowly |

Code runs on this machine, so a test that wants it makes its conversation through the server with `code: {where:
"local"}`, as `askWhereCodeRuns` in `e2e/fixtures.ts` does. `e2e/replay.spec.ts` replaces a conversation's event stream
with events written in the test, for what the scripted lead does not do, such as a turn that is cut short, and
`e2e/asking.spec.ts` uses it to show every way a call, a question, and a connection can stand.

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
