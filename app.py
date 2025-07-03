import re
import os
import json
import pprint
import requests
import subprocess
import io
import uuid
from fpdf import FPDF
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm

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
    return render_template('index.html', textbooks=textbooks, textbooks_json=json.dumps(textbooks))

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

    return {
        "number": chapter.get("number"),
        "chapter": chapter.get("chapter"),
        "topics": normalized_topics,
        "reason": chapter.get("reason"),
        "for": chapter.get("for")
    }

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
    # Load selected structure
    try:
        with open("structured_data/selected_structure.json", "r") as f:
            selected_structure = json.load(f)
    except FileNotFoundError:
        return "Error: selected_structure.json not found."

    # Load and build tree
    tree = build_prerequisite_tree(selected_structure)

    # Flatten tree to markdown-style input
    def flatten_tree(chapters, level=0):
        lines = []
        for ch in chapters:
            prefix = "  " * level + "- "
            line = f"{prefix}{ch['chapter']} (Chapter {ch['number']}, {ch['class']})"
            if "reason" in ch:
                line += f"\n{'  ' * (level + 1)}Reason: {ch['reason']}"
            lines.append(line)
            if ch.get("prerequisites"):
                lines.extend(flatten_tree(ch["prerequisites"], level + 1))
        return lines

    flat_lines = []
    for class_key, subject_map in tree.items():
        for subject, chapters in subject_map.items():
            flat_lines.append(f"## {subject} - {class_key}")
            flat_lines.extend(flatten_tree(chapters, 1))

    prerequisite_text = "\n".join(flat_lines)

    # Basic metadata for prompt
    class_name = list(selected_structure.keys())[0].replace("class_", "")
    subjects = list(selected_structure[list(selected_structure.keys())[0]].keys())

    min_questions = request.args.get("min_questions", "1")
    max_questions = request.args.get("max_questions", "2")
    total_questions = request.args.get("total_questions", "10")

    prompt_data = {
        "task": "Generate multiple-choice questions",
        "class": class_name,
        "subjects": subjects,
        "prerequisites": prerequisite_text,
        "min_questions": min_questions,
        "max_questions": max_questions,
        "total_questions": total_questions
    }

    system_prompt = (
        "You are an AI that only responds with valid JSON. "
        "Do not include any explanations or natural language text. "
        "Just return a JSON object with the format:\n"
        "{ 'class': '8', 'subject': ['Mathematics'], 'questions': [ { 'question': ..., 'options': [...], 'correct_answer': ... } ] }\n"
        f"Generate exactly {total_questions} MCQs based on the prerequisite context provided below."
    )

    ollama_prompt = f"{system_prompt}\n\n---\n\n{json.dumps(prompt_data, indent=2)}"

    try:
        result = subprocess.run(["ollama", "run", "llama3"], input=ollama_prompt, capture_output=True, text=True, timeout=1000000)
        output = result.stdout.strip()
        print("Ollama Output:", output)
        paper_json = json.loads(output[output.find('{'):output.rfind('}') + 1]) if output else {}
        if not paper_json.get("questions"):
            return "Error: Ollama did not return valid questions. Please retry."
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

    # Create subject → chapter name → chapter dict map for all classes
    all_chapter_map = {}
    for class_key in selected_structure:
        for subject, chapters in selected_structure[class_key].items():
            all_chapter_map.setdefault(subject, {})
            for ch in chapters:
                ch_name = ch.get("chapter")
                if ch_name:
                    all_chapter_map[subject][ch_name] = copy.deepcopy(ch)

    # Helper to recursively attach prerequisites
    def attach_prerequisites(subject, chapter_name, current_class_index, visited=None):
        if visited is None:
            visited = set()
        if chapter_name in visited:
            return []
        visited.add(chapter_name)

        prerequisites = []
        # Look only in lower classes
        for lower_class_index in range(current_class_index + 1, len(sorted_classes)):
            class_key = sorted_classes[lower_class_index]
            chapters = selected_structure.get(class_key, {}).get(subject, [])

            for ch in chapters:
                target = ch.get("for")
                ch_name = ch.get("chapter")

                # Case 1: Chapter explicitly points to current chapter
                if target == chapter_name:
                    ch_copy = copy.deepcopy(ch)
                    ch_copy.pop("for", None)
                    ch_copy["prerequisites"] = attach_prerequisites(subject, ch_name, lower_class_index, visited)
                    prerequisites.append(ch_copy)

                # Case 2: No "for" field — assume it applies to all higher chapters
                elif not target:
                    ch_copy = copy.deepcopy(ch)
                    ch_copy["prerequisites"] = attach_prerequisites(subject, ch_name, lower_class_index, visited)
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
    if level > 1:
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
            board, str(int(class_name) - level + 1), subjects, depth=level, max_depth=5
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

if __name__ == '__main__':
    app.run(debug=True)