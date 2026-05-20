import base64
from openai import OpenAI

client = OpenAI(
    base_url="https://varying-pushcart-ladle.ngrok-free.dev/v1",
    api_key="token"
)

# 이미지 파일을 Base64 문자열로 변환하는 함수
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

base64_image = encode_image("test.png")

response = client.chat.completions.create(
    model="mlx-community/gemma-4-26b-a4b-it-4bit",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "이 이미지에 쓰여있는 글씨를 그대로 OCR 해줘. 모든 내용을 빠짐과 중략없이 모든 글씨를 텍스트로 변환해줘."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        }
    ]
)

print(response.choices[0].message.content)