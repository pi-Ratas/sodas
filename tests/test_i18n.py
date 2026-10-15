"""The interface's languages: the dictionaries the browser gets and the extraction of the Lithuanian texts."""
import json
import unittest

from kalba_sodas import i18n
from kalba_sodas.i18n import istraukti


class DictionaryTests(unittest.TestCase):
    def test_every_language_has_a_script_and_lithuanian_needs_no_dictionary(self):
        self.assertEqual(set(i18n.LANGS), {"lt", "en", "lv", "pl", "uk", "be", "ru", "de", "fr", "es", "it", "pt", "ar", "ja", "zh"})
        self.assertEqual(i18n.dictionary("lt"), {})
        for lang in i18n.LANGS:
            body = i18n.script(lang)
            self.assertTrue(body.startswith("window.SODAS_I18N = "))
            data = json.loads(body.removeprefix("window.SODAS_I18N = ").rstrip().rstrip(";"))
            self.assertEqual(data["lang"], lang)
        self.assertEqual(json.loads(i18n.script("xx").split(" = ", 1)[1].rstrip().rstrip(";"))["lang"], i18n.DEFAULT)

    def test_translations_keep_the_placeholders_of_their_text(self):
        keys = i18n.read_tsv(i18n.HERE / "raktai.tsv")
        for lang in i18n.LANGS:
            if lang == "lt":
                continue
            for k, v in i18n.read_tsv(i18n.HERE / f"{lang}.tsv").items():
                self.assertTrue(k in keys, f"{lang}.tsv: numerio {k} nėra raktai.tsv")
                self.assertEqual(sorted(set(istraukti.re.findall(r"\{\d+\}", keys[k]))), sorted(set(istraukti.re.findall(r"\{\d+\}", v))),
                                 f"{lang}.tsv {k}: {keys[k]!r} → {v!r}")


class ExtractionTests(unittest.TestCase):
    def test_texts_of_scripts_and_markup(self):
        out = set()
        istraukti.from_js('toast(`Ištrinta ${n} mazgų`); el.className = "kb-avatar big"; const re = /["<]/g; '
                          'x.innerHTML = `<button title="Uždaryti">×</button><b>${esc(a)}</b> Nauja grupė`;', out)
        self.assertEqual(out, {"Ištrinta {0} mazgų", "Uždaryti", "Nauja grupė"})

    def test_python_messages_become_patterns(self):
        out = set()
        istraukti.from_py('def f(g):\n    """Docstring – ne."""\n    raise ValueError(f"grupė „{g}“ nerasta")\n', out)
        self.assertEqual(out, {"grupė „{0}“ nerasta"})


if __name__ == "__main__":
    unittest.main()
