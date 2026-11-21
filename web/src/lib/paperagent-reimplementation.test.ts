import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  canCheck,
  checkBudget,
  checkChoice,
  checkInputs,
  checkMatching,
  describeChecking,
  describeEntry,
  describeMatchingCounts,
  describeOffer,
  describeParameters,
  describeTask,
  describeWriting,
  draftOf,
  emptyMatching,
  inputsText,
  MAX_NAME_CHARS,
  matchingTitle,
  sameChoice,
  writingTitle,
} from "./paperagent-reimplementation";
import type {
  MatchingClaim,
  MatchingEntry,
  MatchingParameter,
  MatchingStatus,
  PaperAgentMatching,
  PaperAgentReimplementation,
  ReimplementationKept,
  ReimplementationOffer,
} from "./types";

const LIMITS: PaperAgentReimplementation["limits"] = { most_chars: 24000, most_goal_chars: 2000, most_search_chars: 200, most_searched: 6, most_sections: 12 };
const CHECK_LIMITS: PaperAgentMatching["limits"] = { most_tried: 12, repeats: 2, default_minutes: 5, most_minutes: 30, most_arguments_chars: 4000 };
const NOW = new Date("2026-11-21T06:00:00Z");
const SPANS = [
  { index: 0, title: "Abstract" },
  { index: 1, title: "Methods" },
  { index: 2, title: "Results" },
];

function offerOf(changes: Partial<ReimplementationOffer> = {}): ReimplementationOffer {
  return {
    name: "doubled_sum",
    goal: null,
    search: null,
    sections: [1],
    places: [{ start: 65, end: 161, section: "Methods", page: null, chars: 96 }],
    cut: false,
    brief: "The paper: Adding and doubling",
    chars: 219,
    model: "gpt-4o",
    file_sha256: "a".repeat(64),
    key: "k".repeat(64),
    ...changes,
  };
}

function keptOf(changes: Partial<ReimplementationKept> = {}): ReimplementationKept {
  return {
    name: "doubled_sum",
    paper_sha256: "a".repeat(64),
    agreed_at: "2026-11-21T05:43:26Z",
    model: "gpt-4o",
    limit: 1,
    started_at: "2026-11-21T05:43:26Z",
    finished_at: "2026-11-21T05:43:27Z",
    status: "written",
    error: null,
    problems: [],
    attempts: 1,
    cost: 0.00045,
    task: {
      goal: null,
      search: null,
      sections: [1],
      places: [{ start: 65, end: 161, section: "Methods", page: null, chars: 96 }],
      cut: false,
      chars: 219,
      brief_sha256: "b".repeat(64),
    },
    function: { status: "verified", source_sha256: "c".repeat(64), modules: [] },
    current: true,
    source: "def doubled_sum(numbers: list[float]) -> float:\n    return 2 * sum(numbers)\n",
    ...changes,
  };
}

function entryOf(changes: Partial<MatchingEntry> = {}): MatchingEntry {
  return {
    claim: "claim-1",
    value: "0.930",
    quote: "The doubled sum was 0.930.",
    by: "model",
    arguments: { numbers: [0.2, 0.25, 0.015] },
    where: "the numbers 0.2, 0.25 and 0.015",
    reason: null,
    note: null,
    hard_coded: [],
    status: "matched",
    found: { path: [], text: "result", value: 0.93, how: "as written" },
    places: 1,
    error: null,
    gave: "0.93",
    seconds: 0.2,
    ...changes,
  };
}

function claimOf(changes: Partial<MatchingClaim> = {}): MatchingClaim {
  return { id: "claim-1", value: "0.930", quote: "The doubled sum was 0.930.", passage: "Methods ...", inputs: null, entry: null, ...changes };
}

const NUMBERS: MatchingParameter = { name: "numbers", hint: "list[float]", required: true, default: null };
const TIMES: MatchingParameter = { name: "times", hint: "int", required: false, default: "2" };

