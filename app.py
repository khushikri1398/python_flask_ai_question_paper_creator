import re
import os
import json
import pprint
import requests
import subprocess
import io
import uuid
from fpdf import FPDF
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session,flash
from markupsafe import Markup
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from collections import defaultdict
import csv
from datetime import datetime
import ollama
from content_generate import fetch_textbooks_list, generate_educational_content, generate_content_with_ollama
import logging
from config import TEXTBOOKS_API, DATA_DIR, FONTS_DIR, CONTENT_DIR, TEXT_LIMIT
from flask import send_from_directory
import os.path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
import traceback


# Imports for SVG Generation
import xml.etree.ElementTree as ET
from time import sleep, time
from urllib.parse import quote
from tenacity import retry, stop_after_attempt, wait_exponential

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

TEXTBOOK_CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'textbook_content')
if not os.path.exists(TEXTBOOK_CONTENT_DIR):
    os.makedirs(TEXTBOOK_CONTENT_DIR)

os.makedirs(CONTENT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)
app.secret_key = os.urandom(24)


TEXTBOOKS_API = "https://staticapis.pragament.com/textbooks/allbooks.json"
SVG_DIR = os.path.join("static", "svgs") # Directory to store generated SVGs

SUBJECT_NAME_MAP_BY_CLASS = {
    "Mathematics": {
        "10": "Mathematics",
        "9": "Maths",
        "8": "Mathematics",
        "7": "Mathematics",
        "6": "Mathematics",
        "5": "Mathematics",
        "4": "Maths",
    }
}

def sanitize_ollama_json(raw_str):
    """
    Fixes malformed JSON responses from the Ollama model.
    - Removes trailing commas
    - Converts invalid answer objects to lists
    """
    # Fix trailing commas before } or ]
    raw_str = re.sub(r',\s*([\]}])', r'\1', raw_str)

    # Fix malformed 'answers' objects
    def fix_answers_block(match):
        answer_block = match.group(1)
        tokens = re.findall(r'"([^"]+)"', answer_block)
        all_items = []
        for item in tokens:
            all_items.extend([s.strip() for s in item.split(',')])
        unique_items = list(dict.fromkeys(filter(None, all_items)))
        return '"answers": ' + json.dumps(unique_items)

    raw_str = re.sub(r'"answers"\s*:\s*\[({[^}]+})\]', fix_answers_block, raw_str)
    return raw_str

# ------------------------------- Fill in the Blanks (FIB) Generation Functions -------------------------------

import json
import logging
import re
import ollama

# Setup a logger (if you don't have one already)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sanitize_ollama_json(raw_str):
    # Fix trailing commas before a closing bracket or brace
    return re.sub(r',\s*([\]}])', r'\1', raw_str)

def generate_fib_content(subject, chapter, topic, subtopic):
    """
    Generates Fill-in-the-Blank content with a new constraint for answer length.
    """
    # **FIX:** Added a constraint for answer length to the prompt.
    prompt = f"""
IMPORTANT: Return only a single valid JSON object. No markdown, no commentary, no explanations.

Subject: "{subject}"
Chapter: "{chapter}"
Topic: "{topic}"
Subtopic: "{subtopic}"

1. Write a 100-150 word paragraph explaining the subtopic.
2. Select 8 key single-word concepts. **Each word must be 9 letters or fewer.**
3. Replace them with blanks (_______) in the paragraph.
4. Create a word bank of the 8 words.
5. Create 8 fill-in-the-blank questions based on the paragraph.Each sentence should be a statement (not a question) and have one of the keywords replaced by a single '______' placeholder.
6. Provide the 8 words as answers. **Each answer must be a single word and 9 letters or fewer.**

Return only JSON with these keys:
- "paragraph"
- "word_bank"
- "questions":(This key will contain the list of fill-in-the-blank sentences)
- "answers"
"""
    try:
        response = ollama.chat(model="llama3", messages=[{"role": "user", "content": prompt}])
        raw_output = response['message']['content']
        json_start = raw_output.find('{')
        json_end = raw_output.rfind('}') + 1

        if json_start == -1 or json_end == 0:
            return {"error": "The AI model's response did not contain a JSON object."}

        json_str = raw_output[json_start:json_end]
        cleaned_output = sanitize_ollama_json(json_str)
        parsed = json.loads(cleaned_output)
        
        required_keys = ["paragraph", "word_bank", "questions", "answers"]
        if all(k in parsed for k in required_keys):
            return parsed
        else:
            return {"error": "The AI-generated JSON is missing required keys."}

    except Exception as e:
        logger.error(f"Error during FIB generation: {e}")
        return {"error": "The AI model returned a malformed JSON object that could not be repaired."} 


def generate_fib_pdf_v2(content, filename, show_answers=False, marker_path=None):
    """
    Generates a Fill-in-the-Blank PDF.
    - Student version uses a two-column layout with one set of 9 boxes at the rightmost, right-aligned text.
    - Omits second line if answer is the last word.
    - Dynamically adjusts question width, no space on right.
    - Teacher version uses a simple answer list format.
    - Updated layout: Instructions in a box with border, info boxes in a table with labels, paragraph and answer bank in separate sections, questions with boxes aligned right, footer with centered signatures.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import os

    doc_width, doc_height = A4
    margin = 2.5 * cm
    doc = SimpleDocTemplate(filename, pagesize=A4, topMargin=margin, bottomMargin=margin, leftMargin=margin, rightMargin=margin)
    styles = getSampleStyleSheet()

    # Define custom styles
    styles.add(ParagraphStyle(name='AnswerKeyTitle', fontSize=14, alignment=1, spaceAfter=12, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='SectionHeader', fontSize=10, fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name='Instructions', fontSize=8, leading=10))
    styles.add(ParagraphStyle(name='AnswerBank', fontSize=9, leading=12))
    styles.add(ParagraphStyle(name='MainParagraph', fontSize=9, leading=11, spaceAfter=12))
    styles.add(ParagraphStyle(name='QuestionStyle', fontSize=9, leading=12, alignment=0, spaceAfter=2))  # Left-aligned
    styles.add(ParagraphStyle(name='PostBoxText', fontSize=9, leading=12, alignment=0, leftIndent=0, spaceBefore=0))

    story = []
    box_style = TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER')
    ])
    available_width = doc_width - (2 * margin)
    box_width = 0.5 * cm
    num_boxes = 9
    blank_width = num_boxes * box_width

    # === TEACHER'S ANSWER KEY (Simple List Format) ===
    if show_answers:
        story.append(Paragraph("Worksheet & Answer Key", styles['AnswerKeyTitle']))
        story.append(Paragraph(content.get("paragraph", ""), styles['MainParagraph']))
        story.append(Paragraph("Word Bank:", styles['SectionHeader']))
        word_bank_str = ", ".join(content.get("word_bank", []))
        story.append(Paragraph(word_bank_str, styles['AnswerBank']))
        story.append(Spacer(1, 1 * cm))
        story.append(Paragraph("Fill in the blanks:", styles['SectionHeader']))
        questions = content.get("questions", [])
        for i, q_text in enumerate(questions):
            story.append(Paragraph(f"{i+1}. {q_text.replace('______', '___________')}", styles['QuestionStyle']))
            story.append(Spacer(1, 0.2 * cm))
        story.append(Spacer(1, 1.5 * cm))
        story.append(Paragraph("■ Answer Key (for teachers only):", styles['SectionHeader']))
        answers = content.get("answers", [])
        for i, ans_text in enumerate(answers):
            story.append(Paragraph(f"<b>{i+1}.</b> {ans_text}", styles['QuestionStyle']))
        doc.build(story)
        return

    # === STUDENT WORKSHEET (Updated Two-Column Layout) ===
    # 1. Instructions in a bordered box
    instructions_text = """
    <b>Instructions for filling the sheet:</b><br/>
    • Don't fold the sheet. Use only ball pen. Read the given paragraph carefully.<br/>
    • Below the paragraph, you will find questions with blanks.<br/>
    • Use the Answer Bank provided to fill in the blanks with the most appropriate word(s).<br/>
    • Each word/phrase from the Answer Bank can be used only once, unless stated otherwise.<br/>
    • Write only the correct word(s) in the blank space provided.<br/>
    • Spelling errors may result in the loss of marks.<br/>
    • Do not use words that are not in the Answer Bank.<br/>
    • <b>Only use <i>UPPER CASE CAPITAL LETTER ALPHABETS</i> in the boxes.</b>
    """
    instructions_table = Table([[Paragraph(instructions_text, styles['Instructions'])]], colWidths=[available_width], style=TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5)
    ]))
    story.append(instructions_table)
    story.append(Spacer(1, 0.4 * cm))

    # 2. Info Boxes in a table with labels
    info_table_data = [
        [Paragraph("<b>Admission number</b>", styles['Instructions']), Table([[''] * 12], colWidths=[0.5 * cm] * 12, rowHeights=0.5 * cm, style=box_style)],
        [Paragraph("<b>Student Name</b>", styles['Instructions']), Table([[''] * 24], colWidths=[0.5 * cm] * 24, rowHeights=0.5 * cm, style=box_style)],
        [Paragraph("<b>Class</b>", styles['Instructions']), Table([[''] * 2], colWidths=[0.5 * cm] * 2, rowHeights=0.5 * cm, style=box_style),
         Paragraph("<b>Section</b>", styles['Instructions']), Table([[''] * 2], colWidths=[0.5 * cm] * 2, rowHeights=0.5 * cm, style=box_style),
         Paragraph("<b>Date (ddmmyyyy)</b>", styles['Instructions']), Table([[''] * 8], colWidths=[0.5 * cm] * 8, rowHeights=0.5 * cm, style=box_style)]
    ]
    info_table = Table(info_table_data, colWidths=[2.5 * cm, 6 * cm, 1 * cm, 1 * cm, 2 * cm, 4 * cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0)
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.4 * cm))

    # 3. Paragraph and Answer Bank in separate sections
    story.append(Paragraph(f"<b>Paragraph:</b> {content.get('paragraph', '')}", styles['MainParagraph']))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>Answer bank:</b> {', '.join(word.upper() for word in content.get('word_bank', []))}", styles['AnswerBank']))
    story.append(Spacer(1, 0.5 * cm))

    # 4. Questions with Two-Column Layout
    questions = content.get("questions", [])
    for i, sentence in enumerate(questions):
        if '______' in sentence:
            parts = sentence.split('______', 1)
            pre_box_text = parts[0].rstrip()
            post_box_text = parts[1].lstrip() if len(parts) > 1 else ''
            show_post_box = bool(post_box_text and post_box_text.strip())
        else:
            pre_box_text = sentence
            post_box_text = ''
            show_post_box = False
        
        adjusted_question_width = available_width - blank_width
        question_para = Paragraph(f"<b>Q{i+1}.</b> {pre_box_text}", styles['QuestionStyle'])
        blank_table = Table([[''] * num_boxes], colWidths=[box_width] * num_boxes, rowHeights=0.5 * cm, style=box_style)
        
        question_data = [[question_para, blank_table]]
        question_table = Table(question_data, colWidths=[adjusted_question_width, blank_width])
        question_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0)
        ]))
        story.append(question_table)
        
        if show_post_box:
            story.append(Paragraph(post_box_text, styles['PostBoxText']))
        
        story.append(Spacer(1, 0.3 * cm))

    # 5. Footer with centered signatures
    footer_data = [[Paragraph("", styles['Instructions'])],
                   [Paragraph("Invigilator's Signature: __________________", styles['Instructions'])],
                   [Paragraph("Student's Signature: ____________________", styles['Instructions'])]]
    footer_table = Table(footer_data, colWidths=[available_width], style=TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    story.append(Spacer(1, 1 * cm))
    story.append(footer_table)

    def draw_corner_markers(canvas, doc):
        canvas.saveState()
        if marker_path and os.path.exists(marker_path):
            from reportlab.lib.utils import ImageReader
            marker = ImageReader(marker_path)
            positions = [
                (0.5 * cm, doc_height - 1.3 * cm),
                (doc_width - 1.3 * cm, doc_height - 1.3 * cm),
                (0.5 * cm, 0.5 * cm),
                (doc_width - 1.3 * cm, 0.5 * cm)
            ]
            for x, y in positions:
                canvas.drawImage(marker, x, y, width=0.8 * cm, height=0.8 * cm, mask='auto')
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_corner_markers, onLaterPages=draw_corner_markers)

# ------------------------------- SVG Generation Functions (IMPROVED) -------------------------------

# Namespaces
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
ET.register_namespace('', SVG_NAMESPACE)
ET.register_namespace('dc', DC_NAMESPACE)

# Rate limiting config
MAX_RETRIES = 3
BASE_DELAY = 2  # seconds
GITHUB_API_DELAY = 1  # seconds between GitHub API requests

def fetch_topics():
    logger.info("📚 Fetching topics list...")
    try:
        api_url = "https://api.github.com/repos/Pragament/json_data/contents/textbooks/page_attributes"
        response = safe_github_request(api_url)
        files = [f for f in response.json() if f['name'].endswith('.json')]

        topics = []
        for file in files[:25]:
            try:
                file_response = safe_raw_request(file['download_url'])
                content = file_response.text.strip()
                if not content.startswith(('{', '[')):
                    continue
                data = json.loads(content)
                if isinstance(data, dict):
                    topic = data.get('title') or data.get('name')
                    if topic:
                        topics.append(topic)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            topic = item.get('title') or item.get('name')
                            if topic:
                                topics.append(topic)
            except Exception as e:
                logger.warning(f"⚠️ File processing error for {file['name']}: {e}")
            finally:
                sleep(GITHUB_API_DELAY)
        if not topics:
            return get_fallback_topics()
        return list(dict.fromkeys(topics))[:25]
    except Exception as e:
        logger.error(f"⚠️ GitHub processing error: {e}")
        return get_fallback_topics()

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=BASE_DELAY))
def safe_github_request(url):
    response = requests.get(url)
    if response.status_code == 403:
        reset_time = int(response.headers.get('X-RateLimit-Reset', 0)) - int(time())
        if reset_time > 0:
            sleep(reset_time)
            raise Exception("Rate limit hit - retrying after reset")
    response.raise_for_status()
    return response

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=BASE_DELAY))
def safe_raw_request(url):
    response = requests.get(url)
    if response.status_code == 429:
        sleep(BASE_DELAY * 2)
        raise Exception("Too Many Requests - retrying")
    response.raise_for_status()
    return response

def get_fallback_topics():
    return [
        "human anatomy", "world map", "electric circuit", "photosynthesis",
        "solar system", "periodic table", "human brain", "digestive system",
        "water cycle", "plant cell", "animal cell", "volcano diagram",
        "rock cycle", "food pyramid", "muscular system", "skeletal system",
        "respiratory system", "heart anatomy", "neuron structure",
        "ecosystem diagram", "climate zones", "tectonic plates",
        "electromagnetic spectrum", "atomic structure", "mitochondria structure"
    ]

def search_wikimedia_svg(topic):
    """
    Searches Wikimedia for SVGs related to the topic and returns up to 5 results.
    """
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f'"{topic}" filetype:svg',
        "srlimit": 5,  # Fetch top 5 results to increase chances of finding a valid one
        "srnamespace": 6
    }
    try:
        response = requests.get("https://commons.wikimedia.org/w/api.php", params=params)
        response.raise_for_status()
        results = response.json().get("query", {}).get("search", [])
        return [item["title"] for item in results] if results else []
    except Exception as e:
        logger.warning(f"⚠️ Search error for {topic}: {e}")
        return []

def get_svg_direct_url(file_title):
    """
    Gets the direct file URL for an SVG from its title.
    """
    params = {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json"
    }
    try:
        response = requests.get("https://commons.wikimedia.org/w/api.php", params=params)
        response.raise_for_status()
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id in pages:
            if "imageinfo" in pages[page_id]:
                return pages[page_id]["imageinfo"][0]["url"]
    except Exception as e:
        logger.error(f"Could not get direct URL for {file_title}: {e}")
    return None

def download_and_validate_svg(file_title, topic):
    """
    Downloads an SVG from a direct URL and validates its content.
    """
    direct_url = get_svg_direct_url(file_title)
    if not direct_url:
        logger.warning(f"Could not resolve direct URL for '{file_title}'. Skipping.")
        return None

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(direct_url, headers=headers, stream=True, timeout=15)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '')
        if 'svg' not in content_type:
            logger.warning(f"Skipping '{file_title}' due to unexpected content type: {content_type}")
            return None

        # Read content for validation before writing
        content_bytes = response.content
        try:
            # Try to decode as utf-8, but fall back to latin-1 if it fails
            content_str = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            content_str = content_bytes.decode('latin-1')


        if not content_str.strip().startswith('<svg'):
            logger.warning(f"Validation failed for '{file_title}'. Content does not start with <svg> tag.")
            return None

        # If validation passes, write the file
        os.makedirs(SVG_DIR, exist_ok=True)
        clean_topic = re.sub(r'\W+', '_', topic.lower())
        filepath = os.path.join(SVG_DIR, f"{clean_topic}.svg")
        
        with open(filepath, "wb") as f:
            f.write(content_bytes)
        
        logger.info(f"✅ Successfully downloaded and validated '{file_title}' for topic '{topic}'.")
        return filepath

    except requests.RequestException as e:
        logger.error(f"Download failed for {direct_url}: {e}")
        return None

def enhance_svg(filepath, topic):
    try:
        if not filepath or not os.path.exists(filepath):
            raise FileNotFoundError("SVG file missing")
        tree = ET.parse(filepath)
        root = tree.getroot()

        # Add title element for accessibility
        title = ET.SubElement(root, "title")
        title.text = f"Educational Diagram: {topic}"

        # Add frontend-compatible attributes
        root.set("data-map-type", "educational")
        root.set("data-zoom-level", "1")
        root.set("data-topic", topic.lower().replace(" ", "-"))

        # Add metadata section with proper namespaces
        metadata = ET.SubElement(root, "metadata")
        dc_title = ET.SubElement(metadata, f"{{{DC_NAMESPACE}}}title")
        dc_title.text = topic
        dc_desc = ET.SubElement(metadata, f"{{{DC_NAMESPACE}}}description")
        dc_desc.text = f"Educational diagram about {topic}"

        tree.write(filepath, xml_declaration=True, encoding="utf-8")
        return filepath
    except Exception as e:
        logger.error(f"⚠️ SVG enhancement failed for {topic}: {e}")
        return filepath

def generate_ai_explanation(filepath, topic):
    try:
        if not filepath or not os.path.exists(filepath):
            raise FileNotFoundError("SVG file missing")
        with open(filepath, "r", encoding="utf-8") as f:
            svg_content = f.read()
        prompt = f"""Analyze this educational SVG diagram and provide:
