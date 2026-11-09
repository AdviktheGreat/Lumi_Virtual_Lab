"""Tests of taking stock of a project's code: what is found in it by looking at its files, that none of it is run, and
that a large or odd project is looked at within limits."""

import json
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.paperagents import stock as stocking
from virtual_lab.paperagents.stock import is_stock, take_stock

MIT = """MIT License

Copyright (c) 2024 The Authors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""
APACHE = "Apache License\nVersion 2.0, January 2004\nhttp://www.apache.org/licenses/\n"
BSD3 = (
    "Redistribution and use in source and binary forms, with or without modification, are permitted provided that "
    "the following conditions are met:\n1. Redistributions of source code must retain the above copyright notice, "
    "this list of conditions and the following disclaimer.\n3. Neither the name of the copyright holder nor the names "
    "of its contributors may be used to endorse or promote products.\n"
)
BSD2 = BSD3.split("3. Neither")[0]
GPL3 = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
GPL2 = "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n"
LGPL = (
    "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
    "This version of the GNU Lesser General Public License incorporates the terms of version 3 of the GNU General "
    "Public License.\n"
)
AGPL = "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007\n"
NONCOMMERCIAL = "This code is free for academic use only. Any commercial use needs a license from the university.\n"
UNRECOGNIZED = "Our code is ours. Ask before you do anything with it.\n"


def tree(root: Path, files: dict[str, str | bytes | dict[str, Any]]) -> Path:
    """Writes a project's files in a folder. A dictionary is written as JSON."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            content = json.dumps(content)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())

    return root


def notebook(code: list[str], markdown: list[str] | None = None, language: str = "python") -> dict[str, Any]:
    cells = [{"cell_type": "markdown", "source": [text]} for text in markdown or []]
    cells += [{"cell_type": "code", "source": [source], "outputs": [], "execution_count": None} for source in code]

    return {"cells": cells, "metadata": {"kernelspec": {"language": language, "name": language}}, "nbformat": 4}


def stock_of(tmp_path: Path, files: dict[str, str | bytes | dict[str, Any]]) -> dict[str, Any]:
    return take_stock(tree(tmp_path / "project", files))


def kinds(found: dict[str, Any]) -> dict[str, str]:
    return {item["path"]: item["kind"] for item in found["tutorials"]["listed"]}


class TestLanguagesAndSize:
    def test_counts_files_and_bytes_for_each_language_biggest_first(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {"a.py": "x = 1\n" * 100, "b.py": "y = 2\n", "c.R": "z <- 1\n", "run.sh": "echo hi\n", "notes.md": "text"},
        )

        assert [language["name"] for language in found["languages"]] == ["Python", "Shell", "R"]
        assert found["languages"][0] == {"name": "Python", "files": 2, "bytes": 606}
        assert found["files"] == 5
        assert found["bytes"] == sum(len(c) for c in ("x = 1\n" * 100, "y = 2\n", "z <- 1\n", "echo hi\n", "text"))
        assert found["complete"] is True

    def test_a_notebook_counts_for_the_language_of_its_kernel_by_its_code(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"n.ipynb": notebook(["library(Seurat)"], language="R")})

        assert found["languages"] == [{"name": "R", "files": 1, "bytes": len("library(Seurat)")}]

    def test_folders_that_others_made_are_not_looked_in(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {"a.py": "x", "node_modules/pkg/index.js": "y" * 1000, ".venv/lib/z.py": "z", "__pycache__/a.py": "c"},
        )

        assert found["files"] == 1

    def test_a_link_is_not_followed_out_of_the_project(self, tmp_path: Path) -> None:
        outside = tree(tmp_path / "outside", {"secret.py": "token = 1\n"})
        root = tree(tmp_path / "project", {"a.py": "x = 1\n"})
        (root / "folder").symlink_to(outside, target_is_directory=True)
        (root / "file.py").symlink_to(outside / "secret.py")

        found = take_stock(root)

        assert found["files"] == 1

    def test_only_so_many_files_are_walked_and_it_says_when_not_all_were(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(stocking, "MAX_FILES", 5)
        found = stock_of(tmp_path, {f"f{number}.py": "x = 1\n" for number in range(12)})

        assert found["files"] == 5
        assert found["complete"] is False

    def test_folders_deeper_than_the_limit_are_not_walked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(stocking, "MAX_DEPTH", 2)
        found = stock_of(tmp_path, {"a.py": "x", "one/b.py": "x", "one/two/c.py": "x", "one/two/three/d.py": "x"})

        assert found["files"] == 3

    def test_names_with_control_characters_are_made_fit_to_show(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"examples/run\nme.py": "x = 1\n"})

        assert found["tutorials"]["listed"][0]["path"] == "examples/run?me.py"
        assert is_stock(found)

    def test_an_empty_project_has_nothing_in_it(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {})

        assert found["files"] == 0 and found["languages"] == [] and found["license"] is None and found["readme"] is None
        assert is_stock(found)


