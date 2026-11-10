"""Tests of finding where the data of a paper is, which is the part that asks nothing of any host: how what a paper or
its code says is read as a place, which places are fetched from and which are only shown, and what a person's choice
of files has to be before anything is fetched."""

from typing import Any

import pytest

from virtual_lab.paperagents import data
from virtual_lab.paperagents.data import (
    DataError,
    DataFile,
    Listing,
    Reference,
    Unsupported,
    choose,
    find,
    folder_of,
    host_matches,
    parse_reference,
    references_in,
    safe_path,
    url_reference,
)


def fact(prefix: str, number: int, quote: str, **fields: str) -> dict[str, Any]:
    return {
        "id": f"{prefix}-{number:08x}",
        "quote": quote,
        **fields,
        "anchor": {"start": number * 100, "end": number * 100 + 10},
    }


class TestWhereAnAddressIs:
    @pytest.mark.parametrize(
        ("text", "key"),
        [
            ("https://zenodo.org/records/1234567", "zenodo:1234567"),
            ("https://zenodo.org/record/1234567/files/x.csv", "zenodo:1234567"),
            ("https://www.zenodo.org/records/1234567?token=x", "zenodo:1234567"),
            ("https://doi.org/10.5281/zenodo.7654321", "zenodo:7654321"),
            ("doi:10.5281/zenodo.7654321", "zenodo:7654321"),
            ("10.5281/zenodo.7654321", "zenodo:7654321"),
            ("https://figshare.com/articles/dataset/Cell_data/12345678", "figshare:12345678"),
            ("https://figshare.com/articles/dataset/Cell_data/12345678/2", "figshare:12345678"),
            ("https://doi.org/10.6084/m9.figshare.12345678.v3", "figshare:12345678"),
            ("https://datadryad.org/stash/dataset/doi:10.5061/dryad.abc123xyz", "dryad:10.5061/dryad.abc123xyz"),
            ("https://datadryad.org/dataset/doi%3A10.5061%2Fdryad.abc123xyz", "dryad:10.5061/dryad.abc123xyz"),
            ("https://github.com/example/cellmapper/releases", "github:example/cellmapper"),
            ("https://github.com/example/cellmapper/releases/tag/v1.2", "github:example/cellmapper@v1.2"),
            ("https://github.com/example/cellmapper/releases/download/v1.2/x.zip", "github:example/cellmapper@v1.2"),
            ("https://huggingface.co/datasets/org/name", "huggingface:org/name"),
            ("https://huggingface.co/datasets/org/name/tree/main", "huggingface:org/name"),
            ("https://huggingface.co/datasets/squad/viewer", "huggingface:squad"),
            ("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345", "geo:GSE12345"),
            ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/", "geo:GSE12345"),
            ("https://www.ncbi.nlm.nih.gov/sra/SRR1039508", "ena:SRR1039508"),
            ("https://www.ncbi.nlm.nih.gov/bioproject/PRJNA123456", "ena:PRJNA123456"),
            ("https://www.ebi.ac.uk/ena/browser/view/PRJEB1787", "ena:PRJEB1787"),
            ("gse12345", "geo:GSE12345"),
            ("PRJNA123456", "ena:PRJNA123456"),
            ("SRP012345", "ena:SRP012345"),
            ("zenodo.org/records/42", "zenodo:42"),
        ],
    )
    def test_an_address_a_doi_or_an_accession_is_the_one_place_however_it_is_written(self, text: str, key: str) -> None:
        assert parse_reference(text).key == key

    def test_a_place_says_what_it_is_and_where_to_look_at_it(self) -> None:
        shown = parse_reference("GSE12345").to_dict()

        assert shown == {
            "key": "geo:GSE12345",
            "source": "geo",
            "reference": "GSE12345",
            "label": "GEO series GSE12345",
            "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
        }

    @pytest.mark.parametrize(
        "text",
        [
            "https://osf.io/abcde/",
            "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/ABC",
            "https://example.org/data.csv",
            "https://github.com/orgs/example/people",
            "10.1038/s41586-020-2649-2",
            "E-MTAB-1234",
            "EGAS00001001234",
            "",
            "   ",
            "not a place",
            None,
            12,
        ],
    )
    def test_a_place_that_is_not_fetched_from_is_refused_when_a_person_points_to_it(self, text: Any) -> None:
        with pytest.raises(DataError) as caught:
            parse_reference(text)

        assert caught.value.kind in ("invalid", "unsupported")

    def test_a_refusal_says_where_data_is_fetched_from(self) -> None:
        with pytest.raises(DataError, match="Zenodo.*Figshare.*Dryad.*GitHub.*Hugging Face.*GEO.*ENA"):
            parse_reference("https://osf.io/abcde/")

    def test_a_project_page_is_not_a_release_when_it_was_found_in_a_paper(self) -> None:
        in_paper = url_reference("https://github.com/example/cellmapper", from_paper=True)
        asked_for = url_reference("https://github.com/example/cellmapper")

        assert isinstance(in_paper, Unsupported) and "release" in in_paper.reason
        assert asked_for == Reference("github", "example/cellmapper")

    def test_a_host_that_only_ends_like_one_is_not_that_host(self) -> None:
        assert url_reference("https://zenodo.org.evil.example/records/123") is None
        assert url_reference("https://evilzenodo.org/records/123") is None
        assert host_matches("a.b.hf.co", ["*.hf.co"]) and not host_matches("hf.co", ["*.hf.co"])
        assert not host_matches("evil-hf.co", ["*.hf.co"])


