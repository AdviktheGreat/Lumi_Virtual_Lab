import { describe, expect, it } from "vitest";
import {
  asksModel,
  checkChecks,
  describeBasis,
  describeDetails,
  describeNeeds,
  describePassed,
  describeStanding,
  describeTiers,
  describeWhen,
  emptyChecks,
  hasChecks,
  statusTitle,
  whyNot,
  type ChecksDraft,
} from "./paperagent-checks";
import type { CheckedTool, CheckEvidence, CheckKind, CheckStatus, PaperAgentChecks } from "./types";

const kinds: CheckKind[] = [
  { kind: "heldout", title: "Inputs the tutorial did not use", said: "said", what: "What it shows.", basis: "function", default: true, model: false },
  { kind: "repo_tests", title: "The code's own tests", said: "said", what: "What it shows.", basis: "tests", default: true, model: false },
  { kind: "paper_numbers", title: "Numbers the paper reports", said: "said", what: "What it shows.", basis: "paper", default: false, model: true },
  { kind: "verifier", title: "Inputs that a model of another family chose", said: "said", what: "What it shows.", basis: "function", default: false, model: true },
];

const bases = {
  function: "the code's own function, called with inputs that the tutorial did not pass",
  tests: "the tests that come with the code",
  paper: "the numbers that the paper reports",
};

function checks(part: Partial<PaperAgentChecks> = {}): PaperAgentChecks {
  return {
    id: "cells",
    docker: { ready: true, message: null },
    made: true,
    tools: [],
    settings_model: "gpt-4o-2024-08-06",
    settings_family: "openai",
    kinds,
    numbers: 4,
    job: null,
    meaning: "What tier B is.",
    bases,
    bases_for_b: 2,
    limits: {
      default_minutes: 5,
      max_minutes: 30,
      default_total_minutes: 30,
      max_total_minutes: 180,
      default_repeats: 2,
      max_repeats: 3,
      default_gigabytes: 2,
      max_gigabytes: 20,
      memory: "8g",
      cpus: "4",
      pids: 1024,
    },
    ...part,
  };
}

const draft = (part: Partial<ChecksDraft> = {}, of: PaperAgentChecks = checks()): ChecksDraft => ({ ...emptyChecks(of), ...part });

function entry(kind: string, status: CheckStatus, part: Partial<CheckEvidence> = {}): CheckEvidence {
  const info = kinds.find((one) => one.kind === kind) as CheckKind;

  return {
    kind,
    title: info.title,
    basis: info.basis,
    what: info.what,
    status,
    summary: "It came to this.",
    file: status === "not_run" ? null : `checks/independent/scale/${kind}.json`,
    checked_at: status === "not_run" ? null : "2026-01-01T00:00:00Z",
    was: null,
    ...part,
  };
}

function tool(statuses: Partial<Record<string, CheckStatus>>, part: Partial<CheckedTool> = {}): CheckedTool {
  const evidence = kinds.map((one) => entry(one.kind, statuses[one.kind] ?? "not_run"));
  const passed = evidence.filter((one) => one.status === "passed");
  const have = [...new Set(passed.map((one) => one.basis))].sort();
  const failed = evidence.some((one) => one.status === "failed");

  return {
    name: "scale",
    module: "cellmapper.core",
    function: "scale",
    made_as: "A",
    tier: have.length >= 2 && !failed ? "B" : "A",
    passed: passed.map((one) => one.kind),
    bases: have,
    evidence,
    ...part,
  };
}

describe("emptyChecks", () => {
  it("is the defaults that the server gives, with the kinds that need no model", () => {
    expect(emptyChecks(checks())).toEqual({
      minutes: "5",
      totalMinutes: "30",
      repeats: "2",
      gigabytes: "2",
      kinds: ["heldout", "repo_tests"],
      budget: "",
      verifier: "",
    });
  });
});

describe("asksModel", () => {
  it("is so if a kind that asks a model is asked for, and only then", () => {
    expect(asksModel({ kinds: ["heldout", "repo_tests"] }, kinds)).toBe(false);
    expect(asksModel({ kinds: ["heldout", "paper_numbers"] }, kinds)).toBe(true);
    expect(asksModel({ kinds: ["verifier"] }, kinds)).toBe(true);
    expect(asksModel({ kinds: [] }, kinds)).toBe(false);
  });
});

