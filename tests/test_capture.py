import cv2
import numpy as np

from focusguard.capture import verkleinere_jpeg


def dekodiere(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def test_lange_kante():
    data = verkleinere_jpeg(np.zeros((1440, 2560, 3), np.uint8), 1280)
    assert data[:2] == b"\xff\xd8" and dekodiere(data).shape[:2] == (720, 1280)


def test_hochformat_und_kein_vergroessern():
    assert dekodiere(verkleinere_jpeg(np.zeros((2000, 1000, 3), np.uint8), 1280)).shape[:2] == (1280, 640)
    assert dekodiere(verkleinere_jpeg(np.zeros((480, 640, 3), np.uint8), 1280)).shape[:2] == (480, 640)


def test_bgra():
    assert dekodiere(verkleinere_jpeg(np.zeros((100, 200, 4), np.uint8), 1280)).shape == (100, 200, 3)
