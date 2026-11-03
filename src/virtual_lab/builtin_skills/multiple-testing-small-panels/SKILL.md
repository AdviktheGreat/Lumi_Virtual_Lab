---
name: multiple-testing-small-panels
description: "Use when counting significant features after Bonferroni, Holm, BH, or BY correction, above all small counts (0, 1, 2) in qPCR, miRNA, or targeted panels; includes delta Ct basics and how to check a count holds."
license: MIT
metadata:
  author: virtual_lab contributors
  version: "1.0"
  source: "Written for virtual_lab from the documentation of statsmodels and R's p.adjust, the delta-delta Ct method (Livak and Schmittgen, 2001), and general practice."
---

# Multiple-Testing Corrections and Borderline Counts in Small Panels

## Overview

In a panel of a few dozen to a few hundred features, the number that pass a corrected threshold is small, and one borderline feature changes it. The number is trustworthy only when it survives the reasonable ways of doing the analysis. Start with the most direct analysis of the values supplied, then test how much the result depends on the choices.

## Family and method

- The family is the set of tests the question treats together, usually every feature in the panel for one comparison. Count it from the data, state it, and correct each comparison separately unless asked otherwise.
- Bonferroni multiplies each p-value by the number of tests, and controls the family-wise error rate. Holm is a step-down version that is never less powerful. Benjamini-Hochberg (BH) controls the false discovery rate for independent or positively dependent tests. Benjamini-Yekutieli (BY) controls it under any dependence, and is more conservative than BH by about the harmonic sum of 1/i over the tests.
- Use `statsmodels.stats.multitest.multipletests` with `method='bonferroni'`, `'holm'`, `'fdr_bh'`, or `'fdr_by'`, or R's `p.adjust`. Do not write them by hand. Check the call on a few p-values you can do by hand.
- Decide how features without a p-value (not detected, too few values) are treated. Dropping them shrinks the family, and that changes the adjusted values. State what you did.
- Check whether the cut-off is "below" or "at most" alpha when a value sits on it.

## Start direct, then test sensitivity

- Run the standard analysis on the values as supplied, in the form the question describes. Add normalisation or preprocessing steps only when the question or the data require them, and then check whether they change the count.
- The test matters at the margin. Student's and Welch's t-tests differ when group sizes or variances differ (R's `t.test` is Welch's by default, and scipy's `ttest_ind` is Student's unless `equal_var=False`). Paired or unpaired, t-test or rank test, and log or linear scale can each move a feature across the cut-off.
- With a count of 0 to 3, tabulate the count for each plausible variant of test, normalisation, and correction. If they all agree, the number is solid. If they differ, report the value from the most direct reading of the question, and name the others with their values.
- Look at the smallest raw and adjusted p-values and how close they are to the threshold.

## Reconcile with reference numbers

- When a paper, supplementary table, or provided file reports its own counts or p-values, compare yours to them. A large disagreement needs an explanation before you answer: check the column labels (a column called adjusted may be raw, or use another method), the family size, the test, and the normalisation.
- If the reference table is mislabeled or inconsistent, say so, and report your own value with the evidence.

## qPCR and miRNA basics

- A lower Ct means more of the target. Delta Ct = Ct(target) - Ct(reference). Delta-delta Ct = delta Ct(case) - delta Ct(control). Fold change = 2^(-delta-delta Ct), which assumes about 100% amplification efficiency for target and reference (use the Pfaffl method if the efficiencies differ).
- Test on the delta Ct values, which are on a log scale, not on the fold changes.
- The reference (a spike-in, a stable endogenous gene, or the mean of all features) changes the results. Use the one the data or the question names.
- Decide how undetermined or very high Ct values (such as 40) are handled, and say so.

## What to report

The number of tests, the test and its variant, the correction method, the threshold, the count for each variant you tried, and any disagreement with reference numbers.