describe("whyNot", () => {
  it("says that the paper has no number to look for, and that no other family can be told when the settings model's is not known", () => {
    expect(whyNot("paper_numbers", checks({ numbers: 0 }))).toContain("no number that it reports with digits enough");
    expect(whyNot("paper_numbers", checks())).toBeNull();
    expect(whyNot("verifier", checks({ settings_family: null, settings_model: "my-tune" }))).toContain("whose model my-tune is");
    expect(whyNot("verifier", checks())).toBeNull();
    expect(whyNot("heldout", checks({ numbers: 0, settings_family: null }))).toBeNull();
  });
});

describe("checkChecks", () => {
  it("asks for the defaults, which need no model and so say nothing of spending", () => {
    expect(checkChecks(draft(), checks())).toEqual({
      value: { minutes: 5, total_minutes: 30, repeats: 2, gigabytes: 2, kinds: ["heldout", "repo_tests"] },
      problems: {},
    });
  });

  it("holds each number to what the server takes", () => {
    const wrong = checkChecks(draft({ minutes: "0", totalMinutes: "500", repeats: "9", gigabytes: "many" }), checks());

    expect(wrong.value).toBeNull();
    expect(wrong.problems.minutes).toBe("The most time for one check of one tool, in minutes, is a whole number from 1 to 30.");
    expect(wrong.problems.totalMinutes).toBe("The most time for all of the checks, in minutes, is a whole number from 1 to 180.");
    expect(wrong.problems.repeats).toBe("How many times each call is made is a whole number from 1 to 3.");
    expect(wrong.problems.gigabytes).toBe("The most one run may write, in gigabytes, is a whole number from 1 to 20.");
    expect(checkChecks(draft({ minutes: "30", totalMinutes: "180", repeats: "3", gigabytes: "20" }), checks()).value).toMatchObject({
      minutes: 30,
      total_minutes: 180,
      repeats: 3,
      gigabytes: 20,
    });
  });

  it("needs a kind", () => {
    const none = checkChecks(draft({ kinds: [] }), checks());

    expect(none.value).toBeNull();
    expect(none.problems.kinds).toBe("Choose at least one kind of check.");
  });

  it("sends the kinds in the order that the server makes them, whatever order they were chosen in", () => {
    const asked = checkChecks(draft({ kinds: ["paper_numbers", "heldout"], budget: "1" }), checks());

    expect(asked.value?.kinds).toEqual(["heldout", "paper_numbers"]);
  });

  it("ignores a kind that it does not know", () => {
    expect(checkChecks(draft({ kinds: ["heldout", "astrology"] }), checks()).value?.kinds).toEqual(["heldout"]);
    expect(checkChecks(draft({ kinds: ["astrology"] }), checks()).problems.kinds).toBe("Choose at least one kind of check.");
  });

  it("asks for what may be spent, as dollars, when a kind that asks a model is asked for, and says nothing of it otherwise", () => {
    const blank = checkChecks(draft({ kinds: ["heldout", "paper_numbers"] }), checks());
    expect(blank.value).toBeNull();
    expect(blank.problems.budget).toBe("Say the most it may spend.");
    expect(checkChecks(draft({ kinds: ["paper_numbers"], budget: "lots" }), checks()).problems.budget).toBe(
      "The most it may spend is an amount in dollars, such as 1 or 0.50.",
    );
    expect(checkChecks(draft({ kinds: ["paper_numbers"], budget: "$0.50" }), checks()).value).toMatchObject({ kinds: ["paper_numbers"], max_cost: 0.5 });
    expect(checkChecks(draft({ kinds: ["paper_numbers"], budget: "0" }), checks()).value?.max_cost).toBe(0);
    // A limit on spending for kinds that ask no model is refused by the server, so what was typed is not sent
    const free = checkChecks(draft({ budget: "5" }), checks());
    expect(free.value).not.toBeNull();
    expect(free.value).not.toHaveProperty("max_cost");
  });

  it("asks for the model that chooses inputs when that kind is asked for, and sends it as it was typed, without the blanks around it", () => {
    expect(checkChecks(draft({ kinds: ["verifier"], budget: "1" }), checks()).problems.verifier).toBe(
      "Name the model that chooses the inputs, of another family than the one in the settings.",
    );
    const asked = checkChecks(draft({ kinds: ["heldout", "verifier"], budget: "1", verifier: "  claude-sonnet-4-6 " }), checks());

    expect(asked.value).toMatchObject({ kinds: ["heldout", "verifier"], max_cost: 1, verifier_model: "claude-sonnet-4-6" });
    expect(checkChecks(draft({ budget: "1", verifier: "claude-sonnet-4-6" }), checks()).value).not.toHaveProperty("verifier_model");
  });

  it("refuses a model that is the one in the settings, however it is written, a name that is too long, and one with a control character", () => {
    const refused = (verifier: string) => checkChecks(draft({ kinds: ["verifier"], budget: "1", verifier }), checks()).problems.verifier;

    expect(refused(" GPT-4o-2024-08-06 ")).toContain("is the model in the settings");
    expect(refused("a".repeat(201))).toBe("A model's name is at most 200 characters.");
    expect(refused("a".repeat(200))).toBeUndefined();
    expect(refused("claude\nsonnet")).toBe("A model's name has no control characters.");
  });

  it("says why a kind cannot be asked for, and does not send it", () => {
    const none = checkChecks(draft({ kinds: ["paper_numbers"], budget: "1" }), checks({ numbers: 0 }));
    expect(none.value).toBeNull();
    expect(none.problems.kinds).toContain("no number that it reports");
    const unknown = checkChecks(draft({ kinds: ["verifier"], budget: "1", verifier: "claude-sonnet-4-6" }), checks({ settings_family: null }));
    expect(unknown.value).toBeNull();
    expect(unknown.problems.kinds).toContain("not known whose model");
  });
});

