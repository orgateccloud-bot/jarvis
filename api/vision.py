"""
JARVIS Vision System
Screen capture, OCR, and visual analysis.
"""

VISION_AVAILABLE = False

try:
    import mss
    import numpy as np
    import cv2
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    VISION_AVAILABLE = True
    print("[JARVIS] Vision system initialized")
except ImportError as e:
    print(f"[JARVIS] Vision dependencies missing: {e}")
except Exception as e:
    print(f"[JARVIS] Vision init error: {e}")


def capture_screen():
    if not VISION_AVAILABLE:
        return None
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except Exception as e:
        print(f"[JARVIS] Screen capture error: {e}")
        return None


def read_screen_text() -> str:
    if not VISION_AVAILABLE:
        return ""
    try:
        img = capture_screen()
        if img is None:
            return ""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray, lang="por+eng")
        return text.strip()[:2000]
    except Exception as e:
        print(f"[JARVIS] OCR error: {e}")
        return ""


def analyze_screen() -> str:
    """Backward compatible wrapper."""
    text = read_screen_text()
    return text if text else "Tela sem conteudo detectavel."


def get_vision_status() -> dict:
    return {"available": VISION_AVAILABLE}
