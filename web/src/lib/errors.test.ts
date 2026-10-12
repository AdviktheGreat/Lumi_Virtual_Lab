import { describe, expect, it } from "vitest";
import { ApiError, NetworkError } from "./api";
import { describeError, plainProblem, problemOf } from "./errors";

describe("what is told of an error", () => {
  it("is the message of the server's, of the network's, or of any other error, and plain words for anything else", () => {
    expect(describeError(new ApiError(422, "invalid", "That model is not known."))).toBe("That model is not known.");
    expect(describeError(new NetworkError(new Error("offline")))).toBe(new NetworkError(new Error("offline")).message);
    expect(describeError(new Error("Broken."))).toBe("Broken.");
    expect(describeError("nope")).toBe("Something went wrong.");
  });
});

describe("a problem", () => {
  it("is plain when it is told in words, with nowhere to put it right", () => {
    expect(plainProblem("Choose a model.")).toEqual({ text: "Choose a model.", fix: null });
  });

  it("is put right with the keys when the server says keys are missing", () => {
    const error = new ApiError(409, "missing_keys", "Set OPENAI_API_KEY first.", { missing: ["OPENAI_API_KEY"] });

    expect(problemOf(error)).toEqual({ text: "Set OPENAI_API_KEY first.", fix: "keys" });
  });

  it("is put right with the setup when code in Docker has no Docker or no image to run in", () => {
    const error = new ApiError(409, "setup_needed", "Docker is not running.", { missing: ["docker"] });

    expect(problemOf(error)).toEqual({ text: "Docker is not running.", fix: "setup" });
  });

  it("has nowhere to be put right for any other error, whatever it is", () => {
    expect(problemOf(new ApiError(422, "invalid", "That is not allowed."))).toEqual({ text: "That is not allowed.", fix: null });
    expect(problemOf(new NetworkError(new Error("offline"))).fix).toBeNull();
    expect(problemOf(new Error("missing_keys"))).toEqual({ text: "missing_keys", fix: null });
    expect(problemOf("nope")).toEqual({ text: "Something went wrong.", fix: null });
    // A word that is on every object is not a code that has a fix
    expect(problemOf(new ApiError(500, "constructor", "Odd.")).fix).toBeNull();
    expect(problemOf(new ApiError(500, "toString", "Odd.")).fix).toBeNull();
  });
});
