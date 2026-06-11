from dotenv import load_dotenv
from openai import OpenAI
import numpy as np

load_dotenv()
client = OpenAI()

texts = [
    "The cat sat on the mat",
    "A feline rested on a rug",
    "The stock market is volatile toda",
]

respone = client.embeddings.create(
    model="text-embedding-3-small",
    input=texts,
)

embedding = [item.embedding for item in respone.data]

print(f"Got {len(embedding)} embeddings, each of dimension {len(embedding[0])} dimensions.")
print(f"First 5 numbers of embedding[0]: {embedding[0][:5]}")

def cosine_sim(a, b):
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

print()
print(f"sim(cat sat on mat  ↔  feline rested on rug):     {cosine_sim(embedding[0], embedding[1]):.4f}")
print(f"sim(cat sat on mat  ↔  stock market crashed):     {cosine_sim(embedding[0], embedding[2]):.4f}")
print(f"sim(feline rested   ↔  stock market crashed):     {cosine_sim(embedding[1], embedding[2]):.4f}")



