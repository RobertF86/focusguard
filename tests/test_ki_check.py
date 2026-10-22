import importlib.util
import json
import pathlib

from focusguard.ai.client import KiRohAntwort

spec = importlib.util.spec_from_file_location("ki_check", pathlib.Path(__file__).parents[1] / "tools" / "ki_check.py")
ki_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ki_check)


def test_pruefe_zaehlt_treffer(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8x")
    (tmp_path / "b.jpg").write_bytes(b"\xff\xd8y")
    (tmp_path / "erwartet.toml").write_text(
        '[[fall]]\ndatei = "a.jpg"\nart = "seite"\naufgabe = "Blender"\nerwartet = "fokus"\nprozess = "blender.exe"\n'
        '[[fall]]\ndatei = "b.jpg"\nart = "handy"\naufgabe = "Blender"\nerwartet = "abgelenkt"\n')
    antwort = json.dumps({"status": "fokus", "begruendung": "x", "sicherheit": 0.9, "gilt_fuer": "seite"})
    faelle = ki_check.lade_faelle(tmp_path)
    assert ki_check.pruefe(faelle, tmp_path, lambda kw: KiRohAntwort(antwort, 1, 1), "claude-haiku-5-5") == (1, 2)
