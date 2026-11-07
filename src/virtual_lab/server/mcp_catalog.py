"""A short list of other people's MCP servers that a person may add to the lab with one click.

Each is run by the group it is named for, on the web, and gives the lead tools to look things up in a public database
or in documentation. They were reached when this list was made, and need no key: one that asks for a person's account
is signed in to in the browser, as a preset of the library's is. What the lead asks of one is sent to that group's
server, which the page says. Anything else is added by describing it, as a server of a person's own is.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

# What the servers are for, which is how the page groups them, in the order it lists the groups
GROUPS = ("Biology", "Software and models")


@dataclass(frozen=True)
class CatalogServer:
    """One server of the catalog.

    :param name: What its tools' names start with, and what it is kept under once it is added.
    :param title: What to call it.
    :param about: What it is for, in a sentence, without its title.
    :param group: What it is for, as one of GROUPS says.
    :param maker: Who runs it.
    :param site: Where to read more of it.
    :param entry: How to reach it, as a config gives it.
    """

    name: str
    title: str
    about: str
    group: str
    maker: str
    site: str
    entry: Mapping[str, Any] = field(repr=False)

    @property
    def signs_in(self) -> bool:
        return self.entry.get("auth") == "oauth"


def server(name: str, title: str, about: str, group: str, maker: str, site: str, **entry: Any) -> CatalogServer:
    return CatalogServer(name, title, about, group, maker, site, entry)


SERVERS: tuple[CatalogServer, ...] = (
    server(
        "open_targets",
        "Open Targets",
        "Which genes and proteins are linked to which diseases, with the evidence, drugs, and genetics behind it",
        "Biology",
        "Open Targets",
        "https://platform.opentargets.org",
        url="https://mcp.platform.opentargets.org/mcp",
    ),
    server(
        "string_db",
        "STRING",
        "Networks of the proteins that interact, and what a set of genes or proteins has in common",
        "Biology",
        "STRING Consortium",
        "https://string-db.org",
        url="https://mcp.string-db.org/",
    ),
    server(
        "gwas_catalog",
        "GWAS Catalog",
        "The variants that genome-wide association studies have linked to a trait, with their statistics",
        "Biology",
        "EMBL-EBI",
        "https://www.ebi.ac.uk/gwas",
        url="https://www.ebi.ac.uk/gwas/mcp",
    ),
    server(
        "interpro",
        "InterPro",
        "Protein families, domains, and sites, and the domains in a sequence that is given to it",
        "Biology",
        "EMBL-EBI",
        "https://www.ebi.ac.uk/interpro",
        url="https://www.ebi.ac.uk/interpro/mcp",
    ),
    server(
        "ols",
        "Ontology Lookup Service",
        "The terms of biomedical ontologies, such as GO, EFO, and HPO, and what each is related to",
        "Biology",
        "EMBL-EBI",
        "https://www.ebi.ac.uk/ols4",
        url="https://www.ebi.ac.uk/ols4/api/mcp",
    ),
    server(
        "expasy",
        "Expasy",
        "Proteins, genes, and reactions, from the databases of the SIB, among them UniProt, Bgee, and Rhea",
        "Biology",
        "SIB Swiss Institute of Bioinformatics",
        "https://www.expasy.org",
        url="https://chat.expasy.org/mcp",
    ),
    server(
        "biocontext",
        "BioContextAI knowledgebase",
        "Many databases in one, among them UniProt, Reactome, AlphaFold, KEGG, and Europe PMC. It gives a great "
        "many tools, which adds to what each message costs",
        "Biology",
        "BioContextAI, a community",
        "https://biocontext.ai",
        url="https://biocontext-kb.fastmcp.app/mcp",
    ),
    server(
        "synapse",
        "Synapse",
        "The research data that groups share on Sage Bionetworks' platform, which a Synapse account is signed in to",
        "Biology",
        "Sage Bionetworks",
        "https://www.synapse.org",
        url="https://mcp.synapse.org/mcp",
        auth="oauth",
        # Its tools were not read, since they are given only to a person who has signed in, and it can change
        # what is kept there, so every call waits for approval
        approval={"ask": ["*"]},
    ),
    server(
        "huggingface",
        "Hugging Face",
        "Search the models, datasets, and papers of the Hugging Face Hub",
        "Software and models",
        "Hugging Face",
        "https://huggingface.co/mcp",
        url="https://huggingface.co/mcp",
    ),
    server(
        "deepwiki",
        "DeepWiki",
        "Read, and ask about, the documentation of a public GitHub repository, such as a bioinformatics tool's",
        "Software and models",
        "Cognition",
        "https://deepwiki.com",
        url="https://mcp.deepwiki.com/mcp",
    ),
    server(
        "context7",
        "Context7",
        "Up-to-date documentation and examples for software libraries",
        "Software and models",
        "Upstash",
        "https://context7.com",
        url="https://mcp.context7.com/mcp",
    ),
)

MCP_CATALOG: MappingProxyType[str, CatalogServer] = MappingProxyType({found.name: found for found in SERVERS})


def describe_catalog(stored: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The catalog as the Tools page shows it, in the order it was written.

    :param stored: The servers that are set up, by name, to say which of these are.
    :return: For each, what it is, who runs it, where it is reached, whether it is signed in to or asks before a call,
        and whether it is set up already.
    """
    return [
        {
            "name": found.name,
            "title": found.title,
            "about": found.about,
            "group": found.group,
            "maker": found.maker,
            "site": found.site,
            "target": found.entry["url"],
            "signs_in": found.signs_in,
            "asks": bool(found.entry.get("approval")),
            "added": found.name in stored,
        }
        for found in MCP_CATALOG.values()
    ]
