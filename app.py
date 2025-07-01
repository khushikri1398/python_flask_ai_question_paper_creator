import re
import os
import json
import pprint
import requests
import subprocess
from fpdf import FPDF
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session

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

    subject_chapter_map = {}
    chapter_number_to_name_map = {}

    def extract_prefix(text):
        """Extracts numeric prefix like '1.1', '2.1.3' from text."""
        match = re.match(r"^([\d\.]+)", text.strip())
        return match.group(1) if match else None

    for subject in subjects:
        matching_book = next(
            (book for book in textbooks
             if book.get('board') == board and str(book.get('class')) == class_name and book.get('subject') == subject),
            None
        )

        if not matching_book:
            print(f"No matching textbook found for subject: {subject}")
            continue

        book_id = matching_book.get("id")
        try:
            response = requests.get(f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json")
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"Error fetching page attributes for {subject}: {e}")
            continue

        # Separate and sort by order
        chapters = sorted([item for item in data if item.get("type") == "chapter"], key=lambda x: x.get('order', 0))
        topics = sorted([item for item in data if item.get("type") == "topic"], key=lambda x: x.get('order', 0))
        subtopics = sorted([item for item in data if item.get("type") == "subtopic"], key=lambda x: x.get('order', 0))

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

        subject_chapter_map[subject] = final_chapters
        chapter_number_to_name_map[subject] = chapter_number_name_map

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
                           subject_chapter_map=subject_chapter_map)
    
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
    chapter["topics"] = normalized_topics
    return chapter

@app.route('/generate', methods=['POST'])
def generate():
    # Step 1: Get form data
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    chapters = request.form.getlist("chapters")
    selected_topics = request.form.getlist("topics")
    selected_subtopics = request.form.getlist("subtopics")

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
    list_data = session.get("list_to_generate_questions", {})
    if not list_data:
        return "Session expired or no data available. Please start again."

    board = list_data.get("board")
    class_name = list_data.get("class")
    subjects = list_data.get("subjects")
    chapters = list_data.get("chapters", [])
    topics = list_data.get("topics", [])
    subtopics = list_data.get("subtopics", [])

    # Just in case defaults were not set earlier
    min_questions = request.args.get("min_questions", "1")
    max_questions = request.args.get("max_questions", "2")
    total_questions = request.args.get("total_questions", "10")

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
        paper_json = json.loads(output[output.find('{'):output.rfind('}')+1]) if output else {}
        if not paper_json.get("questions"):
            return "Error: Ollama did not return valid questions. Please retry with more input."
    except Exception as e:
        return f"Error: Could not generate questions. Details: {str(e)}"

    with open("paper.json", "w") as f:
        json.dump(paper_json, f)

    generate_pdf(paper_json, "Question.pdf")

    return render_template('result.html', paper_json=paper_json, pdf_code="PDF generated successfully.")

def generate_pdf(data, output_pdf):
    pdf = FPDF()
    pdf.add_page()
    # pdf.add_font('DejaVu', '', os.path.join("fonts", 'DejaVuSans.ttf'), uni=True)
    pdf.set_font("Arial", size=12)
    # pdf.set_font("DejaVu", size=12)

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

def fetch_structured_previous_year_content(board, class_name, subjects, depth=1, max_depth=3):
    if depth > max_depth:
        return {}

    previous_class = str(int(class_name) - 1)
    try:
        response = requests.get(TEXTBOOKS_API)
        response.raise_for_status()
        textbooks = response.json().get('data', {}).get('getBooks', [])
    except requests.RequestException as e:
        return {}

    full_structure = {}

    for subject in subjects:
        book = next(
            (b for b in textbooks if b.get('board') == board and str(b.get('class')) == previous_class and b.get('subject') == subject),
            None
        )
        if not book:
            continue

        book_id = book.get("id")
        try:
            response = requests.get(f"https://staticapis.pragament.com/textbooks/page_attributes/{book_id}.json")
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
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

        full_structure[subject] = full_chapter_structure

    # Save full_structure to file
    os.makedirs("structured_data", exist_ok=True)
    path = f"structured_data/previous_year_depth_{depth}.json"
    with open(path, "w") as f:
        json.dump(full_structure, f, indent=4)
    return full_structure

