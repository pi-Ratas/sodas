"""Dataset download: a GitHub archive is unpacked into the folder datasets.yaml names (no network in tests)."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from kalba_import import download as dl
from kalba_import.import_all import IMPORT_ORDER


def fake_archive(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class DownloadTests(unittest.TestCase):
    def test_every_dataset_has_a_pinned_source(self):
        self.assertEqual(set(dl.CATALOG), set(IMPORT_ORDER))
        for src in dl.CATALOG.values():
            self.assertRegex(src.commit, r"^[0-9a-f]{40}$")
            self.assertTrue(src.archive.startswith("https://codeload.github.com/"))

    def test_download_unpacks_into_the_configured_folder_and_keeps_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "datasets.yaml"
            dl.ensure_config(config)
            data = fake_archive({"phoible-abc/cldf/values.csv": "ID\n1\n", "phoible-abc/README.md": "x"})
            r = dl.download("phoible", config, progress=lambda m: None, opener=lambda req, timeout: FakeResponse(data))
            target = Path(r["path"])
            self.assertEqual(target, (Path(tmp) / "duomenynai" / "phoible").resolve())
            self.assertTrue((target / "cldf" / "values.csv").exists())
            self.assertEqual(json.loads((target / dl.MARKER).read_text())["version"], dl.CATALOG["phoible"].version)
            again = dl.download("phoible", config, progress=lambda m: None, opener=lambda req, timeout: FakeResponse(data))
            self.assertEqual(again["status"], "skipped")

    def test_a_path_outside_the_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "datasets.yaml"
            dl.ensure_config(config)
            evil = fake_archive({"../../evil.txt": "x"})
            with self.assertRaises(ValueError):
                dl.download("wals", config, progress=lambda m: None, opener=lambda req, timeout: FakeResponse(evil))
            self.assertFalse((Path(tmp) / "evil.txt").exists())
            self.assertFalse((Path(tmp) / "duomenynai" / "wals").exists())


if __name__ == "__main__":
    unittest.main()
