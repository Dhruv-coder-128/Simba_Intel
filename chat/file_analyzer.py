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


_CODE_AND_TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".xml", ".yaml", ".yml", ".log", ".env", ".sql",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".sass",
    ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs", ".rs", ".go",
    ".php", ".rb", ".swift", ".kt", ".sh", ".bash", ".zsh", ".bat", ".ps1",
    ".ini", ".cfg", ".conf", ".toml", ".tsv",
}


def analyze_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        text = ""
        try:
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text[:4000].strip() if text else "No extractable text found in PDF."
        except Exception as e:
            return f"Error reading PDF: {e}"

    elif ext == ".csv":
        try:
            df = pd.read_csv(filepath)
            return f"""CSV FILE ANALYSIS
Rows: {df.shape[0]}
Columns: {df.shape[1]}

Columns:
{list(df.columns)}

Preview:
{df.head().to_string()}
"""
        except Exception:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()[:4000]
            except Exception as e:
                return f"Error reading CSV: {e}"

    elif ext in _CODE_AND_TEXT_EXTENSIONS:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return content[:4000]
        except Exception as e:
            return f"Error reading file: {e}"

    elif ext in _IMAGE_MIME_TYPES:
        mime_type = _IMAGE_MIME_TYPES.get(ext, "image/png")
        try:
            with open(filepath, "rb") as f:
                image_bytes = f.read()

            api_key = get_provider("nvidia").api_key
            text = extract_text_from_image(api_key, image_bytes, mime_type)
            return f"""IMAGE TEXT DETECTED:

{text}
"""
        except Exception as e:
            return f"Image OCR analysis unavailable: {e}"

    return "Unsupported file type"