class TestWhatATextNames:
    def test_it_finds_each_place_once_in_the_order_it_is_given(self) -> None:
        text = (
            "Reads are at GSE12345 (https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345), the tables at "
            "https://doi.org/10.5281/zenodo.7654321, and 10.5281/zenodo.7654321. Raw reads: PRJNA123456."
        )

        assert [item.key for item in references_in(text)] == ["geo:GSE12345", "zenodo:7654321", "ena:PRJNA123456"]

    def test_a_dot_after_an_accession_or_a_link_is_not_part_of_it(self) -> None:
        found = references_in("See GSE12345. And https://zenodo.org/records/42.")

        assert [item.key for item in found] == ["zenodo:42", "geo:GSE12345"]

    def test_places_that_are_not_fetched_from_are_still_named(self) -> None:
        found = references_in("Data are at https://osf.io/abcde/ and E-MTAB-1234 and EGAS00001001234.")

        assert [(type(item).__name__, item.key) for item in found] == [
            ("Unsupported", "link:osf.io/abcde/"),
            ("Unsupported", "accession:E-MTAB-1234"),
            ("Unsupported", "accession:EGAS00001001234"),
        ]
        assert "EGA" in found[2].reason and "approves" in found[2].reason  # type: ignore[union-attr]

    def test_it_finds_nothing_in_a_text_with_no_place_in_it(self) -> None:
        assert references_in("The data are available on request. See https://example.org/lab.") == []


