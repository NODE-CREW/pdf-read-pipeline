import os
import fitz

pdf_path = "data/정보처리기사20210814(학생용).pdf"
output_dir = "output/images"
os.makedirs(output_dir, exist_ok=True)

doc = fitz.open(pdf_path)

for page_index, page in enumerate(doc):
    print(f"\n===== PAGE {page_index + 1} =====")

    text = page.get_text().strip()
    print("[TEXT]")
    if text:
        print(text)
    else:
        print("(no extractable text)")

    print("\n[TEXT BLOCKS]")
    blocks = page.get_text("blocks")
    if blocks:
        for block_index, block in enumerate(blocks, start=1):
            x0, y0, x1, y1, block_text, *_ = block
            print(
                f"- block {block_index}: bbox=({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f})"
            )
            print(block_text.strip())
    else:
        print("(no text blocks)")

    print("\n[IMAGES]")
    images = page.get_images(full=True)
    if images:
        for image_index, image_info in enumerate(images, start=1):
            xref = image_info[0]
            width = image_info[2]
            height = image_info[3]
            bpc = image_info[4]
            colorspace = image_info[5]
            ext_info = doc.extract_image(xref)
            image_bytes = ext_info["image"]
            image_ext = ext_info["ext"]
            image_path = os.path.join(
                output_dir,
                f"page_{page_index + 1:03d}_img_{image_index:02d}.{image_ext}",
            )
            with open(image_path, "wb") as image_file:
                image_file.write(image_bytes)

            print(
                f"- image {image_index}: xref={xref}, size={width}x{height}, "
                f"bpc={bpc}, colorspace={colorspace}, saved={image_path}"
            )
    else:
        print("(no embedded images)")