# --- Recursive Prerequisite Route ---
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
        if request.method == "POST":
            selected_chapters = request.form.getlist("selected_prereq_chapter")
            selected_topics = request.form.getlist("selected_prereq_topic")
            selected_subtopics = request.form.getlist("selected_prereq_subtopic")

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

            for ch_name in selected_chapters:
                for subject in previous_level_data:
                    full_chapter_list = previous_level_data[subject]
                    matched = next((ch for ch in full_chapter_list if ch["chapter"] == ch_name), None)
                    if matched and matched["chapter"] not in {item["chapter"] for item in current_structure[class_key][subject]}:
                        chapter_obj = normalize_chapter_structure(matched)
                        current_structure[class_key][subject].append(chapter_obj)

            for subject in previous_level_data:
                full_chapter_list = previous_level_data[subject]
                for chapter in full_chapter_list:
                    chapter_name = chapter.get("chapter")
                    if chapter_name in {item["chapter"] for item in current_structure[class_key][subject]}:
                        continue
                    matched = False
                    for topic in chapter.get("topics", []):
                        if topic.get("topic") in selected_topics or any(sub.get("text") in selected_subtopics for sub in topic.get("subtopics", [])):
                            matched = True
                            break
                    if matched:
                        chapter_obj = normalize_chapter_structure(chapter)
                        current_structure[class_key][subject].append(chapter_obj)

            with open(selected_structure_path, "w") as f:
                json.dump(current_structure, f, indent=4)

        # Inject reason logic
        with open(selected_structure_path, "r") as f:
            selected_data = json.load(f)

        render_path = os.path.join("structured_data", f"prereq_render_items_level_{level - 1}.json")
        if os.path.exists(render_path):
            with open(render_path, "r") as f:
                render_items = json.load(f)
        else:
            render_items = []

        # Build normalized reason map
        reason_map = {
            (item.get("subject", "").strip().lower(), item.get("chapter", "").strip().lower()): item.get("reason")
            for item in render_items
        }

        # Inject reasons into selected_data
        for class_key, subjects_data in selected_data.items():
            for subject, chapter_list in subjects_data.items():
                subj_key = subject.strip().lower()
                for chapter in chapter_list:
                    chap_key = chapter.get("chapter", "").strip().lower()
                    reason = reason_map.get((subj_key, chap_key))
                    if reason:
                        chapter["reason"] = reason

        print("Selected Data with Reasons:")
        import pprint
        pprint.pprint(selected_data)
        pprint.pprint(current_structure)

        return render_template("next_step.html", selected_json=selected_data)

    # --- NORMAL FLOW ---
    if request.method == 'POST':
        selected_chapters = request.form.getlist("selected_prereq_chapter")
        selected_topics = request.form.getlist("selected_prereq_topic")
        selected_subtopics = request.form.getlist("selected_prereq_subtopic")
    else:
        selected_chapters = selected_chapter_names
        selected_topics = []
        selected_subtopics = []

    prev_year_struct_path = f"structured_data/previous_year_depth_{level}.json"
    if os.path.exists(prev_year_struct_path):
        with open(prev_year_struct_path, "r") as f:
            previous_year_data = json.load(f)
    else:
        previous_year_data = fetch_structured_previous_year_content(
            board, str(int(class_name) - level + 1), subjects, depth=level, max_depth=5
        )

    chapter_index_map = {
        subject: {ch['number']: ch['chapter'] for ch in chapters}
        for subject, chapters in previous_year_data.items()
    }

    prompt = f"""
You are an academic AI assistant.

Given:
- The selected chapters by the user from the previous year (with chapter numbers and names).
- The older year's chapter list for the same subject and board.

Return only relevant prerequisites (chapter number + name) with reasons.

Format:
{{
  "prerequisites": {{
    "Subject": [
      {{
        "number": 1,
        "chapter": "Exact Chapter Name",
        "reason": "Why this chapter is needed"
      }}
    ]
  }}
}}

Selected Chapters:
{json.dumps(selected_chapters, indent=2)}

Previous Year Chapters:
{json.dumps(chapter_index_map, indent=2)}
"""

    try:
        result = subprocess.run([
            "ollama", "run", "llama3"
        ], input=prompt, capture_output=True, text=True, timeout=1000000)
        output = result.stdout.strip()
        prereq_json = json.loads(output[output.find("{"):output.rfind("}") + 1]) if output else {}
    except Exception as e:
        return f"Error during prerequisite generation: {str(e)}"

    render_items = []
    for subject, prereqs in prereq_json.get("prerequisites", {}).items():
        full_chapter_list = previous_year_data.get(subject, [])
        for req in prereqs:
            chapter_num = req["number"]
            matched_ch = next((ch for ch in full_chapter_list if ch.get("number") == chapter_num), None)
            if matched_ch:
                render_items.append({
                    "subject": subject,
                    "number": chapter_num,
                    "chapter": matched_ch.get("chapter", ""),
                    "topics": matched_ch.get("topics", []),
                    "reason": req.get("reason", "")
                })

    with open(os.path.join("structured_data", f"prereq_render_items_level_{level}.json"), "w") as f:
        json.dump(render_items, f, indent=2)

    if request.method == "POST":
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

        for ch_name in selected_chapters:
            for subject in previous_level_data:
                full_chapter_list = previous_level_data[subject]
                matched = next((ch for ch in full_chapter_list if ch["chapter"] == ch_name), None)
                if matched and matched["chapter"] not in {item["chapter"] for item in current_structure[class_key][subject]}:
                    chapter_obj = normalize_chapter_structure(matched)
                    current_structure[class_key][subject].append(chapter_obj)

        for subject in previous_level_data:
            full_chapter_list = previous_level_data[subject]
            for chapter in full_chapter_list:
                chapter_name = chapter.get("chapter")
                if chapter_name in {item["chapter"] for item in current_structure[class_key][subject]}:
                    continue
                matched = False
                for topic in chapter.get("topics", []):
                    if topic.get("topic") in selected_topics or any(sub.get("text") in selected_subtopics for sub in topic.get("subtopics", [])):
                        matched = True
                        break
                if matched:
                    chapter_obj = normalize_chapter_structure(chapter)
                    current_structure[class_key][subject].append(chapter_obj)

        with open(selected_structure_path, "w") as f:
            json.dump(current_structure, f, indent=4)
        
        inject_reasons_into_selected_data(current_structure, level - 1)
        with open(selected_structure_path, "w") as f:
            json.dump(current_structure, f, indent=4)

    return render_template("recursive_prereq.html", prerequisites=render_items, level=level + 1)

def inject_reasons_into_selected_data(selected_data, level):
    render_path = os.path.join("structured_data", f"prereq_render_items_level_{level}.json")
    if not os.path.exists(render_path):
        return

    with open(render_path, "r") as f:
        render_items = json.load(f)

    reason_map = {
        (item.get("subject", "").strip().lower(), item.get("chapter", "").strip().lower()): item.get("reason")
        for item in render_items
    }

    for class_key, subjects_data in selected_data.items():
        for subject, chapter_list in subjects_data.items():
            subj_key = subject.strip().lower()
            for chapter in chapter_list:
                chap_key = chapter.get("chapter", "").strip().lower()
                reason = reason_map.get((subj_key, chap_key))
                if reason:
                    chapter["reason"] = reason

if __name__ == '__main__':
    app.run(debug=True)