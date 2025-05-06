from flask import Flask, Response, request, render_template_string
from omr_pdf import OMRGenerator

app = Flask(__name__)

FORM_HTML = """
<!doctype html>
<html>
<head>
    <title>OMR Sheet Generator</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        h2 { color: #333; }
        input[type="number"] { padding: 8px; margin: 10px 0; width: 100px; }
        input[type="submit"] { padding: 10px 15px; background-color: #4CAF50; color: white; 
                              border: none; cursor: pointer; }
        input[type="submit"]:hover { background-color: #45a049; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Generate OMR Answer Sheet PDF</h2>
        <form method="post">
            <div>
                <label for="questions">Number of Questions:</label>
                <input type="number" id="questions" name="questions" value="40" min="1" max="200">
            </div>
            <div>
                <input type="submit" value="Generate OMR Sheet">
            </div>
        </form>
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        questions = int(request.form['questions'])
        pdf = OMRGenerator(questions)
        pdf_bytes = pdf.generate()
        return Response(pdf_bytes, mimetype='application/pdf',
                        headers={"Content-Disposition": "attachment;filename=omr_sheet.pdf"})
    return render_template_string(FORM_HTML)

if __name__ == '__main__':
    app.run(debug=True)
