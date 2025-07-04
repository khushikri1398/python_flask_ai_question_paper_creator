from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
import os
import json
import subprocess
import uuid

from utils import (
    read_json,
    write_json,
    load_json,
    fetch_textbooks,
    build_subject_chapter_map,
    build_selected_structure,
    build_prompt,
    generate_pdf,
    generate_prerequisite_pdf,
    handle_final_level,
    build_prerequisite_tree,
    fetch_structured_previous_year_content,
)

SUBJECT_NAME_MAP_BY_CLASS = {
    "Mathematics": {
        "10": "Mathematics",
        "9": "Maths",
        "8": "Mathematics",
        "7": "Mathematics",
        "6": "Mathematics",
        "5": "Mathematics",
        "4": "Maths",
    },
    "Science": {
        "10": "Science",
        "9": "General Science",
        "8": "Science"
    },
    "Social Science": {
        "10": "Social Studies",
        "9": "Social Science",
        "8": "Social"
    },
    "English": {
        "10": "English",
        "9": "English",
        "8": "English"
    }
}

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def index():
    textbooks = fetch_textbooks()
    return render_template('index.html', textbooks=textbooks, textbooks_json=json.dumps(textbooks))

@app.route('/select', methods=['POST'])
def select():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")

    textbooks = fetch_textbooks()
    subject_chapter_map, chapter_number_to_name_map = build_subject_chapter_map(board, class_name, subjects, textbooks)

    os.makedirs("structured_data", exist_ok=True)
    write_json(subject_chapter_map, "structured_data/all_chapters.json")

    session['chapter_number_to_name_map'] = chapter_number_to_name_map

    return render_template('select.html',
                           board=board,
                           class_name=class_name,
                           subjects=subjects,
                           subject_chapter_map=subject_chapter_map)

@app.route('/generate', methods=['POST'])
def generate():
    board = request.form.get("board")
    class_name = request.form.get("class")
    subjects = request.form.getlist("subject")
    chapters = request.form.getlist("chapters")

    all_chapters_by_subject = load_json("structured_data/all_chapters.json")
    selected_structure = build_selected_structure(class_name, subjects, chapters, all_chapters_by_subject)

    os.makedirs("structured_data", exist_ok=True)
    write_json(selected_structure, "structured_data/selected_structure.json")

    session['form_data'] = {
        "board": board,
        "class": class_name,
        "subjects": subjects,
        "chapters": chapters
    }

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
    selected_structure = read_json("structured_data/selected_structure.json")
    tree = build_prerequisite_tree(selected_structure)

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

    write_json(paper_json, "paper.json")
    generate_pdf(paper_json, "Question.pdf")

    return render_template('result.html', paper_json=paper_json, pdf_code="PDF generated successfully.")