function counts(changes: Partial<Record<MatchingStatus, number>> = {}): Record<MatchingStatus, number> {
  return { matched: 0, not_found: 0, ambiguous: 0, unstable: 0, error: 0, not_run: 0, hard_coded: 0, no_inputs: 0, ...changes };
}

describe("what is chosen to begin with", () => {
  it("is what the server's offer is of, with its sections in order", () => {
    expect(draftOf({ offer: offerOf({ sections: [3, 1], search: "doubling", goal: "Sum them" }), default_sections: [1] })).toEqual({
      sections: [1, 3],
      search: "doubling",
      name: "doubled_sum",
      goal: "Sum them",
    });
  });

  it("is the sections of the method, and no name, when there is no offer", () => {
    expect(draftOf({ offer: null, default_sections: [2, 4] })).toEqual({ sections: [2, 4], search: "", name: "", goal: "" });
  });
});

describe("checkChoice", () => {
  const draft = { sections: [2, 1], search: "", name: "doubled_sum", goal: "" };

  it("asks only for what was said, with the sections in order", () => {
    expect(checkChoice(draft, LIMITS)).toEqual({ value: { sections: [1, 2], name: "doubled_sum" }, problems: {} });
    expect(checkChoice({ sections: [], search: "  doubling  ", name: " doubled_sum ", goal: " Sum them " }, LIMITS).value).toEqual({
      search: "doubling",
      name: "doubled_sum",
      goal: "Sum them",
    });
  });

  it("wants a section or words to look for, as the server takes neither to mean the method's", () => {
    expect(checkChoice({ ...draft, sections: [] }, LIMITS).problems.sections).toBe("Choose a section of the paper, or say words to look for in it.");
    expect(checkChoice({ ...draft, sections: [], search: "   " }, LIMITS).value).toBeNull();
  });

  it("holds the sections, the words, and what is wanted to their limits", () => {
    const many = Array.from({ length: LIMITS.most_sections + 1 }, (_, index) => index);
    expect(checkChoice({ ...draft, sections: many }, LIMITS).problems.sections).toBe(`Choose at most ${LIMITS.most_sections} sections.`);
    expect(checkChoice({ ...draft, sections: many.slice(1) }, LIMITS).problems.sections).toBeUndefined();
    expect(checkChoice({ ...draft, search: "a".repeat(201) }, LIMITS).problems.search).toBe("The words to look for are at most 200 characters.");
    expect(checkChoice({ ...draft, search: "a".repeat(200) }, LIMITS).problems.search).toBeUndefined();
    expect(checkChoice({ ...draft, goal: "a".repeat(2001) }, LIMITS).problems.goal).toBe("What you want of it is at most 2000 characters.");
    expect(checkChoice({ ...draft, goal: "a".repeat(2000) }, LIMITS).problems.goal).toBeUndefined();
  });

  it("wants a name that is one", () => {
    expect(checkChoice({ ...draft, name: "  " }, LIMITS).problems.name).toBe("Say what the function is called.");
    for (const name of ["Doubled", "1st", "doubled-sum", "doubled sum", "a".repeat(MAX_NAME_CHARS + 1)]) {
      expect(checkChoice({ ...draft, name }, LIMITS).problems.name).toContain("lowercase letters, digits, and underscores");
    }
    for (const name of ["_doubled", "sum2", "a".repeat(MAX_NAME_CHARS)]) {
      expect(checkChoice({ ...draft, name }, LIMITS).problems.name).toBeUndefined();
    }
  });
});

