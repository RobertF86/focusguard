from focusguard.sensors.verwaltung import SensorVerwaltung


class FakeThread:
    alle = []

    def __init__(self, name, schritt, intervall_s, ausgabe, fehler, beim_stopp=None, **kw):
        self.name, self.laeuft, self.beim_stopp = name, False, beim_stopp
        FakeThread.alle.append(self)

    def start(self):
        self.laeuft = True

    def stoppe(self):
        self.laeuft = False

    def join(self, timeout=None):
        pass


class FakeKameraSensor:
    def __init__(self, smartphone):
        self.smartphone, self.problem = smartphone, None

    def schritt(self):
        return []

    def schliesse(self):
        pass


def test_setze_und_stoppe():
    FakeThread.alle = []
    kameras = []
    v = SensorVerwaltung(print, print, lambda: (lambda: []),
                         lambda sp: kameras.append(FakeKameraSensor(sp)) or kameras[-1], FakeThread)
    v.setze(True, False, False)
    assert [(t.name, t.laeuft) for t in FakeThread.alle] == [("pc", True)]
    v.setze(True, True, False)
    assert kameras[-1].smartphone is False
    v.setze(True, True, True)
    assert kameras[-1].smartphone is True and len(kameras) == 2
    assert [t.laeuft for t in FakeThread.alle if t.name == "kamera"] == [False, True]
    v.setze(False, False, False)
    assert not any(t.laeuft for t in FakeThread.alle)
    v.setze(True, True, True)
    v.stoppe()
    assert not any(t.laeuft for t in FakeThread.alle)
