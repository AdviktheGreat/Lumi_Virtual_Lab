---
name: variant-call-statistics
description: "Use when computing Ts/Tv, SNP and indel counts, or heterozygosity from VCF files: what in the caller, filters, variant types, and regions changes them, and how to check the VCF is the call set the question means."
license: MIT
metadata:
  author: virtual_lab contributors
  version: "1.0"
  source: "Written for virtual_lab from the documentation of bcftools, GATK, and general practice."
---

# Variant Call Summary Statistics and Their Dependence on Caller and Filters

## Overview

Summary numbers from a VCF depend on the caller that made it, the filters applied, and what was counted. The same sequencing reads can give a different Ts/Tv or SNP count with another caller or a different quality cut-off. Count exactly what the question asks, and say which call set you used.

## Definitions

- Transitions are the changes A to G and C to T (and the reverse). The other eight single-base changes are transversions. Ts/Tv is the number of transitions over the number of transversions, counted over SNPs only.
- Leave out indels, multi-nucleotide variants, and symbolic alleles. Decide how to treat multi-allelic sites, and say what you did.
- `bcftools stats file.vcf` reports the SNP and indel counts and Ts/Tv. Compare your own counting code with it on the same file.
- The expected value depends on the organism, the region (coding or genome-wide), and the caller. Calls dominated by errors drift toward 0.5, which is the value for random substitutions. Compare with what is expected for the organism and the kind of data rather than a rule of thumb from another species.

## What changes the number

- The caller and its version (GATK HaplotypeCaller, bcftools, FreeBayes, DeepVariant), single-sample or joint calling, and the ploidy setting.
- The filters: all records or only `FILTER=PASS`, thresholds on QUAL, depth, and mapping quality, and hard filters or recalibration.
- The regions: whole genome, targets, or named contigs, and whether plasmids or other small contigs are in.
- The reference the reads were aligned to.

When the question names a caller or a filter, use it. When it names none, compute the numbers for the unfiltered records and for the passing records, and lead with the one the question's wording selects.

## Check the supplied call set

- Read the VCF header (`##source`, the command lines, the reference) and look at the FILTER values, the QUAL distribution, and the read depth.
- Compare the SNP count with what the genome size and the divergence from the reference would give. A count far lower than expected may be a filtered or partial call set.
- When alignments (BAM or CRAM) and the reference are supplied beside a VCF, the question may intend for the variants to be called from them. Do a quick standard calling, for example `bcftools mpileup -f ref.fa aln.bam | bcftools call -mv` (with the organism's ploidy), filter on QUAL, and compare the SNP count and Ts/Tv with the supplied VCF. Install bcftools and samtools if they are missing (conda from bioconda), or use the wrappers pysam bundles, such as `pysam.bcftools.call`.
- If the two disagree, report both with the settings used, and say which the question most plausibly means.

## What to report

The file or call set used, the caller if it is known, the filters, the variant types counted, the SNP, transition, and transversion counts, and the ratio.
