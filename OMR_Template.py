import json
import os
import logging
from pdf2image import convert_from_path
from PIL import Image

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def convert_pdf_to_image(pdf_path, output_image_path=None, dpi=300):
    """Convert PDF to image and save it if output path is provided."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        images = convert_from_path(pdf_path, dpi=dpi)
        if not images:
            raise ValueError("No pages found in PDF.")

        img = images[0]  # Use first page

        if output_image_path:
            os.makedirs(os.path.dirname(output_image_path) or '.', exist_ok=True)
            img.save(output_image_path)
            logging.info(f"Image saved to: {output_image_path}")

        return img
    except Exception as e:
        raise RuntimeError(f"Failed to convert PDF to image: {str(e)}") from e

def generate_template_json_from_omr(image_path, marker_path, output_path="template.json"):
    """Generate OMR template JSON based on image and marker dimensions."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"OMR sheet image not found: {image_path}")
    if not os.path.exists(marker_path):
        raise FileNotFoundError(f"Marker image not found: {marker_path}")

    try:
        # Get dimensions of both images
        with Image.open(image_path) as img:
            sheet_width, sheet_height = img.size
            if sheet_width == 0 or sheet_height == 0:
                raise ValueError(f"OMR sheet image has zero dimension: {sheet_width}x{sheet_height}")

        with Image.open(marker_path) as marker_img:
            marker_width, marker_height = marker_img.size
            if marker_width == 0 or marker_height == 0:
                raise ValueError(f"Marker image has zero dimension: {marker_width}x{marker_height}")

        sheet_to_marker_width_ratio = round(sheet_width / marker_width, 2)
        if sheet_to_marker_width_ratio < 2:
            logging.warning(
                f"Unusual sheetToMarkerWidthRatio: {sheet_to_marker_width_ratio}. "
                "Check if the marker image is too large or same as the OMR sheet."
            )

    except Exception as e:
        raise ValueError(f"Error while validating image dimensions or calculating ratio: {str(e)}") from e

    # Create template structure
    template = {
        "pageDimensions": [sheet_width, sheet_height],
        "bubbleDimensions": [30, 42],
        "customLabels": {
            "AdmissionNo": [str(i) for i in range(1,9)]  # Digits 0-9 for admission number
        },
        "fieldBlocks": {},
        "preProcessors": [
            {
                "name": "CropOnMarkers",
                "options": {
                    "relativePath": os.path.basename(marker_path),
                    "sheetToMarkerWidthRatio": sheet_to_marker_width_ratio,
                    "apply_erode_subtract": False
                }
            }
        ],
        "outputColumns": [],
        "emptyValue": ""
    }

    # Admission number block
    admission_labels = template["customLabels"]["AdmissionNo"]
    template["fieldBlocks"]["AdmissionBlock"] = {
        "fieldType": "QTYPE_INT",
        "origin": [7, 703],
        "fieldLabels": admission_labels,
        "bubblesGap": 93,
        "labelsGap": 103
    }
    template["outputColumns"].append("AdmissionNo")

    # Subject question blocks
    subjects = ["Math1", "Math2", "Physics", "Chemistry", "MAT"]
    questions_per_block = 10
    current_q_index = 1

    # Layout configuration
    base_origin_x = 172
    base_origin_y = 1858
    subject_col_gap_x = 487
    question_row_gap_y = 80
    bubble_option_gap_x = 88

    for i, subject in enumerate(subjects):
        block_label = f"{subject}_Block"
        block_labels = [f"Q{current_q_index + j:03}" for j in range(questions_per_block)]

        template["fieldBlocks"][block_label] = {
            "fieldType": "QTYPE_MCQ4",  # Assuming 4 options per question
            "origin": [base_origin_x + i * subject_col_gap_x, base_origin_y],
            "fieldLabels": block_labels,
            "bubblesGap": bubble_option_gap_x,
            "labelsGap": question_row_gap_y
        }
        template["outputColumns"].extend(block_labels)
        current_q_index += questions_per_block

    # Save the template
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(template, f, indent=4)

    logging.info(f"template.json generated at: {output_path}")
    return template

def main():
    """Main function to execute the conversion and template generation."""
    try:
        base_dir = "./Sample"
        os.makedirs(base_dir, exist_ok=True)

        pdf_path = os.path.join(base_dir, "omr_sheet.pdf")
        image_path = os.path.join(base_dir, "converted_omr.png")
        marker_path = os.path.join(base_dir, "marker.png")
        template_path = os.path.join(base_dir, "template.json")

        logging.info("Converting PDF to image (if PDF exists)...")
        if os.path.exists(pdf_path):
            convert_pdf_to_image(pdf_path, image_path)
        else:
            logging.warning(f"PDF not found at {pdf_path}. Skipping PDF conversion.")
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Neither PDF nor existing image found at {image_path}.")

        logging.info("Generating template.json...")
        generate_template_json_from_omr(image_path, marker_path, output_path=template_path)

    except Exception as e:
        logging.error(f"Error during setup: {str(e)}", exc_info=True)
        return 1

    return 0

if __name__ == "__main__":
    exit(main())