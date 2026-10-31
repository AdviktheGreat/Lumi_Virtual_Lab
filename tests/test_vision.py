"""Tests of looking at images and at the pages of PDFs: keeping the lead in the working directory, drawing pages, and
bringing an image to a size a model is sent whole."""

import base64
import io
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from virtual_lab import vision
from virtual_lab.vision import (
    MAX_IMAGE_SIDE,
    MAX_IMAGES_PER_VIEW,
    VIEW_IMAGE_TOOL_NAME,
    Picture,
    ViewError,
    find_file,
    look_at,
    parse_pages,
    view_content,
    view_image_tool,
    viewable,
)


def image_file(path: Path, size: tuple[int, int] = (200, 100), mode: str = "RGB", colour: Any = "white") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, colour).save(path)

    return path


def pdf_file(path: Path, pages: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    slides = []
    for number in range(pages):
        slide = Image.new("RGB", (600, 800), "white")
        ImageDraw.Draw(slide).text((50, 50), f"Slide {number + 1}", fill="black")
        slides.append(slide)
    slides[0].save(path, save_all=True, append_images=slides[1:])

    return path


def size_of(picture: Picture) -> tuple[int, int]:
    with Image.open(io.BytesIO(picture.data)) as opened:
        return opened.size


class TestFindingTheFile:
    def test_a_file_is_found_by_its_path_in_the_working_directory(self, tmp_path: Path) -> None:
        image_file(tmp_path / "plots" / "a.png")

        assert find_file(tmp_path, "plots/a.png") == (tmp_path / "plots" / "a.png").resolve()
        assert find_file(tmp_path, "  plots/a.png \n") == (tmp_path / "plots" / "a.png").resolve()

    def test_a_path_as_the_code_sees_it_or_as_it_is_here_is_understood(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "uploads" / "a.png").resolve()

        assert find_file(tmp_path, "/workspace/uploads/a.png", "/workspace") == file
        assert find_file(tmp_path, "/workspace/uploads/a.png", "/workspace/") == file
        assert find_file(tmp_path, str(file), "/workspace") == file
        assert find_file(tmp_path, str(file)) == file

    def test_a_path_outside_the_working_directory_is_refused(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        image_file(tmp_path / "secret.png")

        for named in ("../secret.png", str(tmp_path / "secret.png"), "/etc/passwd", "uploads/../../secret.png"):
            with pytest.raises(ViewError, match="Only files in the working directory"):
                find_file(work, named)

    def test_a_path_with_the_code_s_directory_in_it_is_not_a_way_out_of_it(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        image_file(tmp_path / "secret.png")

        with pytest.raises(ViewError, match="Only files in the working directory"):
            find_file(work, "/workspace/../secret.png", "/workspace")

    def test_a_link_to_a_file_outside_is_refused(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        image_file(tmp_path / "secret.png")
        (work / "link.png").symlink_to(tmp_path / "secret.png")

        with pytest.raises(ViewError, match="Only files in the working directory"):
            find_file(work, "link.png")

    def test_a_link_to_a_file_inside_is_followed(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "real.png").resolve()
        (tmp_path / "link.png").symlink_to(file)

        assert find_file(tmp_path, "link.png") == file

    def test_a_file_that_is_missing_or_not_a_file_is_said_so(self, tmp_path: Path) -> None:
        (tmp_path / "folder.png").mkdir()

        for named in ("missing.png", "folder.png"):
            with pytest.raises(ViewError, match=f"There is no file {named} in the working directory"):
                find_file(tmp_path, named)

    def test_a_path_is_needed(self, tmp_path: Path) -> None:
        with pytest.raises(ViewError, match="Say which file"):
            find_file(tmp_path, "  ")

    def test_only_images_and_pdfs_can_be_looked_at(self, tmp_path: Path) -> None:
        (tmp_path / "counts.csv").write_text("a,b\n")

        with pytest.raises(ViewError, match=r"counts.csv is not an image or a PDF.*\.pdf"):
            find_file(tmp_path, "counts.csv")

    def test_a_file_in_capitals_is_the_same_kind(self, tmp_path: Path) -> None:
        image_file(tmp_path / "A.PNG")

        assert find_file(tmp_path, "A.PNG").name == "A.PNG"
        assert viewable("Slides.PDF") and viewable("a.jpeg") and viewable("a.WEBP")
        assert not viewable("a.csv") and not viewable("noextension")

    def test_a_file_too_large_to_open_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        image_file(tmp_path / "a.png")
        monkeypatch.setattr(vision, "MAX_SOURCE_BYTES", 10)

        with pytest.raises(ViewError, match="larger than the 0 MB"):
            find_file(tmp_path, "a.png")


class TestWhichPages:
    @pytest.mark.parametrize(
        ("asked", "expected"),
        [
            (3, [3]),
            ([2, 5], [2, 5]),
            ("4", [4]),
            ("2-4", [2, 3, 4]),
            ("1, 3-4, 9", [1, 3, 4, 9]),
            (["2-3", 7], [2, 3, 7]),
            ([5, 2, 5, 2], [5, 2]),
            ("", []),
            ([], []),
        ],
    )
    def test_pages_are_read_in_the_order_asked_and_each_once(self, asked: Any, expected: list[int]) -> None:
        assert parse_pages(asked, 10) == expected

    @pytest.mark.parametrize(
        ("asked", "problem"),
        [
            (0, "there is no page 0"),
            ([1, 11], "there is no page 11"),
            (-2, "there is no page -2"),
            ("3-1", "not a range"),
            ("one", "not a page number"),
            ([True], "not a page number"),
            ("1.5", "not a page number"),
            ("1-100", "not a range"),
        ],
    )
    def test_a_page_the_document_does_not_have_or_that_is_not_a_page_is_refused(self, asked: Any, problem: str) -> None:
        with pytest.raises(ViewError, match=problem):
            parse_pages(asked, 10)

    def test_no_more_pages_than_can_be_looked_at_at_once_are_taken(self) -> None:
        assert len(parse_pages(list(range(1, MAX_IMAGES_PER_VIEW + 1)), 50)) == MAX_IMAGES_PER_VIEW

        with pytest.raises(ViewError, match=f"at most {MAX_IMAGES_PER_VIEW} pages"):
            parse_pages(list(range(1, MAX_IMAGES_PER_VIEW + 2)), 50)


class TestImages:
    def test_an_image_that_is_small_enough_is_sent_as_it_is(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "a.png")

        (picture,) = look_at(file, "a.png")

        assert picture == Picture("a.png", "image/png", file.read_bytes())

    def test_an_image_that_is_too_large_is_brought_down_with_its_shape_kept(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "big.png", size=(3200, 800))

        (picture,) = look_at(file, "big.png")

        assert picture.media_type == "image/png"
        assert size_of(picture) == (MAX_IMAGE_SIDE, MAX_IMAGE_SIDE // 4)

    def test_transparency_is_put_on_white_so_that_a_model_does_not_see_black(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "t.png", size=(2000, 100), mode="RGBA", colour=(0, 0, 0, 0))

        (picture,) = look_at(file, "t.png")

        with Image.open(io.BytesIO(picture.data)) as opened:
            assert opened.mode == "RGB"
            assert opened.getpixel((5, 5)) == (255, 255, 255)

    def test_an_image_that_is_a_large_file_is_sent_as_a_smaller_jpeg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        noise = Image.effect_noise((300, 300), 80).convert("RGB")
        file = tmp_path / "noise.png"
        noise.save(file)
        monkeypatch.setattr(vision, "MAX_IMAGE_BYTES", file.stat().st_size - 1)

        (picture,) = look_at(file, "noise.png")

        assert picture.media_type == "image/jpeg"
        assert len(picture.data) < file.stat().st_size

    def test_a_gif_is_sent_as_a_png_of_its_first_frame(self, tmp_path: Path) -> None:
        file = tmp_path / "a.gif"
        Image.new("P", (20, 20)).save(file)

        (picture,) = look_at(file, "a.gif")

        assert picture.media_type == "image/png"
        assert size_of(picture) == (20, 20)

    def test_a_file_that_is_not_an_image_though_it_is_named_as_one_is_said_to_be_unreadable(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "fake.png").write_bytes(b"not an image")

        with pytest.raises(ViewError, match="fake.png could not be read as an image"):
            look_at(tmp_path / "fake.png", "fake.png")

    def test_pages_are_not_something_an_image_has(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "a.png")

        with pytest.raises(ViewError, match="an image, which has no pages"):
            look_at(file, "a.png", [1])
        assert look_at(file, "a.png", [])[0].label == "a.png"

    def test_without_pillow_a_small_image_is_still_sent_and_a_large_one_is_told_what_to_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        small = image_file(tmp_path / "small.png")
        large = tmp_path / "large.png"
        large.write_bytes(small.read_bytes() + b"\0" * 100)
        monkeypatch.setitem(sys.modules, "PIL", None)
        monkeypatch.setattr(vision, "MAX_IMAGE_BYTES", small.stat().st_size)

        assert look_at(small, "small.png")[0].data == small.read_bytes()
        with pytest.raises(ViewError, match=r"Pillow.*not installed.*virtual-lab\[vision\]"):
            look_at(large, "large.png")


class TestPdfs:
    def test_the_pages_asked_for_are_drawn_and_named(self, tmp_path: Path) -> None:
        file = pdf_file(tmp_path / "slides.pdf", pages=5)

        pictures = look_at(file, "uploads/slides.pdf", [4, 2])

        assert [picture.label for picture in pictures] == [
            "uploads/slides.pdf, page 4 of 5",
            "uploads/slides.pdf, page 2 of 5",
        ]
        assert {picture.media_type for picture in pictures} == {"image/png"}
        assert all(max(size_of(picture)) <= MAX_IMAGE_SIDE for picture in pictures)
        assert all(picture.data.startswith(b"\x89PNG") for picture in pictures)

    def test_a_page_is_drawn_at_a_size_a_model_reads_it_at(self, tmp_path: Path) -> None:
        (picture,) = look_at(pdf_file(tmp_path / "slides.pdf", pages=1), "slides.pdf")

        assert max(size_of(picture)) == MAX_IMAGE_SIDE

    def test_pages_can_be_asked_for_as_text_ranges(self, tmp_path: Path) -> None:
        file = pdf_file(tmp_path / "slides.pdf", pages=5)

        pictures = look_at(file, "slides.pdf", "2-3, 5")

        assert [picture.label.rsplit(", ", 1)[1] for picture in pictures] == ["page 2 of 5", "page 3 of 5", "page 5 of 5"]

    def test_a_document_of_a_page_needs_none_said_and_one_of_more_does(self, tmp_path: Path) -> None:
        one = pdf_file(tmp_path / "one.pdf", pages=1)
        many = pdf_file(tmp_path / "many.pdf", pages=3)

        assert look_at(one, "one.pdf")[0].label == "one.pdf, page 1 of 1"
        with pytest.raises(ViewError, match=r"many.pdf has 3 pages. Say which to look at, at most 6"):
            look_at(many, "many.pdf")

    def test_a_page_it_does_not_have_is_refused_with_how_many_it_has(self, tmp_path: Path) -> None:
        file = pdf_file(tmp_path / "slides.pdf", pages=3)

        with pytest.raises(ViewError, match="has 3 pages, numbered from 1, so there is no page 4"):
            look_at(file, "slides.pdf", [4])

    def test_a_file_that_is_not_a_pdf_though_it_is_named_as_one_is_said_to_be_unreadable(self, tmp_path: Path) -> None:
        (tmp_path / "fake.pdf").write_bytes(b"not a pdf")

        with pytest.raises(ViewError, match="fake.pdf could not be opened as a PDF"):
            look_at(tmp_path / "fake.pdf", "fake.pdf", [1])

    def test_without_pypdfium2_what_to_install_is_said(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        file = pdf_file(tmp_path / "slides.pdf", pages=1)
        monkeypatch.setitem(sys.modules, "pypdfium2", None)

        with pytest.raises(ViewError, match=r"needs pypdfium2 and Pillow.*virtual-lab\[vision\]"):
            look_at(file, "slides.pdf")


class TestWhatTheModelIsSent:
    def test_a_question_is_followed_by_each_picture_after_a_line_that_says_what_it_is(self) -> None:
        pictures = [Picture("a.png", "image/png", b"abc"), Picture("b.pdf, page 2 of 9", "image/jpeg", b"xyz")]

        content = view_content("What is it?", pictures)

        assert content == [
            {"type": "text", "text": "What is it?"},
            {"type": "text", "text": "a.png:"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(b'abc').decode()}"}},
            {"type": "text", "text": "b.pdf, page 2 of 9:"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(b'xyz').decode()}"}},
        ]


class TestTheTool:
    def make(self, work: Path, answer: str = "A cell.", where: str | None = None) -> tuple[Any, list[tuple[str, Any]]]:
        asked: list[tuple[str, Any]] = []

        def ask(question: str, pictures: Any) -> str:
            asked.append((question, list(pictures)))
            return answer

        return view_image_tool(work, ask, where), asked

    def test_it_asks_about_the_pictures_and_says_what_was_looked_at(self, tmp_path: Path) -> None:
        file = image_file(tmp_path / "plots" / "a.png")
        tool, asked = self.make(tmp_path)

        output = tool.function(path="plots/a.png", question="What does it show?")

        assert tool.name == VIEW_IMAGE_TOOL_NAME == "view_image"
        assert output == "Looked at plots/a.png.\n\nA cell."
        assert asked == [("What does it show?", [Picture("plots/a.png", "image/png", file.read_bytes())])]

    def test_it_looks_at_pages_of_a_pdf(self, tmp_path: Path) -> None:
        pdf_file(tmp_path / "uploads" / "slides.pdf", pages=4)
        tool, asked = self.make(tmp_path, where="/workspace")

        output = tool.function(path="/workspace/uploads/slides.pdf", question="Title?", pages=[2, 3])

        assert output.startswith(
            "Looked at /workspace/uploads/slides.pdf, page 2 of 4; /workspace/uploads/slides.pdf, page 3 of 4."
        )
        assert [len(pictures) for _, pictures in asked] == [2]

    def test_what_cannot_be_looked_at_is_told_to_the_lead_and_the_model_is_not_asked(self, tmp_path: Path) -> None:
        (tmp_path / "counts.csv").write_text("a\n1\n")
        pdf_file(tmp_path / "many.pdf", pages=3)
        tool, asked = self.make(tmp_path)

        outputs = [
            tool.function(path="missing.png", question="?"),
            tool.function(path="../x.png", question="?"),
            tool.function(path="counts.csv", question="?"),
            tool.function(path="many.pdf", question="?"),
            tool.function(path="many.pdf", question="?", pages=[7]),
            tool.function(path="many.pdf", question="  ", pages=[1]),
        ]

        assert all(output.startswith("Cannot look at it: ") for output in outputs)
        assert "say what to find out" in outputs[-1]
        assert asked == []

    def test_a_model_that_says_nothing_is_not_taken_for_having_looked(self, tmp_path: Path) -> None:
        image_file(tmp_path / "a.png")
        tool, _ = self.make(tmp_path, answer="  \n")

        assert tool.function(path="a.png", question="?") == "The model said nothing of a.png. Ask again, more specifically."

    def test_it_asks_for_a_file_and_a_question_and_for_pages_only_if_there_are_some(self) -> None:
        tool = view_image_tool(Path("."), lambda question, pictures: "")

        assert tool.parameters["required"] == ["path", "question"]
        assert set(tool.parameters["properties"]) == {"path", "question", "pages"}
        assert str(MAX_IMAGES_PER_VIEW) in tool.description
