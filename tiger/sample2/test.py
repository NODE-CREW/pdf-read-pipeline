import opendataloader_pdf

# Batch all files in one call — each convert() spawns a JVM process, so repeated calls are slow
opendataloader_pdf.convert(
    input_path=["컴활문제/01_raw/comh1_040215.pdf"],
    output_dir="output/",
    format="json"
)