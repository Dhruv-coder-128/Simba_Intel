
import os
from dotenv import load_dotenv
from pathlib import Path


def load_env():
    base_dir = Path(__file__).resolve().parent.parent.parent
    load_dotenv(os.path.join(base_dir, ".env"))


def get_env_var(key: str, default: str = "") -> str:
    return os.getenv(key, default)


load_env()
