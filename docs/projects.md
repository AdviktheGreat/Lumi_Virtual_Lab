# Repairing code and running a project

[Back to the README](../README.md). Fixing code that fails, and running many meetings within one budget, by hand or with the principal investigator deciding each step.

## Fixing code that fails

`run_with_repair` writes a meeting's code, runs it, and hands the traceback back to the agent that wrote it, asking for a correction. It stops as soon as the code runs, when the attempts are used up, or when an attempt reproduces the previous error.

```python
from virtual_lab import DockerExecutor, run_with_repair, save_execution_record

outcome = run_with_repair(
    artifacts=code,
    author=machine_learning_specialist,
    save_dir=Path("results"),
    save_name="discussion",
    executor=DockerExecutor(),
)
save_execution_record(
    save_dir=Path("results"),
    save_name="discussion",
    outcome=outcome,
    author=machine_learning_specialist,
    executor=DockerExecutor(),
)
```

The failure goes to the author rather than to the critic because the author knows what the code was meant to do, while the critic's job is scientific judgement rather than debugging. Each attempt past the first costs another round of code generation, so `max_attempts` defaults to 3. The record written to `executions/<save_name>.json` lists every attempt, the code it ran, and what that produced, alongside the total token usage and cost of the repairs, making the multiplier visible rather than buried.

Repairs take the same limits as a meeting: `max_cost` is checked before each repair request, `max_completion_tokens` caps each one, and `on_usage` and `before_request` let a caller keep a running total or stop the loop. If the loop is stopped partway, by its limit, a request that fails, or Ctrl-C, every attempt it ran and what the repairs cost are recorded under `save_dir/partial/executions/<save_name>.json` before the error propagates.

The result can then be reviewed as evidence rather than as a claim, by passing it into the next meeting as context:

```python
run_meeting(
    meeting_type="individual",
    agenda="Review the results of running the analysis.",
    save_dir=Path("results"),
    team_member=machine_learning_specialist,
    contexts=(outcome.report(),),
)
```

`outcome.report()` states plainly whether the code worked, whether it had to be corrected first, and whether it was abandoned. A critic that is not told the code failed three times will review the code as though it had worked.


## Running a project within one budget, and resuming it

A project is many meetings, with code run and repaired between them. `Project` holds them to one budget and keeps a ledger, `project.json`, of every step: what it was asked to do, what it cost, how it ended, and where it was saved.

```python
from virtual_lab import CodeArtifacts, DockerExecutor, Project, ProjectBudgetExceededError

project = Project(Path("results/project"), goal="Find the genes that separate responders from non-responders.", max_cost=20.0, session=session)

try:
    plan = project.meeting(
        "team", "Choose the computational tools.", name="tools",
        team_lead=principal_investigator, team_members=(immunologist, ml_specialist), num_rounds=2,
    )
    code = project.meeting(
        "individual", "Write the ESM scoring script.", name="esm",
        team_member=ml_specialist, summaries=(plan.summary,), output_schema=CodeArtifacts,
    )
    outcome = project.repair(code.output, ml_specialist, DockerExecutor(), name="esm_run")
except ProjectBudgetExceededError as error:
    print(f"Stopped at ${error.spent:.2f} of ${error.limit:.2f}")
print(project.spent, project.remaining)
```

- `max_cost` covers every meeting and repair in the project, across every run of it on the same directory. Each step is given what is left as its own limit, and the project's total is checked before every request any step sends, so steps run from several threads at once are stopped together. As for a meeting, the limit can be overrun by the cost of one request per step running at the time.
- Each step is recorded as soon as it starts, and what it has cost is updated after every response. A step that fails, or is interrupted by Ctrl-C, is recorded with its error and what it cost. One whose process is killed outright is found running when the project is next opened and is marked interrupted, with what it had cost by its last response.
- A step that finished is never paid for twice. Opening the project again on the same directory and asking for a step under the same name and with the same inputs reads it back from disk, for nothing. A script that stopped partway, for its budget, an error, or Ctrl-C, therefore carries on where it stopped when run again, perhaps with a higher `max_cost`. A failed step is held again.
- Asking for a finished step under its name with different inputs is refused with `ProjectStateError`, which names the inputs that differ, since replacing it could change what later steps were built on; give the new step a name of its own. Agents, tools, and resources are compared by everything the agents are told of them, so a tool described differently or a know-how document edited is a different input. A meeting's transcript, record, and structured output, and a repair's record and code, are checked against hashes in the ledger before they are read back, so a file changed since is refused too. A directory holding a project with another goal is refused.
- Steps are named `meeting_001`, `meeting_002`, and so on, and `repair_001` onwards, in the order they are asked for, unless named. Name every step run from a thread, since that order is not fixed. Meetings and repairs are saved under `meetings/` by name, laid out as `hold_meeting` and `run_with_repair` lay them out.
- Options given to `Project` apply to every meeting, under those given to a meeting. `session`, `chat_models`, and `client` are the project's own, and are used for repairs too. A session does not survive the process, so meetings read back on a later run leave nothing in its interpreter; the files they wrote in its directory remain. Only one process should use a project's directory at a time.

