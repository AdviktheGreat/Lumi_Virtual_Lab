"""Looking at images and at the pages of PDFs: finding the file the lead names, and getting from it what a model that
reads images is sent.

A figure, a slide, a scanned page, or a screenshot says what its text layer, if it has one, leaves out. The lead is
given the view_image tool, which asks its own model a question about what is shown (Chat.ask_about_images). This module
does the part that does not need a model: it keeps the lead inside the working directory, renders a PDF's pages, and
brings every image down to a size a model is sent whole.

Pillow reads and resizes the images, and pypdfium2 renders the pages, both of which `pip install "virtual-lab[vision]"`
installs. An image that is small enough and of a kind a model takes is sent as it is, without Pillow.
"""

import base64
import io
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virtual_lab.tools import Tool

# The name of the tool that looks at images, which a conversation is given if its model reads them
VIEW_IMAGE_TOOL_NAME = "view_image"

# What a model can be sent as an image, by the file's extension
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
PDF_SUFFIX = ".pdf"

# The most that is asked about at once: each image costs a model about a thousand tokens or more to read
MAX_IMAGES_PER_VIEW = 6

# The longest side, in pixels, that an image is sent at. Models shrink what is larger, and a request is slower for it.
MAX_IMAGE_SIDE = 1600

# The largest image sent, as a file. Over it, a picture is sent as a JPEG, which is smaller.
MAX_IMAGE_BYTES = 3 * 1024**2

# The largest file that is opened, so that one that is not an image of a sensible size is not read into memory
MAX_SOURCE_BYTES = 200 * 1024**2

# The most a page is magnified to be drawn, which a page that is small, as a stamp is, would otherwise be drawn at
MAX_PAGE_SCALE = 4.0

INSTALL_HELP = 'pip install "virtual-lab[vision]"'


class ViewError(ValueError):
    """Raised when what the lead asked to look at cannot be looked at. What it says is for the lead, to correct the
    call, so it names what to do."""


@dataclass(frozen=True)
class Picture:
    """An image ready to be sent to a model.

    :param label: What it is, for the model and for the lead: the file, with the page if it is one.
    :param media_type: Its type, as image/png.
    :param data: Its bytes.
    """

    label: str
    media_type: str
    data: bytes

    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode('ascii')}"


def viewable(path: str) -> bool:
    """Whether a file is one that can be looked at, by its name."""
    suffix = Path(path).suffix.lower()

    return suffix in IMAGE_TYPES or suffix == PDF_SUFFIX


def find_file(work_dir: Path, path: str, where_code_runs: str | None = None) -> Path:
    """Finds the file the lead named, which has to be in the working directory.

    :param work_dir: The working directory, on this machine.
    :param path: What the lead wrote: relative to the working directory, or as the code sees it.
    :param where_code_runs: The working directory as the code sees it, which is where this one is mounted in a
        container.
    :raises ViewError: If it is not a file of the working directory, or not one that can be looked at.
    :return: Where it is.
    """
    named = path.strip()
    if not named:
        raise ViewError("Say which file to look at, by its path in the working directory.")

    base = work_dir.resolve()
    shown_to_code = where_code_runs.rstrip("/") if where_code_runs else None
    for prefix in {str(base), shown_to_code}:
        if prefix and (named == prefix or named.startswith(prefix + "/")):
            named = named[len(prefix) :].lstrip("/")
            break

    if Path(named).is_absolute():
        raise ViewError(f"Only files in the working directory ({where_code_runs or base}) can be looked at: {path}")

    file = (base / named).resolve()
    if base != file and base not in file.parents:
        raise ViewError(f"Only files in the working directory ({where_code_runs or base}) can be looked at: {path}")
    if not file.is_file():
        raise ViewError(f"There is no file {named} in the working directory.")

    suffix = file.suffix.lower()
    if suffix not in IMAGE_TYPES and suffix != PDF_SUFFIX:
        kinds = ", ".join(sorted({*IMAGE_TYPES, PDF_SUFFIX}))
        raise ViewError(f"{named} is not an image or a PDF, which are what can be looked at ({kinds}).")
    if file.stat().st_size > MAX_SOURCE_BYTES:
        raise ViewError(f"{named} is larger than the {MAX_SOURCE_BYTES // 1024**2} MB that can be opened.")

    return file


