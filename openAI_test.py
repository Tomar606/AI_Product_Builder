from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()
client = OpenAI()


response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "user", "content": "In one sentence, explain why APIs are eating the world."}
    ]
)

print(response.choices[0].message.content)