import pdfplumber
import pandas as pd
from PIL import Image
import pytesseract


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


    elif filepath.endswith(".jpg") or filepath.endswith(".png"):

        img = Image.open(filepath)

        text = pytesseract.image_to_string(img)

        return f"""
IMAGE TEXT DETECTED:

{text}
"""

    return "Unsupported file type"