describe("sameChoice", () => {
  it("is so only when the offer is of all that is chosen now", () => {
    const offer = offerOf({ sections: [1, 3], search: "doubling", goal: "Sum them" });
    const choice = { sections: [3, 1], search: "doubling", name: "doubled_sum", goal: "Sum them" };

    expect(sameChoice(choice, offer)).toBe(true);
    expect(sameChoice({ ...choice, sections: [1] }, offer)).toBe(false);
    expect(sameChoice({ ...choice, sections: [1, 2] }, offer)).toBe(false);
    expect(sameChoice({ ...choice, search: undefined }, offer)).toBe(false);
    expect(sameChoice({ ...choice, name: "other" }, offer)).toBe(false);
    expect(sameChoice({ ...choice, goal: undefined }, offer)).toBe(false);
    expect(sameChoice({ name: "doubled_sum" }, offerOf({ sections: [] }))).toBe(true);
  });
});

describe("checkBudget", () => {
  it("wants the most it may spend said, as dollars", () => {
    expect(checkBudget("")).toEqual({ value: null, problem: "Say the most it may spend." });
    expect(checkBudget("$0.50")).toEqual({ value: 0.5 });
    expect(checkBudget("a lot").problem).toBe("The most it may spend is an amount in dollars, such as 1 or 0.50.");
  });
});

describe("describeOffer", () => {
  it("says how much of the paper, from where, and what the function would be called", () => {
    expect(describeOffer(offerOf(), 24000, SPANS)).toBe(
      "1 place of the paper (Methods), 219 characters in all of the most 24,000. The function would be called doubled_sum.",
    );
    const places = [
      { start: 0, end: 10, section: "Methods", page: 2, chars: 10 },
      { start: 20, end: 30, section: null, page: null, chars: 10 },
      { start: 40, end: 50, section: "Methods", page: 3, chars: 10 },
      { start: 60, end: 70, section: "Results", page: 4, chars: 10 },
    ];
    expect(describeOffer(offerOf({ places, chars: 12345, goal: "Sum them" }), 24000, SPANS)).toBe(
      "4 places of the paper (Methods, Results), 12,345 characters in all of the most 24,000, with what you want of it, as your words. The function would be called doubled_sum.",
    );
    expect(describeOffer(offerOf({ sections: [], places: [] }), 24000, SPANS)).toContain("no place of the paper, 219 characters");
    expect(describeOffer(offerOf({ sections: [], places: [{ start: 0, end: 1, section: null, page: null, chars: 1 }] }), 24000, SPANS)).toContain(
      "1 place of the paper, 219",
    );
  });

  it("names every section that was chosen, as sections that touch one another are one place that has only the first of their headings", () => {
    const merged = offerOf({ sections: [2, 1], places: [{ start: 65, end: 289, section: "Methods", page: null, chars: 224 }] });

    expect(describeOffer(merged, 24000, SPANS)).toContain("1 place of the paper (Methods, Results), 219 characters");
    expect(describeOffer(offerOf({ sections: [9], places: [] }), 24000, SPANS)).toContain("no place of the paper, 219");
    // The headings of the places that a search found come after those of the sections
    const found = offerOf({ sections: [1], search: "doubling", places: [{ start: 0, end: 5, section: "Abstract", page: null, chars: 5 }, { start: 65, end: 161, section: "Methods", page: null, chars: 96 }] });
    expect(describeOffer(found, 24000, SPANS)).toContain("2 places of the paper (Methods, Abstract)");
  });
});

