from focusguard.steuerung import Steuerung
from focusguard.storage import Speicher
from focusguard.clock import TestUhr
from focusguard.models import AufgabenListen, KiArt, KiErgebnis, KiUrteil, Status
from hilfen import pc, einst


class FakeUi:
    def __init__(self):
        self.log = []

    def __getattr__(self, name):
        return lambda *a: self.log.append((name, *a))

    def namen(self):
        return [x[0] for x in self.log]


class FakeSensoren:
    def __init__(self):
        self.gesetzt, self.gestoppt = [], False

    def setze(self, *a):
        self.gesetzt.append(a)

    def stoppe(self):
        self.gestoppt = True

    def problem(self):
        return None

    def kamera_jpeg(self):
        return None


class FakeBlocker:
    def __init__(self):
        self.gesperrt = []

    def pruefe(self, b, gesperrt, fokus):
        self.gesperrt.append(gesperrt)
        return None


class FakeRichter:
    def __init__(self):
        self.anfragen, self.geleert, self.pausen = [], False, []

    def einreihen(self, a, aufgabe):
        self.anfragen.append(a)

    def leeren(self):
        self.geleert = True

    def setze_bildschirm_pause(self, an):
        self.pausen.append(an)


def aufbau(dauer=50, richter=True):
    u, ui, sens, bl = TestUhr(1000.0), FakeUi(), FakeSensoren(), FakeBlocker()
    r = FakeRichter() if richter else None
    st = Steuerung(einst(), Speicher(":memory:"), ui, lambda aus, feh: sens, bl, r, u)
    st.starte_session("Blender lernen", dauer, AufgabenListen(fokus_programme=("blender.exe",)))
    return st, u, ui, sens, bl, r


def ticks(st, u, sekunden, beob=None):
    for _ in range(int(sekunden * 4)):
        if beob:
            st.beobachtung(beob(u()))
        u.vor(0.25)
        st.tick()


def arten(st):
    return [e.art for e in st._speicher.ereignisse(st._session.id)]


def test_start():
    st, u, ui, sens, bl, r = aufbau()
    assert st.aktiv and sens.gesetzt == [(True, True, True)] and ("icon", "gruen") in ui.log
    assert arten(st) == ["statuswechsel"]


def test_ablenkung_hinweis_mit_aufgabe():
    st, u, ui, *_ = aufbau()
    ticks(st, u, 11, lambda t: pc(url="https://instagram.com", zeit=t))
    [h] = [x for x in ui.log if x[0] == "hinweis"]
    assert "Blender lernen" in h[1]
    assert "eskalation" in arten(st)


def test_unklare_seite_eingereiht_und_ergebnis_gespeichert():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 1, lambda t: pc(url="https://example.org", titel="T", zeit=t))
    [a] = r.anfragen
    assert a.art is KiArt.SEITE
    st.ki_ergebnis(KiErgebnis(a, KiUrteil(Status.FOKUS, "passt", 0.9, "seite"), None, 1000, 20))
    ticks(st, u, 0.25)
    assert len(st._speicher.lade_gedaechtnis("blender lernen")) == 1 and "ki_aufruf" in arten(st)


def test_ohne_richter_keine_anfragen():
    st, u, *_ = aufbau(richter=False)
    ticks(st, u, 1, lambda t: pc(url="https://example.org", zeit=t))   # must not raise


def test_stufe3_sperrt_und_aufheben():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 72, lambda t: pc(url="https://instagram.com", zeit=t))
    assert "domain:instagram.com" in bl.gesperrt[-1]
    st.sperren_aufheben()
    ticks(st, u, 0.25, lambda t: pc(url="https://instagram.com", zeit=t))
    assert bl.gesperrt[-1] == frozenset() and "sperre_aufgehoben" in arten(st)


def test_gehoert_zur_aufgabe():
    st, u, ui, *_ = aufbau()
    ticks(st, u, 45, lambda t: pc(url="https://instagram.com", zeit=t))
    st.gehoert_zur_aufgabe("domain:instagram.com")
    assert "instagram.com" in st._speicher.lade_listen("blender lernen").fokus_domains
    assert ui.namen()[-2:] == ["overlay_schliessen", "icon"] and "korrektur" in arten(st)


