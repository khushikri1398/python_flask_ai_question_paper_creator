import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import os
import hashlib
import logging
from datetime import datetime
import ollama
from config import TEXTBOOKS_API, DATA_DIR, CONTENT_DIR, TEXT_LIMIT

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def normalize_class(class_name):
    """Normalize class name (e.g., 'Class 10' -> '10')."""
    if not class_name:
        return ''
    class_name = class_name.lower().replace('class', '').strip()
    return class_name

def normalize_subject(subject, class_name):
    """Normalize subject name."""
    if not subject:
        return ''
    subject = subject.lower().strip()
    subject_map = {
        'math': 'maths',
        'mathematics': 'maths',
        # Add more mappings as needed
    }
    return subject_map.get(subject, subject)

def fetch_textbooks_list(api_url, board, class_name, subject):
    """Fetch textbooks and return s3_folder for the matching book."""
    try:
        # Cache the API response
        cache_path = os.path.join(DATA_DIR, 'allbooks.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                textbooks = json.load(f)
            logger.info("Using cached allbooks.json")
        else:
            session = requests.Session()
            retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
            session.mount('https://', HTTPAdapter(max_retries=retries))
            response = session.get(api_url, headers={}, timeout=30)
            response.raise_for_status()
            textbooks = response.json()
            os.makedirs(DATA_DIR, exist_ok=True, mode=0o755)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(textbooks, f, indent=4)
            logger.info(f"Cached allbooks.json to {cache_path}")

        books = textbooks.get('data', {}).get('getBooks', [])
        if not isinstance(books, list):
            logger.error("Invalid textbook API response structure")
            return None

        logger.info(f"Fetched {len(books)} textbooks from {api_url}")

        # Normalize inputs
        normalized_board = board.lower().strip()
        normalized_class = normalize_class(class_name).lower().strip()
        normalized_subject = normalize_subject(subject, normalized_class).lower().strip()

        for book in books:
            book_board = book.get('board', '').lower().strip()
            book_class = book.get('class', '').lower().strip()
            book_subject = book.get('subject', '').lower().strip()
            if (book_board == normalized_board and
                book_class == normalized_class and
                book_subject == normalized_subject):
                s3_folder = book.get('s3_folder')
                if s3_folder:
                    logger.info(f"Found book {book.get('id')} with s3_folder: {s3_folder}")
                    return s3_folder
                logger.warning(f"No s3_folder for book {book.get('id')}")
                return None
        logger.warning(f"No matching textbook for board: {board}, class: {class_name}, subject: {subject}")
        return None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch textbooks: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from {api_url}: {e}")
        return None

def generate_educational_content(board, class_name, subject, chapter_number, chapter_name, content_types=None):
    """Generate educational content for a specific chapter based on metadata."""
    try:
        if not chapter_number or not isinstance(chapter_number, int):
            logger.error(f"Invalid chapter_number: {chapter_number}")
            return [], "Invalid chapter number"
        if not chapter_name or not isinstance(chapter_name, str):
            logger.error(f"Invalid chapter_name: {chapter_name}")
            return [], "Invalid chapter name"
        if not board or not class_name or not subject:
            logger.error(f"Invalid metadata: board={board}, class={class_name}, subject={subject}")
            return [], "Invalid board, class, or subject"

        if content_types is None:
            content_types = [
                "Chapter Summaries", "Important Points", "Definition Bank", "Formula Sheet",
                "Concept Explanation", "Solved Examples", "Practice Questions", "Quiz Creation",
                "Fill in the Blanks", "True/False", "Higher Order Thinking (HOTS)", "Real Life Applications"
            ]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        content_dir = os.path.join(CONTENT_DIR, f"content_{timestamp}")
        os.makedirs(content_dir, exist_ok=True, mode=0o755)
        logger.info(f"Created unique directory: {content_dir}")

        try:
            ollama.list()
            logger.info("Ollama is available.")
        except Exception as e:
            logger.warning(f"Ollama is not available: {e}")
            return [], f"Ollama service unavailable: {e}"

        output_paths = []
        errors = []
        for content_type in content_types:
            output_path = os.path.join(content_dir, f"{content_type.lower().replace(' ', '')}{chapter_number}.json")
            content_data = {
                "content_type": content_type,
                "chapter_number": chapter_number,
                "chapter_name": chapter_name,
                "board": board,
                "class": class_name,
                "subject": subject,
                "generated_content": {}
            }
            try:
                prompt = f"""
                Generate educational content for the following:
                - Board: {board}
                - Class: {class_name}
                - Subject: {subject}
                - Chapter: {chapter_name}
                - Chapter Number: {chapter_number}
                - Content Type: {content_type}
                No page content available. Generate content based on the chapter title and subject context.
                """
                logger.info(f"Generating {content_type} for {subject} - {chapter_name} using chapter metadata")
                generated_content = generate_content_with_ollama(
                    prompt=prompt,
                    content_type=content_type,
                    chapter_number=chapter_number,
                    chapter_name=chapter_name,
                    text_limit=TEXT_LIMIT
                )
                content_data["generated_content"][content_type] = generated_content['content']
            except Exception as e:
                logger.error(f"Error generating {content_type} for {subject} - {chapter_name}: {e}")
                content_data["generated_content"][content_type] = f"Error: {e}"
                errors.append(f"Error generating {content_type} for {subject} - {chapter_name}: {e}")

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(content_data, f, indent=4)
            output_paths.append(output_path)
            logger.info(f"Generated {content_type}: {output_path}")

        return output_paths, "; ".join(errors) if errors else None
    except Exception as e:
        logger.error(f"Error in generate_educational_content: {e}")
        return [], str(e)

def generate_content_with_ollama(prompt, content_type, chapter_number, chapter_name, text_limit=200):
    """Generate content using Ollama for a specific content type."""
    try:
        prompt_templates = {
            "Chapter Summaries": f"Summarize the following chapter content in {text_limit} words or less, suitable for a class 10 student:\n{prompt}",
            "Important Points": f"List 5-7 key points or formulas from the following chapter content, in simple language:\n{prompt}",
            "Definition Bank": f"Extract 3-5 key terms and their definitions from the following chapter content, in simple words:\n{prompt}",
            "Formula Sheet": f"List all formulas from the following chapter content with a brief explanation for each:\n{prompt}",
            "Concept Explanation": f"Explain the main concepts from the following chapter content in simple terms, suitable for a class 10 student:\n{prompt}",
            "Solved Examples": f"Create 2-3 solved example problems based on the following chapter content:\n{prompt}",
            "Practice Questions": f"Generate 5 practice questions (with answers) based on the following chapter content:\n{prompt}",
            "Quiz Creation": f"Create a 5-question multiple-choice quiz (with 4 options and correct answers) based on the following chapter content:\n{prompt}",
            "Fill in the Blanks": f"Generate 5 fill-in-the-blank questions (with answers) based on the following chapter content:\n{prompt}",
            "True/False": f"Generate 5 true/false questions (with answers) based on the following chapter content:\n{prompt}",
            "Higher Order Thinking (HOTS)": f"Generate 3 higher-order thinking questions based on the following chapter content:\n{prompt}",
            "Real Life Applications": f"Describe 2-3 real-life applications of the concepts in the following chapter content:\n{prompt}"
        }

        final_prompt = prompt_templates.get(content_type, prompt)
        response = ollama.generate(model='llama3', prompt=final_prompt)
        generated_text = response.get('response', '').strip()
        
        if not generated_text:
            logger.warning(f"No content generated for {content_type} in chapter {chapter_number} ({chapter_name})")
            return {'content': f"No {content_type} generated for chapter {chapter_number} ({chapter_name}). Please check the input content."}

        words = generated_text.split()
        if len(words) > text_limit:
            generated_text = ' '.join(words[:text_limit]) + '...'
        
        logger.info(f"Generated {content_type} for chapter {chapter_number} ({chapter_name}): {generated_text[:100]}...")
        return {'content': generated_text}
    except Exception as e:
        logger.error(f"Error generating {content_type} for chapter {chapter_number} ({chapter_name}): {e}")
        return {'content': f"Error generating {content_type}: {str(e)}"}