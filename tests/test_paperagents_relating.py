"""Tests of how papers are found to relate to one another from what was read of each: shared datasets, methods, and
software, code at the same address, a paper whose words name another, and claims that agree or differ. Nothing is
run, so these are on the facts themselves."""

from typing import Any

import pytest

from virtual_lab.paperagents import relating


def fact(number: int, quote: str = "a sentence of the paper", **fields: Any) -> dict[str, Any]:
    return {"id": f"f{number}", "quote": quote, "anchor": {"page": number, "section": "Methods"}, **fields}


def claim(number: int, value: str, quote: str) -> dict[str, Any]:
    return {
        "id": f"c{number}",
        "kind": "number",
        "value": value,
        "quote": quote,
        "anchor": {"page": number, "section": "Results"},
    }


def paper(name: str, title: str | None = None, **more: Any) -> dict[str, Any]:
    return {
        "id": name,
        "title": title or f"Paper {name.upper()}",
        "doi": None,
        "url": None,
        "code": None,
        "commit": None,
        "read": True,
        "facts": {},
        "claims": [],
        "reproduction": None,
        **more,
    }


def of_kind(graph: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [each for each in graph["relations"] if each["kind"] == kind]


class TestWhatNumbersAndWordsAre:
    def test_a_number_is_told_by_its_value_and_not_how_it_is_written(self) -> None:
        assert relating.numbers_of("92.0% and 92 and 1e3 and -4") == {"92", "1000", "-4"}

    def test_words_leave_out_the_little_ones_and_numbers(self) -> None:
        assert relating.words_of("The accuracy of 92 cells") == {"accuracy", "cells"}

    @pytest.mark.parametrize(
        ("number", "telling"),
        [
            ("0.5", True),
            ("92", True),
            ("1e+06", True),
            ("-12", True),
            ("7", False),
            ("1899", True),
            ("1900", False),
            ("2023", False),
            ("2100", False),
            ("2101", True),
        ],
    )
    def test_a_number_in_common_says_two_claims_are_alike_unless_it_is_a_digit_or_a_year(
        self, number: str, telling: bool
    ) -> None:
        assert relating.is_telling(number) is telling

    @pytest.mark.parametrize(
        ("url", "key"),
        [
            ("https://github.com/Owner/Name.git", "github.com/owner/name"),
            ("github.com/owner/name/", "github.com/owner/name"),
            ("https://www.gitlab.com/g/sub/proj", "gitlab.com/g/sub/proj"),
            (None, None),
            ("", None),
        ],
    )
    def test_code_at_the_same_place_has_one_key(self, url: str | None, key: str | None) -> None:
        assert relating.code_key(url) == key

    @pytest.mark.parametrize(
        ("quote", "how"),
        [
            ("We replicate the analysis of X", "replicates"),
            ("we reproduced the figures of X", "replicates"),
            ("This replaces X for single cells", "replaces"),
            ("It improves upon X", "replaces"),
            ("It outperforms X", "replaces"),
            ("It builds on X", "builds_on"),
            ("Based on X, we", "builds_on"),
            ("We used X", "mentions"),
            ("a reproducible workflow with X", "mentions"),
            ("We replicate X and improve upon it", "replicates"),
            ("It builds on X and replaces it", "replaces"),
        ],
    )
    def test_how_a_paper_refers_to_another_is_read_from_the_words_around_the_name(self, quote: str, how: str) -> None:
        assert relating.how_it_refers(quote) == how

    def test_each_two_papers_are_paired_once_by_where_they_are_with_the_earlier_first(self) -> None:
        assert relating.pairs([2, 0, 1]) == [(0, 1), (0, 2), (1, 2)]
        assert relating.pairs([4]) == [] and relating.pairs([]) == []


class TestSharedDatasets:
    def papers(self, first: dict[str, Any], second: dict[str, Any]) -> list[dict[str, Any]]:
        return [paper("a", facts={"datasets": [first]}), paper("b", facts={"datasets": [second]})]

    def test_the_same_accession_is_the_same_dataset_with_the_quotes_it_is_said_in(self) -> None:
        first = fact(1, "Data are at GEO GSE12345", name="Mouse brain atlas", accession="GSE12345")
        second = fact(2, "We used GSE-12345 from GEO", name="Brain cells", accession="gse-12345")

        graph = relating.build(self.papers(first, second))

        (found,) = of_kind(graph, "dataset")
        assert (found["a"], found["b"], found["basis"], found["directed"]) == ("a", "b", "accession", False)
        evidence = found["evidence"][0]
        assert evidence["basis"] == "accession" and evidence["a"]["quote"] == "Data are at GEO GSE12345"
        assert evidence["b"]["page"] == 2 and evidence["b"]["section"] == "Methods"
        assert "GSE12345" in found["summary"] or "Mouse brain atlas" in found["summary"]

    def test_papers_that_share_a_dataset_are_related_wherever_they_are_among_the_others(self) -> None:
        shared = fact(1, name="Tabula Muris", accession="GSE1111")
        papers = [
            paper("a", facts={"datasets": [fact(3, name="Other data", accession="GSE9999")]}),
            paper("b", facts={"datasets": [shared]}),
            paper("c", facts={"datasets": [fact(2, name="Tabula Muris", accession="GSE1111")]}),
            paper("d", facts={"datasets": [fact(4, name="Tabula Muris", accession="GSE1111")]}),
        ]

        found = of_kind(relating.build(papers), "dataset")

        assert [(each["a"], each["b"]) for each in found] == [("b", "c"), ("b", "d"), ("c", "d")]

    def test_the_same_name_with_no_accession_is_the_same_dataset_by_its_name(self) -> None:
        first = fact(1, name="Tabula Muris", accession=None)
        second = fact(2, name="tabula-muris", accession=None)

        (found,) = of_kind(relating.build(self.papers(first, second)), "dataset")

        assert found["basis"] == "name"

    def test_a_pair_of_facts_that_match_by_accession_and_by_name_is_said_once(self) -> None:
        first = fact(1, name="Tabula Muris", accession="GSE1111")
        second = fact(2, name="Tabula Muris", accession="GSE1111")

        (found,) = of_kind(relating.build(self.papers(first, second)), "dataset")

        assert found["basis"] == "accession" and [item["basis"] for item in found["evidence"]] == ["accession"]

    def test_one_relation_of_a_pair_holds_what_matched_by_the_accession_and_what_matched_by_the_name(self) -> None:
        papers = [
            paper(
                "a", facts={"datasets": [fact(1, name="Atlas one", accession="GSE1111"), fact(2, name="Tabula Muris")]}
            ),
            paper(
                "b", facts={"datasets": [fact(3, name="Atlas two", accession="GSE1111"), fact(4, name="Tabula Muris")]}
            ),
        ]

        (found,) = of_kind(relating.build(papers), "dataset")

        assert [(item["basis"], item["a"]["fact"], item["b"]["fact"]) for item in found["evidence"]] == [
            ("accession", "f1", "f3"),
            ("name", "f2", "f4"),
        ]

    def test_the_same_name_with_other_accessions_is_not_the_same_dataset(self) -> None:
        first = fact(1, name="Tabula Muris", accession="GSE1111")
        second = fact(2, name="Tabula Muris", accession="GSE2222")

        assert of_kind(relating.build(self.papers(first, second)), "dataset") == []

    def test_the_same_name_when_only_one_gives_an_accession_is_the_same_dataset(self) -> None:
        first = fact(1, name="Tabula Muris", accession="GSE1111")
        second = fact(2, name="Tabula Muris", accession=None)

        (found,) = of_kind(relating.build(self.papers(first, second)), "dataset")

        assert found["basis"] == "name"

    @pytest.mark.parametrize("name", ["data", "Dataset", "cells", "ab"])
    def test_a_name_of_nothing_in_particular_is_not_a_dataset_in_common(self, name: str) -> None:
        first = fact(1, name=name, accession=None)
        second = fact(2, name=name, accession=None)

        assert of_kind(relating.build(self.papers(first, second)), "dataset") == []

    def test_other_datasets_are_not_in_common(self) -> None:
        first = fact(1, name="Tabula Muris", accession="GSE1")
        second = fact(2, name="Allen Brain", accession="GSE2")

        assert of_kind(relating.build(self.papers(first, second)), "dataset") == []

    def test_no_more_evidence_than_the_most_is_kept_and_a_paper_is_not_set_against_itself(self) -> None:
        many = [fact(number, name=f"Set{number}", accession=f"GSE{number}") for number in range(1, 8)]
        graph = relating.build([paper("a", facts={"datasets": many}), paper("b", facts={"datasets": many})])

        (found,) = of_kind(graph, "dataset")

        assert len(found["evidence"]) == relating.MOST_EVIDENCE
        same = relating.build([paper("a", facts={"datasets": many})])
        assert same["relations"] == []

    def test_three_papers_with_one_dataset_are_three_relations(self) -> None:
        one = fact(1, name="Tabula Muris", accession=None)
        graph = relating.build([paper(name, facts={"datasets": [one]}) for name in "abc"])

        assert [(each["a"], each["b"]) for each in of_kind(graph, "dataset")] == [("a", "b"), ("a", "c"), ("b", "c")]
        assert {item["id"]: item["relations"] for item in graph["papers"]} == {"a": 2, "b": 2, "c": 2}


class TestSharedMethodsAndSoftware:
    def test_a_method_that_both_name_is_shared(self) -> None:
        graph = relating.build(
            [
                paper("a", facts={"methods": [fact(1, name="Louvain clustering")]}),
                paper("b", facts={"methods": [fact(2, name="louvain  clustering")]}),
            ]
        )

        (found,) = of_kind(graph, "method")

        assert found["basis"] == "name" and "Louvain clustering" in found["summary"]

    def test_software_is_shared_with_the_versions_that_each_says(self) -> None:
        graph = relating.build(
            [
                paper("a", facts={"software": [fact(1, name="Scanpy", version="1.8.2")]}),
                paper("b", facts={"software": [fact(2, name="scanpy", version="1.9.1")]}),
                paper("c", facts={"software": [fact(3, name="scanpy", version="1.9.1")]}),
            ]
        )

        found = {(each["a"], each["b"]): each["evidence"][0] for each in of_kind(graph, "software")}

        assert found[("a", "b")]["same_version"] is False and found[("b", "c")]["same_version"] is True
        assert found[("a", "b")]["versions"] == {"a": "1.8.2", "b": "1.9.1"}

    def test_a_version_that_is_not_said_is_not_a_difference(self) -> None:
        graph = relating.build(
            [
                paper("a", facts={"software": [fact(1, name="Scanpy", version="")]}),
                paper("b", facts={"software": [fact(2, name="Scanpy", version="1.9")]}),
            ]
        )

        (found,) = of_kind(graph, "software")

        assert found["evidence"][0]["same_version"] is None and found["evidence"][0]["versions"]["a"] is None

    @pytest.mark.parametrize("name", ["Python", "R", "NumPy", "pandas"])
    def test_software_that_nearly_every_paper_uses_is_not_in_common(self, name: str) -> None:
        graph = relating.build(
            [
                paper("a", facts={"software": [fact(1, name=name, version="1")]}),
                paper("b", facts={"software": [fact(2, name=name, version="1")]}),
            ]
        )

        assert of_kind(graph, "software") == []


class TestTheSameCode:
    def test_code_at_the_same_address_is_shared_and_says_whether_it_is_the_same_commit(self) -> None:
        graph = relating.build(
            [
                paper("a", code="https://github.com/o/tool", commit="1" * 40),
                paper("b", code="https://github.com/O/Tool.git", commit="2" * 40),
                paper("c", code="https://github.com/o/tool", commit="1" * 40),
                paper("d", code="https://github.com/o/other", commit="1" * 40),
            ]
        )

        found = {(each["a"], each["b"]): each["evidence"][0] for each in of_kind(graph, "code")}

        assert sorted(found) == [("a", "b"), ("a", "c"), ("b", "c")]
        assert found[("a", "b")]["same_commit"] is False and found[("a", "c")]["same_commit"] is True
        assert found[("a", "b")]["commits"] == {"a": "1" * 40, "b": "2" * 40}

    def test_a_commit_that_is_not_known_is_not_a_difference(self) -> None:
        graph = relating.build([paper("a", code="https://github.com/o/t"), paper("b", code="https://github.com/o/t")])

        assert of_kind(graph, "code")[0]["evidence"][0]["same_commit"] is None

    def test_papers_with_no_code_have_none_in_common(self) -> None:
        assert of_kind(relating.build([paper("a"), paper("b")]), "code") == []

    def test_papers_with_the_same_code_do_not_name_each_other_by_it(self) -> None:
        link = fact(1, "Code is at https://github.com/o/mapper", url="https://github.com/o/mapper")
        graph = relating.build(
            [
                paper("a", code="https://github.com/o/mapper", facts={"links": [link]}),
                paper("b", code="https://github.com/o/mapper"),
            ]
        )

        assert of_kind(graph, "refers") == [] and len(of_kind(graph, "code")) == 1


class TestAPaperThatNamesAnother:
    def named(self, fact_of_a: dict[str, Any], kind: str = "links", **of_b: Any) -> dict[str, Any]:
        papers = [
            paper("a", facts={kind: [fact_of_a]}),
            paper("b", title="Mapping cell types of the mouse brain", **of_b),
        ]

        return relating.build(papers)

    def test_a_doi_in_a_link_is_the_surest_way(self) -> None:
        link = fact(
            1,
            "The method is described in https://doi.org/10.1000/Mapper.2020",
            url="https://doi.org/10.1000/Mapper.2020",
        )

        (found,) = of_kind(self.named(link, doi="10.1000/mapper.2020"), "refers")

        assert (found["a"], found["b"], found["directed"], found["basis"], found["how"]) == (
            "a",
            "b",
            True,
            "doi",
            "mentions",
        )
        assert found["evidence"][0]["at"]["quote"].startswith("The method is described")

    def test_a_doi_that_is_written_in_capitals_is_found_and_one_that_goes_on_is_not(self) -> None:
        link = fact(1, "It is described in 10.1000/mapper.2020", url="10.1000/mapper.2020")
        longer = fact(1, "It is described in 10.1000/mapper.20201", url="10.1000/mapper.20201")

        found = of_kind(self.named(link, doi="10.1000/Mapper.2020"), "refers")
        other = of_kind(self.named(longer, doi="10.1000/Mapper.2020"), "refers")

        assert [each["basis"] for each in found] == ["doi"] and other == []

    def test_a_paper_does_not_name_itself(self) -> None:
        own = fact(1, "This paper is 10.1000/mapper.2020 and Mapping Cell Types of the Mouse Brain", name="x")
        papers = [paper("a", doi="10.1000/mapper.2020", title="Mapping cell types of the mouse brain")]

        assert relating.build([{**papers[0], "facts": {"links": [own]}}])["relations"] == []

    def test_a_title_is_found_whatever_the_marks_between_its_words(self) -> None:
        said = claim(1, "92%", "Unlike Mapping: Cell Types, of the Mouse-Brain, this paper reports 92%")
        papers = [paper("a", claims=[said]), paper("b", title="Mapping cell types of the mouse brain")]

        (found,) = of_kind(relating.build(papers), "refers")

        assert found["basis"] == "title"

    def test_the_surest_way_is_first_in_the_evidence_and_is_what_the_relation_is_by(self) -> None:
        papers = [
            paper(
                "a",
                facts={
                    "links": [
                        fact(1, "Cell types of the mouse brain were mapped by Mapping Cell Types of the Mouse Brain"),
                        fact(2, "See https://doi.org/10.1000/mapper.2020", url="https://doi.org/10.1000/mapper.2020"),
                    ]
                },
            ),
            paper("b", doi="10.1000/mapper.2020", title="Mapping cell types of the mouse brain"),
        ]

        (found,) = of_kind(relating.build(papers), "refers")

        assert found["basis"] == "doi" and [item["by"] for item in found["evidence"]] == ["doi", "title"]

    def test_the_address_of_the_code_is_found_in_a_link_and_not_in_a_longer_name(self) -> None:
        link = fact(1, "We used the code at https://github.com/o/mapper", url="https://github.com/o/mapper")
        longer = fact(2, "See https://github.com/o/mapper-two", url="https://github.com/o/mapper-two")

        found = of_kind(self.named(link, code="https://github.com/o/mapper"), "refers")
        other = of_kind(self.named(longer, code="https://github.com/o/mapper"), "refers")

        assert [each["basis"] for each in found] == ["code"] and other == []

    def test_the_name_of_the_code_is_found_as_a_word_of_its_own_in_the_software_used(self) -> None:
        used = fact(1, "We ran CellMapper on the data", name="CellMapper", version="2.0")

        (found,) = of_kind(self.named(used, "software", code="https://github.com/o/cellmapper"), "refers")
        in_a_word = fact(1, "We ran CellMapperPlus on the data", name="CellMapperPlus")

        assert found["basis"] == "name" and found["evidence"][0]["at"]["kind"] == "software"
        assert of_kind(self.named(in_a_word, "software", code="https://github.com/o/cellmapper"), "refers") == []

    @pytest.mark.parametrize("name", ["code", "paper", "data"])
    def test_a_name_of_code_that_is_of_nothing_in_particular_is_not_looked_for(self, name: str) -> None:
        used = fact(1, f"We used the {name} of the authors", name=name)

        assert of_kind(self.named(used, "software", code=f"https://github.com/o/{name}"), "refers") == []

    def test_a_short_name_of_code_is_not_looked_for(self) -> None:
        used = fact(1, "We ran tool", name="tool")

        assert of_kind(self.named(used, "software", code="https://github.com/o/tool"), "refers") == []

    def test_the_title_of_the_other_paper_in_a_claim_names_it(self) -> None:
        said = {**claim(1, "92%", "Unlike Mapping Cell Types of the Mouse Brain, this paper reports 92%")}
        papers = [paper("a", claims=[said]), paper("b", title="Mapping cell types of the mouse brain")]

        (found,) = of_kind(relating.build(papers), "refers")

        assert found["basis"] == "title" and found["evidence"][0]["at"]["kind"] == "claims"

    def test_a_short_title_is_not_looked_for(self) -> None:
        said = claim(1, "92%", "Cell atlas gives 92%")
        papers = [paper("a", claims=[said]), paper("b", title="Cell atlas")]

        assert of_kind(relating.build(papers), "refers") == []

    @pytest.mark.parametrize(
        ("quote", "how"),
        [
            ("We replicate the pipeline of CellMapper", "replicates"),
            ("This replaces CellMapper", "replaces"),
            ("Our tool builds on CellMapper", "builds_on"),
            ("We ran CellMapper", "mentions"),
        ],
    )
    def test_how_it_says_it_is_read_from_the_quote(self, quote: str, how: str) -> None:
        used = fact(1, quote, name="CellMapper")

        (found,) = of_kind(self.named(used, "software", code="https://github.com/o/cellmapper"), "refers")

        assert found["how"] == how
        assert found["summary"].startswith("Paper A")

    def test_the_strongest_way_it_says_it_is_what_the_relation_says(self) -> None:
        papers = [
            paper(
                "a",
                facts={
                    "software": [fact(1, "We ran CellMapper", name="CellMapper")],
                    "limitations": [fact(2, "It replaces CellMapper", name="CellMapper")],
                },
            ),
            paper("b", code="https://github.com/o/cellmapper"),
        ]

        (found,) = of_kind(relating.build(papers), "refers")

        assert found["how"] == "replaces" and len(found["evidence"]) == 2

    def test_each_paper_that_names_the_other_makes_a_relation_of_its_own(self) -> None:
        papers = [
            paper(
                "a",
                code="https://github.com/o/alpha-tool",
                facts={"software": [fact(1, "Ran BetaTool", name="BetaTool")]},
            ),
            paper(
                "b",
                code="https://github.com/o/betatool",
                facts={"software": [fact(2, "Ran Alpha-Tool", name="Alpha-Tool")]},
            ),
        ]

        graph = relating.build(papers)

        assert [(each["a"], each["b"]) for each in of_kind(graph, "refers")] == [("a", "b"), ("b", "a")]


class TestClaimsThatAgreeOrDiffer:
    def two(self, first: str, second: str, **more: Any) -> list[dict[str, Any]]:
        return [
            paper("a", claims=[claim(1, *first.split("|"))], **more),
            paper("b", claims=[claim(1, *second.split("|"))]),
        ]

    def test_the_same_words_and_a_number_in_common_agree(self) -> None:
        graph = relating.build(
            self.two(
                "92%|accuracy of mapping cell types in mouse brain was 92%",
                "92%|the mapping of cell types in mouse brain gave accuracy of 92%",
            )
        )

        (found,) = of_kind(graph, "agrees")

        assert (found["basis"], found["corroborated"]) == ("words", False)
        assert found["evidence"][0]["numbers"] == ["92"] and "accuracy" in found["evidence"][0]["words"]
        assert found["evidence"][0]["a"]["page"] == 1 and found["evidence"][0]["a"]["section"] == "Results"
        assert of_kind(graph, "differs") == []

    def test_the_same_words_and_no_number_in_common_differ(self) -> None:
        graph = relating.build(
            self.two(
                "92%|accuracy of mapping cell types in mouse brain was 92%",
                "71%|the mapping of cell types in mouse brain gave accuracy of 71%",
            )
        )

        (found,) = of_kind(graph, "differs")

        assert found["corroborated"] is None and of_kind(graph, "agrees") == []

    def test_a_number_in_common_that_is_a_digit_or_a_year_is_neither(self) -> None:
        graph = relating.build(
            self.two(
                "5|accuracy of mapping cell types in mouse brain was measured in 5 samples in 2021",
                "9|mapping cell types in mouse brain accuracy was measured in 5 donors in 2021",
            )
        )

        assert of_kind(graph, "agrees") == [] and of_kind(graph, "differs") == []

    def test_claims_with_other_words_are_not_set_against_each_other(self) -> None:
        graph = relating.build(
            self.two("92%|accuracy of mapping cell types was 92%", "71%|survival of zebrafish larvae was 71%")
        )

        assert graph["relations"] == []

    def test_claims_that_share_one_word_among_many_are_not_set_against_each_other(self) -> None:
        graph = relating.build(
            self.two(
                "92%|accuracy of the mapping of cell types was measured across many different tissues",
                "71%|accuracy rose when sequencing depth, library preparation, and batches changed",
            )
        )

        assert graph["relations"] == []

    def test_two_words_in_common_among_many_are_not_a_likeness(self) -> None:
        graph = relating.build(
            self.two(
                "1.5|mapping cell types gave 1.5 on alpha beta gamma delta epsilon zeta eta",
                "1.5|mapping cell types gave 1.5 on theta iota kappa lambda mu nu xi",
            )
        )

        assert graph["relations"] == []

    def test_words_that_nearly_every_claim_has_do_not_count_towards_the_words_in_common(self) -> None:
        crowd_a = [claim(number, "1.5", f"alpha beta filler{number}x was 1.5") for number in range(1, 31)]
        crowd_b = [claim(number, "1.5", f"alpha beta other{number}x was 1.5") for number in range(1, 31)]
        target_a = claim(40, "7.5", "alpha beta gamma tango was 7.5")
        target_b = claim(40, "7.5", "alpha beta gamma sierra was 7.5")

        graph = relating.build([paper("a", claims=[*crowd_a, target_a]), paper("b", claims=[*crowd_b, target_b])])

        assert graph["relations"] == []

    def test_a_claim_with_no_number_is_not_set_against_another(self) -> None:
        said = [
            paper("a", claims=[claim(1, "high", "mapping cell types in mouse brain is accurate")]),
            paper("b", claims=[claim(1, "high", "mapping cell types in mouse brain is accurate")]),
        ]

        assert relating.build(said)["relations"] == []

    def test_a_number_that_one_paper_reproduced_makes_the_agreement_corroborated(self) -> None:
        first = "92%|accuracy of mapping cell types in mouse brain was 92%"
        second = "92%|the mapping of cell types in mouse brain gave accuracy of 92%"

        graph = relating.build(self.two(first, second, reproduction={"c1": "reproduced"}))

        (found,) = of_kind(graph, "agrees")
        assert found["corroborated"] is True and found["evidence"][0]["a"]["reproduction"] == "reproduced"
        assert found["evidence"][0]["b"]["reproduction"] is None
        node = next(item for item in graph["papers"] if item["id"] == "a")
        assert node["reproduction"] == {"reproduced": 1, "partly": 0, "not_reproduced": 0, "not_attempted": 0}

    def test_a_number_that_was_tried_and_not_reproduced_does_not_corroborate(self) -> None:
        first = "92%|accuracy of mapping cell types in mouse brain was 92%"
        second = "92%|the mapping of cell types in mouse brain gave accuracy of 92%"

        graph = relating.build(self.two(first, second, reproduction={"c1": "not_reproduced"}))

        assert of_kind(graph, "agrees")[0]["corroborated"] is False

    def test_only_the_closest_claims_of_a_pair_are_kept_and_the_most_alike_come_first(self) -> None:
        base = "accuracy of mapping cell types in mouse brain was 92%"
        many = [
            claim(number, "92%", f"{base} {' '.join(f'word{n}x' for n in range(number))}") for number in range(1, 7)
        ]

        graph = relating.build([paper("a", claims=[claim(9, "92%", base)]), paper("b", claims=list(reversed(many)))])

        (found,) = of_kind(graph, "agrees")
        assert [item["b"]["fact"] for item in found["evidence"]] == ["c1", "c2", "c3"]

    def test_words_that_nearly_every_claim_has_do_not_find_a_likeness(self) -> None:
        crowd = [claim(number, "1.5", f"cells {number} were measured at 1.5") for number in range(1, 80)]
        graph = relating.build([paper("a", claims=crowd[:40]), paper("b", claims=crowd[40:])])

        assert graph["relations"] == []

    def test_no_more_claims_of_a_paper_than_the_most_are_set_against_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(relating, "MOST_CLAIMS_EACH", 2)
        said = [
            claim(1, "1.5", "alpha beta gamma was 1.5"),
            claim(2, "2.5", "delta epsilon zeta was 2.5"),
            claim(3, "3.5", "eta theta iota was 3.5"),
        ]
        other = [claim(1, "3.5", "eta theta iota was 3.5")]

        assert relating.build([paper("a", claims=said), paper("b", claims=other)])["relations"] == []


class TestTheGraph:
    def test_a_paper_is_a_line_of_what_was_read_of_it_and_how_many_relations_it_is_in(self) -> None:
        graph = relating.build(
            [
                paper(
                    "a",
                    facts={"methods": [fact(1, name="Louvain clustering")], "datasets": []},
                    claims=[claim(1, "1", "x")],
                ),
                paper("b", read=False, code="https://github.com/o/t"),
            ]
        )

        first, second = graph["papers"]

        assert first == {
            "id": "a",
            "title": "Paper A",
            "read": True,
            "code": None,
            "claims": 1,
            "facts": {"methods": 1, "datasets": 0},
            "reproduction": None,
            "relations": 0,
        }
        assert second["read"] is False and second["code"] == "https://github.com/o/t"

    def test_relations_are_in_the_order_of_their_kinds_and_then_of_the_papers(self) -> None:
        shared = {"datasets": [fact(1, name="Tabula Muris", accession=None)]}
        graph = relating.build(
            [
                paper("a", code="https://github.com/o/t", facts=shared),
                paper("b", code="https://github.com/o/t", facts=shared),
            ]
        )

        assert [each["kind"] for each in graph["relations"]] == ["code", "dataset"]
        assert graph["counts"] == {
            "refers": 0,
            "code": 1,
            "dataset": 1,
            "software": 0,
            "method": 0,
            "agrees": 0,
            "differs": 0,
        }
        assert graph["truncated"] is False

    def test_no_more_relations_than_the_most_are_given_and_it_is_said(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(relating, "MOST_RELATIONS", 2)
        shared = {"datasets": [fact(1, name="Tabula Muris", accession=None)]}

        graph = relating.build([paper(name, facts=shared) for name in "abcd"])

        assert len(graph["relations"]) == 2 and graph["truncated"] is True and graph["counts"]["dataset"] == 6

    def test_as_many_relations_as_the_most_are_not_said_to_be_cut(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(relating, "MOST_RELATIONS", 3)
        shared = {"datasets": [fact(1, name="Tabula Muris", accession=None)]}

        graph = relating.build([paper(name, facts=shared) for name in "abc"])

        assert len(graph["relations"]) == 3 and graph["truncated"] is False

    def test_relations_are_in_the_order_of_the_kinds_there_are_and_not_of_how_they_were_found(self) -> None:
        said = "accuracy of mapping cell types in mouse brain was 92%"
        facts = {"methods": [fact(1, name="Louvain clustering")], "software": [fact(2, name="STAR", version="2.7")]}
        papers = [paper(name, facts=facts, claims=[claim(1, "92%", said)]) for name in "ab"]

        graph = relating.build(papers)

        assert [each["kind"] for each in graph["relations"]] == ["software", "method", "agrees"]

    def test_no_papers_and_one_paper_have_no_relations(self) -> None:
        assert relating.build([])["relations"] == [] and relating.build([paper("a")])["relations"] == []

    def test_a_fact_that_is_not_as_it_is_written_does_not_break_it(self) -> None:
        odd = {"id": "x", "quote": None, "name": 3, "anchor": "no"}
        graph = relating.build(
            [paper("a", facts={"datasets": [odd], "software": [odd]}), paper("b", facts={"datasets": [odd]})]
        )

        assert graph["relations"] == []


class TestSelecting:
    @pytest.fixture
    def graph(self) -> dict[str, Any]:
        shared = {"datasets": [fact(1, "Used Tabula Muris", name="Tabula Muris", accession=None)]}
        return relating.build(
            [
                paper("a", title="Mouse atlas", facts=shared),
                paper("b", title="Brain mapping", facts=shared, code="https://github.com/o/t"),
                paper("c", title="Other", code="https://github.com/o/t"),
            ]
        )

    def test_nothing_asked_is_everything_even_a_paper_that_is_related_to_none(self, graph: dict[str, Any]) -> None:
        lone = relating.build([paper("a"), paper("b")])

        assert len(relating.select(graph)["relations"]) == 2 and len(relating.select(graph)["papers"]) == 3
        assert relating.select(lone)["relations"] == [] and len(relating.select(lone)["papers"]) == 2
        assert relating.select(lone, kind="code")["papers"] == []

    def test_a_kind_chooses_its_relations(self, graph: dict[str, Any]) -> None:
        chosen = relating.select(graph, kind="dataset")

        assert [each["kind"] for each in chosen["relations"]] == ["dataset"]
        assert {item["id"] for item in chosen["papers"]} == {"a", "b"}
        assert chosen["counts"]["dataset"] == 1 and chosen["counts"]["code"] == 0

    def test_a_paper_by_its_id_or_a_part_of_its_title_chooses_the_relations_it_is_in(
        self, graph: dict[str, Any]
    ) -> None:
        assert {each["kind"] for each in relating.select(graph, agent="b")["relations"]} == {"dataset", "code"}
        assert [each["kind"] for each in relating.select(graph, agent="OTHER")["relations"]] == ["code"]
        assert relating.select(graph, agent="nothing like it")["relations"] == []

    def test_words_choose_the_relations_that_have_them_in_what_they_say(self, graph: dict[str, Any]) -> None:
        assert [each["kind"] for each in relating.select(graph, about="tabula muris")["relations"]] == ["dataset"]
        assert [each["kind"] for each in relating.select(graph, about="used")["relations"]] == ["dataset"]
        assert relating.select(graph, about="zebrafish")["relations"] == []

    def test_any_of_the_words_is_enough(self, graph: dict[str, Any]) -> None:
        assert [each["kind"] for each in relating.select(graph, about="zebrafish tabula")["relations"]] == ["dataset"]

    def test_a_kind_that_is_not_one_and_words_of_nothing_are_refused(self, graph: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="kind of relation"):
            relating.select(graph, kind="friends")
        with pytest.raises(ValueError, match="words"):
            relating.select(graph, about="the of")

    def test_what_was_cut_is_still_said_to_be(self, graph: dict[str, Any]) -> None:
        assert relating.select({**graph, "truncated": True})["truncated"] is True