class TestNotebooksAndTutorials:
    def test_a_notebook_is_a_tutorial_with_the_cells_of_code_it_has(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path, {"docs/intro.ipynb": notebook(["import mylib", "mylib.run()"], markdown=["# Intro"])}
        )

        assert found["notebooks"]["count"] == 1
        assert found["notebooks"]["listed"][0]["code_cells"] == 2
        assert found["notebooks"]["listed"][0]["language"] == "Python"
        assert kinds(found) == {"docs/intro.ipynb": "notebook"}
        assert found["tutorials"]["characters"] == len("import mylib") + len("mylib.run()") + len("# Intro")

    def test_a_notebook_with_no_code_is_not_a_tutorial(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"notes.ipynb": notebook([], markdown=["only text"])})

        assert found["notebooks"]["count"] == 1
        assert found["tutorials"]["count"] == 0

    def test_a_notebook_that_cannot_be_read_is_listed_and_is_a_tutorial_that_may_be(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"broken.ipynb": "{not json"})

        assert found["notebooks"]["listed"][0]["code_cells"] is None
        assert found["tutorials"]["count"] == 1

    def test_a_notebook_among_the_tests_and_in_a_checkpoint_folder_is_not_one(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {"tests/t.ipynb": notebook(["assert True"]), ".ipynb_checkpoints/x-checkpoint.ipynb": notebook(["1"])},
        )

        assert found["notebooks"]["count"] == 0

    def test_scripts_are_tutorials_by_the_folder_they_are_in_or_what_they_are_called(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "examples/basic.py": "run()\n",
                "tutorials/step1.R": "run()\n",
                "demo_pipeline.py": "run()\n",
                "quickstart.sh": "run\n",
                "vignettes/intro.Rmd": "# x\n",
                "report.qmd": "# y\n",
                "src/lib.py": "def run(): ...\n",
                "examples/__init__.py": "",
                "tests/test_examples.py": "def test(): ...\n",
            },
        )

        assert kinds(found) == {
            "demo_pipeline.py": "script",
            "examples/basic.py": "script",
            "quickstart.sh": "script",
            "report.qmd": "document",
            "tutorials/step1.R": "script",
            "vignettes/intro.Rmd": "document",
        }

    def test_the_tests_are_counted_by_where_they_are_and_what_they_are_called(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "tests/test_a.py": "x",
                "pkg/test_b.py": "x",
                "pkg/c_test.py": "x",
                "conftest.py": "x",
                "tests/testthat/test-d.R": "x",
                "pkg/lib.py": "x",
            },
        )

        assert found["tests"]["count"] == 5