@app.route('/download_prereqs')
def download_prereqs():
    try:
        tree = read_json("structured_data/prerequisite_tree.json")
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
        paper_json = read_json("paper.json")
        if not paper_json.get("questions"):
            return "Error: No questions available."
        if not os.path.exists("Question.pdf"):
            generate_pdf(paper_json, "Question.pdf")
        return send_file("Question.pdf", as_attachment=True)
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/recursive_prereq/<int:level>', methods=['GET', 'POST'])
def recursive_prereq(level):
    board = session.get("form_data", {}).get("board")
    class_name = session.get("form_data", {}).get("class")
    subjects = session.get("form_data", {}).get("subjects", [])

    if level > 2:
        return handle_final_level(level, class_name, subjects, "structured_data/selected_structure.json")

    prev_year_struct_path = f"structured_data/previous_year_depth_{level}.json"
    if os.path.exists(prev_year_struct_path):
        previous_year_data = read_json(prev_year_struct_path)
    else:
        prev_class = str(int(class_name) - level + 1)
        previous_year_data = fetch_structured_previous_year_content(
            board, prev_class, subjects, depth=level, max_depth=5
        )

    selected_combined = request.form.getlist("selected_prereq_combined") if request.method == "POST" else []
    selected_chapters = []
    subject_to_selected_chapters = {}

    # ✅ Always build subject-to-chapter map from previous render items
    if selected_combined:
        selected_ids = [item.split("|||")[0] for item in selected_combined]
        prev_level_items_path = f"structured_data/prereq_render_items_level_{level - 1}.json"
        if os.path.exists(prev_level_items_path):
            prev_items = read_json(prev_level_items_path)
            for item in prev_items:
                if item["id"] in selected_ids:
                    subject = item.get("subject")
                    chapter = item.get("chapter")
                    subject_to_selected_chapters.setdefault(subject, set()).add(chapter)
    else:
        # ✅ Special fallback ONLY for level 1 (when nothing is selected yet)
        if level == 1:
            selected_structure = read_json("structured_data/selected_structure.json")
            current_class_key = f"class_{int(class_name)}"
            for subject, chapters in selected_structure.get(current_class_key, {}).items():
                for ch in chapters:
                    chapter = ch.get("chapter")
                    if chapter:
                        subject_to_selected_chapters.setdefault(subject, set()).add(chapter)

    print("🎯 Subject-to-chapter mapping for prompt generation:", subject_to_selected_chapters)

    prev_class_num = str(int(class_name) - level + 1)

    render_items = set()

    render_items = []
    prompted_chapters = set()

    for subject, chapter_names in subject_to_selected_chapters.items():
        normalized_name = None
        for canonical, mapping in SUBJECT_NAME_MAP_BY_CLASS.items():
            if subject == canonical or subject in mapping.values():
                normalized_name = mapping.get(prev_class_num)
                break
        if not normalized_name:
            normalized_name = subject

        previous_year_chapters = previous_year_data.get(normalized_name, [])
        if not previous_year_chapters:
            continue
        for chapter_name in chapter_names:
            if not chapter_name or (subject, chapter_name) in prompted_chapters:
                continue
            prompted_chapters.add((subject, chapter_name))

            prompt = build_prompt(subject, chapter_name, previous_year_chapters)

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

                for req in prereqs:
                    chapter_num = req.get("number")
                    matched_ch = next((c for c in previous_year_chapters if c.get("number") == chapter_num), None)
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
                print(f"❌ Error while generating prereqs for {subject} - {chapter_name}: {e}")
                continue

    output_path = f"structured_data/prereq_render_items_level_{level}.json"
    os.makedirs("structured_data", exist_ok=True)
    write_json(render_items, output_path)

    # --- Write mid-level prerequisites to selected_structure.json if level > 1
    if level > 1:
        selected_structure = read_json("structured_data/selected_structure.json")
        class_key = f"class_{int(class_name) - level + 1}"
        selected_structure.setdefault(class_key, {})
        for item in render_items:
            subject = item["subject"]
            normalized_subject = None
            for canonical, mapping in SUBJECT_NAME_MAP_BY_CLASS.items():
                if subject == canonical or subject in mapping.values():
                    normalized_subject = mapping.get(str(int(class_name) - level + 1))
                    break
            if not normalized_subject:
                normalized_subject = subject
            chapter = item["chapter"]
            matched = next((ch for ch in previous_year_data.get(normalized_subject, []) if ch["chapter"] == chapter), None)
            if not matched:
                continue
            chapter_obj = {
                "number": item["number"],
                "chapter": chapter,
                "topics": matched.get("topics", []),
                "reason": item.get("reason"),
                "for": item.get("for")
            }
            selected_structure[class_key].setdefault(normalized_subject, [])
            if not any(c.get("chapter") == chapter_obj["chapter"] and c.get("for") == chapter_obj.get("for") for c in selected_structure[class_key][normalized_subject]):
                selected_structure[class_key][normalized_subject].append(chapter_obj)
        write_json(selected_structure, "structured_data/selected_structure.json")

    return render_template("recursive_prereq.html",
                           prerequisites=render_items,
                           level=level + 1,
                           class_name=(int(class_name) - level))

if __name__ == '__main__':
    app.run(debug=True)