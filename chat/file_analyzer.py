import os
import pdfplumber
import pandas as pd

from chat.providers.nvidia_vision_provider import extract_text_from_image
from chat.services.provider_manager import get_provider

# Image attachment OCR now runs entirely through NVIDIA vision models
# (chat/providers/nvidia_vision_provider.py) instead of a local pytesseract
# install - "no Tesseract, no OCR library, everything must use NVIDIA Vision."
_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def analyze_file(filepath):

    if filepath.endswith(".pdf"):

        text = ""

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += page.extract_text()

        return text[:2000]


    elif filepath.endswith(".csv"):

        df = pd.read_csv(filepath)

        return f"""
CSV FILE ANALYSIS

Rows: {df.shape[0]}
Columns: {df.shape[1]}

Columns:
{list(df.columns)}

Preview:
{df.head().to_string()}
"""


    elif filepath.endswith(".txt"):

        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()

        return text[:2000]


    elif filepath.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):

        ext = os.path.splitext(filepath)[1].lower()
        mime_type = _IMAGE_MIME_TYPES.get(ext, "image/png")

        with open(filepath, "rb") as f:
            image_bytes = f.read()

        api_key = get_provider("nvidia").api_key
        text = extract_text_from_image(api_key, image_bytes, mime_type)

        return f"""
IMAGE TEXT DETECTED:

{text}
"""

    return "Unsupported file type"
