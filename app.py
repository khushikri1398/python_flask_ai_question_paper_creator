from flask import Flask, render_template, request, jsonify, send_file
import requests
import subprocess
import json
from fpdf import FPDF
import os

app = Flask(__name__)

TEXTBOOKS_API = "https://staticapis.pragament.com/textbooks/allbooks.json"
PAGE_ATTRIBUTES_API = "https://staticapis.pragament.com/textbooks/page_attributes/668e5c2d3b5af2561c87eab5.json"

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
    subjects = request.form.getlist("subject")  # Changed to handle multiple subjects

    print(f"Received Board: {board}, Class: {class_name}, Subjects: {subjects}")

    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        print(f"Error fetching textbooks: {e}")
        textbooks = []

    all_chapters = []
    all_topics = []
    all_subtopics = []

    for subject in subjects:
        matching_book = next(
            (book for book in textbooks if
             book.get('board') == board and
             str(book.get('class')) == class_name and
             book.get('subject') == subject),
            None
        )

        if not matching_book:
            print(f"No matching textbook found for subject: {subject}")
            continue

        book_id = matching_book.get("id")
        print(f"Matched book ID for {subject}: {book_id}")

        try:
            page_attr_url = f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json"
            response = requests.get(page_attr_url)
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

    prompt_data = {
        "task": "Generate multiple-choice questions",
        "board": board if board else "Unknown",
        "class": class_name if class_name else "Unknown",
        "subject": subjects if subjects else ["Unknown"],
        "chapters": chapters,
        "topics": topics,
        "subtopics": subtopics,
        "min_questions": min_questions or "1",
        "max_questions": max_questions or "1",
        "total_questions": total_questions or "1"
    }

    system_prompt = (
        "You are an AI that only responds with valid JSON. "
        "Do not include any explanations or natural language text. "
        "Just return a JSON object with the following format:\n"
        "{\n"
        '  "board": "CBSE",\n'
        '  "class": "10",\n'
        '  "subject": ["Mathematics", "Science"],\n'
        '  "questions": [\n'
        "    {\n"
        '      "question": "Sample question?",\n'
        '      "options": ["Option A", "Option B", "Option C", "Option D"],\n'
        '      "correct_answer": "Option A"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        f"Generate exactly {prompt_data['total_questions']} multiple-choice questions. "
        "Ensure each has 4 options and 1 correct answer. "
        "Base the questions on the provided board, class, subjects (multiple allowed), chapters, topics, and subtopics. "
        "Respond only with JSON."
    )

    ollama_prompt = f"{system_prompt}\n{json.dumps(prompt_data, indent=4)}"

    model_name = "llama3"

    try:
        result = subprocess.run(
            ["ollama", "run", model_name],
            input=ollama_prompt,
            capture_output=True,
            text=True,
            timeout=1000000
        )

        print(f"Ollama raw output:\n{result.stdout}")

        if result.returncode != 0 or not result.stdout.strip():
            print(f"Error executing Ollama:\nstderr: {result.stderr}")
            paper_json = {}
        else:
            try:
                # Try parsing directly
                paper_json = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Fallback: extract JSON from output
                try:
                    json_start = result.stdout.find("{")
                    json_end = result.stdout.rfind("}") + 1
                    paper_json = json.loads(result.stdout[json_start:json_end])
                except Exception as e:
                    print(f"Fallback JSON extraction failed: {e}")
                    paper_json = {}

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Error generating JSON with Ollama: {e}")
        paper_json = {}

    json_path = "paper.json"
    with open(json_path, "w") as f:
        json.dump(paper_json, f)

    pdf_path = "Question.pdf"
    generate_pdf(paper_json, pdf_path)

    return render_template('result.html', paper_json=paper_json, pdf_code="PDF generated successfully.")



def generate_pdf(data, output_pdf):
    pdf = FPDF()
    pdf.add_page()
    
    # Add Unicode font
    font_path = os.path.join("fonts", 'DejaVuSans.ttf')
    pdf.add_font('DejaVu', '', font_path, uni=True)
    pdf.set_font("DejaVu", size=12)

    pdf.cell(200, 10, txt="Generated Question Paper", ln=1, align='C')

    subjects = data.get('subject', [])
    subjects_str = ", ".join(subjects) if isinstance(subjects, list) else subjects
    pdf.cell(200, 10, txt=f"Board: {data.get('board', 'N/A')}, Class: {data.get('class', 'N/A')}, Subject: {subjects_str}", ln=2, align='C')
    pdf.ln(10)

    questions = data.get("questions", [])

    if not questions:
        pdf.cell(200, 10, txt="No questions available.", ln=1, align='C')
    else:
        for idx, q in enumerate(questions, start=1):
            pdf.multi_cell(0, 10, txt=f"{idx}. {q.get('question', 'No question text available')}")
            pdf.ln(3)

            for opt_idx, opt in enumerate(q.get("options", []), start=1):
                pdf.cell(0, 10, txt=f"({chr(64 + opt_idx)}) {opt}", ln=1)

            pdf.cell(0, 10, txt=f"Correct Answer: {q.get('correct_answer', 'N/A')}", ln=1)
            pdf.ln(5)

    pdf.output(output_pdf)
    print(f"PDF successfully generated: {output_pdf}")

@app.route('/download_pdf')
def download_pdf():
    pdf_path = "Question.pdf"

    try:
        with open("paper.json", "r") as f:
            paper_json = json.load(f)

        if not paper_json.get("questions", []):
            return "Error: No questions available in the JSON."

        if not os.path.exists(pdf_path):
            generate_pdf(paper_json, pdf_path)

        return send_file(pdf_path, as_attachment=True)

    except FileNotFoundError:
        return "Error: paper.json file is missing."
    except json.JSONDecodeError:
        return "Error: Invalid JSON format."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