1. Key elements explanation
2. Real-world applications
3. Common student misconceptions
4. Interactive learning suggestions

SVG Content:
{svg_content}"""
        response = ollama.chat(
            model="mistral",
            messages=[{"role": "user", "content": prompt}]
        )
        clean_topic = re.sub(r'\W+', '_', topic.lower())
        explanation_path = os.path.join(SVG_DIR, f"{clean_topic}_explanation.md")
        with open(explanation_path, "w", encoding="utf-8") as f:
            f.write(f"# Educational Guide\n{response['message']['content']}")
        logger.info(f"📘 Explanation saved: {explanation_path}")
        return explanation_path
    except Exception as e:
        logger.error(f"⚠️ AI explanation failed: {e}")
        return None


def process_topic(topic):
    """
    Orchestrates the process of finding, downloading, enhancing, and explaining an SVG for a topic.
    """
    logger.info(f"\n🔍 Processing topic: {topic}")
    
    # Step 1: Search for multiple potential SVG files
    file_titles = search_wikimedia_svg(topic)
    if not file_titles:
        logger.warning(f"No SVG search results found for '{topic}'.")
        return None, None

    # Step 2: Iterate through results and try to download the first valid one
    svg_path = None
    for title in file_titles:
        logger.info(f"  Attempting to download and validate: {title}")
        svg_path = download_and_validate_svg(title, topic)
        if svg_path:
            break  # Stop after the first success
    
    # Step 3: If no valid SVG was found after trying all results, give up for this topic
    if not svg_path:
        logger.error(f"❌ Failed to find a valid SVG for '{topic}' after trying {len(file_titles)} candidates.")
        return None, None

    # Step 4: Enhance the valid SVG and generate an explanation
    enhanced_path = enhance_svg(svg_path, topic)
    explanation_path = generate_ai_explanation(enhanced_path, topic)
    
    return enhanced_path, explanation_path


# ------------------------------- Original App Functions -------------------------------

def strip_number_prefix(option):
    """Strips a leading number and period (e.g. '1. ') from the option."""
    return re.sub(r'^\s*\d+\.\s*', '', option.strip())

def normalize_chapter_structure(chapter):
    normalized_topics = []
    for topic in chapter.get("topics", []):
        topic_name = topic.get("topic") or topic.get("text")
        subtopics = topic.get("subtopics", [])
        normalized_subtopics = [{"text": sub.get("text")} for sub in subtopics if "text" in sub]
        normalized_topics.append({
            "topic": topic_name,
            "subtopics": normalized_subtopics
        })

    return {
        "number": chapter.get("number"),
        "chapter": chapter.get("chapter"),
        "topics": normalized_topics,
        "reason": chapter.get("reason"),
        "for": chapter.get("for")
    }

def fetch_structured_previous_year_content(
    board,
    starting_class,
    current_class,
    starting_subjects,
    depth=1,
    max_depth=3
):
    if depth > max_depth:
        return {}

    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch textbooks: {e}")
        return {}

    full_structure = {}

    for start_sub in starting_subjects:
        found = False
        for canonical_sub, subject_mapping in SUBJECT_NAME_MAP_BY_CLASS.items():
            if subject_mapping.get(str(starting_class)) == start_sub:
                mapped_current_subject = subject_mapping.get(str(current_class))
                if not mapped_current_subject:
                    print(f"[WARN] ❌ No mapping found for current_class {current_class} under subject '{canonical_sub}'")
                    continue

                print(f"[DEBUG] 🎯 Found match for '{start_sub}' in subject group '{canonical_sub}'")
                print(f"[DEBUG] 🔁 Using mapped subject '{mapped_current_subject}' for class {current_class}")

                # Find the correct book
                book = next(
                    (b for b in textbooks if b.get('board') == board and str(b.get('class')) == str(current_class) and b.get('subject') == mapped_current_subject),
                    None
                )
                if not book:
                    print(f"[WARN] ❌ No book found for subject '{mapped_current_subject}' in class {current_class}")
                    continue

                book_id = book.get("id")
                try:
                    response = requests.get(f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json")
                    response.raise_for_status()
                    data = response.json()
                except requests.RequestException as e:
                    print(f"[ERROR] Failed to fetch book data for '{mapped_current_subject}': {e}")
                    continue

                chapters = sorted([item for item in data if item.get("type") == "chapter"], key=lambda x: x.get('order', 0))
                topics = sorted([item for item in data if item.get("type") == "topic"], key=lambda x: x.get('order', 0))
                subtopics = sorted([item for item in data if item.get("type") == "subtopic"], key=lambda x: x.get('order', 0))

                def extract_prefix(text):
                    match = re.match(r"^([\d\.]+)", text.strip())
                    return match.group(1) if match else None

                topic_prefix_map = {
                    extract_prefix(t.get('text', '')): {
                        "text": t.get("text", ""),
                        "subtopics": []
                    }
                    for t in topics if extract_prefix(t.get('text', ''))
                }

                subtopic_prefix_map = {
                    extract_prefix(s.get('text', '')): s.get('text', '')
                    for s in subtopics if extract_prefix(s.get('text', ''))
                }

                for sub_prefix, sub_text in subtopic_prefix_map.items():
                    parent_prefix = ".".join(sub_prefix.split('.')[:-1])
                    if parent_prefix in topic_prefix_map:
                        topic_prefix_map[parent_prefix]['subtopics'].append({"text": sub_text})

                full_chapter_structure = []
                for idx, ch in enumerate(chapters, start=1):
                    chapter_prefix = str(idx)
                    chapter_topics = []
                    for topic_prefix, topic_data in topic_prefix_map.items():
                        if topic_prefix.startswith(chapter_prefix + "."):
                            chapter_topics.append({
                                "text": topic_data["text"],
                                "subtopics": topic_data["subtopics"]
                            })
                    full_chapter_structure.append({
                        "chapter": ch.get("text", ""),
                        "number": idx,
                        "topics": chapter_topics
                    })

                # ✅ Store using the original subject name from input
                full_structure[start_sub] = full_chapter_structure
                found = True
                break

        if not found:
            print(f"[WARN] ⚠️ No previous year mapping found for subject '{start_sub}'")

    # Save full_structure to file
    os.makedirs("structured_data", exist_ok=True)
    path = f"structured_data/previous_year_depth_{depth}.json"
    with open(path, "w") as f:
        json.dump(full_structure, f, indent=4)

    return full_structure

def build_prerequisite_tree(selected_structure):
    import copy

    # Sort class keys by descending class number
    sorted_classes = sorted(
        selected_structure.keys(),
        key=lambda k: int(k.split('_')[1]),
        reverse=True
    )

    if not sorted_classes:
        return {}

    top_class_key = sorted_classes[0]
    result = copy.deepcopy(selected_structure[top_class_key])  # Start with topmost class chapters

    # Add class info to top level chapters
    for subject, chapters in result.items():
        for chapter in chapters:
            chapter["class"] = top_class_key

    # Create subject → chapter name → chapter dict map for all classes
    all_chapter_map = {}
    for class_key in selected_structure:
        for subject, chapters in selected_structure[class_key].items():
            all_chapter_map.setdefault(subject, {})
            for ch in chapters:
                ch_name = ch.get("chapter")
                if ch_name:
                    ch_copy = copy.deepcopy(ch)
                    ch_copy["class"] = class_key  # 👈 Add class info
                    all_chapter_map[subject][ch_name] = ch_copy

    # Helper to recursively attach prerequisites
    def attach_prerequisites(subject, chapter_name, current_class_index, visited=None):
        if visited is None:
            visited = set()
        if chapter_name in visited:
            return []
        visited.add(chapter_name)

        prerequisites = []
        for lower_class_index in range(current_class_index + 1, len(sorted_classes)):
            class_key = sorted_classes[lower_class_index]
            chapters = selected_structure.get(class_key, {}).get(subject, [])

            for ch in chapters:
                target = ch.get("for")
                ch_name = ch.get("chapter")

                if ch_name in visited:
                    continue

                if target == chapter_name or not target:
                    ch_copy = copy.deepcopy(ch)
                    ch_copy.pop("for", None)
                    ch_copy["class"] = class_key  # 👈 Add class here too
                    ch_copy["prerequisites"] = attach_prerequisites(subject, ch_name, lower_class_index, visited.copy())
                    prerequisites.append(ch_copy)

        return prerequisites

    # Build tree from topmost class downward
    for subject, chapters in result.items():
        for chapter in chapters:
            chapter_name = chapter.get("chapter")
            chapter["prerequisites"] = attach_prerequisites(subject, chapter_name, 0)

    return {top_class_key: result}

def build_prerequisite_tree_minimal(selected_structure):
    import copy

    # Sort class keys like ['class_8', 'class_7', ...]
    sorted_classes = sorted(
        selected_structure.keys(),
        key=lambda k: int(k.split('_')[1]),
        reverse=True
    )

    if not sorted_classes:
        return {}

    top_class_key = sorted_classes[0]
    result = {}

    # Helper to extract minimal chapter info including reason
    def minimal_chapter_obj(ch, class_key):
        obj = {
            "number": ch.get("number"),
            "chapter": ch.get("chapter"),
            "class": class_key
        }
        if ch.get("reason"):
            obj["reason"] = ch["reason"]
        return obj

    # Only attach if 'for' matches a chapter
    def attach_prerequisites(subject, chapter_name, current_class_index, visited=None):
        if visited is None:
            visited = set()
        if (subject, chapter_name) in visited:
            return []
        visited.add((subject, chapter_name))

        prerequisites = []
        for lower_class_index in range(current_class_index + 1, len(sorted_classes)):
            class_key = sorted_classes[lower_class_index]
            chapters = selected_structure.get(class_key, {}).get(subject, [])

            for ch in chapters:
                ch_name = ch.get("chapter")
                target = ch.get("for")
                if target and target.strip() == chapter_name:
                    ch_entry = minimal_chapter_obj(ch, class_key)
                    ch_entry["prerequisites"] = attach_prerequisites(subject, ch_name, lower_class_index, visited)
                    prerequisites.append(ch_entry)

        return prerequisites

    result[top_class_key] = {}
    for subject, chapters in selected_structure[top_class_key].items():
        result[top_class_key][subject] = []
        for ch in chapters:
            chapter_name = ch.get("chapter")
            ch_entry = minimal_chapter_obj(ch, top_class_key)
            ch_entry["prerequisites"] = attach_prerequisites(subject, chapter_name, 0)
            result[top_class_key][subject].append(ch_entry)

    return result

def verify_answer_with_models(question_obj):
    models = ["llama3"]
    responses = []
    model_outputs = {}

    def get_answer_from_model(model_name, prompt_text):
        try:
            print(f"🔍 Running model: {model_name}")
            result = subprocess.run(
                ["ollama", "run", model_name],
                input=prompt_text,
                capture_output=True,
                text=True,
                timeout=180
            )
            answer = result.stdout.strip().lower()
            print(f"✅ Answer from {model_name}: {answer}")
            return answer
        except Exception as e:
            print(f"❌ Error verifying with model {model_name}: {e}")
            return None

    options = [opt.strip() for opt in question_obj["options"]]
    question_text = question_obj["question"]

    # Strip leading option numbering (e.g., '1. ') if present
    stripped_options = []
    for opt in options:
        if opt[:2].isdigit() and opt[2:3] in ['.', ')']:
            stripped_options.append(opt[3:].strip())
        else:
            stripped_options.append(opt)

    # Construct prompt with numbered stripped options
    prompt = f"Question: {question_text}\nOptions:\n"
    for idx, opt in enumerate(stripped_options, 1):
        prompt += f"{idx}. {opt}\n"
    prompt += "\nRespond only with the correct option number (e.g., 1, 2, 3, 4). No explanation, text, or punctuation."

    print(f"\n📤 Prompt sent to models:\n{prompt}\n")

    for idx, model in enumerate(models):
        answer = get_answer_from_model(model, prompt)
        model_outputs[model] = answer
        if answer and answer.strip().isdigit():
            responses.append(int(answer.strip()))

    print(f"\n📥 All model responses: {responses}")

    match_counts = {}
    for resp in responses:
        match_counts[resp] = match_counts.get(resp, 0) + 1

    if match_counts:
        most_common = max(match_counts.items(), key=lambda x: x[1])
        if most_common[1] >= 2:
            question_obj["correct_option"] = most_common[0]
            question_obj["verified"] = True
            print(f"✅ Final verdict: Verified ✅ — Correct option: {most_common[0]}")
        else:
            question_obj["verified"] = False
            print("⚠️ Final verdict: Not Verified — All models gave different answers ❌")
    else:
        question_obj["verified"] = False
        print("❌ Final verdict: Not Verified — No valid numeric responses from models")

    # Store what each model said for frontend visibility
    question_obj["model_responses"] = model_outputs

    print("------------------------------------------------------")

def generate_pdf(data, output_pdf, show_metadata=True):
    from fpdf import FPDF
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    font_path = os.path.join("fonts", "DejaVuSans.ttf")
    if not os.path.exists(font_path):
        raise FileNotFoundError(f"Font file not found at {font_path}. Please add DejaVuSans.ttf to the 'fonts' folder.")

    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.set_font("DejaVu", size=12)

    pdf.cell(200, 10, txt="Generated Question Paper", ln=1, align='C')
    pdf.ln(5)

    for idx, q in enumerate(data.get("questions", []), start=1):
        if(show_metadata):
            tag_line = f"[Class: {q.get('class')}] [Subject: {q.get('subject')}] [Chapter: {q.get('chapter')}] [Topic: {q.get('topic')}]"
            if q.get("subtopic"):
                tag_line += f" [Subtopic: {q.get('subtopic')}]"
            pdf.multi_cell(0, 10, txt=tag_line)
            pdf.ln(1)

        pdf.multi_cell(0, 10, txt=f"{idx}. {q.get('question')}")
        pdf.ln(2)

        for opt in q.get("options", []):
            pdf.cell(0, 10, txt=opt, ln=1)

        correct_num = q.get("correct_option")
        correct_text = (
            q["options"][correct_num - 1]
            if correct_num and 1 <= correct_num <= len(q["options"])
            else "N/A"
        )
        pdf.set_text_color(0, 128, 0)
        pdf.cell(0, 10, txt=f"Correct Answer: {correct_text}", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

    pdf.output(output_pdf)

def generate_prerequisite_pdf(tree):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin_left = 30
    margin_right = 30
    margin_top = 40
    margin_bottom = 40

    y = height - margin_top
    line_height = 22
    max_indent = 80
    sidebar_width = 5

    background_colors = [colors.whitesmoke, colors.lightgrey]
    sidebar_colors = [
        colors.red, colors.orange, colors.green, 
        colors.cadetblue, colors.purple, colors.brown, colors.teal
    ]

    line_counter = 0  # for background color alternation

    def draw_text_block(text, level, font="Helvetica", font_size=11):
        nonlocal y, line_counter

        if y < margin_bottom + line_height:
            c.showPage()
            y = height - margin_top
            line_counter = 0  # reset background alternation

        indent = min(level * 20, max_indent)
        x_pos = margin_left + indent + sidebar_width + 5

        # Draw background band
        bg_color = background_colors[line_counter % 2]
        c.setFillColor(bg_color)
        c.rect(margin_left, y - line_height + 4, width - margin_left - margin_right, line_height, fill=1, stroke=0)

        # Draw left color sidebar
        sidebar_color = sidebar_colors[level % len(sidebar_colors)]
        c.setFillColor(sidebar_color)
        c.rect(margin_left, y - line_height + 4, sidebar_width, line_height, fill=1, stroke=0)

        # Draw text
        c.setFillColor(colors.black)
        c.setFont(font, font_size)
        c.drawString(x_pos, y, text)

        y -= line_height
        line_counter += 1

    def draw_chapters(chapters, level=0):
        for chapter in chapters:
            chapter_text = f"{chapter['chapter']} (Chapter {chapter['number']}, {chapter['class']})"
            draw_text_block(chapter_text, level, font="Helvetica-Bold", font_size=12)

            if "reason" in chapter:
                reason_text = f"Reason: {chapter['reason']}"
                draw_text_block(reason_text, level + 1, font="Helvetica-Oblique", font_size=10)

            if chapter.get("prerequisites"):
                draw_chapters(chapter["prerequisites"], level + 1)

    for class_key, subjects in tree.items():
        for subject, chapters in subjects.items():
            heading_text = f"{subject} - {class_key}"
            draw_text_block(heading_text, 0, font="Helvetica-Bold", font_size=14)
            draw_chapters(chapters, level=1)
            y -= line_height // 2  # small space between subjects

    c.save()
    buffer.seek(0)
    return buffer

def inject_reasons_into_selected_data(selected_data, level):
    render_path = os.path.join("structured_data", f"prereq_render_items_level_{level}.json")
    if not os.path.exists(render_path):
        return

    with open(render_path, "r") as f:
        render_items = json.load(f)

    # Use (subject, chapter, for) as key for better granularity
    enriched_map = {
        (
            (item.get("subject") or "").strip().lower(),
            (item.get("chapter") or "").strip().lower(),
            (item.get("for") or "").strip().lower()
        ): {
            "reason": item.get("reason"),
            "for": item.get("for")
        }
        for item in render_items
    }

    for class_key, subjects_data in selected_data.items():
        for subject, chapter_list in subjects_data.items():
            subj_key = subject.strip().lower()
            for chapter in chapter_list:
                chap_key = (chapter.get("chapter" )or "").strip().lower()
                for_key = (chapter.get("for") or "").strip().lower()
                
                enrichment = enriched_map.get((subj_key, chap_key, for_key))
                if enrichment:
                    chapter["reason"] = enrichment.get("reason")
                    chapter["for"] = enrichment.get("for")

def generate_study_material_pdf(study_material, output_pdf):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        font_path = os.path.join("fonts", "DejaVuSans.ttf")
        bold_font_path = os.path.join("fonts", "DejaVuSans-Bold.ttf")
        italic_font_path = os.path.join("fonts", "DejaVuSans-Oblique.ttf")

        # Register regular font
        if not os.path.exists(font_path):
            logger.warning(f"Font file not found at {font_path}. Falling back to Helvetica.")
            pdf.set_font("Helvetica", size=12)
            use_helvetica = True
        else:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            pdf.set_font("DejaVu", size=12)
            use_helvetica = False

        # Register bold font if available
        if os.path.exists(bold_font_path):
            pdf.add_font("DejaVu", "B", bold_font_path, uni=True)
            has_bold = True
        else:
            logger.warning(f"Bold font file not found at {bold_font_path}. Using regular font for bold text.")
            has_bold = False

        # Register italic font if available
        if os.path.exists(italic_font_path):
            pdf.add_font("DejaVu", "I", italic_font_path, uni=True)
            has_italic = True
        else:
            logger.warning(f"Italic font file not found at {italic_font_path}. Using regular font for italic text.")
            has_italic = False

        # Title
        if use_helvetica:
            pdf.set_font("Helvetica", size=14, style="B" if has_bold else "")
        else:
            pdf.set_font("DejaVu", size=14, style="B" if has_bold else "")
        pdf.cell(200, 10, txt="Study Material", ln=1, align='C')
        pdf.ln(5)

        for subject_data in study_material:
            # Subject heading
            if use_helvetica:
                pdf.set_font("Helvetica", size=14, style="B" if has_bold else "")
            else:
                pdf.set_font("DejaVu", size=14, style="B" if has_bold else "")
            pdf.cell(200, 10, txt=f"Subject: {subject_data['subject']}", ln=1)
            pdf.ln(2)

            for chapter_data in subject_data['chapters']:
                # Chapter heading
                if use_helvetica:
                    pdf.set_font("Helvetica", size=12, style="B" if has_bold else "")
                else:
                    pdf.set_font("DejaVu", size=12, style="B" if has_bold else "")
                pdf.cell(200, 10, txt=f"Chapter {chapter_data['number']}: {chapter_data['chapter']}", ln=1)
                pdf.ln(2)

                for content_type, content in chapter_data['content'].items():
                    if content:
                        # Content type
                        if use_helvetica:
                            pdf.set_font("Helvetica", size=11, style="I" if has_italic else "")
                        else:
                            pdf.set_font("DejaVu", size=11, style="I" if has_italic else "")
                        pdf.cell(200, 10, txt=content_type, ln=1)
                        # Content text
                        if use_helvetica:
                            pdf.set_font("Helvetica", size=10)
                        else:
                            pdf.set_font("DejaVu", size=10)
                        pdf.multi_cell(0, 8, txt=content)
                        pdf.ln(2)
                pdf.ln(4)

        pdf.output(output_pdf)
        logger.info(f"PDF generated successfully at {output_pdf}")
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        raise
# ------------------------------- Routes ----------------------------------

# 1. Home route to display textbooks (index.html)
@app.route('/')
def index():
    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        print(f"Error fetching textbooks: {e}")
        textbooks = []
    return render_template('index.html', textbooks=textbooks, textbooks_json=json.dumps(textbooks))

# 2. Route to handle main selection (select.html)
@app.route('/select', methods=['POST'])
def select():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    errors = []  # Added to collect and display errors in the template

    # Normalize inputs
    normalized_class = normalize_class(class_name)
    normalized_subjects = [normalize_subject(subject) for subject in subjects]
    logger.info(f"Normalized inputs: board={board}, class={normalized_class}, subjects={normalized_subjects}")

    # Fetch textbook data with caching and fallback
    textbooks = fetch_textbooks_list(TEXTBOOKS_API)
    if not textbooks or not textbooks.get('data', {}).get('getBooks', []):
        logger.warning("API returned no textbooks, trying cache")
        textbooks = load_cached_textbooks()
        if not textbooks:
            logger.warning("No cached textbooks, using fallback")
            textbooks = FALLBACK_TEXTBOOKS
            errors.append({
                'message': 'Failed to fetch textbooks from API and cache; using fallback data',
                'is_json_upload_error': False
            })

    # Cache textbooks if newly fetched
    if textbooks and textbooks != load_cached_textbooks():
        save_cached_textbooks(textbooks)

    subject_chapter_map = {}
    chapter_number_to_name_map = {}

    def extract_prefix(text):
        """Extracts numeric prefix like '1.1', '2.1.3' from text."""
        match = re.match(r"^([\d\.]+)", text.strip())
        return match.group(1) if match else None

    for subject in normalized_subjects:
        matching_book = next(
            (book for book in textbooks.get('data', {}).get('getBooks', [])
             if book.get('board') == board and str(book.get('class')) == normalized_class and normalize_subject(book.get('subject')) == subject),
            None
        )

        if not matching_book:
            error_msg = f"No matching textbook found for subject: {subject}, class: {normalized_class}, board: {board}"
            errors.append({'message': error_msg, 'is_json_upload_error': False, 'subject': subject})
            logger.warning(error_msg)
            continue

        book_id = matching_book.get("id")
        try:
            response = requests.get(f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json")
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            error_msg = f"Error fetching page attributes for {subject}: {e}"
            errors.append({'message': error_msg, 'is_json_upload_error': False, 'subject': subject})
            logger.error(error_msg)
            continue

        # Separate and sort by order, with fallback for missing 'order'
        chapters = sorted(
            [item for item in data if item.get("type") == "chapter"],
            key=lambda x: x.get('order', float('inf'))
        )
        topics = sorted(
            [item for item in data if item.get("type") == "topic"],
            key=lambda x: x.get('order', float('inf'))
        )
        subtopics = sorted(
            [item for item in data if item.get("type") == "subtopic"],
            key=lambda x: x.get('order', float('inf'))
        )

        # Map prefixes to clean data
        topic_prefix_map = {
            extract_prefix(t.get('text', '')): {
                "text": t.get("text", ""),
                "subtopics": []
            }
            for t in topics if extract_prefix(t.get('text', ''))
        }

        subtopic_prefix_map = {
            extract_prefix(s.get('text', '')): s.get('text', '')
            for s in subtopics if extract_prefix(s.get('text', ''))
        }

        # Attach subtopics to topics
        for sub_prefix, sub_text in subtopic_prefix_map.items():
            parent_prefix = ".".join(sub_prefix.split('.')[:-1])
            if parent_prefix in topic_prefix_map:
                topic_prefix_map[parent_prefix]['subtopics'].append({"text": sub_text})

        # Attach topics to chapters
        final_chapters = []
        chapter_number_name_map = {}

        for idx, ch in enumerate(chapters, start=1):
            chapter_prefix = str(idx)
            chapter_topics = []

            for topic_prefix, topic_data in topic_prefix_map.items():
                if topic_prefix.startswith(chapter_prefix + "."):
                    chapter_topics.append({
                        "text": topic_data["text"],
                        "subtopics": topic_data["subtopics"]
                    })

            chapter_name = ch.get("text", "")
            if chapter_name:  # Only include chapters with a name
                final_chapters.append({
                    "chapter": chapter_name,
                    "number": idx,
                    "topics": [
                        {
                            "topic": t["text"],
                            "subtopics": t["subtopics"]
                        } for t in chapter_topics
                    ]
                })

                # Map chapter number to name
                chapter_number_name_map[idx] = chapter_name

        if final_chapters:  # Only add subject if chapters are found
            subject_chapter_map[subject] = final_chapters
            chapter_number_to_name_map[subject] = chapter_number_name_map
        else:
            errors.append({
                'message': f"No valid chapters found for {subject} in class {normalized_class}",
                'is_json_upload_error': False,
                'subject': subject
            })
            logger.warning(f"No valid chapters found for {subject}")

    # Create folder if it doesn't exist
    output_folder = "structured_data"
    os.makedirs(output_folder, exist_ok=True)
    output_path = os.path.join(output_folder, "list_of_all_chapters_for_selected_class.json")

    # Save structured data to file
    with open(output_path, "w") as f:
        json.dump(subject_chapter_map, f, indent=4)

    # Store only chapter number-name map in session
    session['chapter_number_to_name_map'] = chapter_number_to_name_map

    return render_template('select.html',
                           board=board,
                           class_name=class_name,
                           subjects=subjects,
                           subject_chapter_map=subject_chapter_map,
                           errors=errors)  # Pass errors to template

# 2.1 Route to handle topic selection for direct question generation (show_selected_chapters.html)
@app.route('/generate_questions_no_prereq', methods=['POST'])
def generate_questions_no_prereq():
    selected_chapters = request.form.getlist('chapters')
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    errors = []  # Added to collect and display errors in the template

    # Normalize inputs
    normalized_class = normalize_class(class_name)
    normalized_subjects = [normalize_subject(subject) for subject in subjects]
    logger.info(f"Normalized inputs: class={normalized_class}, subjects={normalized_subjects}, selected_chapters={selected_chapters}")

    # Parse selected_chapters to extract chapter names
    parsed_chapters = []
    for ch in selected_chapters:
        parts = ch.split('|')
        if len(parts) == 3:
            chapter_name, _, subject = parts
            parsed_chapters.append((normalize_subject(subject), chapter_name))
        else:
            errors.append({
                'message': f"Invalid chapter format: {ch}",
                'is_json_upload_error': False,
                'subject': None
            })
            logger.warning(f"Invalid chapter format: {ch}")

    # Load chapter data
    json_path = os.path.join('structured_data', 'list_of_all_chapters_for_selected_class.json')
    if not os.path.exists(json_path):
        errors.append({
            'message': 'No chapter data available. Please select subjects and chapters again.',
            'is_json_upload_error': False,
            'subject': None
        })
        logger.error(f"Chapter data file not found: {json_path}")
        return render_template(
            'show_selected_chapters.html',
            subject_chapter_map={},
            class_name=class_name,
            errors=errors
        )

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        errors.append({
            'message': f"Error loading chapter data: {str(e)}",
            'is_json_upload_error': False,
            'subject': None
        })
        logger.error(f"Error loading {json_path}: {str(e)}")
        return render_template(
            'show_selected_chapters.html',
            subject_chapter_map={},
            class_name=class_name,
            errors=errors
        )

    # Build subject_chapter_map with topics and subtopics
    subject_chapter_map = {}
    for subject in normalized_subjects:
        subject_data = data.get(subject, [])
        if not subject_data:
            errors.append({
                'message': f"No chapters found for subject: {subject}",
                'is_json_upload_error': False,
                'subject': subject
            })
            logger.warning(f"No chapters found for subject: {subject}")
            continue

        filtered_chapters = [
            chapter for chapter in subject_data
            if any(s == subject and c == chapter['chapter'] for s, c in parsed_chapters)
        ]
        for chapter in filtered_chapters:
            # Ensure topics and subtopics are present
            if 'topics' not in chapter:
                chapter['topics'] = []
                logger.warning(f"No topics found for chapter {chapter['chapter']} in {subject}")
            for topic in chapter['topics']:
                if 'subtopics' not in topic:
                    topic['subtopics'] = []
                # Ensure topic has a 'topic' key (rename 'text' to 'topic' for consistency)
                if 'text' in topic and 'topic' not in topic:
                    topic['topic'] = topic['text']

        if filtered_chapters:
            subject_chapter_map[subject] = filtered_chapters
        else:
            errors.append({
                'message': f"No selected chapters found for subject: {subject}",
                'is_json_upload_error': False,
                'subject': subject
            })
            logger.warning(f"No selected chapters found for subject: {subject}")

    logger.debug(f"subject_chapter_map: {json.dumps(subject_chapter_map, indent=2)}")

    return render_template(
        'show_selected_chapters.html',
        subject_chapter_map=subject_chapter_map,
        class_name=class_name,
        errors=errors
    )

# 2.1.1 Route to handle topic selection for direct question generation (show_selected_chapters.html)
@app.route('/generate_questions_directly', methods=['POST'])
def generate_questions_directly():
    selected_chapters = request.form.getlist("selected_chapters")
    selected_topics = request.form.getlist("selected_topics")
    selected_subtopics = request.form.getlist("selected_subtopics")
    show_metadata = request.form.get("show_metadata", "off")

    def nested_dict():
        return defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"topics": defaultdict(list)})))

    prepared_data = nested_dict()

    def parse_parts(item, expected_parts):
        parts = [p.strip() for p in item.split('|')]
        return parts if len(parts) == expected_parts else None

    for item in selected_chapters:
        parsed = parse_parts(item, 3)
        if parsed:
            chapter, class_name, subject = parsed
            _ = prepared_data[class_name][subject][chapter]["topics"]

    for item in selected_topics:
        parsed = parse_parts(item, 4)
        if parsed:
            chapter, topic, class_name, subject = parsed
            _ = prepared_data[class_name][subject][chapter]["topics"][topic]

    for item in selected_subtopics:
        parsed = parse_parts(item, 5)
        if parsed:
            chapter, topic, subtopic, class_name, subject = parsed
            prepared_data[class_name][subject][chapter]["topics"][topic].append(subtopic)

    final_data = json.loads(json.dumps(prepared_data))
    os.makedirs("structured_data", exist_ok=True)
    
    with open("structured_data/prepared_selected_data_direct.json", "w") as f:
        json.dump(final_data, f, indent=2)

    return redirect(url_for("generate_questions_from_direct", show_metadata=show_metadata))

# 2.1.2 Route to generate questions directly from selected topics (result.html)
@app.route('/generate_questions_from_direct')
def generate_questions_from_direct():
    show_metadata = request.args.get("show_metadata") == "on"

    try:
        with open("structured_data/prepared_selected_data_direct.json", "r") as f:
            selected_data = json.load(f)
    except FileNotFoundError:
        return "Error: prepared_selected_data_direct.json not found."

    all_questions = []
    grouped_targets = []

    for class_key in sorted(selected_data.keys()):
        for subject in sorted(selected_data[class_key].keys()):
            flat_items = []
            for chapter, content in selected_data[class_key][subject].items():
                topics = content.get("topics", {})
                for topic, subtopics in topics.items():
                    if subtopics:
                        for subtopic in subtopics:
                            flat_items.append({
                                "class": class_key,
                                "subject": subject,
                                "chapter": chapter,
                                "topic": topic,
                                "subtopic": subtopic
                            })
                    else:
                        flat_items.append({
                            "class": class_key,
                            "subject": subject,
                            "chapter": chapter,
                            "topic": topic,
                            "subtopic": None
                        })

            if flat_items:
                grouped_targets.append({
                    "class": class_key,
                    "subject": subject,
                    "items": flat_items
                })

    system_prompt = (
        "You are a JSON-only AI. Return strictly valid JSON only. Do NOT include explanations or natural language.\n\n"
        "You are tasked with creating 1 high-quality multiple choice question per topic or subtopic, considering the following:\n"
        "- The question must reflect the difficulty and knowledge level appropriate for the given class (grade level).\n"
        "- Use the chapter name as the primary context.\n"
        "- For subjects like 'Mathematics', ensure questions are **numerical, formula-based, or calculation-oriented**. Avoid generic or theory-based questions.\n"
        "- For theoretical subjects like 'Biology', 'History', or 'Civics', focus on **conceptual understanding** but avoid vague or overly general questions.\n"
        "- Do NOT repeat topics or give trivial questions.\n\n"
        "Each question must include:\n"
        "- 'question': the question string\n"
        "- 'options': a list of 4 strings, each starting with a number and a period (e.g., '1. 32 cm')\n"
        "- 'correct_option': the correct option number (1 to 4), not the text\n"
        "- 'class', 'subject', 'chapter', 'topic', 'subtopic': included as metadata (subtopic can be null)\n\n"
        "Your entire response must be in this format:\n"
        "{ \"questions\": [ { \"class\": ..., \"subject\": ..., \"chapter\": ..., \"topic\": ..., \"subtopic\": ..., \"question\": ..., \"options\": [...], \"correct_option\": 1 }, ... ] }"
    )

    for group in grouped_targets:
        class_key = group["class"]
        subject = group["subject"]
        items = group["items"]

        user_prompt = {
            "task": "Generate 1 MCQ per topic/subtopic using class difficulty and chapter context",
            "class": class_key,
            "subject": subject,
            "items": items
        }

        full_prompt = f"{system_prompt}\n\n---\n\n{json.dumps(user_prompt, indent=2)}"

        try:
            result = subprocess.run(
                ["ollama", "run", "llama3"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=300
            )
            output = result.stdout.strip()
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                output_json = json.loads(output[json_start:json_end])
                questions = output_json.get("questions", [])
                for q in questions:
                    verify_answer_with_models(q)
                all_questions.extend(questions)
        except Exception as e:
            print(f"❌ Error generating for {class_key} > {subject}: {e}")

    if not all_questions:
        return "Error: No questions generated."

    final_output = {"questions": all_questions}

    with open("paper.json", "w") as f:
        json.dump(final_output, f, indent=2)

    generate_pdf(final_output, "Question.pdf", show_metadata)

    return render_template("review_questions.html", questions=final_output["questions"])

# 2.2 Route to handle selected chapters for prerequisite selection (recursive_prereq.html)
@app.route('/generate', methods=['POST'])
def generate():
    # Step 1: Get form data
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    chapters = request.form.getlist("chapters")

    # Save the selected structure to a file for later use (for recursive_prereq)
    output_folder = "structured_data"
    os.makedirs(output_folder, exist_ok=True)
    selected_structure_path = os.path.join(output_folder, "selected_structure.json")
    # Structure: { class_<class>: { subject: [chapter_objects] } }
    selected_structure = {
        f"class_{class_name}": {}
    }
    for subject in subjects:
        selected_structure[f"class_{class_name}"][subject] = []
    # For each selected chapter, try to get the full chapter object from list_of_all_chapters_for_selected_class.json
    chapters_data_path = os.path.join(output_folder, "list_of_all_chapters_for_selected_class.json")
    if os.path.exists(chapters_data_path):
        with open(chapters_data_path, "r") as f:
            all_chapters_by_subject = json.load(f)
    else:
        all_chapters_by_subject = {}
    for subject in subjects:
        subject_chapters = all_chapters_by_subject.get(subject, [])
        for ch_name in chapters:
            matched = next((ch for ch in subject_chapters if ch.get("chapter") == ch_name), None)
            if matched and matched not in selected_structure[f"class_{class_name}"][subject]:
                selected_structure[f"class_{class_name}"][subject].append(normalize_chapter_structure(matched))
    with open(selected_structure_path, "w") as f:
        json.dump(selected_structure, f, indent=4)

    # Store for recursive prerequisite route (minimal session usage)
    session['form_data'] = {
        "board": board,
        "class": class_name,
        "subjects": subjects,
        "chapters": chapters
    }
    # Redirect to recursive prerequisite route (start at level 1)
    return redirect(url_for("recursive_prereq", level=1))

# 2.2.1 Route to handle recursive prerequisite selection (recursive_prereq.html)
@app.route('/recursive_prereq/<int:level>', methods=['GET', 'POST'])
def recursive_prereq(level):
    board = session.get("form_data", {}).get("board")
    class_name = session.get("form_data", {}).get("class")
    subjects = session.get("form_data", {}).get("subjects", [])

    selected_structure_path = os.path.join("structured_data", "selected_structure.json")
    if os.path.exists(selected_structure_path):
        with open(selected_structure_path, "r") as f:
            selected_structure = json.load(f)
    else:
        selected_structure = {}

    selected_chapter_names = selected_structure.get("chapters", [])

    # LAST LEVEL
    if level > 3:
        render_path = os.path.join("structured_data", f"prereq_render_items_level_{level - 1}.json")
        if os.path.exists(render_path):
            with open(render_path, "r") as f:
                render_items = json.load(f)
        else:
            render_items = []

        if request.method == "POST":
            selected_combined = request.form.getlist("selected_prereq_combined")
            selected_topics = request.form.getlist("selected_prereq_topic")
            selected_subtopics = request.form.getlist("selected_prereq_subtopic")

            selected_ids = []
            selected_chapters = []

            for item in selected_combined:
                try:
                    id_, chapter = item.split("|||", 1)
                    selected_ids.append(id_)
                    selected_chapters.append(chapter)
                except ValueError:
                    print(f"⚠️ Skipped invalid combined item: {item}")
                    continue

            print("📌 Received selected_ids from POST:", selected_ids)

            id_map = {item["id"]: item for item in render_items}
            selected_items = [id_map[i] for i in selected_ids if i in id_map]

            if os.path.exists(selected_structure_path):
                with open(selected_structure_path, "r") as f:
                    current_structure = json.load(f)
            else:
                current_structure = {}

            class_key = f"class_{int(class_name) - level + 1}"
            current_structure.setdefault(class_key, {})
            for subject in subjects:
                current_structure[class_key].setdefault(subject, [])

            prev_level = level - 1
            prev_json_path = f"structured_data/previous_year_depth_{prev_level}.json"
            if os.path.exists(prev_json_path):
                with open(prev_json_path, "r") as f:
                    previous_level_data = json.load(f)
            else:
                previous_level_data = {}

            for item in selected_items:
                subject = item["subject"]
                chapter_name = item["chapter"]
                print(f"\n🔄 Selected item ID: {item['id']} | Chapter: {chapter_name} | Subject: {subject}")

                full_chapter_list = previous_level_data.get(subject, [])
                matched = next((ch for ch in full_chapter_list if ch["chapter"] == chapter_name), None)
                if not matched:
                    print(f"❌ No match found in previous level for: {chapter_name}")
                    continue

                chapter_obj = normalize_chapter_structure(matched)
                chapter_obj["for"] = item.get("for")
                chapter_obj["reason"] = item.get("reason")

                existing_chapters = current_structure[class_key][subject]

                def is_duplicate(chapter_obj):
                    return any(
                        existing["chapter"] == chapter_obj["chapter"] and
                        existing.get("for") == chapter_obj.get("for")
                        for existing in existing_chapters
                    )

                if not is_duplicate(chapter_obj):
                    print(f"➕ Adding Chapter: {chapter_obj}")
                    existing_chapters.append(chapter_obj)
                else:
                    print(f"⚠️ Skipping duplicate chapter for same target: {chapter_obj['chapter']} → {chapter_obj.get('for')}")

            # ✅ Match by topic/subtopic
            for subject in previous_level_data:
                for chapter in previous_level_data[subject]:
                    chapter_name = chapter.get("chapter")
                    matched = False
                    for topic in chapter.get("topics", []):
                        if topic.get("topic") in selected_topics or any(
                            sub.get("text") in selected_subtopics for sub in topic.get("subtopics", [])
                        ):
                            matched = True
                            break
                    if matched:
                        chapter_obj = normalize_chapter_structure(chapter)
                        current_structure[class_key][subject].append(chapter_obj)

            with open(selected_structure_path, "w") as f:
                json.dump(current_structure, f, indent=4)

        # ✅ Inject reasons again (for safety)
        with open(selected_structure_path, "r") as f:
            selected_data = json.load(f)

        reason_map = {
            (item.get("subject", "").strip().lower(), item.get("chapter", "").strip().lower(), item.get("for", "").strip().lower()): {
                "reason": item.get("reason"),
                "for": item.get("for")
            }
            for item in render_items
        }

        for class_key, subjects_data in selected_data.items():
            for subject, chapter_list in subjects_data.items():
                subj_key = subject.strip().lower()
                for chapter in chapter_list:
                    chap_key = (chapter.get("chapter") or "").strip().lower()
                    for_key = (chapter.get("for") or "").strip().lower()
                    reason = reason_map.get((subj_key, chap_key, for_key))
                    if reason:
                        chapter["reason"] = reason["reason"]
                        chapter["for"] = reason["for"]

        with open(selected_structure_path, "w") as f:
            json.dump(selected_data, f, indent=4)

        with open("structured_data/selected_structure.json", "r") as f:
            selected_structure = json.load(f)

        tree = build_prerequisite_tree(selected_structure)

        with open("structured_data/prerequisite_tree.json", "w") as f:
            json.dump(tree, f, indent=2)

        return render_template("next_step.html", tree_json=tree)
    
    # --- NORMAL FLOW ---
    if request.method == 'POST':
        selected_topics = request.form.getlist("selected_prereq_topic")
        selected_subtopics = request.form.getlist("selected_prereq_subtopic")
        selected_combined = request.form.getlist("selected_prereq_combined")

        selected_ids = []
        selected_chapters = []

        for item in selected_combined:
            try:
                id_, chapter = item.split("|||", 1)
                selected_ids.append(id_)
                selected_chapters.append(chapter)
            except ValueError:
                print(f"⚠️ Skipped invalid combined item: {item}")
                continue
        print("📌 Received selected_ids from POST:", selected_ids)

    else:
        if level == 1:
            current_class_key = f"class_{class_name}"
            selected_chapters = []

            if os.path.exists(selected_structure_path):
                with open(selected_structure_path, "r") as f:
                    selected_structure_data = json.load(f)

                for subject, chapters in selected_structure_data.get(current_class_key, {}).items():
                    for ch in chapters:
                        selected_chapters.append(ch.get("chapter"))

            selected_ids = []  # no IDs available yet
            selected_topics = []
            selected_subtopics = []
        else:
            selected_chapters = selected_chapter_names
            selected_ids = []
            selected_topics = []
            selected_subtopics = []

    prev_year_struct_path = f"structured_data/previous_year_depth_{level}.json"
    if os.path.exists(prev_year_struct_path):
        with open(prev_year_struct_path, "r") as f:
            previous_year_data = json.load(f)
    else:
        previous_year_data = fetch_structured_previous_year_content(
            board, starting_class = class_name, current_class = str(int(class_name) - level), starting_subjects = subjects, depth=level, max_depth=5
        )

    chapter_index_map = {
        subject: {ch['number']: ch['chapter'] for ch in chapters}
        for subject, chapters in previous_year_data.items()
    }

    render_items = []

    for subject in subjects:
        relevant_chapters = [{"chapter": name} for name in selected_chapters]

        prompted_chapters = set()
        for ch in relevant_chapters:
            chapter_name = ch.get("chapter")
            if not chapter_name or (subject, chapter_name) in prompted_chapters:
                continue
            prompted_chapters.add((subject, chapter_name))

            prompt = f"""
    You are an academic AI assistant helping to identify prerequisite chapters.

    Context:
    - The user has selected a specific chapter from a current year's syllabus.
    - You are also given the chapter list from the previous year's syllabus for the same subject and board.

    Instructions:
    1. Identify only those prerequisite chapters that are clearly and directly related.
    2. Avoid abstract or general background prerequisites.
    3. All suggested prerequisites must come from the previous year's chapter list.

    Output Format:
    {{
    "prerequisites": {{
        "{subject}": [
        {{
            "number": 1,
            "chapter": "Exact Chapter Name",
            "reason": "Why this chapter is needed",
            "for": "{chapter_name}"
        }}
        ]
    }}
    }}

    Selected Chapter:
    {json.dumps([{"chapter": chapter_name}], indent=2)}

    Previous Year Chapters:
    {json.dumps(chapter_index_map.get(subject, {}), indent=2)}
    """
            try:
                result = subprocess.run(
                    ["ollama", "run", "llama3"],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=1000000
                )
                output = result.stdout.strip()
                print("📥 Ollama Output:\n", output[:300])
                prereq_json = json.loads(output[output.find("{"):output.rfind("}") + 1]) if output else {}

                prereqs = prereq_json.get("prerequisites", {}).get(subject, [])
                full_chapter_list = previous_year_data.get(subject, [])

                for req in prereqs:
                    chapter_num = req.get("number")
                    matched_ch = next((c for c in full_chapter_list if c.get("number") == chapter_num), None)
                    if matched_ch:
                        new_item = {
                            "id": str(uuid.uuid4()),
                            "subject": subject,
                            "number": chapter_num,
                            "chapter": matched_ch.get("chapter", ""),
                            "topics": matched_ch.get("topics", []),
                            "reason": req.get("reason", ""),
                            "for": req.get("for", chapter_name)
                        }
                        print("📘 Adding render item:", new_item)
                        render_items.append(new_item)

            except Exception as e:
                print(f"❌ Error for {subject} - {chapter_name}: {e}")
                continue

    with open(os.path.join("structured_data", f"prereq_render_items_level_{level}.json"), "w") as f:
        json.dump(render_items, f, indent=2)

    # POST-only logic: apply selected IDs and add to structure
    if request.method == "POST":
        
        render_path = os.path.join("structured_data", f"prereq_render_items_level_{level - 1}.json")
        if os.path.exists(render_path):
            with open(render_path, "r") as f:
                render_items = json.load(f)
        
        print("🔄 Running structure update logic for selected IDs")
        if os.path.exists(selected_structure_path):
            with open(selected_structure_path, "r") as f:
                current_structure = json.load(f)
        else:
            current_structure = {}

        class_key = f"class_{int(class_name) - level + 1}"
        current_structure.setdefault(class_key, {})
        for subject in subjects:
            current_structure[class_key].setdefault(subject, [])

        prev_level = level - 1
        prev_json_path = f"structured_data/previous_year_depth_{prev_level}.json"
        if os.path.exists(prev_json_path):
            with open(prev_json_path, "r") as f:
                previous_level_data = json.load(f)
        else:
            previous_level_data = {}

        print("🧱 Loaded render IDs from level", level - 1, ":", [item["id"] for item in render_items[:5]])
        id_map = {item["id"]: item for item in render_items}
        selected_items = [id_map[i] for i in selected_ids if i in id_map]
        print("✅ Matched selected_items:", selected_items)

        for item in selected_items:
            subject = item["subject"]
            chapter_name = item["chapter"]

            full_chapter_list = previous_level_data.get(subject, [])
            matched = next((ch for ch in full_chapter_list if ch["chapter"] == chapter_name), None)

            if not matched:
                print(f"❌ No match found for: {chapter_name}")
                continue

            chapter_obj = normalize_chapter_structure(matched)
            chapter_obj["for"] = item.get("for")
            chapter_obj["reason"] = item.get("reason")

            print(f"➕ Appending Chapter: {chapter_obj}")
            current_structure[class_key][subject].append(chapter_obj)

        # Topic/Subtopic matching logic
        for subject in previous_level_data:
            full_chapter_list = previous_level_data[subject]
            for chapter in full_chapter_list:
                chapter_name = chapter.get("chapter")
                matched = False
                for topic in chapter.get("topics", []):
                    if topic.get("topic") in selected_topics or any(sub.get("text") in selected_subtopics for sub in topic.get("subtopics", [])):
                        matched = True
                        break
                if matched:
                    chapter_obj = normalize_chapter_structure(chapter)
                    current_structure[class_key][subject].append(chapter_obj)

        print("💾 Writing updated structure to selected_structure_path")
        with open(selected_structure_path, "w") as f:
            json.dump(current_structure, f, indent=4)

        inject_reasons_into_selected_data(current_structure, level - 1)

        print("💾 Rewriting after injecting reasons")
        with open(selected_structure_path, "w") as f:
            json.dump(current_structure, f, indent=4)
            
    next_render_path = os.path.join("structured_data", f"prereq_render_items_level_{level}.json")
    if os.path.exists(next_render_path):
        with open(next_render_path, "r") as f:
            next_render_items = json.load(f)
    else:
        next_render_items = []

    return render_template("recursive_prereq.html", prerequisites=next_render_items, level=level + 1, class_name=(int(class_name) - level))

# 2.2.2 Route to prepare selected data for question generation (next_step.html)
@app.route('/prepare_selected_data', methods=['POST'])
def prepare_selected_data():
    # Existing logic to build selected_data...
    selected_chapters = request.form.getlist("selected_prereq_chapter")
    selected_topics = request.form.getlist("selected_topics")
    selected_subtopics = request.form.getlist("selected_subtopics")

    # New: Get show_metadata value (will be 'on' if checked)
    show_metadata = request.form.get("show_metadata", "off")

    # Build and save data (same as you have)
    def nested_dict():
        return defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"topics": defaultdict(list)})))

    prepared_data = nested_dict()

    def parse_parts(item, expected_parts):
        parts = item.split('|')
        if len(parts) != expected_parts:
            return None
        return parts

    for item in selected_chapters:
        parsed = parse_parts(item, 3)
        if not parsed:
            continue
        chapter, class_name, subject = parsed
        _ = prepared_data[class_name][subject][chapter]["topics"]

    for item in selected_topics:
        parsed = parse_parts(item, 4)
        if not parsed:
            continue
        chapter, topic, class_name, subject = parsed
        _ = prepared_data[class_name][subject][chapter]["topics"][topic]

    for item in selected_subtopics:
        parsed = parse_parts(item, 5)
        if not parsed:
            continue
        chapter, topic, subtopic, class_name, subject = parsed
        prepared_data[class_name][subject][chapter]["topics"][topic].append(subtopic)

    final_data = json.loads(json.dumps(prepared_data))
    os.makedirs("structured_data", exist_ok=True)
    with open("structured_data/prepared_selected_data.json", "w") as f:
        json.dump(final_data, f, indent=2)

    # Pass metadata flag as query param
    return redirect(url_for("generate_questions", show_metadata=show_metadata))

# 2.2.2.1 Route to download prerequisite tree as PDF (next_step.html)
@app.route('/download_prereqs')
def download_prereqs():
    try:
        with open("structured_data/prerequisite_tree.json", "r") as f:
            tree = json.load(f)
    except FileNotFoundError:
        return "Prerequisite tree not found", 404

    pdf_buffer = generate_prerequisite_pdf(tree)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name="Prerequisite_Tree.pdf",
        mimetype="application/pdf"
    )

# 2.2.2.2 Route to generate questions based on selected data (result.html)
@app.route('/generate_questions')
def generate_questions():
    show_metadata = request.args.get("show_metadata") == "on"

    try:
        with open("structured_data/prepared_selected_data.json", "r") as f:
            selected_data = json.load(f)
    except FileNotFoundError:
        return "Error: prepared_selected_data.json not found."

    all_questions = []
    grouped_targets = []

    for class_key in sorted(selected_data.keys()):
        for subject in sorted(selected_data[class_key].keys()):
            flat_items = []
            chapters = selected_data[class_key][subject]

            for chapter, content in chapters.items():
                topics = content.get("topics", {})
                for topic, subtopics in topics.items():
                    if subtopics:
                        for subtopic in subtopics:
                            flat_items.append({
                                "class": class_key,
                                "subject": subject,
                                "chapter": chapter,
                                "topic": topic,
                                "subtopic": subtopic
                            })
                    else:
                        flat_items.append({
                            "class": class_key,
                            "subject": subject,
                            "chapter": chapter,
                            "topic": topic,
                            "subtopic": None
                        })

            if flat_items:
                grouped_targets.append({
                    "class": class_key,
                    "subject": subject,
                    "items": flat_items
                })

    system_prompt = (
        "You are a JSON-only AI. Return strictly valid JSON only. Do NOT include explanations or natural language.\n\n"
        "You are tasked with creating 1 high-quality multiple choice question per topic or subtopic, considering the following:\n"
        "- The question must reflect the difficulty and knowledge level appropriate for the given class (grade level).\n"
        "- Use the chapter name as the primary context.\n"
        "- For subjects like 'Mathematics', ensure questions are **numerical, formula-based, or calculation-oriented**. Avoid generic or theory-based questions.\n"
        "- For theoretical subjects like 'Biology', 'History', or 'Civics', focus on **conceptual understanding** but avoid vague or overly general questions.\n"
        "- Do NOT repeat topics or give trivial questions.\n\n"
        "Each question must include:\n"
        "- 'question': the question string\n"
        "- 'options': a list of 4 strings, each starting with a number and a period (e.g., '1. 32 cm')\n"
        "- 'correct_option': the correct option number (1 to 4), not the text\n"
        "- 'class', 'subject', 'chapter', 'topic', 'subtopic': included as metadata (subtopic can be null)\n\n"
        "Your entire response must be in this format:\n"
        "{ \"questions\": [ { \"class\": ..., \"subject\": ..., \"chapter\": ..., \"topic\": ..., \"subtopic\": ..., \"question\": ..., \"options\": [...], \"correct_option\": 1 }, ... ] }"
    )


    for group in grouped_targets:
        class_key = group["class"]
        subject = group["subject"]
        items = group["items"]

        user_prompt = {
            "task": "Generate 1 MCQ per topic/subtopic using class and chapter context",
            "class": class_key,
            "subject": subject,
            "items": items
        }

        full_prompt = f"{system_prompt}\n\n---\n\n{json.dumps(user_prompt, indent=2)}"

        try:
            result = subprocess.run(
                ["ollama", "run", "llama3"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout.strip()
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                output_json = json.loads(output[json_start:json_end])
                questions = output_json.get("questions", [])
                for q in questions:
                    verify_answer_with_models(q)
                all_questions.extend(questions)
            else:
                print(f"⚠️ Warning: Invalid JSON returned for {class_key} > {subject}")

        except Exception as e:
            print(f"❌ Error generating for {class_key} > {subject}: {e}")

    if not all_questions:
        return "Error: No questions generated."

    final_output = {"questions": all_questions}

    with open("paper.json", "w") as f:
        json.dump(final_output, f, indent=2)

    generate_pdf(final_output, "Question.pdf", show_metadata)

    return render_template("review_questions.html", questions=final_output["questions"])

# 2.3 Route to review and finalize questions (review_questions.html)
@app.route('/finalize_questions', methods=['POST'])
def finalize_questions():
    selected_indexes = list(map(int, request.form.getlist("selected_indexes")))
    all_questions_json = request.form["all_questions_json"]
    all_questions = json.loads(all_questions_json)

    selected_questions = [all_questions[i] for i in selected_indexes]

    if not selected_questions:
        return "No questions selected."

    final_output = {"questions": selected_questions}

    with open("paper.json", "w") as f:
        json.dump(final_output, f, indent=2)

    show_metadata = True  # Optional: You can use a hidden input to let the user decide this too
    generate_pdf(final_output, "Question.pdf", show_metadata)

    return render_template("result.html", paper_json=final_output, pdf_code="PDF generated successfully.")

# 3 Route to download the generated PDF (result.html)
@app.route('/download_pdf')
def download_pdf():
    try:
        with open("paper.json", "r") as f:
            paper_json = json.load(f)
        if not paper_json.get("questions"):
            return "Error: No questions available."
        if not os.path.exists("Question.pdf"):
            generate_pdf(paper_json, "Question.pdf")
        return send_file("Question.pdf", as_attachment=True)
    except Exception as e:
        return f"Error: {str(e)}"

# (select_prereq.html)
@app.route('/finalize_prereq', methods=['POST'])
def finalize_prereq():
    selected_prereq_topics = request.form.getlist("selected_prereq_topic")
    selected_prereq_subtopics = request.form.getlist("selected_prereq_subtopic")

    if not selected_prereq_topics and not selected_prereq_subtopics:
        return "Error: Please select at least one prerequisite topic or subtopic."

    session['prereq_only'] = {
        "topics": selected_prereq_topics,
        "subtopics": selected_prereq_subtopics
    }

    return redirect(url_for("generate_questions"))

# Route to export questions to CSV (review_questions.html)
@app.route('/export_to_csv')
def export_to_csv():
    try:
        with open("paper.json", "r") as f:
            paper_json = json.load(f)
        
        questions = paper_json.get("questions", [])
        if not questions:
            return "Error: No questions available.", 400

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = ["Class", "Subject", "Chapter", "Topic", "Subtopic", "Question", "Option 1", "Option 2", "Option 3", "Option 4", "Correct Option", "Verified", "Model Responses"]
        writer.writerow(headers)
        
        # Write question data
        for q in questions:
            options = q.get("options", [""] * 4) + [""] * (4 - len(q.get("options", [])))
            model_responses = "; ".join([f"{k}: {v}" for k, v in q.get("model_responses", {}).items()])
            row = [
                q.get("class", ""),
                q.get("subject", ""),
                q.get("chapter", ""),
                q.get("topic", ""),
                q.get("subtopic", "") or "",
                q.get("question", ""),
                options[0],
                options[1],
                options[2],
                options[3],
                str(q.get("correct_option", "")),
                str(q.get("verified", "")),
                model_responses
            ]
            writer.writerow(row)
        
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            as_attachment=True,
            download_name="Questions.csv",
            mimetype="text/csv"
        )
    except FileNotFoundError:
        return "Error: Question data not found.", 404
    except Exception as e:
        return f"Error: {str(e)}", 500

def normalize_subject(subject):
    subject = subject.strip().lower()
    subject_map = {
        'maths': 'Mathematics',
        'mathematics': 'Mathematics',
        'math': 'Mathematics',
        'science': 'Science',
        'physics': 'Physics',
        'chemistry': 'Chemistry',
        'biology': 'Biology',
        'english': 'English',
        'english language': 'English',
        'english language and literature': 'English',
        'english core': 'English',
        'english elective': 'English Elective',
        'first flight': 'English',
        'footprints without feet': 'English',
        'social science': 'Social Science',
        'social studies': 'Social Science',
        'hindi': 'Hindi',
    }
    return subject_map.get(subject, subject.capitalize())

def normalize_class(class_name):
    class_name = str(class_name).strip().lower().replace('class ', '').replace('grade ', '')
    class_map = {
        '10': '10',
        'class 10': '10',
        'grade 10': '10',
        '9': '9',
        'class 9': '9',
        'grade 9': '9',
    }
    return class_map.get(class_name, class_name)

# Cache
TEXTBOOK_CACHE = os.path.join(DATA_DIR, 'textbook_cache.json')

def load_cached_textbooks():
    try:
        if os.path.exists(TEXTBOOK_CACHE):
            with open(TEXTBOOK_CACHE, 'r', encoding='utf-8') as f:
                return json.load(f)
        logger.info(f"No cached textbooks found at {TEXTBOOK_CACHE}")
        return None
    except Exception as e:
        logger.error(f"Failed to load cached textbooks: {e}")
        return None

def save_cached_textbooks(textbooks):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TEXTBOOK_CACHE, 'w', encoding='utf-8') as f:
            json.dump(textbooks, f, indent=4)
        logger.info(f"Saved textbook cache to {TEXTBOOK_CACHE}")
    except Exception as e:
        logger.error(f"Failed to save textbook cache: {e}")

def fetch_textbooks_list(api_url):
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            return response.json()
        logger.error(f"Failed to fetch textbooks: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Exception while fetching textbooks: {e}")
        return None

# Fallback
FALLBACK_TEXTBOOKS = {
    'data': {
        'getBooks': [
            {
                'id': 'ncert_math_10',
                'class': '10',
                'subject': 'Mathematics',
                'board': 'NCERT',
                's3folder': 'ncert/10thmaths'
            },
            {
                'id': 'ncert_science_10',
                'class': '10',
                'subject': 'Science',
                'board': 'NCERT',
                's3folder': 'ncert/10thscience'
            },
            {
                'id': 'ncert_english_10',
                'class': '10',
                'subject': 'English',
                'board': 'NCERT',
                's3folder': 'ncert/10thenglish'
            },
            {
                'id': 'ncert_socialscience_10',
                'class': '10',
                'subject': 'Social Science',
                'board': 'NCERT',
                's3folder': 'ncert/10thsocialscience'
            },
            {
                'id': 'ncert_hindi_10',
                'class': '10',
                'subject': 'Hindi',
                'board': 'NCERT',
                's3folder': 'ncert/10thhindi'
            }
        ]
    }
}

@app.route('/generate_study_material', methods=['POST'])
def generate_study_material():
    board = request.form.get('board')
    class_name = request.form.get('class')
    subjects = request.form.getlist('subject')
    selected_chapters = request.form.getlist('chapters')
    content_types = request.form.getlist('content_types')
    errors = []

    # Normalize inputs
    normalized_class = normalize_class(class_name)
    normalized_subjects = [normalize_subject(subject) for subject in subjects]
    logger.info(f"Normalized inputs: class={normalized_class}, subjects={normalized_subjects}, chapters={selected_chapters}, content_types={content_types}")

    # Fetch textbook data
    textbooks = fetch_textbooks_list(TEXTBOOKS_API)
    if not textbooks or not textbooks.get('data', {}).get('getBooks', []):
        logger.warning("API returned no textbooks, trying cache")
        textbooks = load_cached_textbooks()
        if not textbooks:
            logger.warning("No cached textbooks, using fallback")
            textbooks = FALLBACK_TEXTBOOKS
            errors.append({
                'message': 'Failed to fetch textbooks from API and cache; using fallback data',
                'is_json_upload_error': False
            })

    # Cache textbooks if newly fetched
    if textbooks and textbooks != load_cached_textbooks():
        save_cached_textbooks(textbooks)

    available_books = [(book.get('subject'), book.get('class'), book.get('s3folder')) for book in textbooks.get('data', {}).get('getBooks', [])]
    logger.debug(f"Available books: {json.dumps(available_books, indent=2)}")

    study_material = []
    pdf_code = None
    pdf_filename = None
    chapter_number_to_name_map = session.get('chapter_number_to_name_map', {})

    # Load chapter data from stored subject_chapter_map
    chapters_data_path = os.path.join("structured_data", "list_of_all_chapters_for_selected_class.json")
    if not os.path.exists(chapters_data_path):
        errors.append({'message': 'No chapter data available. Please select subjects and chapters again.', 'is_json_upload_error': False})
        return render_template("study_material.html", study_material=study_material,
                              pdf_code=pdf_code, pdf_filename=pdf_filename,
                              errors=errors, board=board, class_name=class_name,
                              subjects=subjects)

    with open(chapters_data_path, 'r', encoding='utf-8') as f:
        subject_chapter_map = json.load(f)

    for subject in normalized_subjects:
        subject_data = {"subject": subject, "chapters": []}
        chapters = subject_chapter_map.get(subject, [])
        selected_subject_chapters = [ch.split("|")[0] for ch in selected_chapters if ch.split("|")[2].lower() == subject.lower()]
        
        if not chapters:
            available_subjects = sorted(set(b[0] for b in available_books if normalize_class(b[1]) == normalized_class))
            error_msg = (f"No book found for {subject} in class {normalized_class} (normalized: {subject}/{normalized_class}). "
                         f"Available subjects for class {normalized_class}: {', '.join(available_subjects) or 'None'}")
            errors.append({'message': error_msg, 'is_json_upload_error': True, 'subject': subject})
            logger.error(error_msg)
            continue

        for chapter_name in selected_subject_chapters:
            chapter = next((ch for ch in chapters if ch['chapter'].lower() == chapter_name.lower()), None)
            if not chapter:
                errors.append({
                    'message': f"Chapter {chapter_name} not found for {subject}",
                    'is_json_upload_error': False,
                    'subject': subject
                })
                logger.warning(f"Chapter {chapter_name} not found in subject_chapter_map for {subject}")
                continue

            chapter_num = chapter['number']
            chapter_data = {
                "number": chapter_num,
                "chapter": chapter_name,
                "content": {}
            }

            logger.info(f"Generating content for {subject} - {chapter_name} (number: {chapter_num})")
            output_paths, gen_errors = generate_educational_content(
                board=board,
                class_name=class_name,
                subject=subject,
                chapter_number=int(chapter_num),
                chapter_name=chapter_name,
                content_types=content_types
            )
            
            if gen_errors:
                errors.append({
                    'message': f"Errors generating content for {subject} - {chapter_name}: {gen_errors}",
                    'is_json_upload_error': False,
                    'subject': subject
                })
                logger.error(f"Errors generating content for {subject} - {chapter_name}: {gen_errors}")
            
            for output_path in output_paths:
                with open(output_path, 'r', encoding='utf-8') as f:
                    content_data = json.load(f)
                    content_type = content_data.get('content_type')
                    generated_content = content_data.get('generated_content', {}).get(content_type, 'No content generated')
                    chapter_data['content'][content_type] = generated_content
                    logger.info(f"Loaded {content_type} from {output_path}: {generated_content[:100]}...")

            if chapter_data['content']:
                subject_data['chapters'].append(chapter_data)

        if subject_data['chapters']:
            study_material.append(subject_data)

    if study_material and not errors:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"study_material_{timestamp}.pdf"
        pdf_path = os.path.join(CONTENT_DIR, pdf_filename)
        try:
            generate_study_material_pdf(study_material, pdf_path)
            pdf_code = f"Study Material PDF generated successfully as {pdf_filename}"
        except Exception as e:
            errors.append({'message': f"Failed to generate PDF: {str(e)}", 'is_json_upload_error': False})
            logger.error(f"Failed to generate PDF: {str(e)}")

    if not study_material and not errors:
        errors.append({'message': 'No study material generated. Please check your selections or upload valid JSON files.', 'is_json_upload_error': True})

    return render_template("study_material.html", study_material=study_material,
                           pdf_code=pdf_code, pdf_filename=pdf_filename,
                           errors=errors, board=board, class_name=class_name,
                           subjects=subjects)

@app.route('/download_study_material/<filename>')
def download_study_material(filename):
    try:
        return send_from_directory(CONTENT_DIR, filename, as_attachment=True)
    except FileNotFoundError:
        logger.error(f"PDF file {filename} not found")
        return render_template("study_material.html", errors=[{
            'message': f"PDF file {filename} not found",
            'is_json_upload_error': False
        }])

# ------------------------------- SVG Generator Routes ----------------------------------

@app.route('/svg_generator')
def svg_generator():
    """Renders the main page for the SVG generator."""
    return render_template('svg_generator.html')

@app.route('/run_svg_generation', methods=['POST'])
def run_svg_generation():
    """Runs the SVG generation process from a generic list of topics."""
    logger.info("🚀 Starting Educational SVG Processor")
    try:
        topics = fetch_topics()
        logger.info(f"📋 Loaded {len(topics)} topics for processing")
        processed_files = []
        for topic in topics:
            svg_path, explanation_path = process_topic(topic)
            if svg_path:
                processed_files.append({
                    "topic": topic,
                    "svg_file": os.path.basename(svg_path),
                    "explanation_file": os.path.basename(explanation_path) if explanation_path else None
                })
            sleep(1)  # Rate limiting
        session['processed_svgs'] = processed_files
        return redirect(url_for('svg_results'))
    except Exception as e:
        logger.critical(f"🔥 Critical error during SVG generation: {e}")
        return "An error occurred during SVG generation. Check the logs for details.", 500

@app.route('/run_svg_generation_from_chapters', methods=['POST'])
def run_svg_generation_from_chapters():
    """Runs the SVG generation process based on topics from selected chapters."""
    logger.info("🚀 Starting Educational SVG Processor from selected chapters...")
    
    selected_chapters_raw = request.form.getlist('chapters')
    if not selected_chapters_raw:
        return "Error: No chapters selected.", 400

    # --- Extract Topics from Selected Chapters ---
    parsed_chapters = []
    for ch_raw in selected_chapters_raw:
        parts = ch_raw.split('|')
        if len(parts) == 3:
            parsed_chapters.append({'name': parts[0], 'subject': parts[2]})

    chapters_data_path = os.path.join("structured_data", "list_of_all_chapters_for_selected_class.json")
    if not os.path.exists(chapters_data_path):
        return "Error: Chapter data file not found. Please go back and re-select subjects.", 500
    
    with open(chapters_data_path, "r", encoding='utf-8') as f:
        all_chapters_data = json.load(f)

    topics_to_process = set()
    for selected_ch in parsed_chapters:
        subject_chapters = all_chapters_data.get(selected_ch['subject'], [])
        chapter_details = next((ch for ch in subject_chapters if ch.get("chapter") == selected_ch['name']), None)
        
        if chapter_details and "topics" in chapter_details:
            for topic in chapter_details["topics"]:
                if topic.get("topic"):
                    topics_to_process.add(re.sub(r'^\d+\.\d+\s*', '', topic["topic"]).strip())
                if "subtopics" in topic:
                    for subtopic in topic["subtopics"]:
                        if subtopic.get("text"):
                            topics_to_process.add(re.sub(r'^\d+\.\d+\.\d+\s*', '', subtopic["text"]).strip())

    if not topics_to_process:
        return "No topics found in the selected chapters.", 400

    logger.info(f"📋 Found {len(topics_to_process)} unique topics for processing: {topics_to_process}")

    processed_files = []
    for topic in list(topics_to_process):
        svg_path, explanation_path = process_topic(topic)
        if svg_path:
            processed_files.append({
                "topic": topic,
                "svg_file": os.path.basename(svg_path),
                "explanation_file": os.path.basename(explanation_path) if explanation_path else None
            })
        sleep(1)

    session['processed_svgs'] = processed_files
    return redirect(url_for('svg_results'))
    

@app.route('/svg_results')
def svg_results():
    """Displays the list of generated SVGs with previews."""
    processed_svgs = session.get('processed_svgs', [])
    
    for item in processed_svgs:
        svg_path = os.path.join(SVG_DIR, item['svg_file'])
        try:
            with open(svg_path, 'r', encoding='utf-8') as f:
                item['svg_data'] = f.read()
        except Exception as e:
            logger.error(f"Could not read SVG file {svg_path} for preview: {e}")
            item['svg_data'] = '<p class="text-red-500">Preview not available</p>'

    return render_template('svg_results.html', items=processed_svgs)

@app.route('/view_svg/<topic>')
def view_svg(topic):
    """Displays a single SVG and its explanation."""
    clean_topic = re.sub(r'\W+', '_', topic.lower())
    svg_filename = f"{clean_topic}.svg"
    placeholder_filename = f"{clean_topic}_placeholder.svg"
    explanation_filename = f"{clean_topic}_explanation.md"

    svg_path = os.path.join(SVG_DIR, svg_filename)
    placeholder_path = os.path.join(SVG_DIR, placeholder_filename)
    explanation_path = os.path.join(SVG_DIR, explanation_filename)

    svg_content = ""
    # Try to read the main SVG, if not found, try the placeholder
    try:
        if os.path.exists(svg_path):
             with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
        elif os.path.exists(placeholder_path):
            with open(placeholder_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
        else:
            svg_content = "<p>SVG file not found.</p>"
    except Exception as e:
        logger.error(f"Error reading SVG file for {topic}: {e}")
        svg_content = f"<p>Error loading SVG: {e}</p>"


    explanation_content = ""
    try:
        if os.path.exists(explanation_path):
            with open(explanation_path, 'r', encoding='utf-8') as f:
                explanation_content = f.read()
        else:
            explanation_content = "No explanation file found."
    except Exception as e:
        logger.error(f"Error reading explanation file for {topic}: {e}")
        explanation_content = f"Error loading explanation: {e}"

    return render_template('view_svg.html', 
                           topic=topic, 
                           svg_content=Markup(svg_content), 
                           explanation_content=explanation_content)

# ------------------------------- NEW FIB Generator Routes ----------------------------------

@app.route('/select_fib_topics', methods=['POST'])
def select_fib_topics():
    """
    This new route takes the selected chapters, finds their topics/subtopics,
    and renders a new page for the user to make a final selection.
    """
    selected_chapters_raw = request.form.getlist('chapters')
    if not selected_chapters_raw:
        # CORRECTED: Changed Flask() to flash()
        flash("You must select at least one chapter to create a worksheet.", "error")
        return redirect(request.referrer or url_for('index'))

    # Load the detailed chapter data saved in the /select route
    chapters_data_path = os.path.join(DATA_DIR, "list_of_all_chapters_for_selected_class.json")
    if not os.path.exists(chapters_data_path):
        flash("Chapter data not found. Please start the selection process over.", "error")
        return redirect(url_for('index'))
    
    with open(chapters_data_path, "r", encoding='utf-8') as f:
        all_chapters_data = json.load(f)

    # Filter the data to only include chapters the user selected
    selected_data = defaultdict(list)
    for ch_raw in selected_chapters_raw:
        try:
            chapter_name, class_name, subject = ch_raw.split('|')
            subject_chapters = all_chapters_data.get(subject, [])
            chapter_details = next((ch for ch in subject_chapters if ch.get("chapter") == chapter_name), None)
            if chapter_details:
                selected_data[subject].append(chapter_details)
        except ValueError:
            continue # Skip any malformed chapter values

    if not selected_data:
        # CORRECTED: Changed Flask() to flash()
        flash("Could not find details for the selected chapters. Please try again.", "warning")
        return redirect(request.referrer)

    return render_template("select_fib_topics.html", selected_data=selected_data)


@app.route('/run_fib_generation', methods=['POST'])
def run_fib_generation():
    selection = request.form.get('fib_selection')
    if not selection:
        flash("You must select a topic/subtopic to generate a worksheet.", "error")
        return redirect(request.referrer or url_for('index'))

    try:
        subject, chapter, topic, subtopic = selection.split('|')
    except ValueError:
        flash("Invalid selection format. Please try again.", "error")
        return redirect(request.referrer or url_for('index'))

    logger.info(f"Generating FIB content for: {subject}/{chapter}/{topic}/{subtopic}")
    content = generate_fib_content(subject, chapter, topic, subtopic)

    if "error" in content:
        flash(content["error"], "error")
        return render_template("fib_results.html", success=False)

    base_name = f"FIB_{subject}_{chapter}_{subtopic}".replace(" ", "_").replace("/", "_")
    student_pdf_name = f"{base_name}_student.pdf"
    answer_pdf_name = f"{base_name}_answer.pdf"

    student_pdf_path = os.path.join(CONTENT_DIR, student_pdf_name)
    answer_pdf_path = os.path.join(CONTENT_DIR, answer_pdf_name)

    os.makedirs(CONTENT_DIR, exist_ok=True)

    marker_path = os.path.join(STATIC_DIR, "img1.jpg")
    if not os.path.exists(marker_path):
        flash("Marker image not found.", "error")
        return render_template("fib_results.html", success=False)

    try:
        generate_fib_pdf_v2(content, student_pdf_path, show_answers=False, marker_path=marker_path)
        generate_fib_pdf_v2(content, answer_pdf_path, show_answers=True, marker_path=marker_path)

        logger.info("FIB PDF generation complete.")
        return render_template("fib_results.html", success=True,
                               student_pdf=student_pdf_name,
                               answer_pdf=answer_pdf_name)
    except Exception as e:
        logger.error(f"Failed to generate PDFs: {e}")
        flash(f"An error occurred while creating the PDF files: {e}", "error")
        return render_template("fib_results.html", success=False)



@app.route('/download_fib/<path:filename>')
def download_fib(filename):
    """Serves a generated FIB PDF from the content directory."""
    return send_from_directory(CONTENT_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    os.makedirs(SVG_DIR, exist_ok=True)
    app.run(debug=True)