class TestTheEnvironment:
    @pytest.mark.parametrize(
        ("text", "pins"),
        [
            ("numpy==1.26.0\npandas==2.1.0\n", "all"),
            ("numpy==1.26.0\npandas>=2\n# comment\n-r other.txt\n", "some"),
            ("numpy\npandas>=2\nscanpy\n", "none"),
            ("# nothing\n-r base.txt\n", None),
            ("mylib @ git+https://github.com/o/mylib@abc123\n", "all"),
        ],
    )
    def test_requirements_say_how_far_the_versions_are_given(self, tmp_path: Path, text: str, pins: str | None) -> None:
        found = stock_of(tmp_path, {"requirements.txt": text})

        assert found["environment"] == [{"path": "requirements.txt", "kind": "pip", "pins": pins}]

    def test_a_conda_environment_counts_its_dependencies_and_not_its_channels(self, tmp_path: Path) -> None:
        text = (
            "name: paper\nchannels:\n  - conda-forge\n  - bioconda\ndependencies:\n  - python=3.10\n  - numpy=1.26\n"
            "  - pip:\n    - scanpy==1.9.5\nprefix: /somewhere\n"
        )

        assert stock_of(tmp_path, {"environment.yml": text})["environment"][0]["pins"] == "all"

    def test_a_conda_environment_with_a_dependency_that_has_no_version_pins_some(self, tmp_path: Path) -> None:
        text = "name: paper\ndependencies:\n  - python=3.10\n  - numpy\n"

        assert stock_of(tmp_path, {"environment.yaml": text})["environment"][0]["pins"] == "some"

    def test_the_files_that_set_a_project_up_are_found_by_kind(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "pyproject.toml": '[project]\nname = "x"\ndependencies = ["numpy"]\n',
                "poetry.lock": "# lock\n",
                "renv.lock": "{}",
                "DESCRIPTION": "Package: mypkg\nImports: ggplot2\n",
                "Dockerfile": "FROM python:3.11\n",
                "docker/Dockerfile.gpu": "FROM python:3.11\n",
                "setup.py": "from setuptools import setup\nsetup()\n",
                "Project.toml": 'name = "X"\n',
            },
        )

        by_kind = {item["path"]: (item["kind"], item["pins"]) for item in found["environment"]}
        assert by_kind == {
            "DESCRIPTION": ("r-package", None),
            "Dockerfile": ("docker", None),
            "Project.toml": ("julia", None),
            "docker/Dockerfile.gpu": ("docker", None),
            "poetry.lock": ("pip", "locked"),
            "pyproject.toml": ("pip", None),
            "renv.lock": ("renv", "locked"),
            "setup.py": ("pip", None),
        }

    def test_a_pyproject_that_only_configures_tools_does_not_set_anything_up(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"pyproject.toml": "[tool.ruff]\nline-length = 100\n"})

        assert found["environment"] == []

    def test_a_requirements_file_deep_in_the_project_is_not_the_projects(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"a/b/c/d/requirements.txt": "numpy\n"})

        assert found["environment"] == []

    def test_requirements_in_a_folder_of_them_are_found(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"requirements/base.txt": "numpy==1.0\n"})

        assert found["environment"][0]["kind"] == "pip"


class TestTheLicense:
    @pytest.mark.parametrize(
        ("text", "name", "kind"),
        [
            (MIT, "MIT", "permissive"),
            (APACHE, "Apache-2.0", "permissive"),
            (BSD3, "BSD-3-Clause", "permissive"),
            (BSD2, "BSD-2-Clause", "permissive"),
            (GPL3, "GPL-3.0", "copyleft"),
            (GPL2, "GPL-2.0", "copyleft"),
            (LGPL, "LGPL", "copyleft"),
            (AGPL, "AGPL-3.0", "copyleft"),
            ("This is free and unencumbered software released into the public domain.", "Unlicense", "public domain"),
            (NONCOMMERCIAL, None, "noncommercial"),
            (UNRECOGNIZED, None, "other"),
        ],
    )
    def test_a_license_file_is_told_by_its_wording(
        self, tmp_path: Path, text: str, name: str | None, kind: str
    ) -> None:
        found = stock_of(tmp_path, {"LICENSE": text})

        assert found["license"] == {"files": ["LICENSE"], "name": name, "kind": kind, "from": "file"}

    @pytest.mark.parametrize("file", ["LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING", "LICENSE-MIT"])
    def test_a_license_file_may_be_called_a_few_ways(self, tmp_path: Path, file: str) -> None:
        assert stock_of(tmp_path, {file: MIT})["license"]["name"] == "MIT"

    def test_a_project_with_none_has_none(self, tmp_path: Path) -> None:
        assert stock_of(tmp_path, {"a.py": "x = 1\n", "README.md": "# hi\n"})["license"] is None

    def test_a_license_in_a_folder_is_not_the_projects(self, tmp_path: Path) -> None:
        assert stock_of(tmp_path, {"vendor/LICENSE": MIT})["license"] is None

    @pytest.mark.parametrize(
        ("file", "text", "name"),
        [
            ("pyproject.toml", '[project]\nname = "x"\nlicense = "MIT"\n', "MIT"),
            ("pyproject.toml", '[project]\nname = "x"\nlicense = {text = "Apache-2.0"}\n', "Apache-2.0"),
            (
                "pyproject.toml",
                '[project]\nname = "x"\nclassifiers = ["License :: OSI Approved :: BSD License"]\n',
                "BSD",
            ),
            ("setup.cfg", "[metadata]\nlicense = GPLv3\n", "GPL-3.0"),
            ("DESCRIPTION", "Package: p\nLicense: GPL-2\n", "GPL-2.0"),
            ("package.json", '{"license": "ISC"}', "ISC"),
        ],
    )
    def test_without_a_license_file_the_manifest_says(self, tmp_path: Path, file: str, text: str, name: str) -> None:
        found = stock_of(tmp_path, {file: text})

        assert found["license"]["name"] == name and found["license"]["from"] == "manifest"
        assert found["license"]["files"] == []

    def test_a_license_file_that_is_not_recognized_leaves_it_to_the_manifest(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"LICENSE": UNRECOGNIZED, "pyproject.toml": '[project]\nlicense = "MIT"\n'})

        assert found["license"]["name"] == "MIT" and found["license"]["files"] == ["LICENSE"]

    def test_a_license_file_that_is_not_recognized_stays_so_when_the_manifest_is_no_better(
        self, tmp_path: Path
    ) -> None:
        found = stock_of(tmp_path, {"LICENSE": UNRECOGNIZED, "setup.cfg": "[metadata]\nlicense = Proprietary\n"})

        assert found["license"]["name"] is None and found["license"]["kind"] == "other"


