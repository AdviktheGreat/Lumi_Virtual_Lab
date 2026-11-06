# Repairing code and running steps within one budget

[Back to the README](../README.md). Fixing code that fails, and running many meetings within one budget, from a script.

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