describe("statusTitle", () => {
  it("is a word for each status, and the status itself if it is not one that the page knows", () => {
    expect(["passed", "failed", "not_obtained", "stale", "not_run"].map(statusTitle)).toEqual(["Passed", "Failed", "Not obtained", "Stale", "Not run"]);
    expect(statusTitle("odd")).toBe("odd");
  });
});

describe("describeBasis", () => {
  it("is what the server says it is, or its name", () => {
    expect(describeBasis("tests", bases)).toBe("the tests that come with the code");
    expect(describeBasis("other", bases)).toBe("other");
  });
});

describe("describePassed", () => {
  it("counts the kinds that passed, of those there are", () => {
    expect(describePassed(tool({ heldout: "passed" }))).toBe("1 of 4 kinds of check passed");
    expect(describePassed(tool({}))).toBe("0 of 4 kinds of check passed");
  });
});

describe("describeStanding", () => {
  const view = checks();

  it("says that nothing has passed, with the tier it was made as", () => {
    expect(describeStanding(tool({}), view)).toBe("Made as tier A. No check of it has passed.");
  });

  it("says that one basis is not two, and that checks of the same basis do not make two", () => {
    expect(describeStanding(tool({ heldout: "passed" }), view)).toBe(
      "Made as tier A. It passed checks against 1 thing (the code's own function, called with inputs that the tutorial did not pass), and tier B needs 2 different.",
    );
    const same = tool({ heldout: "passed", verifier: "passed" });

    expect(same.tier).toBe("A");
    expect(describeStanding(same, view)).toContain("It passed checks against 1 thing");
  });

  it("says what tier B comes of", () => {
    const both = tool({ heldout: "passed", repo_tests: "passed" });

    expect(both.tier).toBe("B");
    expect(describeStanding(both, view)).toBe(
      "Made as tier A. It passed checks against 2 different things: the code's own function, called with inputs that the tutorial did not pass; the tests that come with the code.",
    );
  });

  it("says that a check that failed keeps it from tier B, whatever else passed", () => {
    const failed = tool({ heldout: "passed", repo_tests: "passed", paper_numbers: "failed" });

    expect(failed.tier).toBe("A");
    expect(describeStanding(failed, view)).toBe("Made as tier A. A check failed, which keeps it from tier B until it is checked again and none fails.");
  });

  it("does not count a stale check, nor one that was not obtained", () => {
    expect(describeStanding(tool({ heldout: "passed", repo_tests: "stale", paper_numbers: "not_obtained" }), view)).toContain("1 thing");
  });
});

describe("describeNeeds", () => {
  const view = checks();

  it("says what it would take for a tool that is not of tier B, naming the bases it has not passed and the kinds that are against each", () => {
    expect(describeNeeds(tool({ heldout: "passed" }), view)).toBe(
      "To be of tier B it needs a check that passes against one more of: the tests that come with the code (The code's own tests); the numbers that the paper reports (Numbers the paper reports). A second check against what it has passed one against does not count.",
    );
    expect(describeNeeds(tool({}), view)).toContain("2 more of: the code's own function, called with inputs that the tutorial did not pass (Inputs the tutorial did not use or Inputs that a model of another family chose)");
  });

  it("says nothing of a tool that is of tier B, or one that has a check that failed", () => {
    expect(describeNeeds(tool({ heldout: "passed", repo_tests: "passed" }), view)).toBeNull();
    expect(describeNeeds(tool({ heldout: "failed" }), view)).toBeNull();
  });
});

