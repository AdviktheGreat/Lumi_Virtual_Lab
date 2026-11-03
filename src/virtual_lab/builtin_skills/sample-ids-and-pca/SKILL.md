---
name: sample-ids-and-pca
description: "Use before PCA, clustering, or differential expression on an expression matrix: duplicated or silently renamed sample ids, matching columns to metadata, replicates, orientation, transformation, scaling, variance explained."
license: MIT
metadata:
  author: virtual_lab contributors
  version: "1.0"
  source: "Written for virtual_lab from the documentation of scikit-learn, R's prcomp, pandas, and general practice."
---

# Sample Identity Checks and PCA on Expression Matrices

## Overview

A principal component analysis is only as good as the table that goes into it. The number it gives for variance explained moves with replicate handling, the transformation, and the genes kept. Look at the input first, make the decisions on purpose, and state them.

## Check sample identity before any statistics

- Read the raw header line of the file as text (`head -1`, or the `csv` module) and look for repeated sample names. pandas renames repeated column names to `x`, `x.1`, `x.2`, and R's `read.csv` does the same by default, so a duplicate check run after loading passes without finding anything. Compare the names with the trailing `.N` removed, or load the header on its own.
- Reconcile the matrix with the metadata: the number of expression columns, the number of metadata rows, and the number of unique ids in each. List ids found in only one, and look for differences in case, whitespace, prefixes, or an `X` added by R in front of ids that start with a digit.
- A repeated id can be a technical replicate, a re-sequenced library, or an error. Compare the repeated columns (identical columns are copies, close ones are replicates) and check whether the metadata agrees across them. Then decide whether to keep them as separate samples, average them, or drop all but one, and say which you did.
- When the choice could change the answer, run PCA both ways and report how far the number moves.

## PCA conventions

- Samples are the observations and genes the variables: a samples by genes matrix for scikit-learn, `prcomp(t(x))` in R when genes are rows.
- Transform counts first (log2(x+1), or a variance-stabilizing transform) unless the data are already normalised or on a log scale. Check the range of the values to see which they are.
- Center each gene, which both scikit-learn and `prcomp` do by default. Scale genes to unit variance only when asked: `prcomp(scale. = TRUE)` and `scale. = FALSE` give different variance explained.
- Remove genes with zero variance, since they add nothing and break scaling. Other filters (low expression, top variable genes) are choices. If the question names none, do not add one, but check how much the answer moves if you do.
- Percent of variance for a component is its eigenvalue over the sum of all eigenvalues (`explained_variance_ratio_` in scikit-learn, `sdev^2 / sum(sdev^2)` in R). Make sure the denominator is all the variance, not only the components that were kept.
- Report to the precision the question asks for. If the value is within a few tenths of a rounding boundary, say so, and give the range the variants produce.

## What to report

The matrix shape before and after any filtering, the number of unique samples, how repeated ids were handled, the transformation, whether genes were centered or scaled, any gene filter, and the variance explained by each of the first components.
