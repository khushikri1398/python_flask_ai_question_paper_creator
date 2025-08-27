# 🧠 AI-Based Question Paper and OMR Sheet Generator

An intelligent Flask application that automates MCQ paper creation and OMR sheet generation. Leverages LLMs (via Ollama and LLaMA 3) to generate prerequisite knowledge and MCQs based on selected curriculum data.


## 🚀 Features

### 📄 Question Paper Generator
- Select **board**, **class**, **subject**, **chapters**, **topics**, and **subtopics**
- Generate intelligent **MCQs** using **Llama3** via **Ollama**
- Automatically detect **prerequisite topics** with reasoning
- Export question papers as **PDF files**

### 📝 OMR Answer Sheet Generator
- Bubble-based answer areas (a–d), admission number field, instruction block
- Branding support via image in all four corners
- Generates high-resolution printable PDF

---

## 🛠️ Build & Run Instructions

### 1. 📥 Clone the Repository

```bash
git clone https://github.com/Pragament/python_flask_ai_question_paper_creator.git
cd python_flask_ai_question_paper_creator
````

---

### 2. 🧪 Install Python Dependencies

Ensure Python 3.8+ is installed.

Use the provided `requirements.txt`:

```txt
flask
fpdf
requests
python-dotenv
Pillow
```

Install with:

```bash
pip install -r requirements.txt
pyinstaller YourFlaskApp.spec
```

---

### 3. 🤖 Set Up Ollama for AI

Install [Ollama](https://ollama.com/) and run:

```bash
ollama run llama3
```

Ensure `ollama` is working from your terminal. The app uses it to generate prerequisites and questions.

---

### 4. 🖼️ Optional – Add Branding Image

Place a file named `img1.jpg` in the `static/` folder. This image appears at the four corners of the OMR sheet.

---

### 5. 🚀 Run the Application

```bash
python app.py
```

Visit the web app at:

```
 http://127.0.0.1:5000
```


## 📁 Folder Structure

```
├── app.py                           # Main Flask app
├── omr_generator_app.py            # OMR sheet generator logic
├── omr_pdf.py                      # OMR PDF generation utilities
├── paper.json                      # AI-generated MCQs & structure
├── Question.pdf                    # Generated MCQ PDF output
├── img1.jpg                        # Branding image for OMR (optional)
├── LICENSE                         # MIT License
├── README.md                       # This file
├── requirements.txt                # Python dependencies
│
├── templates/                      # HTML templates
│   ├── index.html
│   ├── select.html
│   ├── select_prereq.html
│   ├── next_step.html
│   └── result.html
│
├── fonts/                          # DejaVu fonts for PDF rendering
│   ├── DejaVuSans.ttf
│   ├── DejaVuSans.pk
│   └── DejaVuSans.cw127
```

---


## 📄 License

This project is open-source and available under the [MIT License](LICENSE).