class TestWhatNeedsAGpu:
    @pytest.mark.parametrize(
        ("file", "text", "signal"),
        [
            ("requirements.txt", "cupy-cuda12x==13.0\n", "cupy"),
            ("requirements.txt", "torch==2.0.1+cu118\n", "a CUDA build of PyTorch"),
            ("requirements.txt", "tensorflow-gpu==2.10\n", "tensorflow-gpu"),
            ("requirements.txt", "flash-attn\n", "flash-attn"),
            ("requirements.txt", "faiss-gpu\n", "faiss-gpu"),
            ("environment.yml", "dependencies:\n  - cudatoolkit=11.8\n", "cudatoolkit"),
            ("environment.yml", "dependencies:\n  - cuml=23.10\n", "RAPIDS"),
            ("Dockerfile", "FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04\n", "an NVIDIA CUDA base image"),
        ],
    )
    def test_what_is_installed_for_a_gpu_is_a_need(self, tmp_path: Path, file: str, text: str, signal: str) -> None:
        found = stock_of(tmp_path, {file: text, "a.py": "x = 1\n"})

        assert found["gpu"]["required"] == [{"path": file, "signal": signal, "kind": "dependency"}]
        assert found["gpu"]["optional"] == []

    def test_packages_that_only_look_like_them_are_not(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"requirements.txt": "scipy\ntensorflow\ntorch==2.0.1\ncupboard\n"})

        assert found["gpu"] == {"required": [], "optional": []}

    def test_code_that_asks_for_cuda_outright_is_a_need(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"model.py": "model = Net().cuda()\n", "run.py": 'device = "cuda"\n'})

        assert {item["signal"] for item in found["gpu"]["required"]} == {".cuda()", 'device="cuda"'}

    def test_code_that_looks_for_a_gpu_and_goes_on_without_one_only_may_use_it(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {"model.py": "model = Net().cuda()\n", "dev.py": "use = torch.cuda.is_available()\n"},
        )

        assert found["gpu"]["required"] == []
        assert [item["signal"] for item in found["gpu"]["optional"]] == [".cuda()"]

    def test_a_dependency_is_a_need_and_code_that_looks_for_a_gpu_is_still_only_a_use_of_one(
        self, tmp_path: Path
    ) -> None:
        found = stock_of(
            tmp_path,
            {"requirements.txt": "cupy-cuda12x\n", "model.py": "m.cuda()\n", "dev.py": "torch.cuda.is_available()\n"},
        )

        assert [item["kind"] for item in found["gpu"]["required"]] == ["dependency"]
        assert [item["signal"] for item in found["gpu"]["optional"]] == [".cuda()"]

    def test_a_readme_that_says_it_needs_one_is_a_need(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"README.md": "# Tool\n\nThis tool requires an NVIDIA GPU with 16 GB of memory.\n"})

        assert [item["kind"] for item in found["gpu"]["required"]] == ["readme"]

    def test_a_readme_that_only_mentions_gpus_is_not(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"README.md": "Runs on a laptop; GPUs are not needed.\n"})

        assert found["gpu"]["required"] == []

    def test_cuda_source_files_are_a_need(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"kernels/add.cu": "__global__ void add() {}\n"})

        assert found["gpu"]["required"][0]["signal"] == "CUDA source code"
        assert found["languages"][0]["name"] == "CUDA"

    def test_the_code_of_the_tests_is_not_looked_at_for_it(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {"tests/test_gpu.py": "x.cuda()\n", "a.py": "x = 1\n"})

        assert found["gpu"]["required"] == []


