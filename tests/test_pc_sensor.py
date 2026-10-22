import os

from focusguard.sensors.pc import beobachtung_aus, PcSensor


def test_beobachtung_aus():
    b = beobachtung_aus(5.0, 42, "Chrome.EXE", "YouTube", "youtube.com/watch")
    assert (b.prozess, b.domain, b.ist_browser, b.fenster_id) == ("chrome.exe", "youtube.com", True, 42)


def test_pc_sensor_ignoriert_eigenes_fenster():
    s = PcSensor(lambda: (1, os.getpid(), "python.exe", "FocusGuard"), lambda f, p: None, lambda: 1.0, os.getpid())
    assert s.schritt() == []


def test_kein_fenster():
    assert PcSensor(lambda: None, lambda f, p: None, lambda: 1.0, 1).schritt() == []


def test_url_nur_bei_titelwechsel_und_nur_lesbare_browser():
    aufrufe, fenster = [], {"v": (7, 99, "chrome.exe", "A")}
    s = PcSensor(lambda: fenster["v"], lambda f, p: aufrufe.append(f) or "https://a.org", lambda: 1.0, 1)
    assert s.schritt()[0].domain == "a.org"
    s.schritt()
    assert len(aufrufe) == 1
    fenster["v"] = (7, 99, "chrome.exe", "B")
    s.schritt()
    assert len(aufrufe) == 2
    fenster["v"] = (8, 98, "firefox.exe", "C")
    [b] = s.schritt()
    assert b.url is None and len(aufrufe) == 2


def test_eigenes_fenster_wiederholt_letzte_fremde_beobachtung():
    uhr = {"t": 1.0}
    fenster = {"v": (7, 99, "chrome.exe", "Insta")}
    s = PcSensor(lambda: fenster["v"], lambda f, p: "https://instagram.com", lambda: uhr["t"], os.getpid())
    s.schritt()
    fenster["v"] = (1, os.getpid(), "python.exe", "FocusGuard")
    uhr["t"] = 9.0
    [b] = s.schritt()
    assert (b.prozess, b.fenstertitel, b.fenster_id, b.domain, b.zeit) == ("chrome.exe", "Insta", 7, "instagram.com", 9.0)