describe("how the writing went", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => vi.useRealTimers());

  it("says when, by which model, in how many attempts, what it cost, and how much of it was run", () => {
    expect(describeWriting(keptOf())).toBe(
      "Written 16 min ago by gpt-4o in 1 attempt, which cost <$0.01. It was imported in a container with no network, and nothing else of it was run.",
    );
    expect(describeWriting(keptOf({ attempts: 3, cost: null, function: { status: "unverified", source_sha256: "c", modules: [] } }))).toBe(
      "Written 16 min ago by gpt-4o in 3 attempts. It was read as Python, and was not run.",
    );
  });

  it("says that none was written, and why it ended", () => {
    expect(describeWriting(keptOf({ status: "failed", attempts: 2, cost: 0.25, function: null }))).toBe(
      "No function was written 16 min ago. gpt-4o was asked in 2 attempts, which cost $0.25.",
    );
    expect(describeWriting(keptOf({ status: "stopped", cost: null, function: null }))).toBe("Stopped 16 min ago, before a function was written.");
    expect(describeWriting(keptOf({ finished_at: "not a time" }))).toContain("Written a while ago");
  });

  it("names each status in words, and one that it does not know as it is", () => {
    expect(writingTitle("written")).toBe("Written");
    expect(writingTitle("failed")).toBe("Not written");
    expect(writingTitle("stopped")).toBe("Stopped");
    expect(writingTitle("lost")).toBe("lost");
  });
});

describe("describeTask", () => {
  it("says what the model was given, and nothing else of the paper", () => {
    expect(describeTask(keptOf().task, SPANS)).toBe("It was given 1 place of the paper (Methods), 219 characters in all, and nothing else of it.");
    expect(describeTask({ ...keptOf().task, cut: true, search: "doubling", goal: "Sum them", chars: 24000 }, SPANS)).toBe(
      'It was given 1 place of the paper (Methods), 24,000 characters in all, cut to the most that is given, and nothing else of it. The places found for "doubling" were among them. It was told what you want of it, as your words.',
    );
    expect(describeTask({ ...keptOf().task, sections: [1, 2] }, SPANS)).toContain("1 place of the paper (Methods, Results)");
  });
});

describe("canCheck", () => {
  it("is so only of a function that was written, from the paper there is now, whose file is as it was written", () => {
    expect(canCheck({ ready: true, kept: keptOf() })).toBe(true);
    expect(canCheck({ ready: false, kept: keptOf() })).toBe(false);
    expect(canCheck({ ready: true, kept: null })).toBe(false);
    expect(canCheck({ ready: true, kept: keptOf({ status: "failed" }) })).toBe(false);
    expect(canCheck({ ready: true, kept: keptOf({ current: false }) })).toBe(false);
    expect(canCheck({ ready: true, kept: keptOf({ source: null }) })).toBe(false);
  });
});

describe("what came of checking the function", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => vi.useRealTimers());

  const kept: NonNullable<PaperAgentMatching["kept"]> = {
    started_at: "2026-11-21T05:43:26Z",
    finished_at: "2026-11-21T05:59:30Z",
    status: "done",
    error: null,
    model: "gpt-4o",
    limit: 1,
    cost: 0.25,
    requests: 2,
    minutes: 5,
    ended: "done",
    output: [],
  };

  it("counts the claims of each status, in the order they are told of", () => {
    expect(describeMatchingCounts(counts({ hard_coded: 1, matched: 2, not_found: 1 }))).toBe("2 matched, 1 not found, 1 hard-coded.");
    expect(describeMatchingCounts(counts())).toBe("No claim was tried.");
  });

  it("names each status in words, and one that it does not know as it is", () => {
    expect(matchingTitle("no_inputs")).toBe("No inputs");
    expect(matchingTitle("hard_coded")).toBe("Hard-coded");
    expect(matchingTitle("lost")).toBe("lost");
  });

  it("says when it was checked, whether a model was asked and what it cost, and how it ended", () => {
    expect(describeChecking(kept)).toBe("Checked just now. gpt-4o was asked for inputs 2 times, which cost $0.25.");
    expect(describeChecking({ ...kept, requests: 1, cost: null })).toBe("Checked just now. gpt-4o was asked for inputs 1 time.");
    expect(describeChecking({ ...kept, model: null, requests: 0, cost: null })).toBe("Checked just now. No model was asked for inputs.");
    expect(describeChecking({ ...kept, model: "gpt-4o", requests: 0 })).toBe("Checked just now. No model was asked for inputs.");
    expect(describeChecking({ ...kept, status: "stopped" })).toContain("It was stopped before it came to its end.");
    expect(describeChecking({ ...kept, status: "failed", error: "Docker went away." })).toContain("It failed: Docker went away.");
    expect(describeChecking({ ...kept, status: "failed" })).toContain("It failed: no reason was given");
  });
});

