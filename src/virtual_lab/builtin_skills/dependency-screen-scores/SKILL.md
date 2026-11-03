---
name: dependency-screen-scores
description: "Use when reading DepMap-style CRISPR or RNAi dependency scores (gene effect, Chronos, CERES, dependency probability): orient the sign before calling genes essential, and correlate scores with expression or other features."
license: MIT
metadata:
  author: virtual_lab contributors
  version: "1.0"
  source: "Written for virtual_lab from the published descriptions of DepMap's gene effect scores (Chronos, CERES) and general practice."
---

# Reading Gene Dependency Scores From CRISPR and RNAi Screens

## Overview

Dependency screens knock out or knock down each gene in many cell lines and score how much the cells' fitness changes. The scores run in a direction that is easy to get backwards: a stronger dependency is a more negative number. Any ranking, correlation, or count of "essential" genes is inverted if that is not handled on purpose.

## Sign convention

- Gene effect scores (Chronos, CERES, and similar) are scaled so that 0 is no effect on growth and -1 is the typical value for genes known to be essential in every line. Below -0.5 is commonly read as a dependency.
- A positive score means the cells grew faster after the gene was lost, as for many tumour suppressors and growth restraints.
- Dependency probabilities run from 0 to 1, and higher means more likely to be a dependency. They run the other way from gene effect.
- RNAi scores (for example DEMETER2) are also negative for dependencies.
- Read the data's own description of its columns and scale. Do not assume one orientation from the name of the file.

## Orient before analysing

- Decide what the question means by "essentiality", "dependency", or "sensitivity". The usual meaning is that a larger value is a stronger dependency. With gene effect scores that means defining `essentiality = -gene_effect`, then ranking, correlating, and thresholding on that.
- A correlation of expression with raw gene effect has the opposite sign to the correlation of expression with essentiality. "Positively correlated with essentiality" is a negative correlation with gene effect.
- Do not mix the two orientations when counting positive and negative correlations, choosing the top genes, or applying a threshold.
- Write the orientation in the code as a comment and in the answer ("essentiality = -gene effect, higher is a stronger dependency").

## Controls

Before trusting a result, check known genes in the data you are using:

- Core fitness genes (ribosomal proteins, proteasome subunits, RNA polymerase and spliceosome components) should have a clearly negative median gene effect.
- Genes that are not expressed, and non-essential genes, should be near 0.
- Growth restraints such as TP53 in TP53 wild-type lines, PTEN, or NF2 can be positive in the lines where they matter.
- If the list of "most essential" genes is full of tumour suppressors, or the ribosomal genes land at the wrong end, the sign is inverted.
- If one tail of a correlation has no genes and the other has many, suspect the sign or a mismatch of the two files before believing it.

## Correlating scores with expression or other features

- Match cell lines by the identifier both files share (ModelID or ACH- ids), not by row position or by name. Report how many lines matched, and how many were in only one file.
- Use the same release for both files where you can, and say which release it is.
- Gene effect and expression are skewed. Use the correlation the question names, and say which. If it names none, report the one you used, and give the other too if the two lead to different counts or rankings.
- Look at both tails: genes whose expression goes with stronger dependency, and genes where it goes with weaker dependency. Count each on the oriented values, with the threshold applied to the signed value, not to its absolute value, unless the question says absolute.
- Restrict to a lineage, mutation group, or subtype only when asked. Report the number of lines in the subset.
- When asked about significance across many genes, correct for multiple testing as the question says. A correlation threshold and a significance threshold are different rules, so apply the ones given.

## What to report

The score type and release, the orientation, the correlation method, the number of cell lines, any filters, the thresholds, and the control genes you checked.