describe("describeWhen", () => {
  it("says that a check was not made, or when it was", () => {
    expect(describeWhen({ checked_at: null })).toBe("Not made");
    expect(describeWhen({ checked_at: new Date(Date.now() - 3 * 60_000).toISOString() })).toBe("Made 3 min ago");
    expect(describeWhen({ checked_at: "not a time" })).toBe("Made a while ago");
  });
});

describe("describeTiers", () => {
  it("counts the tools of each tier now", () => {
    expect(describeTiers([])).toBe("There are no tools.");
    expect(describeTiers([tool({})])).toBe("1 tool: 1 of tier A.");
    expect(describeTiers([tool({}), tool({ heldout: "passed", repo_tests: "passed" }), tool({})])).toBe("3 tools: 2 of tier A, 1 of tier B.");
  });
});

describe("hasChecks", () => {
  it("is so if any kind of any tool was made, which is what there is to take away", () => {
    expect(hasChecks([tool({}), tool({})])).toBe(false);
    expect(hasChecks([tool({}), tool({ repo_tests: "not_obtained" })])).toBe(true);
    expect(hasChecks([tool({ heldout: "stale" })])).toBe(true);
    expect(hasChecks([])).toBe(false);
  });
});

describe("describeDetails", () => {
  const cases = [
    { from: 0, tutorial: "01", change: "numbers moved", args: "{'values': [1, 2], 'factor': 2.75}", verdict: "agree", differences: [], error: null },
    { from: 0, tutorial: "01", change: "numbers moved", args: "{'values': [1], 'factor': 3}", verdict: "differs", differences: ["What the tool gave is not what the code's own function gave: [3] != [4]"], error: null },
  ];

  it("says how the changed calls went, and each call, for the inputs that a rule changed", () => {
    const sections = describeDetails("heldout", {
      repeats: 2,
      tolerance: { relative: 1e-9, absolute: 1e-12 },
      counts: { agree: 1, same_error: 0, differs: 1, unstable: 0, not_run: 0 },
      cases,
    });

    expect(sections.map((section) => section.title)).toEqual(["How the calls went", "Calls that were changed"]);
    expect(sections[0].lines).toEqual([
      "1 call gave the same through the tool as from the code's own function; 1 call gave something else through the tool than the code's own function did. Each call was made 2 times.",
    ]);
    expect(sections[1].lines).toHaveLength(2);
    expect(sections[1].lines[0]).toBe("numbers moved: {'values': [1, 2], 'factor': 2.75}: the tool and the code's own function gave the same");
    expect(sections[1].lines[1]).toContain("they gave something else. What the tool gave is not what the code's own function gave: [3] != [4]");
  });

  it("says when no call could be compared, and uses was and were for those that were not made", () => {
    expect(describeDetails("heldout", { repeats: 1, counts: { agree: 0, same_error: 0, differs: 0, unstable: 0, not_run: 0 }, cases: [] })[0].lines).toEqual([
      "No call was compared. Each call was made 1 time.",
    ]);
    expect(describeDetails("heldout", { counts: { agree: 0, same_error: 0, differs: 0, unstable: 1, not_run: 2 }, cases: [] })[0].lines).toEqual([
      "1 call was not compared, as the code's own function gave something else each time; 2 calls were not made in the time.",
    ]);
  });

  it("says which model chose the inputs and what it cost, what was not run and why, its reasons, and its notes as its words", () => {
    const sections = describeDetails("verifier", {
      repeats: 2,
      counts: { agree: 1, same_error: 0, differs: 0, unstable: 0, not_run: 0 },
      cases: [{ ...cases[0], change: "proposed by a model", reason: "An empty list, which the wrapper may not pass on." }],
      model: "claude-sonnet-4-6",
      cost: 0.0312,
      gaps: ["The wrapper gives factor a default that the function does not."],
      proposed: 3,
      usable: 1,
      refused: [{ arguments: '{"values": "x"}', why: "It gives values a text, where the tool takes a list." }],
    });

    expect(sections.map((section) => section.title)).toEqual([
      "The model",
      "Proposed inputs that were not run",
      "How the calls went",
      "Inputs the model proposed that were run",
      "Where the model thought the wrapper and the code might differ",
    ]);
    expect(sections[0].lines).toEqual(["Asked claude-sonnet-4-6, and it cost $0.03.", "It proposed 3 inputs, and 1 could be run."]);
    expect(sections[1].lines).toEqual(['{"values": "x"}: It gives values a text, where the tool takes a list.']);
    expect(sections[3].lines[0]).toContain("proposed by a model: {'values': [1, 2], 'factor': 2.75}: the tool and the code's own function gave the same. Its reason: An empty list");
    expect(sections[4].lines).toEqual(["The wrapper gives factor a default that the function does not."]);
    expect(sections[4].words).toBe("These are the model's words. They are no part of how the check came out.");
    expect(sections.filter((section) => section.words !== undefined)).toHaveLength(1);
  });

  it("says that what a model cost is not known when it is not", () => {
    const sections = describeDetails("verifier", { model: "claude-sonnet-4-6", cost: null, proposed: 0, usable: 0, gaps: [] });

    expect(sections[0].lines[0]).toBe("Asked claude-sonnet-4-6, and what it cost is not known.");
  });

  it("says how the code's own tests went, which did not pass, and which were run", () => {
    const sections = describeDetails("repo_tests", {
      ids: ["tests/test_core.py::test_scale", "tests/test_core.py::test_scale_empty"],
      tests: 2,
      passed: 1,
      failed: 1,
      errors: 0,
      skipped: 0,
      failures: [{ name: "tests/test_core.py::test_scale_empty", message: "assert [] == [0]" }],
    });

    expect(sections.map((section) => section.title)).toEqual(["How the tests went", "Tests that did not pass", "Tests that call the function"]);
    expect(sections[0].lines).toEqual(["2 tests ran: 1 passed, 1 failed, 0 stopped with an error, and 0 were skipped."]);
    expect(sections[1].lines).toEqual(["tests/test_core.py::test_scale_empty: assert [] == [0]"]);
    expect(sections[2].lines).toHaveLength(2);
  });

  it("says what was looked for in the numbers that the paper reports, and where, with what the tool gave", () => {
    const sections = describeDetails("paper_numbers", {
      numbers: 4,
      ambiguous: 0,
      candidates: 2,
      accepted: 1,
      model: "gpt-4o-2024-08-06",
      cost: 0.0021,
      counts: { match: 1, differs: 0, error: 0, not_run: 0 },
      links: [
        {
          claim: "c1",
          quote: "The score was 0.931 on the test set.",
          number: { text: "0.931", value: 0.931, decimals: 3, percent: false },
          call: 1,
          tutorial: "01",
          path: ["score"],
          at: "result['score']",
          verdict: "match",
        },
      ],
    });

    expect(sections.map((section) => section.title)).toEqual(["What was looked for", "Where the paper's numbers were looked for in what the tool gave"]);
    expect(sections[0].lines).toEqual([
      "4 numbers of the paper had digits enough to be looked for.",
      "2 places in what the calls gave held one.",
      "The model said that 1 of them hold the quantity that the paper's sentence is about.",
      "Asked gpt-4o-2024-08-06, and it cost <$0.01.",
    ]);
    expect(sections[1].lines).toEqual(["0.931 at result['score'] (“The score was 0.931 on the test set.”): the tool gave it every time"]);
  });

  it("says nothing of what it does not know how to read, and does not throw on what is not as the server writes it", () => {
    expect(describeDetails("heldout", undefined)).toEqual([]);
    expect(describeDetails("heldout", null)).toEqual([]);
    expect(describeDetails("heldout", [1, 2])).toEqual([]);
    expect(describeDetails("heldout", "text")).toEqual([]);
    expect(describeDetails("astrology", { counts: {} })).toEqual([]);
    expect(describeDetails("heldout", { counts: "many", cases: [1, null, "x", { verdict: 7 }] })).toEqual([
      { title: "Calls that were changed", lines: ["Changed: : ?"] },
    ]);
    expect(describeDetails("verifier", { refused: [5, { arguments: 1, why: 2 }], gaps: [1, "kept"], proposed: "3" })).toEqual([
      { title: "Proposed inputs that were not run", lines: [": "] },
      {
        title: "Where the model thought the wrapper and the code might differ",
        lines: ["kept"],
        words: "These are the model's words. They are no part of how the check came out.",
      },
    ]);
    expect(describeDetails("repo_tests", { tests: "2", failures: [3] })).toEqual([]);
    expect(describeDetails("paper_numbers", { links: [null, { number: 5, verdict: "odd" }] })).toEqual([
      { title: "Where the paper's numbers were looked for in what the tool gave", lines: ["? at ? (“”): odd"] },
    ]);
  });

  it("cuts what is long, so that one line does not take the page", () => {
    const long = "x".repeat(500);
    const sections = describeDetails("verifier", { gaps: [long], refused: [{ arguments: long, why: long }] });

    expect(sections[0].lines[0].length).toBeLessThanOrEqual(100 + 2 + 200 + 2);
    expect(sections[1].lines[0].length).toBe(301);
  });
});