describe("describeEntry", () => {
  it("says what the inputs were and whose, where the model read them, and what was found", () => {
    expect(describeEntry(entryOf())).toEqual([
      'Called with the inputs that the model read in the passage: {"numbers":[0.2,0.25,0.015]}.',
      'The model said that the passage gives them in: "the numbers 0.2, 0.25 and 0.015".',
      "It gave 0.93, and 0.93 at result rounds to the paper's 0.930.",
    ]);
    expect(describeEntry(entryOf({ by: "person", where: "ignored" }))[0]).toBe('Called with the inputs that you gave: {"numbers":[0.2,0.25,0.015]}.');
    expect(describeEntry(entryOf({ by: "person", where: "ignored" }))).toHaveLength(2);
    expect(describeEntry(entryOf({ where: null }))).toHaveLength(2);
  });

  it("says why there were no inputs, and what the code has in it that rounds to the number", () => {
    expect(describeEntry(entryOf({ arguments: null, note: "The passage gives no inputs.", status: "no_inputs", found: null, gave: null }))).toEqual([
      "The passage gives no inputs.",
    ]);
    expect(describeEntry(entryOf({ status: "hard_coded", hard_coded: ["0.93", "0.930"], found: null, gave: null }))[2]).toBe(
      "The code has 0.93, 0.930 in it, which rounds to the paper's number, so finding the number in what it gave would show nothing.",
    );
  });

  it("says what it gave when it did not match, and what it raised", () => {
    expect(describeEntry(entryOf({ status: "ambiguous", places: 3, found: null })).at(-1)).toBe("It gave 0.93, which has the number in 3 places.");
    expect(describeEntry(entryOf({ status: "ambiguous", places: 2, found: null, gave: null })).at(-1)).toBe("It gave a value, which has the number in 2 places.");
    expect(describeEntry(entryOf({ status: "not_found", found: null, gave: "1.5" })).at(-1)).toBe("It gave 1.5.");
    expect(describeEntry(entryOf({ status: "matched", found: null, gave: "0.93" })).at(-1)).toBe("It gave 0.93.");
    // Where the number was found is said only of a match
    expect(describeEntry(entryOf({ status: "unstable", gave: "0.93" })).at(-1)).toBe("It gave 0.93.");
    expect(describeEntry(entryOf({ status: "matched", gave: null })).at(-1)).toBe("It gave a value, and 0.93 at result rounds to the paper's 0.930.");
    expect(describeEntry(entryOf({ status: "error", found: null, gave: null, error: "ValueError: no numbers." })).at(-1)).toBe("It raised ValueError: no numbers.");
  });
});

