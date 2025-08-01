# config.py
import os

TEXTBOOKS_API = os.getenv("TEXTBOOKS_API", "https://staticapis.pragament.com/textbooks/allbooks.json")
DATA_DIR = os.getenv("DATA_DIR", "structured_data")
TEXTBOOK_PAGES_DIR = os.getenv("TEXTBOOK_PAGES_DIR", "textbook_pages")
FONTS_DIR = os.getenv("FONTS_DIR", "fonts")
CONTENT_DIR = os.getenv("CONTENT_DIR", "textbook_content")
TEXT_LIMIT = int(os.getenv("TEXT_LIMIT", 3000))