# Checking What an Analysis Function Computes

---

## Metadata

**Short Description**: Before trusting a number from a library or command-line tool (alignment statistics, phylogenetic or sequence metrics, statistical tests), record its version, read how it treats gaps, missing values, ties, and defaults, and check it against the textbook definition on a small example.

**Authors**: virtual_lab contributors

**Version**: 1.0

**Last Updated**: November 2026

**License**: MIT

**Commercial Use**: ✅ Allowed

**Source**: Written for virtual_lab from the documentation of scipy and R's stats package, and general practice.

---

## Overview

A function with the same name can compute different quantities in different tools, or in different releases of one tool. Gaps or missing values may be counted or dropped, a proportion may be taken over the whole length or the ungapped length, and a default may change between versions. A result that looks extreme, or that disagrees with a published value, is a reason to check the definition before answering.

## Routine

1. Record the version of every package or program that produces a reported number (`importlib.metadata.version('pkg')`, `tool --version`), and put it in the answer.
2. Read the docstring, and the source when needed (`inspect.getsource`), of the function you call. Find how it treats gaps, missing values, ties, and single or constant inputs, what the denominator is, and what the defaults are.
3. Write the quantity again from its textbook or original definition in a few lines, and compare it with the tool's output on the whole data, or on a subset. If they agree, go on. If they do not, find out why before choosing between them.
4. When the cause is a change between versions, read the release notes, and try another release in a fresh environment (`uv venv` and `pip install pkg==X.Y`). Report both values with the versions. Prefer the definition that the question and the method it cites imply.
5. Log what the tool dropped silently: records that were skipped, sequences with no variation, ids that did not match. Report the counts.

## Sequence and alignment statistics

Metrics such as relative composition variability, GC content, the fraction of variable or parsimony-informative sites, and gap fractions differ between tools in two ways: whether gaps and ambiguity codes (`-`, `N`, `X`, `?`) count as characters, and whether proportions are taken over the full alignment length or only the positions that are not gaps. Check which a tool does with a toy alignment that has gaps in it, and compare with the definition in the paper that introduced the metric.

## Statistical tests

- Check the alternative (two-sided or one-sided), whether the p-value is exact or approximate, any continuity correction, how ties are handled, and whether the samples are treated as paired. `scipy.stats.mannwhitneyu` and R's `wilcox.test` differ in when they use the exact distribution and in how they apply the continuity correction.
- Report the test, the statistic, the p-value in scientific notation at full precision, the group sizes, and the software versions.
- Very small p-values are sensitive to the definition. A small change in what is counted or how the groups are built can move one by many orders of magnitude, so check the inputs as well as the test.

## What to report

The function and package versions, the definition used, any difference from another definition or version, and the value each gives when they differ.