def parse_pages(pages: Any, count: int) -> list[int]:
    """The pages the lead asked for, as page numbers from 1, in the order asked and each once.

    :param pages: A page number, a list of them, or text such as "3-5, 9", where a range is a-b.
    :param count: How many pages the document has.
    :raises ViewError: If it names a page the document does not have, or too many.
    """
    tokens: list[Any] = list(pages) if isinstance(pages, (list, tuple)) else [pages]
    wanted: list[int] = []
    for token in tokens:
        if isinstance(token, bool):
            raise ViewError(f"{token!r} is not a page number.")
        if isinstance(token, int):
            wanted.append(token)
            continue
        for part in str(token).split(","):
            part = part.strip()
            if not part:
                continue
            if found := re.fullmatch(r"(\d+)\s*-\s*(\d+)", part):
                start, end = int(found[1]), int(found[2])
                if end < start or end - start >= count:
                    raise ViewError(f"{part} is not a range of this document's pages, which are 1 to {count}.")
                wanted.extend(range(start, end + 1))
            elif part.isdigit():
                wanted.append(int(part))
            else:
                raise ViewError(f"{part!r} is not a page number or a range of them such as 3-5.")

    ordered = list(dict.fromkeys(wanted))
    if bad := [page for page in ordered if not 1 <= page <= count]:
        raise ViewError(f"This document has {count} pages, numbered from 1, so there is no page {bad[0]}.")
    if len(ordered) > MAX_IMAGES_PER_VIEW:
        raise ViewError(
            f"Look at at most {MAX_IMAGES_PER_VIEW} pages at a time; {len(ordered)} were asked for. Ask again for "
            "the rest, with a question about each."
        )

    return ordered


def look_at(file: Path, shown_as: str, pages: Any = None) -> list[Picture]:
    """The pictures of a file: itself if it is an image, and the pages asked for if it is a PDF.

    :param file: A file that find_file found.
    :param shown_as: How it is named to the model, which is the path the lead gave.
    :param pages: Which pages of a PDF, as parse_pages reads them. A PDF with more than one page needs them said.
    :raises ViewError: If it cannot be opened or drawn, or pages are named for an image, or not for a PDF.
    """
    if file.suffix.lower() == PDF_SUFFIX:
        return render_pages(file, shown_as, pages)
    if pages not in (None, [], ""):
        raise ViewError(f"{shown_as} is an image, which has no pages: leave pages out.")

    return [picture_of_image(file, shown_as)]


def picture_of_image(file: Path, shown_as: str) -> Picture:
    media_type = IMAGE_TYPES[file.suffix.lower()]
    raw = file.read_bytes()
    try:
        from PIL import Image
    except ImportError:
        if len(raw) > MAX_IMAGE_BYTES:
            raise ViewError(
                f"{shown_as} is larger than the {MAX_IMAGE_BYTES // 1024**2} MB that can be sent as it is, and "
                f"Pillow, which would make it smaller, is not installed: {INSTALL_HELP}."
            ) from None
        return Picture(shown_as, media_type, raw)

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            fits = max(opened.size) <= MAX_IMAGE_SIDE
            if fits and len(raw) <= MAX_IMAGE_BYTES and opened.format != "GIF":
                return Picture(shown_as, media_type, raw)
            return encode(opened, shown_as)
    except ViewError:
        raise
    except Exception as error:
        raise ViewError(f"{shown_as} could not be read as an image: {error}") from None


