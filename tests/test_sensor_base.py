import threading
import time

from focusguard.sensors.base import AbsturzZaehler, SensorThread


def test_absturzzaehler():
    z = AbsturzZaehler(3, 300)
    assert z.absturz(0) and z.absturz(10) and not z.absturz(20)
    z2 = AbsturzZaehler(3, 300)
    assert z2.absturz(0) and z2.absturz(100) and z2.absturz(400)


def warte(bedingung, s=2.0):
    ende = time.time() + s
    while time.time() < ende and not bedingung():
        time.sleep(0.01)
    return bedingung()


def test_liefert_und_stoppt():
    raus, gestoppt = [], threading.Event()
    t = SensorThread("pc", lambda: ["x"], 0.01, raus.append, lambda *a: None, beim_stopp=gestoppt.set)
    t.start()
    assert warte(lambda: len(raus) >= 3)
    t.stoppe()
    t.join(1)
    assert not t.is_alive() and gestoppt.is_set()


def test_neustart_und_aufgeben():
    zaehler, raus, fehler = {"n": 0}, [], []

    def schritt():
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            raise RuntimeError("kaputt")
        return ["ok"]

    t = SensorThread("pc", schritt, 0.01, raus.append, lambda n, m: fehler.append(m), neustart_s=0.01)
    t.start()
    assert warte(lambda: raus)
    t.stoppe()
    t.join(1)
    assert len(fehler) == 1 and "kaputt" in fehler[0]

    fehler2 = []

    def immer():
        raise RuntimeError("immer")

    t2 = SensorThread("cam", immer, 0.01, raus.append, lambda n, m: fehler2.append(m), neustart_s=0.01)
    t2.start()
    t2.join(2)
    assert not t2.is_alive() and fehler2[-1] == "Sensor dauerhaft ausgeschaltet"
