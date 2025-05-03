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
    subject = request.form.get("subject")

    print(f"Received Board: {board}, Class: {class_name}, Subject: {subject}")

    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])

        matching_book = next(
            (book for book in textbooks if
             book.get('board') == board and
             str(book.get('class')) == class_name and
             book.get('subject') == subject),
            None
        )

        if not matching_book:
            print("No matching textbook found for the given inputs.")
            return render_template('select.html', board=board, class_name=class_name, subject=subject,
                                   chapters=[], topics=[], subtopics=[])

        book_id = matching_book.get("id") 
        print(f"Matched book ID (subject ID): {book_id}")

        page_attr_url = f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json"
        response = requests.get(page_attr_url)
        response.raise_for_status()
        topics_data = response.json()
    except requests.RequestException as e:
        print(f"Error fetching page attributes: {e}")
        topics_data = []

    chapters = [item for item in topics_data if item.get('type') == 'chapter']
    topics = [item for item in topics_data if item.get('type') == 'topic']
    subtopics = [item for item in topics_data if item.get('type') == 'subtopic']

    return render_template('select.html', board=board, class_name=class_name, subject=subject,
                           chapters=chapters, topics=topics, subtopics=subtopics)


@app.route('/generate', methods=['POST'])
def generate():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subject = request.form.get("subject")
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
        "subject": subject if subject else "Unknown",
        "chapters": chapters,
        "topics": topics,
        "subtopics": subtopics,
        "min_questions": min_questions or "1",
        "max_questions": max_questions or "1",
        "total_questions": total_questions or "1"
    }

    system_prompt = (
    "You are an AI that only responds with valid JSON."
    "Do not include any explanations or natural language text. "
    "Just return a JSON object with the following format:\n"
    "{\n"
    '  "board": "CBSE",\n'
    '  "class": "10",\n'
    '  "subject": "Mathematics",\n'
    '  "questions": [\n'
    "    {\n"
    '      "question": "Sample question?",\n'
    '      "options": ["Option A", "Option B", "Option C", "Option D"],\n'
    '      "correct_answer": "Option A"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Generate exactly {n} multiple-choice questions. "
    "Ensure each has 4 options and 1 correct answer. "
    "Base the questions on the provided subject, class, board, chapters, topics, and subtopics. "
    "Respond only with JSON.".replace("{n}", str(prompt_data['total_questions']))
    )


    ollama_prompt = f"{system_prompt}\n{json.dumps(prompt_data, indent=4)}"

    model_name = "llama3"

    try:
        result = subprocess.run(
            ["ollama", "run", model_name],
            input=ollama_prompt,
            capture_output=True,
            text=True,
            timeout=1600
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

    # Save JSON to file
    json_path = "paper.json"
    with open(json_path, "w") as f:
        json.dump(paper_json, f)

    # Generate PDF
    pdf_path = "Question.pdf"
    generate_pdf(paper_json, pdf_path)

    return render_template('result.html', paper_json=paper_json, pdf_code="PDF generated successfully.")


def generate_pdf(data, output_pdf):
    pdf = FPDF()
    pdf.add_page()
    
    # Add Unicode font
    font_path = "fonts\DejaVuSans.ttf"
    pdf.add_font('DejaVu', '', font_path, uni=True)
    pdf.set_font("DejaVu", size=12)

    pdf.cell(200, 10, txt="Generated Question Paper", ln=1, align='C')
    pdf.cell(200, 10, txt=f"Board: {data.get('board', 'N/A')}, Class: {data.get('class', 'N/A')}, Subject: {data.get('subject', 'N/A')}", ln=2, align='C')
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
