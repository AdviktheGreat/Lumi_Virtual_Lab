# Checklist for Questions That Ask for a Number From Data

---

## Metadata

**Short Description**: A checklist for any question that asks for a count, p-value, correlation, percentage, ratio, or other number from supplied data files: restate the question, read the inputs, orient signs and units, take the literal reading, test the open choices, and state what was done.

**Authors**: virtual_lab contributors

**Version**: 1.0

**Last Updated**: November 2026

**License**: MIT

**Commercial Use**: ✅ Allowed

**Source**: Written for virtual_lab from general practice in computational biology.

---

## Overview

Most wrong numbers in a data analysis come from a quiet choice rather than from a mistake in the code: a sign that is the reverse of what was assumed, a table that is not what it seemed, a filter that was added or left out. This list is for planning an analysis and for checking it before the number is given.

## Before the analysis

1. Restate what is asked: the quantity, the unit, the subset, the threshold, and the format of the answer.
2. List each decision the question leaves open (filters, normalisation, how replicates are handled, which test, which background, which caller). Take the reading the wording gives most directly. Do not add steps the question does not ask for, and do not drop the ones it names. If it asks for an adjusted p-value, the answer is built on an adjusted p-value.
3. Read the files before using them: the raw header and the first rows, the shape, the types, the identifiers, missing values, and the units. Read any README, data dictionary, or methods text that comes with them.
4. Check each convention that can flip a result: the sign of a score (is more negative stronger?), the base of a logarithm, the direction of a ratio ("A versus B"), lower Ct meaning more, and which group is the reference.

## During the analysis

5. Print the number of rows or items before and after each filter or join, and keep those counts. Check that joins on identifiers matched what you expected, with no repeated or unmatched ids.
6. Run known positives and negatives through the analysis and check that they land where they should.
7. Compute the answer a second way (another library, or by hand on a subset) and compare.

## Before answering

8. For each open decision, check how far the answer moves when it is made the other way. If the answer is stable, say so. If it flips or changes, give the value for the most direct reading, and name the other readings with their values.
9. Compare with any reference numbers in the materials (a table in a paper, a provided summary). Resolve a disagreement or say plainly that it is unresolved.
10. State the choices you made, in a sentence or two, and give the answer in the format asked.
