import math

import numpy as np
import pytest

from focusguard.sensors.gesicht import pitch_aus_matrix
from focusguard.sensors.handy import handy_score
from focusguard.sensors.kamera import KameraSensor
from focusguard.sensors.modelle import stelle_modell_bereit, ModellFehler
from focusguard.models import WebcamBeobachtung, HandyBeobachtung
from focusguard.clock import TestUhr


def rx(grad):
    c, s = math.cos(math.radians(grad)), math.sin(math.radians(grad))
    m = np.eye(4)
    m[1:3, 1:3] = [[c, -s], [s, c]]
    return m


def test_pitch():
    assert pitch_aus_matrix(np.eye(4)) == pytest.approx(0)
    assert pitch_aus_matrix(rx(25)) == pytest.approx(25) and pitch_aus_matrix(rx(-10)) == pytest.approx(-10)


def test_handy_score():
    assert handy_score([("cell phone", 0.7), ("person", 0.9), ("cell phone", 0.4)]) == 0.7
    assert handy_score([]) == 0.0


class FakeKamera:
    def __init__(self, auf=True):
        self.auf, self.versuche, self.offen = auf, 0, False

    def oeffne(self):
        self.versuche += 1
        self.offen = self.auf
        return self.auf

    def lies(self):
        return np.zeros((480, 640, 3), np.uint8) if self.offen else None

    def schliesse(self):
        self.offen = False


class Fix:
    def __init__(self, wert):
        self.wert = wert

    def analysiere(self, bild):
        return self.wert


def test_kamera_sensor_liefert():
    u = TestUhr(5)
    s = KameraSensor(FakeKamera(), Fix((True, 12.0)), Fix(0.8), u)
    assert s.schritt() == [WebcamBeobachtung(5, True, 12.0), HandyBeobachtung(5, True, 0.8)]
    s2 = KameraSensor(FakeKamera(), Fix((False, None)), Fix(0.3), u)
    assert s2.schritt()[1] == HandyBeobachtung(5, False, 0.3)
    assert KameraSensor(FakeKamera(), Fix((True, 1.0)), None, u).schritt() == [WebcamBeobachtung(5, True, 1.0)]


def test_kamera_nicht_verfuegbar_neuer_versuch_nach_30_s():
    u, k = TestUhr(0), FakeKamera(auf=False)
    s = KameraSensor(k, Fix((True, 0.0)), None, u)
    assert s.schritt() == [] and s.problem == "Kamera nicht verfügbar" and k.versuche == 1
    u.vor(10)
    s.schritt()
    assert k.versuche == 1
    u.vor(21)
    k.auf = True
    assert len(s.schritt()) == 1 and s.problem is None


def test_modell_einmal_laden(tmp_path):
    aufrufe = []

    def lade(url, ziel):
        aufrufe.append(url)
        ziel.write_bytes(b"modell")

    p = stelle_modell_bereit("m.task", "https://x/m.task", tmp_path, lade)
    stelle_modell_bereit("m.task", "https://x/m.task", tmp_path, lade)
    assert p.read_bytes() == b"modell" and len(aufrufe) == 1

    def kaputt(url, ziel):
        raise OSError("offline")

    with pytest.raises(ModellFehler):
        stelle_modell_bereit("n.task", "https://x/n.task", tmp_path, kaputt)


def test_standard_download_mit_timeout(tmp_path, monkeypatch):
    import io
    from focusguard.sensors import modelle
    gesehen = {}

    def urlopen(url, timeout=None):
        gesehen["timeout"] = timeout
        return io.BytesIO(b"daten")

    monkeypatch.setattr(modelle.urllib.request, "urlopen", urlopen)
    p = stelle_modell_bereit("x.task", "https://x/x.task", tmp_path)
    assert p.read_bytes() == b"daten" and gesehen["timeout"] == 30
