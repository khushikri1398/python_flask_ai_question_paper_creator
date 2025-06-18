from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
import requests
import subprocess
import json
from fpdf import FPDF
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

TEXTBOOKS_API = "https://staticapis.pragament.com/textbooks/allbooks.json"

@app.route('/')
def index():
    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        print(f"Error fetching textbooks: {e}")
        textbooks = []
    return render_template('index.html', textbooks=textbooks)

@app.route('/select', methods=['POST'])
def select():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")

    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        print(f"Error fetching textbooks: {e}")
        textbooks = []

    all_chapters, all_topics, all_subtopics = [], [], []

    for subject in subjects:
        matching_book = next(
            (book for book in textbooks if book.get('board') == board and str(book.get('class')) == class_name and book.get('subject') == subject),
            None
        )

        if not matching_book:
            print(f"No matching textbook found for subject: {subject}")
            continue

        book_id = matching_book.get("id")
        try:
            response = requests.get(f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json")
            response.raise_for_status()
            topics_data = response.json()
        except requests.RequestException as e:
            print(f"Error fetching page attributes for {subject}: {e}")
            continue

        all_chapters.extend([item for item in topics_data if item.get('type') == 'chapter'])
        all_topics.extend([item for item in topics_data if item.get('type') == 'topic'])
        all_subtopics.extend([item for item in topics_data if item.get('type') == 'subtopic'])

    return render_template('select.html', board=board, class_name=class_name, subjects=subjects,
                           chapters=all_chapters, topics=all_topics, subtopics=all_subtopics)

@app.route('/generate', methods=['POST'])
def generate():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    chapters = request.form.getlist("chapters")
    topics = request.form.getlist("topics")
    subtopics = request.form.getlist("subtopics")
    min_questions = request.form.get("min_questions")
    max_questions = request.form.get("max_questions")
    total_questions = request.form.get("total_questions")
    is_prerequisite = request.form.get("prerequisite") == 'on'

    session['form_data'] = {
        "board": board,
        "class": class_name,
        "subjects": subjects,
        "chapters": chapters,
        "topics": topics,
        "subtopics": subtopics,
        "min_questions": min_questions,
        "max_questions": max_questions,
        "total_questions": total_questions
    }

    if is_prerequisite:
        reasoning_prompt = {
            "task": "Find prerequisite topics and subtopics for the selected ones with mandatory detailed reasons",
            "selected_topics": topics,
            "selected_subtopics": subtopics,
            "output_format": "{ 'prerequisites': [ { 'topic': '...', 'subtopics': ['...'], 'reason': '...' } ] }",
            "require_reason": True,
            "require_subtopics": True,
            "language": "English"
        }

        ollama_prompt = (
            "You are an expert educational curriculum planner. "
            "For the given selected topics and subtopics, return a list of prerequisite topics and subtopics the student must know. "
            "Every topic must include a detailed reason and a list of prerequisite subtopics. "
            "Output should be JSON only in the format:\n"
            "{ 'prerequisites': [ { 'topic': '...', 'subtopics': ['...'], 'reason': '...' } ] }\n"
            "Do not include any natural language or explanation outside of this JSON.\n\n"
            f"{json.dumps(reasoning_prompt, indent=4)}"
        )

        try:
            result = subprocess.run(["ollama", "run", "llama3"], input=ollama_prompt, capture_output=True, text=True, timeout=1000000)
            output = result.stdout.strip()
            print("OLLAMA RAW OUTPUT:\n", output)
            prereq_json = json.loads(output[output.find('{'):output.rfind('}')+1]) if output else {}
        except Exception as e:
            print(f"Ollama prerequisite generation failed: {e}")
            prereq_json = {}

        prerequisites = prereq_json.get("prerequisites", [])
        prerequisites = [p for p in prerequisites if 'reason' in p and p['reason'].strip() and 'subtopics' in p]

        session['prereq_full_list'] = prerequisites
        return render_template("select_prereq.html", prerequisites=prerequisites)
    else:
        session['prereq_only'] = None
        return redirect(url_for("generate_questions"))

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

@app.route('/generate_questions')
def generate_questions():
    data = session.get("form_data", {})
    if not data:
        return "Session expired. Please go back and select topics."

    prereq_data = session.get("prereq_only", {})
    topics = prereq_data.get("topics") if prereq_data else data.get("topics")
    subtopics = prereq_data.get("subtopics") if prereq_data else data.get("subtopics")

    if not topics and not subtopics:
        return "Error: No topics or subtopics selected for question generation. Please go back and select."

    board = data["board"]
    class_name = data["class"]
    subjects = data["subjects"]
    chapters = data["chapters"]
    min_questions = data["min_questions"] or "1"
    max_questions = data["max_questions"] or "1"
    total_questions = data["total_questions"] or "1"

    prompt_data = {
        "task": "Generate multiple-choice questions",
        "board": board,
        "class": class_name,
        "subject": subjects,
        "chapters": chapters,
        "topics": topics,
        "subtopics": subtopics,
        "min_questions": min_questions,
        "max_questions": max_questions,
        "total_questions": total_questions
    }

    system_prompt = (
        "You are an AI that only responds with valid JSON. "
        "Do not include any explanations or natural language text. "
        "Just return a JSON object with the format:\n"
        "{ 'board': 'CBSE', 'class': '10', 'subject': ['Mathematics'], 'questions': [ { 'question': ..., 'options': [...], 'correct_answer': ... } ] }\n"
        f"Generate exactly {total_questions} MCQs based on provided inputs."
    )

    ollama_prompt = f"{system_prompt}\n{json.dumps(prompt_data, indent=4)}"

    try:
        result = subprocess.run(["ollama", "run", "llama3"], input=ollama_prompt, capture_output=True, text=True, timeout=1000000)
        output = result.stdout.strip()
        print("OLLAMA MCQ OUTPUT:\n", output)
        paper_json = json.loads(output[output.find('{'):output.rfind('}')+1]) if output else {}
        if not paper_json.get("questions"):
            return "Error: Ollama did not return valid questions. Please retry with more input."
    except Exception as e:
        print(f"Error generating JSON with Ollama: {e}")
        return f"Error: Could not generate questions. Details: {str(e)}"

    with open("paper.json", "w") as f:
        json.dump(paper_json, f)

    generate_pdf(paper_json, "Question.pdf")

    return render_template('result.html', paper_json=paper_json, pdf_code="PDF generated successfully.")

def generate_pdf(data, output_pdf):
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', os.path.join("fonts", 'DejaVuSans.ttf'), uni=True)
    pdf.set_font("DejaVu", size=12)

    pdf.cell(200, 10, txt="Generated Question Paper", ln=1, align='C')
    pdf.cell(200, 10, txt=f"Board: {data.get('board', 'N/A')}, Class: {data.get('class', 'N/A')}, Subject: {', '.join(data.get('subject', []))}", ln=2, align='C')
    pdf.ln(10)

    for idx, q in enumerate(data.get("questions", []), start=1):
        pdf.multi_cell(0, 10, txt=f"{idx}. {q.get('question')}")
        pdf.ln(3)
        for i, opt in enumerate(q.get("options", []), start=1):
            pdf.cell(0, 10, txt=f"({chr(64+i)}) {opt}", ln=1)
        pdf.cell(0, 10, txt=f"Correct Answer: {q.get('correct_answer')}", ln=1)
        pdf.ln(5)

    pdf.output(output_pdf)

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

if __name__ == '__main__':
    app.run(debug=True)