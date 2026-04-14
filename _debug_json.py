import opendataloader_pdf
from pathlib import Path

pdf = Path("2024_정보처리기사 필기 기출문제/1. 2024년1회_정보처리기사필기기출문제.pdf")
out = Path("output/1_debug/")
out.mkdir(parents=True, exist_ok=True)

opendataloader_pdf.convert(
    input_path=[str(pdf)],
    output_dir=str(out),
    format="json"
)

# JSON 구조 분석
import json
json_path = out / "1. 2024년1회_정보처리기사필기기출문제.json"
data = json.loads(json_path.read_text())

print(f"Pages: {data.get('number of pages')}")
print(f"Top-level kids: {len(data.get('kids', []))}")
print()

# 처음 30개 노드의 타입과 내용 샘플
for i, kid in enumerate(data['kids'][:30]):
    t = kid.get('type', '?')
    pg = kid.get('page number', '?')
    content = kid.get('content', '')[:60]
    if t == 'list':
        items = kid.get('list items', [])
        print(f"[{i}] {t} pg={pg} items={len(items)}")
        if items:
            first = items[0]
            fc = first.get('content', '')[:60]
            print(f"     first item: {fc}")
    else:
        print(f"[{i}] {t} pg={pg} {content}")