describe("the inputs that the person gives", () => {
  it("says the function's parameters, which are what inputs are given for", () => {
    expect(describeParameters([NUMBERS, TIMES])).toBe("Its parameters: numbers (list[float], must be given); times (int, 2 if not given).");
    expect(describeParameters([{ ...TIMES, default: null }])).toBe("Its parameters: times (int, has a default if not given).");
    expect(describeParameters([])).toBe("It takes no parameters.");
  });

  it("begins as the person's, or else the model's, or else each parameter that must be given", () => {
    const given = { claim: "claim-1", arguments: { numbers: [1] }, given_at: "2026-11-21T05:43:26Z" };

    expect(inputsText(claimOf({ inputs: given, entry: entryOf() }), [NUMBERS])).toBe(JSON.stringify({ numbers: [1] }, null, 2));
    expect(inputsText(claimOf({ entry: entryOf() }), [NUMBERS])).toBe(JSON.stringify({ numbers: [0.2, 0.25, 0.015] }, null, 2));
    expect(inputsText(claimOf({ entry: entryOf({ arguments: null }) }), [NUMBERS, TIMES])).toBe(JSON.stringify({ numbers: null }, null, 2));
    expect(inputsText(claimOf(), [TIMES])).toBe("{}");
  });

  it("are read as a JSON object, by the names of the parameters, with those that have no default given", () => {
    expect(checkInputs(' {"numbers": [1, 2]} ', [NUMBERS, TIMES], 4000)).toEqual({ value: { numbers: [1, 2] } });
    expect(checkInputs("{}", [TIMES], 4000)).toEqual({ value: {} });
    expect(checkInputs("  ", [NUMBERS], 4000).problem).toContain("Give the inputs as JSON");
    expect(checkInputs("{numbers}", [NUMBERS], 4000).problem).toBe("This is not JSON. Give the inputs as an object, by the names of the parameters.");
    for (const text of ["[1, 2]", "null", "2"]) {
      expect(checkInputs(text, [NUMBERS], 4000).problem).toBe("The inputs are a JSON object, by the names of the parameters.");
    }
    expect(checkInputs('{"numbers": [1], "count": 2, "size": 3}', [NUMBERS], 4000).problem).toBe("The function has no parameter named count, size.");
    expect(checkInputs('{"times": 3}', [NUMBERS, TIMES], 4000).problem).toBe("Give numbers, which has no default.");
    expect(checkInputs("{}", [NUMBERS, { ...NUMBERS, name: "weights" }], 4000).problem).toBe("Give numbers, weights, which have no default.");
  });

  it("are held to the most characters that a call may be given", () => {
    const text = JSON.stringify({ numbers: "a".repeat(20) });

    expect(checkInputs(text, [NUMBERS], text.length - 1).problem).toBe(`The inputs are at most ${text.length - 1} characters.`);
    expect(checkInputs(text, [NUMBERS], text.length).problem).toBeUndefined();
  });
});

describe("checkMatching", () => {
  const checks = { limits: CHECK_LIMITS, claims: [claimOf()] };

  it("begins with a model asked, no limit said, and the server's minutes", () => {
    expect(emptyMatching(checks)).toEqual({ ask: true, budget: "", minutes: "5" });
  });

  it("wants the most a model may spend when one is asked, and not otherwise", () => {
    expect(checkMatching({ ask: true, budget: "0.5", minutes: "5" }, checks)).toEqual({ value: { ask: true, max_cost: 0.5, minutes: 5 }, problems: {} });
    expect(checkMatching({ ask: true, budget: "", minutes: "5" }, checks).problems.budget).toBe("Say the most it may spend.");
    const given = { claim: "claim-1", arguments: { numbers: [1] }, given_at: "2026-11-21T05:43:26Z" };
    expect(checkMatching({ ask: false, budget: "", minutes: "5" }, { ...checks, claims: [claimOf(), claimOf({ id: "claim-2", inputs: given })] })).toEqual({
      value: { ask: false, minutes: 5 },
      problems: {},
    });
  });

  it("wants inputs of a claim when no model is asked, as the function has nothing to be called with otherwise", () => {
    expect(checkMatching({ ask: false, budget: "", minutes: "5" }, checks).problems.ask).toContain("Give the inputs of a claim first");
  });

  it("holds the minutes to the server's limits", () => {
    expect(checkMatching({ ask: true, budget: "1", minutes: "0" }, checks).problems.minutes).toBe("The most minutes the calls may take is a whole number from 1 to 30.");
    expect(checkMatching({ ask: true, budget: "1", minutes: "31" }, checks).value).toBeNull();
    expect(checkMatching({ ask: true, budget: "1", minutes: "30" }, checks).value?.minutes).toBe(30);
    expect(checkMatching({ ask: true, budget: "1", minutes: "1" }, checks).value?.minutes).toBe(1);
  });
});
