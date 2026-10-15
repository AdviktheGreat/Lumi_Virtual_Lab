import { BookOpen, Dna, Download, FileSpreadsheet, FlaskConical, FolderOpen, MessageSquareText, Search, Terminal, Users, Wrench } from "lucide-react";

// What marks a call to the tool of this name
export function CallIcon({ name, className }: { name: string; className?: string }) {
  switch (name) {
    case "run_code":
      return <Terminal className={className} aria-hidden />;
    case "find_resources":
      return <Search className={className} aria-hidden />;
    case "convene_team":
      return <Users className={className} aria-hidden />;
    case "consult":
      return <MessageSquareText className={className} aria-hidden />;
    case "pubmed_search":
    case "europepmc_search":
    case "europepmc_lookup":
    case "europepmc_fulltext":
    case "arxiv_search":
      return <BookOpen className={className} aria-hidden />;
    case "uniprot_search":
    case "uniprot_lookup":
    case "pdb_lookup":
    case "alphafold_lookup":
      return <Dna className={className} aria-hidden />;
    case "fetch_structure_file":
      return <Download className={className} aria-hidden />;
    case "pubchem_lookup":
    case "chembl_search":
    case "chembl_lookup":
    case "chembl_target_search":
    case "chembl_activities":
      return <FlaskConical className={className} aria-hidden />;
    case "data_files":
      return <FolderOpen className={className} aria-hidden />;
    case "inspect_data_file":
      return <FileSpreadsheet className={className} aria-hidden />;
    default:
      return <Wrench className={className} aria-hidden />;
  }
}