def render_pages(file: Path, shown_as: str, pages: Any) -> list[Picture]:
    try:
        import pypdfium2
        from PIL import Image  # noqa: F401  (pypdfium2 draws into Pillow images)
    except ImportError:
        raise ViewError(
            f"Looking at the pages of a PDF needs pypdfium2 and Pillow, which are not installed: {INSTALL_HELP}."
        ) from None

    try:
        document = pypdfium2.PdfDocument(file)
    except Exception as error:
        raise ViewError(f"{shown_as} could not be opened as a PDF: {error}") from None

    try:
        count = len(document)
        if count == 0:
            raise ViewError(f"{shown_as} has no pages.")
        if pages in (None, [], ""):
            if count > 1:
                raise ViewError(f"{shown_as} has {count} pages. Say which to look at, at most {MAX_IMAGES_PER_VIEW}.")
            pages = [1]
        wanted = parse_pages(pages, count)
        pictures = []
        for number in wanted:
            page = document[number - 1]
            try:
                width, height = page.get_size()
                scale = min(MAX_PAGE_SCALE, MAX_IMAGE_SIDE / max(width, height, 1.0))
                image = page.render(scale=scale).to_pil()
            except Exception as error:
                raise ViewError(f"Page {number} of {shown_as} could not be drawn: {error}") from None
            finally:
                page.close()
            pictures.append(encode(image, f"{shown_as}, page {number} of {count}"))

        return pictures
    finally:
        document.close()


def encode(image: Any, label: str) -> Picture:
    """A Pillow image as the picture to send: no larger than MAX_IMAGE_SIDE, with no transparency, and a PNG, or a
    JPEG if that is too large a file."""
    from PIL import Image

    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        flat = Image.new("RGB", image.size, "white")
        flat.paste(image, mask=image.getchannel("A"))
        image = flat
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if max(image.size) > MAX_IMAGE_SIDE:
        image = image.copy()
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    if buffer.tell() <= MAX_IMAGE_BYTES:
        return Picture(label, "image/png", buffer.getvalue())

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)

    return Picture(label, "image/jpeg", buffer.getvalue())


def view_content(question: str, pictures: Sequence[Picture]) -> list[dict[str, Any]]:
    """What a model is sent to be asked about pictures, in the shape chat models take: the question, then each
    picture after a line that says what it is."""
    content: list[dict[str, Any]] = [{"type": "text", "text": question}]
    for picture in pictures:
        content.append({"type": "text", "text": f"{picture.label}:"})
        content.append({"type": "image_url", "image_url": {"url": picture.data_url()}})

    return content


def labels(pictures: Iterable[Picture]) -> str:
    return "; ".join(picture.label for picture in pictures)


# What answers a question about pictures: a model that reads images, as Chat.ask_about_images asks the lead's own
AskAboutImages = Callable[[str, Sequence[Picture]], str]


def view_image_tool(work_dir: Path, ask: AskAboutImages, where_code_runs: str | None = None) -> Tool:
    """The tool with which the lead looks at an image, or at pages of a PDF, in the working directory.

    :param work_dir: The working directory on this machine, which the files named are in and cannot be left from.
    :param ask: Asks a model that reads images a question about pictures, and gives back its answer. If the answer is
        empty the lead is told to ask again.
    :param where_code_runs: The working directory as the code sees it, if that is not where it is here, so that a path
        the code printed is understood.
    """

    def view_image(path: str, question: str, pages: Any = None) -> str:
        if not str(question).strip():
            return "Cannot look at it: say what to find out from it, in question."
        try:
            pictures = look_at(find_file(work_dir, str(path), where_code_runs), str(path).strip(), pages)
        except ViewError as error:
            return f"Cannot look at it: {error}"

        answer = ask(str(question), pictures).strip()
        if not answer:
            return f"The model said nothing of {labels(pictures)}. Ask again, more specifically."

        return f"Looked at {labels(pictures)}.\n\n{answer}"

    return Tool(
        name=VIEW_IMAGE_TOOL_NAME,
        description=(
            "Look at an image, or at pages of a PDF, and be told what is in it, by asking a question about it. Use it "
            "for a figure, a slide, a scanned page, a plot you made, or a screenshot, when the text of the file does "
            "not say enough; reading text with code is cheaper. The answer is only what the question asks, and it "
            "cannot see this conversation, so ask for exactly what you need: the text word for word, the steps of a "
            f"diagram in order, the values of a plot. At most {MAX_IMAGES_PER_VIEW} pages or images at a time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file, in the working directory: an image (png, jpg, gif, webp) or a PDF, such "
                    "as uploads/slides.pdf or plots/figure_1.png.",
                },
                "question": {"type": "string", "description": "What to find out from it."},
                "pages": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "For a PDF: which pages, numbered from 1, such as [45, 46, 47]. A PDF of more than "
                    "one page needs them.",
                },
            },
            "required": ["path", "question"],
        },
        function=view_image,
    )
