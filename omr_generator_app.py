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
        .container { max-width: 400px; margin: 0 auto; }
        h2 { color: #333; text-align: center; }
        table { width: 100%; border-collapse: separate; border-spacing: 0 16px; }
        td { vertical-align: middle; }
        label { font-size: 1.05em; }
        input[type="number"] {
            padding: 8px;
            width: 120px;
            font-size: 1em;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        .submit-row { text-align: center; }
        input[type="submit"] {
            padding: 10px 25px;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 1.1em;
            cursor: pointer;
            margin-top: 10px;
        }
        input[type="submit"]:hover {
            background-color: #45a049;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>Generate OMR Answer Sheet PDF</h2>
        <form method="post">
            <table>
                <tr>
                    <td><label for="math1">Mathematics-1:</label></td>
                    <td><input type="number" id="math1" name="math1" value="50" min="0" max="100"></td>
                </tr>
                <tr>
                    <td><label for="math2">Mathematics-2:</label></td>
                    <td><input type="number" id="math2" name="math2" value="50" min="0" max="100"></td>
                </tr>
                <tr>
                    <td><label for="physics">Physics:</label></td>
                    <td><input type="number" id="physics" name="physics" value="30" min="0" max="100"></td>
                </tr>
                <tr>
                    <td><label for="chemistry">Chemistry:</label></td>
                    <td><input type="number" id="chemistry" name="chemistry" value="30" min="0" max="100"></td>
                </tr>
                <tr>
                    <td><label for="mat">MAT:</label></td>
                    <td><input type="number" id="mat" name="mat" value="40" min="0" max="100"></td>
                </tr>
                <tr class="submit-row">
                    <td colspan="2">
                        <input type="submit" value="Generate OMR Sheet">
                    </td>
                </tr>
            </table>
        </form>
    </div>
</body>
</html>
"""


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            subject_questions = [
                int(request.form['math1']),
                int(request.form['math2']),
                int(request.form['physics']),
                int(request.form['chemistry']),
                int(request.form['mat'])
            ]
            if sum(subject_questions) == 0:
                return "Please enter at least one question.", 400
        except Exception:
            return "Invalid input.", 400

        pdf = OMRGenerator(subject_questions)
        pdf_bytes = pdf.generate()
        return Response(pdf_bytes, mimetype='application/pdf',
                        headers={"Content-Disposition": "attachment;filename=omr_sheet.pdf"})
    return render_template_string(FORM_HTML)

if __name__ == '__main__':
    app.run(debug=True)
