import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from focusguard.models import AufgabenListen, Status  # noqa: E402
from focusguard.auswertung import Auswertung  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def knopf(widget, text):
    return next(b for b in widget.findChildren(QtWidgets.QPushButton) if b.text() == text)


def test_overlay_knoepfe_und_esc(app):
    from focusguard.ui.overlay import Overlay
    log = []
    o = Overlay(lambda: log.append("zurueck"), lambda q: log.append(q))
    o.zeige("Zurück zu: Blender", "Instagram", "domain:instagram.com")
    assert o.ist_offen
    knopf(o.fenster[0], "Gehört zur Aufgabe").click()
    assert log == ["domain:instagram.com"] and not o.ist_offen
    o.zeige("t", "x", "q")
    QTest.keyClick(o.fenster[0], Qt.Key_Escape)
    assert log[-1] == "zurueck" and not o.ist_offen


def test_start_dialog_mit_vorschlag(app):
    from focusguard.ui.start_dialog import StartDialog
    d = StartDialog(lambda a: None, lambda a: AufgabenListen(fokus_programme=("blender.exe",)), ausfuehren=lambda f: f())
    assert not knopf(d, "Weiter").isEnabled()
    d.findChild(QtWidgets.QLineEdit, "aufgabe").setText("Blender lernen")
    knopf(d, "Weiter").click()
    app.processEvents()
    knopf(d, "Session starten").click()
    aufgabe, dauer, listen = d.ergebnis()
    assert (aufgabe, dauer, listen.fokus_programme) == ("Blender lernen", 25, ("blender.exe",))


def test_start_dialog_nutzt_gespeicherte_listen(app):
    from focusguard.ui.start_dialog import StartDialog
    aufrufe = []
    d = StartDialog(lambda a: AufgabenListen(fokus_domains=("blender.org",)), lambda a: aufrufe.append(a),
                    ausfuehren=lambda f: f())
    d.findChild(QtWidgets.QLineEdit, "aufgabe").setText("Blender lernen")
    assert knopf(d, "Weiter").isEnabled()
    knopf(d, "Weiter").click()
    knopf(d, "Session starten").click()
    assert d.ergebnis()[2].fokus_domains == ("blender.org",) and aufrufe == []


def test_auswertungsfenster(app):
    from focusguard.ui.report import AuswertungsFenster
    a = Auswertung(1, "Blender", 0.0, 12, 50, True, {Status.FOKUS: 600.0}, 0.83, [("domain:instagram.com", 2, 90.0)],
                   {1: 2}, 1, 0, 0, 5, 0.01)
    f = AuswertungsFenster(a, [a])
    texte = " ".join(l.text() for l in f.findChildren(QtWidgets.QLabel))
    assert "83%" in texte and "vorzeitig beendet nach 12 von 50 min" in texte


def test_tray_menue(app):
    from focusguard.ui.tray import Tray
    log = []
    cb = {n: (lambda *a, n=n: log.append((n, *a))) for n in
          ("bei_start", "bei_ende", "bei_sensor", "bei_aufheben", "bei_einstellungen", "bei_auswertung",
           "bei_beenden", "zurueck", "gehoert")}
    t = Tray(sensoren=(True, True, False), **cb)
    texte = [a.text() for a in t.contextMenu().actions() if a.text()]
    assert texte == ["Session starten …", "Session beenden", "PC", "Webcam", "Smartphone", "Sperren aufheben",
                     "Einstellungen …", "Auswertung …", "Beenden"]
    smartphone = next(a for a in t.contextMenu().actions() if a.text() == "Smartphone")
    assert not smartphone.isChecked()
    smartphone.trigger()
    assert log[-1] == ("bei_sensor", "smartphone", True)
    t.setze_session_aktiv(False)
    assert not next(a for a in t.contextMenu().actions() if a.text() == "Session beenden").isEnabled()