### Letting the principal investigator run the project

`run_project` hands the deciding to the team lead. The team lead chooses a team, unless one is given, the team makes a plan, and then every round the team lead reads what the project has done and decides one next step, restating the plan with each task's status:

- `team_meeting`: a discussion it leads, with the team members and critic it names.
- `individual_meeting`: one team member, or the team lead, works on an agenda, with the critic critiquing.
- `write_code`: one of them writes code, which is run with `executor` and repaired if it fails. Offered only with an executor.
- `change_team`: scientists are brought onto the team, up to `max_team_size`, or let go.
- `finish`: the team lead gives the project's answer. The critic reviews it against the goal and the work done, and the project ends only if the critic agrees; otherwise its objections are what the next round goes on.

```python
from virtual_lab import DockerExecutor, Project, run_project

project = Project(Path("results/project"), goal="Find the genes that separate responders from non-responders.", max_cost=20.0)
report = run_project(project, max_rounds=12, executor=DockerExecutor())
print(report.status, report.reason)
print(report.answer)
```

- A run ends `finished` when the critic accepts an answer, `out_of_budget` when the project's `max_cost` runs out, `out_of_rounds` after `max_rounds` rounds, `stalled` after `max_stalled_rounds` rounds in a row without one more of the plan's tasks done, or `stopped` by the approve hook. Running out of budget ends it with a report, not an error.
- Every meeting is told the goal, the team, and the plan as it stands, and is given what the work so far found, as `memory` says (below). A decision that cannot be carried out, such as one naming someone not on the team, is recorded and the team lead is told why in the next round.
- `approve` is called with each round's number and decision before it is carried out, and returns the decision to carry out, which it may change, or `None` to stop the project. With none, the project runs on its own. A `steer` given to the `Project` adds a person's notes to its meetings as they go (see [Steering a meeting as it happens](meetings.md#steering-a-meeting-as-it-happens)).
- `on_event` is called with a `ProjectEvent` when the team is chosen or changed (`team`), the plan is made (`plan`), each step is decided (`decided`, before `approve` is asked), code is run (`code`), each round ends (`round`), and the project ends (`finished`, with the report), and with every `MeetingEvent` of every meeting it holds, so a project can be followed as it happens. The `Project`'s own `on_event`, if it has one, is called first. An exception it raises stops the project like any other error, except when it is told the project ended, once the report is saved, which is only warned about.
- `research_log.json` records every round, with the decision as proposed and as carried out, and every change to the team, and is saved after every round. The run ends with `report.json` and `report.md`: the answer, or the last one the critic did not accept and its objections, the team, the plan, every round, and the cost. A run that fails with any other error leaves no report, and the log says what the error was.
- Every step is a step of the project, so a run that stopped is carried on by running it again on the same directory: the steps it took are read back for nothing. Nothing a step is asked depends on `max_cost`, `max_rounds`, or `max_stalled_rounds`, so they can be raised to carry a project on. For the same reason, the team lead is not told how many rounds or how much money is left. Every decision carried out, whether the approve hook changed it or there was no hook, is kept in the log and not asked about again, however far a later run gets before it stops; one the hook stopped is asked about again.

#### What each step is given of the work before it

Passing every meeting the summary of every meeting before it, as the original Virtual Lab (Swanson et al.) does, fills the context as a project grows, with much that the meeting at hand does not need. So `run_project` keeps what the work established in a `LabMemory`, as findings: each meeting restates what it found as `Findings`, one claim and its evidence apiece, in one more request, and after code is run its author says what the run established, in a short meeting of its own. Each finding gets an id, `F1`, `F2`, and so on. What a step is given then depends on `memory`:

- `"pick"`, the default: the team lead is shown every finding by its id and claim, and what each step found, with the latest step in full, and names in each decision the findings the step needs. The step is given those in full and no others; for `finish`, the critic is given the ones the answer rests on. This is how Biomni's agent picks the tools, data, and know-how a task needs, and costs no requests beyond the findings themselves. A decision naming a finding that does not exist is refused.
- `"bm25"`: each step is given the findings whose claim and evidence best match its agenda and questions, or a proposed answer, by BM25, at most `findings_per_step` of them.
- `"summaries"`: no findings are kept, and each step is given the summary of every step before it, as before.

The findings are saved in `memory.json` and listed in the report, and the research log records which findings each round was given and which it made. A memory can be used on its own too:

```python
from virtual_lab import Finding, LabMemory

memory = LabMemory()
memory.add([Finding(claim="TP53 is higher in the treated samples.", evidence="DESeq2, three replicates.")], source="assay")
memory.search("TP53 expression", limit=5)  # by BM25
memory.get(["F1"])
memory.save(Path("memory.json"))
```
