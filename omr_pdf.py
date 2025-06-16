from fpdf import FPDF

class OMRGenerator(FPDF):
    def __init__(self, subject_questions):
        super().__init__()
        self.subjects = ["Mathematics-1", "Mathematics-2", "Physics", "Chemistry", "MAT"]
        self.subject_questions = subject_questions  # List of 5 integers
        self.total_questions = sum(subject_questions)
        self.bubble_diameter = 4.5
        self.page_height = 297
        self.page_width = 210
        self.set_auto_page_break(auto=False)
        self.set_font("Helvetica", "", 8)
        self.options = ['a', 'b', 'c', 'd']

    def header(self):
        img_size = 15
        # Top corners
        self.image("img1.jpg", x=10, y=10, w=img_size, h=img_size)
        self.image("img1.jpg", x=self.page_width - img_size - 10, y=10, w=img_size, h=img_size)
        # Bottom corners (adjusted upward to prevent overlap with signatures)
        self.image("img1.jpg", x=10, y=self.page_height - img_size - 5, w=img_size, h=img_size)
        self.image("img1.jpg", x=self.page_width - img_size - 10, y=self.page_height - img_size - 5, w=img_size, h=img_size)

        self.set_font("Helvetica", "B", 12)
        self.set_xy(0, 20)
        self.cell(self.page_width, 10, "OMR Answer Sheet", 0, 1, "C")

    def add_instructions(self):
        self.set_font("Helvetica", "", 8)
        self.set_xy(90, 30)
        self.cell(0, 5, "Instructions for filling the sheet:", 0, 2)
        instructions = [
            "- Circle should be darkened completely.",
            "- Don't fold the sheet. Answer once marked cannot be changed.",
            "- Use only ball pen to darken the appropriate circle.",
            "- Only use UPPER CASE CAPITAL LETTER ALPHABETS in the boxes."
        ]
        for line in instructions:
            self.cell(0, 4, line, 0, 2)

    def add_student_info_fields(self):
        block_x = 10
        block_y = 55
        cols = 8
        rows = 10
        col_width = 7
        row_height = 7
        bubble_dia = 4.5

        self.set_font("Helvetica", "B", 10)
        self.set_xy(block_x, block_y)
        self.cell(col_width * (cols + 1), 8, "Admission Number", 0, 2, 'C')

        self.set_font("Helvetica", "", 7)
        self.set_xy(block_x + col_width, block_y + 8)
        for col in range(cols):
            self.cell(col_width, row_height, f"D{col+1}", 0, 0, 'C')
        self.ln(row_height)

        for row in range(rows):
            self.set_xy(block_x, block_y + 8 + row_height * (row + 1))
            self.cell(col_width, row_height, str(row), 0, 0, 'C')
            for col in range(cols):
                cx = block_x + col_width * (col + 1) + col_width / 2
                cy = block_y + 8 + row_height * (row + 1) + row_height / 2
                self.cell(col_width, row_height, "", 0, 0)
                self.ellipse(cx - bubble_dia/2, cy - bubble_dia/2, bubble_dia, bubble_dia)

        self.set_draw_color(0, 0, 0)
        self.rect(block_x, block_y + 8, col_width * (cols + 1), row_height * (rows + 1))

        for col in range(cols + 1):
            x = block_x + col_width * col
            y1 = block_y + 8
            y2 = block_y + 8 + row_height * (rows + 1)
            self.line(x, y1, x, y2)

        for row in range(rows + 2):
            y = block_y + 8 + row_height * row
            x1 = block_x
            x2 = block_x + col_width * (cols + 1)
            self.line(x1, y, x2, y)

        info_x = block_x + col_width * (cols + 1) + 10
        info_y = block_y
        name_width = 110
        left_width = 60
        right_width = 50

        self.set_xy(info_x, info_y)
        self.set_font("Helvetica", "", 8)
        self.cell(name_width, 8, "Student Name", 1, 2, 'C')
        self.set_x(info_x)
        self.cell(name_width, 8, "", 1, 2)

        self.set_x(info_x)
        self.cell(left_width, 8, "Exam Name", 1, 0, 'C')
        self.cell(right_width, 8, "Class (6,7,8,9)", 1, 2, 'C')
        self.set_x(info_x)
        self.cell(left_width, 8, "", 1, 0)
        self.cell(right_width, 8, "", 1, 2)

        self.set_x(info_x)
        self.cell(left_width, 8, "Section", 1, 0, 'C')
        self.cell(right_width, 8, "Date", 1, 2, 'C')
        self.set_x(info_x)
        self.cell(left_width, 8, "", 1, 0)
        self.cell(right_width, 8, "", 1, 2)

    def add_signature_fields(self):
        self.set_y(self.page_height - 20)
        self.set_font("Helvetica", "", 8)

        signature_width = 80
        spacing = 20
        total_width = 2 * signature_width + spacing
        x_start = (self.page_width - total_width) / 2

        self.set_x(x_start)
        self.cell(signature_width, 5, "Invigilator's Signature: _________________", 0, 0, 'C')
        self.cell(spacing, 5, "", 0, 0)
        self.cell(signature_width, 5, "Student's Signature: _________________", 0, 1, 'C')

    def add_question_bubbles(self):
        x_start = 20
        y_start_first = 145
        y_start_others = 40
        total_width = 170
        col_width = total_width / len(self.subjects)
        row_height = 6

        max_questions = max(self.subject_questions)
        question_indices = [0] * len(self.subjects)
        page = 1
        finished = False

        while not finished:
            if page == 1:
                y_start = y_start_first
            else:
                self.add_page()
                y_start = y_start_others

            self.set_font("Helvetica", "B", 8)
            for i, subject in enumerate(self.subjects):
                self.set_xy(x_start + i*col_width, y_start)
                self.cell(col_width, 6, subject, 0, 0, 'C')

            self.set_font("Helvetica", "", 7)
            for i in range(len(self.subjects)):
                x = x_start + i*col_width
                for j, opt in enumerate(self.options):
                    self.set_xy(x + 10 + j*6, y_start + 6)
                    self.cell(6, 5, opt, 0, 0, 'C')

            max_rows = int((self.page_height - (y_start + 12) - 35) // row_height)

            for row in range(max_rows):
                any_drawn = False
                for section in range(len(self.subjects)):
                    if question_indices[section] < self.subject_questions[section]:
                        x = x_start + section*col_width
                        y = y_start + 12 + row*row_height
                        qnum = question_indices[section] + 1
                        self.set_xy(x, y)
                        self.set_font("Helvetica", "", 7)
                        self.cell(10, 5, f"Q{qnum:03d}", 0, 0)
                        for o in range(len(self.options)):
                            bx = x + 10 + o*6
                            by = y + 2.5
                            self.ellipse(bx, by, self.bubble_diameter, self.bubble_diameter)
                        question_indices[section] += 1
                        any_drawn = True
                if all(qi >= sq for qi, sq in zip(question_indices, self.subject_questions)):
                    finished = True
                    break
            page += 1

    def generate(self):
        self.add_page()
        self.add_instructions()
        self.add_student_info_fields()
        self.add_question_bubbles()
        self.add_signature_fields()
        return self.output(dest='S').encode('latin-1')