class TestThePlacesAPaperAndItsCodePointTo:
    CARD = {
        "datasets": [
            fact("ds", 1, "Reads were deposited at GEO under GSE12345", name="Cell reads", accession="GSE12345"),
            fact("ds", 2, "We also used the Allen atlas", name="Allen atlas", accession=""),
        ]
    }
    RESOURCES = {
        "links": [
            fact(
                "lk",
                3,
                "tables at https://zenodo.org/records/7654321",
                url="https://zenodo.org/records/7654321",
                role="data",
            ),
            fact("lk", 4, "see https://osf.io/abcde/", url="https://osf.io/abcde/", role="data"),
            fact(
                "lk",
                5,
                "code at https://github.com/example/cellmapper",
                url="https://github.com/example/cellmapper",
                role="code",
            ),
            fact("lk", 6, "our lab at https://example.org/lab", url="https://example.org/lab", role="other"),
        ],
        "availability": [
            fact("av", 7, "Raw reads are under PRJNA123456.", kind="data"),
            fact("av", 8, "Code is at https://github.com/example/other", kind="code"),
        ],
    }

    def test_each_place_is_listed_once_with_where_the_paper_says_it(self) -> None:
        found = find(self.CARD, self.RESOURCES, None)

        assert [candidate["key"] for candidate in found["candidates"]] == [
            "geo:GSE12345",
            "zenodo:7654321",
            "ena:PRJNA123456",
            "link:osf.io/abcde/",
        ]
        geo = found["candidates"][0]
        assert geo["supported"] and geo["reason"] is None and not geo["in_code"]
        assert [place["id"] for place in geo["facts"]] == ["ds-00000001"]
        assert geo["facts"][0]["quote"] == "Reads were deposited at GEO under GSE12345"

    def test_a_place_that_is_not_fetched_from_is_listed_and_says_why(self) -> None:
        osf = find(self.CARD, self.RESOURCES, None)["candidates"][-1]

        assert osf["supported"] is False and osf["source"] is None
        assert "not one of the places" in osf["reason"]
        assert osf["url"] == "https://osf.io/abcde/"

    def test_a_link_to_the_code_or_to_something_else_is_not_a_place_for_data(self) -> None:
        keys = [candidate["key"] for candidate in find(self.CARD, self.RESOURCES, None)["candidates"]]

        assert not any("cellmapper" in key or "example.org" in key or "other" in key for key in keys)

    def test_each_dataset_the_paper_names_is_listed_and_points_to_its_place_if_its_accession_does(self) -> None:
        found = find(self.CARD, self.RESOURCES, None)

        assert [(d["key"], d["name"], d["candidate"]) for d in found["datasets"]] == [
            ("ds-00000001", "Cell reads", "geo:GSE12345"),
            ("ds-00000002", "Allen atlas", None),
        ]

    def test_the_code_names_places_too_and_is_said_to_when_the_paper_does_as_well(self) -> None:
        stock = {
            "links": ["https://zenodo.org/records/7654321", "https://osf.io/zzzzz/"],
            "accessions": ["GSE12345", "SRR1039508", "E-MTAB-99"],
        }
        found = find(self.CARD, self.RESOURCES, stock)
        by_key = {candidate["key"]: candidate for candidate in found["candidates"]}

        assert by_key["zenodo:7654321"]["in_code"] and by_key["zenodo:7654321"]["facts"]
        assert by_key["ena:SRR1039508"]["in_code"] and by_key["ena:SRR1039508"]["facts"] == []
        assert by_key["link:osf.io/zzzzz/"]["in_code"]
        assert "accession:E-MTAB-99" in by_key
        keys = [candidate["key"] for candidate in found["candidates"]]
        assert keys.index("ena:SRR1039508") > keys.index("ena:PRJNA123456")
        assert keys.index("link:osf.io/zzzzz/") > keys.index("ena:SRR1039508")

    def test_a_paper_that_has_not_been_read_has_none(self) -> None:
        assert find({}, {}, None) == {"candidates": [], "datasets": []}


class TestNamesAHostGives:
    @pytest.mark.parametrize(
        "name",
        [
            "counts.csv",
            "matrix/GSE1_series_matrix.txt.gz",
            "data v2 (final).tsv",
            "Ünïcode.txt",
            "a/b/c.txt",
            "x+y=z@1.txt",
        ],
    )
    def test_an_ordinary_name_is_kept_as_it_is(self, name: str) -> None:
        assert safe_path(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            ".",
            "..",
            "../x",
            "a/../b",
            "/etc/passwd",
            "a//b",
            ".hidden",
            "a/.git/config",
            "back\\slash",
            "new\nline",
            "tab\tname",
            "NUL\x00name",
            "trailing.",
            "trailing ",
            "-leading",
            "x" * 201,
            "a/" * 9 + "b",
            "x" * 401,
            "semi;colon",
            "dollar$name",
            "q?uery",
            "pipe|name",
            None,
            5,
        ],
    )
    def test_a_name_that_could_go_somewhere_else_or_do_something_is_not(self, name: Any) -> None:
        assert safe_path(name) is None

    def test_the_folder_of_a_place_is_named_from_the_place(self) -> None:
        assert folder_of(Reference("zenodo", "123")) == "zenodo/123"
        assert folder_of(Reference("huggingface", "org/name")) == "huggingface/org_name"
        assert folder_of(Reference("github", "example/cellmapper@v1.2")) == "github/example_cellmapper@v1.2"
        assert folder_of(Reference("dryad", "10.5061/dryad.abc")) == "dryad/10.5061_dryad.abc"
        assert ".." not in folder_of(Reference("github", "../..@../"))


def listing(*files: DataFile) -> Listing:
    return Listing(Reference("zenodo", "123"), "A record", None, list(files), len(files))


def entry(name: str, size: int | None = 100, why: str | None = None) -> DataFile:
    return DataFile(name, size, f"https://zenodo.org/api/records/123/files/{name}/content", why=why)