class TestDataAndModels:
    def test_big_files_of_data_and_models_are_listed_largest_first_and_small_ones_are_not(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "data/cells.h5ad": bytes(300_000),
                "data/small.csv": "a,b\n1,2\n",
                "data/table.csv": bytes(80_000),
                "weights/model.pt": bytes(120_000),
            },
        )

        assert found["data"]["count"] == 3
        assert found["data"]["bytes"] == 500_000
        assert [(item["path"], item["kind"]) for item in found["data"]["listed"]] == [
            ("data/cells.h5ad", "data"),
            ("weights/model.pt", "model"),
            ("data/table.csv", "data"),
        ]

    def test_files_that_are_pointers_to_lfs_are_found_and_the_project_says_it_uses_it(self, tmp_path: Path) -> None:
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "b" * 64 + "\nsize 99999999\n"
        found = stock_of(tmp_path, {"d/a.h5ad": pointer, "d/b.npz": pointer, "c.py": "x = 1\n"})

        assert found["data"]["lfs_pointers"] == 2 and found["data"]["lfs"] is True

    def test_a_gitattributes_that_uses_lfs_says_so_with_no_pointers_found(self, tmp_path: Path) -> None:
        found = stock_of(tmp_path, {".gitattributes": "*.h5ad filter=lfs diff=lfs merge=lfs -text\n"})

        assert found["data"]["lfs"] is True and found["data"]["lfs_pointers"] == 0

    def test_a_project_that_uses_dvc_says_so(self, tmp_path: Path) -> None:
        assert stock_of(tmp_path, {"data/raw.csv.dvc": "outs:\n- md5: abc\n"})["data"]["dvc"] is True
        assert stock_of(tmp_path / "other", {"dvc.yaml": "stages: {}\n"})["data"]["dvc"] is True

    def test_links_to_where_data_is_kept_and_accessions_are_found_in_the_readme_and_notebooks(
        self, tmp_path: Path
    ) -> None:
        found = stock_of(
            tmp_path,
            {
                "README.md": "Data: https://zenodo.org/records/1234567. See https://github.com/o/n for code.\n"
                "Also GSE123456 on GEO.",
                "n.ipynb": notebook(
                    ["x = 1"],
                    markdown=[
                        "Get https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE99999 and "
                        "https://springernature.figshare.com/articles/dataset/x/1 or https://example.org/data."
                    ],
                ),
            },
        )

        assert sorted(found["data"]["links"]) == [
            "https://springernature.figshare.com/articles/dataset/x/1",
            "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE99999",
            "https://zenodo.org/records/1234567",
        ]
        assert found["data"]["accessions"] == ["GSE123456", "GSE99999"]

    @pytest.mark.parametrize(
        ("address", "leads"),
        [
            ("https://zenodo.org/records/1", True),
            ("https://sandbox.zenodo.org/records/1", True),
            ("https://huggingface.co/datasets/o/n", True),
            ("https://huggingface.co/o/model", False),
            ("https://ncbi.nlm.nih.gov/geo/x", True),
            ("https://ncbi.nlm.nih.gov/pubmed/1", False),
            ("https://notzenodo.org/records/1", False),
            ("https://example.org/zenodo.org/1", False),
            ("http://[bad", False),
        ],
    )
    def test_which_addresses_are_of_where_data_is_kept(self, address: str, leads: bool) -> None:
        assert stocking.leads_to_data(address) is leads

    def test_submodules_are_listed_with_where_they_are_from(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {".gitmodules": '[submodule "ext"]\n\tpath = ext/lib\n\turl = https://github.com/o/lib\n'},
        )

        assert found["submodules"] == [{"path": "ext/lib", "url": "https://github.com/o/lib"}]