def test_session_endet_nach_ablauf():
    st, u, ui, sens, *_ = aufbau(dauer=1)
    ticks(st, u, 61)
    assert not st.aktiv and sens.gestoppt and ("hinweis", "Session geschafft!") in ui.log
    assert "zeige_auswertung" in ui.namen()
    [s] = st._speicher.sessions_seit(0)
    assert s.vorzeitig_beendet is False


def test_vorzeitig_beenden_schliesst_overlay_und_hebt_sperren_auf():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 72, lambda t: pc(url="https://instagram.com", zeit=t))
    st.beende_session(vorzeitig=True)
    assert "overlay_schliessen" in ui.namen() and ("icon", "grau") in ui.log and sens.gestoppt and r.geleert
    assert ("hinweis", "Session geschafft!") not in ui.log
    [s] = st._speicher.sessions_seit(0)
    assert s.vorzeitig_beendet is True
    st.beende_session(vorzeitig=True)                       # second call is a no-op


def test_checkbox_und_sensorfehler():
    st, u, ui, sens, *_ = aufbau()
    st.setze_sensoren(True, False, True)
    st.sensor_fehler("kamera", "kaputt")
    ticks(st, u, 0.25)
    assert sens.gesetzt[-1] == (True, False, True) and {"checkbox", "sensor_fehler"} <= set(arten(st))
    st.sensor_fehler("kamera", "Sensor dauerhaft ausgeschaltet")
    ticks(st, u, 0.25)
    assert "kamera-Sensor ausgeschaltet" in [x for x in ui.log if x[0] == "tooltip"][-1][1]


def test_ki_ergebnis_nach_sessionende_ignoriert():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 1, lambda t: pc(url="https://example.org", zeit=t))
    [a] = r.anfragen
    st.beende_session(vorzeitig=True)
    st.ki_ergebnis(KiErgebnis(a, KiUrteil(Status.FOKUS, "x", 0.9, "seite"), None))
    st.tick()  # must not raise


def _bestaetige_stichprobe(st, u, r, beob):
    """Zwei Stichproben in Folge melden Ablenkung, danach gilt sie als bestätigt."""
    ticks(st, u, 121, beob)
    for _ in range(2):
        a = [x for x in r.anfragen if x.art is KiArt.STICHPROBE][-1]
        st.ki_ergebnis(KiErgebnis(a, KiUrteil(Status.ABGELENKT, "Video auf Monitor 2", 0.9, "seite"), None))
        ticks(st, u, 31, beob)


def test_zurueck_zur_aufgabe_beendet_stichproben_ablenkung():
    st, u, ui, sens, bl, r = aufbau()
    blender = lambda t: pc("blender.exe", zeit=t)
    _bestaetige_stichprobe(st, u, r, blender)
    ticks(st, u, 15, blender)
    assert "overlay_zeigen" in ui.namen()
    st.zurueck_zur_aufgabe()
    ui.log.clear()
    ticks(st, u, 20, blender)
    assert "overlay_zeigen" not in ui.namen() and "hinweis" not in ui.namen()


def test_korrektur_deckt_keine_stichprobe_auf():
    st, u, ui, sens, bl, r = aufbau()
    insta = lambda t: pc(url="https://instagram.com", zeit=t)
    _bestaetige_stichprobe(st, u, r, insta)
    st.gehoert_zur_aufgabe("domain:instagram.com")
    ui.log.clear()
    ticks(st, u, 20, insta)
    assert "overlay_zeigen" not in ui.namen() and "hinweis" not in ui.namen()


def test_overlay_pausiert_bildschirm_anfragen():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 41, lambda t: pc(url="https://instagram.com", zeit=t))
    assert r.pausen[-1] is True
    ticks(st, u, 1, lambda t: pc("blender.exe", zeit=t))
    assert r.pausen[-1] is False
    assert st.aktuelle_pc().prozess == "blender.exe"