class TestWhatAChoiceOfFilesHasToBe:
    def test_the_files_that_were_chosen_are_returned_in_the_order_asked_for(self) -> None:
        shown = listing(entry("a.csv", 10), entry("b.csv", 20), entry("c.csv", 30))

        chosen = choose(shown, ["c.csv", "a.csv"], 40, 1000)

        assert [file.name for file in chosen] == ["c.csv", "a.csv"]

    def test_a_file_named_twice_is_taken_once(self) -> None:
        assert len(choose(listing(entry("a.csv", 10)), ["a.csv", "a.csv"], 10, 1000)) == 1

    def test_a_choice_of_nothing_is_not_a_choice(self) -> None:
        with pytest.raises(DataError) as caught:
            choose(listing(entry("a.csv")), [], 0, 1000)

        assert caught.value.kind == "invalid"

    def test_a_file_the_place_does_not_have_is_refused(self) -> None:
        with pytest.raises(DataError, match="no file called 'z.csv'") as caught:
            choose(listing(entry("a.csv")), ["a.csv", "z.csv"], 100, 1000)

        assert caught.value.kind == "invalid"

    def test_a_file_that_cannot_be_fetched_is_refused_with_its_reason(self) -> None:
        with pytest.raises(DataError, match="needs an account") as caught:
            choose(listing(entry("a.csv", why="needs an account")), ["a.csv"], 100, 1000)

        assert caught.value.kind == "refused"

    def test_a_file_that_is_kept_already_is_refused(self) -> None:
        with pytest.raises(DataError, match="kept already") as caught:
            choose(listing(entry("a.csv")), ["a.csv"], 100, 1000, kept={"a.csv"})

        assert caught.value.kind == "kept"

    def test_names_that_differ_only_in_capitals_are_refused_since_a_disk_may_keep_one_of_them(self) -> None:
        with pytest.raises(DataError, match="capital letters"):
            choose(listing(entry("A.csv", 10), entry("a.csv", 10)), ["A.csv", "a.csv"], 20, 1000)

    def test_a_name_that_differs_only_in_capitals_from_one_that_is_kept_is_refused(self) -> None:
        with pytest.raises(DataError, match="differ only in their capital letters"):
            choose(listing(entry("a.csv")), ["a.csv"], 100, 1000, kept={"A.csv"})

    def test_a_file_cannot_have_the_name_of_a_folder_that_another_chosen_file_is_in(self) -> None:
        shown = listing(entry("a", 10), entry("a/b.csv", 10))

        with pytest.raises(DataError, match="cannot be kept together") as caught:
            choose(shown, ["a/b.csv", "a"], 20, 1000)

        assert caught.value.kind == "invalid" and "folder" in str(caught.value)
        assert [file.name for file in choose(shown, ["a/b.csv"], 10, 1000)] == ["a/b.csv"]

    def test_a_file_cannot_be_put_in_a_folder_that_has_the_name_of_a_file_that_is_kept(self) -> None:
        with pytest.raises(DataError, match="folder that has the name of the file a"):
            choose(listing(entry("a/b.csv")), ["a/b.csv"], 100, 1000, kept={"a"})

    def test_a_file_cannot_have_the_name_of_a_folder_that_a_file_that_is_kept_is_in(self) -> None:
        with pytest.raises(DataError, match="name of a folder that a/b.csv is in"):
            choose(listing(entry("a")), ["a"], 100, 1000, kept={"a/b.csv"})

    def test_files_in_different_folders_are_kept_together(self) -> None:
        shown = listing(entry("a/x.csv", 10), entry("b/x.csv", 10), entry("a/y/x.csv", 10), entry("ab.csv", 10))

        chosen = choose(shown, ["a/x.csv", "b/x.csv", "a/y/x.csv", "ab.csv"], 40, 1000, kept={"a/z.csv"})

        assert len(chosen) == 4

    def test_files_that_are_not_the_size_the_person_was_shown_are_not_fetched(self) -> None:
        with pytest.raises(DataError, match="not the 90 that were shown") as caught:
            choose(listing(entry("a.csv", 100)), ["a.csv"], 90, 1000)

        assert caught.value.kind == "changed"

    def test_files_over_the_limit_are_not_fetched_even_if_they_are_what_was_shown(self) -> None:
        with pytest.raises(DataError, match="more than the 50") as caught:
            choose(listing(entry("a.csv", 100)), ["a.csv"], 100, 50)

        assert caught.value.kind == "too_big"

    def test_names_that_are_not_text_are_refused(self) -> None:
        with pytest.raises(DataError):
            choose(listing(entry("a.csv")), [["a.csv"]], 100, 1000)

    def test_too_many_files_at_once_are_refused(self) -> None:
        files = [entry(f"f{number}.csv", 1) for number in range(data.MAX_CHOSEN_FILES + 1)]

        with pytest.raises(DataError, match="At most"):
            choose(listing(*files), [file.name for file in files], len(files), 10_000)