class TestTheReadme:
    @pytest.mark.parametrize(
        ("text", "example"),
        [
            ("# Tool\n\n## Usage\n\n```python\nimport tool\n```\n", True),
            ("# Tool\n\n## Quick start\n\nRun it.\n", True),
            ("# Tool\n\nExample:\n\n```\ntool run\n```\n", True),
            ("# Tool\n\nIt does things.\n", False),
        ],
    )
    def test_it_says_whether_the_readme_shows_how_it_is_used(self, tmp_path: Path, text: str, example: bool) -> None:
        assert stock_of(tmp_path, {"README.md": text})["readme"] == {"path": "README.md", "example": example}


class TestWhatWouldStopExamplesRunningElsewhere:
    def test_a_tutorial_that_reads_from_someones_computer_is_found(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "examples/run.py": 'data = read("/home/jsmith/project/data.csv")\n',
                "tutorials/t.ipynb": notebook(['df = pd.read_csv("/Users/asha/Desktop/x.csv")']),
                "examples/fine.py": 'data = read("data/x.csv")\n',
                "src/lib.py": 'path = "/home/jsmith/lib"\n',
            },
        )

        assert found["absolute_paths"]["count"] == 2
        assert sorted(item["path"] for item in found["absolute_paths"]["listed"]) == [
            "examples/run.py",
            "tutorials/t.ipynb",
        ]
        assert found["absolute_paths"]["listed"][0]["example"].startswith(("/home/jsmith/", "/Users/asha/"))


class TestNothingIsRun:
    def test_the_files_of_a_project_are_only_read(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "RAN"
        program = f"open({str(sentinel)!r}, 'w').close()\n"
        stock_of(
            tmp_path,
            {
                "setup.py": program,
                "conftest.py": program,
                "examples/run.py": program,
                "n.ipynb": notebook([program]),
                "Makefile": f"all:\n\ttouch {sentinel}\n",
                "run.sh": f"touch {sentinel}\n",
            },
        )

        assert not sentinel.exists()

    def test_a_file_that_is_not_text_is_skipped_and_one_that_is_too_big_to_read_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(stocking, "MAX_READ_BYTES", 1000)
        found = stock_of(
            tmp_path,
            {"binary.py": b"\x00\x01\x02" * 100, "huge.py": "x.cuda()\n" + "# pad\n" * 1000, "README.md": "# hi\n"},
        )

        assert found["gpu"]["required"] == []
        assert found["languages"][0]["name"] == "Python"

    def test_how_much_is_read_in_all_is_limited_and_it_says_when_it_ran_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(stocking, "MAX_TOTAL_READ", 50)
        found = stock_of(
            tmp_path, {f"examples/e{number}.py": "print('a long enough line of code')\n" for number in range(5)}
        )

        assert found["complete"] is False


class TestTheShapeOfAStock:
    def test_what_is_made_is_a_stock_and_stays_one_through_json(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "README.md": "## Usage\n\n```\nx\n```\n",
                "LICENSE": MIT,
                "requirements.txt": "numpy==1\n",
                "examples/a.ipynb": notebook(["x"]),
                "data/big.csv": bytes(60_000),
            },
        )

        assert is_stock(found)
        assert is_stock(json.loads(json.dumps(found)))

    @pytest.mark.parametrize(
        "edit",
        [
            lambda stock: stock.pop("data"),
            lambda stock: stock["data"].pop("count"),
            lambda stock: stock.update(files="many"),
            lambda stock: stock.update(files=True),
            lambda stock: stock.update(schema=2),
            lambda stock: stock["languages"].append({"name": 1}),
            lambda stock: stock.update(license={"files": []}),
            lambda stock: stock["tests"].update(listed=[1]),
            lambda stock: stock.update(readme="yes"),
        ],
    )
    def test_one_that_was_edited_is_not(self, tmp_path: Path, edit: Any) -> None:
        found = json.loads(
            json.dumps(stock_of(tmp_path, {"a.py": "x", "README.md": "# x", "LICENSE": MIT, "examples/a.py": "y"}))
        )
        edit(found)

        assert not is_stock(found)

    @pytest.mark.parametrize("value", [None, [], "stock", 3])
    def test_what_is_not_a_dictionary_is_not(self, value: Any) -> None:
        assert not is_stock(value)
