import os
from fastapi.security import APIKeyHeader
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column, Session
from fastapi import Depends
from openai import OpenAI
from dotenv import load_dotenv
from typing import Literal
import numpy as np


load_dotenv()
openai_client = OpenAI()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/ai_product_builder")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def verify_api_key(provided_key: str | None = Depends(api_key_header)):
    expected = os.environ.get("API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="server misconfigured: API_KEY not set")
    if provided_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    
class ContactCreate(BaseModel):
    text: str

class SummarizeResponse(BaseModel):
    summary: str

class SummarizeRequest(BaseModel):
    text: str

class Base(DeclarativeBase):
    pass

documents_store: list[dict] = []
next_doc_id = 1

class ContactDB(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    age: Mapped[int]
    email: Mapped[str]

class SummarizeStructured(BaseModel):
    summary: str
    key_topics: list[str]
    sentiment: Literal["positive", "neutral", "negative"]
    estimated_reading_time_minutes: int
    
class DocumentCreate(BaseModel):
    text: str

class Document(BaseModel):
    id: int
    text: str

class SearchResult(BaseModel):
    document: Document
    similarity: float  

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_embedding(text: str) -> list[float]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding

def cosine_sim(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))

app = FastAPI()

class ContactCreate(BaseModel):
    name: str
    age: int
    email: str

class Contact(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    age: int
    email: str

@app.get("/contacts", response_model=list[Contact], dependencies=[Depends(verify_api_key)])
def list_contacts(
    age_min: int | None = None,
    age_max: int | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(ContactDB)
    if age_min is not None:
        stmt = stmt.where(ContactDB.age >= age_min)
    if age_max is not None:
        stmt = stmt.where(ContactDB.age <= age_max)
    return db.scalars(stmt).all()



@app.post("/contacts", response_model=Contact, status_code=201, dependencies=[Depends(verify_api_key)])
def create_contact(contact: ContactCreate, db: Session = Depends(get_db)):
    db_contact = ContactDB(**contact.model_dump())
    db.add(db_contact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Contact with name '{contact.name}' already exists"
        )
    db.refresh(db_contact)         # reload so id (DB-generated) is populated
    return db_contact

@app.get("/contacts/{name}", response_model=Contact, dependencies=[Depends(verify_api_key)])
def get_contact(name: str, db: Session = Depends(get_db)):
    stmt = select(ContactDB).where(ContactDB.name == name)
    contact = db.scalars(stmt).first()
    if contact is None:
        raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")
    return contact


@app.put("/contacts/{name}", response_model=Contact, dependencies=[Depends(verify_api_key)])
def update_contact(name: str, contact: ContactCreate, db: Session = Depends(get_db)):
    stmt = select(ContactDB).where(ContactDB.name == name)
    db_contact = db.scalars(stmt).first()
    if db_contact is None:
        raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")
    db_contact.name = contact.name
    db_contact.age = contact.age
    db_contact.email = contact.email
    db.commit()
    db.refresh(db_contact)
    return db_contact



@app.delete("/contacts/{name}", response_model=Contact, dependencies=[Depends(verify_api_key)])
def delete_contact(name: str, db: Session = Depends(get_db)):
    stmt = select(ContactDB).where(ContactDB.name == name)
    db_contact = db.scalars(stmt).first()
    if db_contact is None:
        raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")
    db.delete(db_contact)
    db.commit()
    return db_contact


@app.post("/summarize", response_model=SummarizeStructured, dependencies=[Depends(verify_api_key)])
def summarize_text(req: SummarizeRequest):
    response = openai_client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizer. Given any text, return a single-sentence summary that capture the key idea. No fluff"
            },
            {
                "role": "user",
                "content": req.text
            }
        ],
        response_format=SummarizeStructured,
    )
    return response.choices[0].message.parsed

@app.post("/documents", response_model=Document, status_code=201, dependencies=[Depends(verify_api_key)])
def create_document(doc: DocumentCreate):
    global next_doc_id
    embedding = get_embedding(doc.text)
    record = {"id": next_doc_id, "text": doc.text, "embedding": embedding}
    documents_store.append(record)
    next_doc_id += 1
    return Document(id=record["id"], text=record["text"])

@app.get("/documents", response_model=list[Document], dependencies=[Depends(verify_api_key)])
def list_documents():
    return [Document(id=d["id"], text=d["text"]) for d in documents_store]


@app.get("/search", response_model=list[SearchResult], dependencies=[Depends(verify_api_key)])
def search(q: str, k: int = 3):
    if not documents_store:
        return []
    q_emb = get_embedding(q)
    scored = [
        SearchResult(
            document=Document(id=d["id"], text=d["text"]),
            similarity=cosine_sim(q_emb, d["embedding"]),
        )
        for d in documents_store
    ]
    scored.sort(key=lambda r: r.similarity, reverse=True)
    return scored[:k]