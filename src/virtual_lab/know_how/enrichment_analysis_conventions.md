# Over-Representation and Pathway Enrichment Analysis Conventions

---

## Metadata

**Short Description**: Conventions and checks for pathway and gene set enrichment (over-representation) analysis with KEGG, GO, and Reactome using clusterProfiler, gseapy, g:Profiler, or Enrichr: matching gene identifiers and organism, the background, pooling or splitting up and down genes, significance thresholds, sensitivity, and what to report.

**Authors**: virtual_lab contributors

**Version**: 1.0

**Last Updated**: November 2026

**License**: MIT

**Commercial Use**: ✅ Allowed

**Source**: Written for virtual_lab from the documentation of clusterProfiler, KEGG, and gseapy, and general practice.

---

## Overview

An enrichment result depends on choices that rarely appear in the final number: the identifiers, the organism, the background, which genes were in the list, and the significance rule. Most wrong answers come from one of these being silently different from what the question means. Make each choice on purpose, check it, and say what it was.

## Match identifiers and organism first

- Use the identifier type the database expects: KEGG takes the organism's own locus tags or NCBI gene ids, while GO and Reactome tools usually take Entrez, Ensembl, UniProt, or gene symbols.
- Bacterial locus tags belong to one strain, and KEGG has a separate organism code (three or four letters) for each strain. Work out the strain from the data (locus tag prefix, genome assembly, the paper's methods), then find its code in KEGG's list (`https://rest.kegg.jp/list/organism`, or `clusterProfiler::search_kegg_organism`). Do not use the code of the best-known strain of the species, because its tags will not match.
- Always count how many input genes mapped to the database. A small mapped fraction means the wrong organism or identifier type. Fix it before testing, and look at a sample of the unmapped ids.
- Convert identifiers with the organism's own annotation (an OrgDb package, biomaRt, UniProt ID mapping, or the genome's GFF), not by matching symbols by eye.

## Gene lists and background

- Use the genes the question describes. Pooled and split lists are both common: pool up and down regulated genes when the question speaks of "differentially expressed genes" without a direction, and run the directions separately when it names one or the comparison between them is the point. Say which you did.
- When the wording does not settle it, run both and lead with the reading it selects.
- The default background is every gene of the organism that has an annotation in the database, which is what clusterProfiler does. Use a custom background (the genes that were tested or detected) when the question or the data call for it. Check whether the choice changes the count and report it if it does.
- Leave the default minimum and maximum gene set sizes unless asked, and note them.

## Significance rules

- Apply the rule the question states. "Adjusted p-value" means the p-value corrected across all the terms tested, by the method the tool applies (Benjamini-Hochberg unless told otherwise). A raw p-value is not an adjusted one, and the reverse.
- When several gene lists are compared, use the same rule, background, and parameters for every one, then compare the sets.
- Make a small table of how many terms pass under the readings that are plausible: raw p-value and adjusted p-value, pooled and split lists, with and without the minimum gene set size. If the number moves, say which reading the question's wording selects and what the others give.
- An empty result, or no overlap between sets, is surprising for a sizeable gene list. Before answering, check the identifier mapping, the organism code, the thresholds, and the set size limits.

## What to report

The tool and its version, the organism code, the identifier type and mapped fraction, the background, how directions were handled, the threshold and the correction method, the number of terms that pass, and the names of the terms.
