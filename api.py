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
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey
from fastapi.responses import StreamingResponse
import json
from typing import Any


load_dotenv()
openai_client = OpenAI()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

CONTACT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": "List all contacts in the database. Returns a list of contacts with id, name, age, email.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Add a new contact to the database. Use when the user wants to create or save a new contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The contact's full name"},
                    "age": {"type": "integer", "description": "The contact's age in years"},
                    "email": {"type": "string", "description": "The contact's email address"},
                },
                "required": ["name", "age", "email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Find a single contact by their exact name. Returns the contact's details or an error if not found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name to search for (exact match)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_contact",
            "description": "Delete a contact by name. Use ONLY when the user explicitly asks to delete or remove a contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The exact name of the contact to delete"},
                },
                "required": ["name"],
            },
        },
    },
]


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

class ContactDB(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    age: Mapped[int]
    email: Mapped[str]

class DocumentDB(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str]
    embedding = mapped_column(Vector(1536))

class ChunkDB(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int]
    text: Mapped[str]
    embedding = mapped_column(Vector(1536))

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

class ChunkResult(BaseModel):
    chunk_id: int
    document_id: int
    text: str
    similarity: float 

class AskRequest(BaseModel):
    question: str
    k: int = 3   # how many docs to retrieve (optional default)

class AskResponse(BaseModel):
    answer: str
    sources: list[int]   # IDs of the docs the LLM cited

class AgentRequest(BaseModel):
    query: str
    max_steps: int = 10   # safety cap to avoid runaway loops

class AgentStep(BaseModel):
    tool: str
    args: dict
    result: Any

class AgentResponse(BaseModel):
    answer: str
    steps: list[AgentStep]


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

def chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    step = size - overlap
    for start in range(0, len(text), step):
        chunks.append(text[start:start + size])
        if start + size >= len(text):
            break
    return chunks

def execute_tool(name: str, args: dict, db: Session) -> dict:
    """Execute a tool by name with given args. Returns a dict to send back to the LLM."""
    if name == "list_contacts":
        contacts = db.scalars(select(ContactDB)).all()
        return {"contacts": [{"id": c.id, "name": c.name, "age": c.age, "email": c.email} for c in contacts]}

    elif name == "add_contact":
        db_c = ContactDB(**args)
        db.add(db_c)
        try:
            db.commit()
            db.refresh(db_c)
            return {"id": db_c.id, "name": db_c.name, "age": db_c.age, "email": db_c.email}
        except IntegrityError:
            db.rollback()
            return {"error": f"Contact named '{args['name']}' already exists"}

    elif name == "find_contact":
        c = db.scalars(select(ContactDB).where(ContactDB.name == args["name"])).first()
        if c is None:
            return {"error": f"No contact named '{args['name']}'"}
        return {"id": c.id, "name": c.name, "age": c.age, "email": c.email}

    elif name == "delete_contact":
        c = db.scalars(select(ContactDB).where(ContactDB.name == args["name"])).first()
        if c is None:
            return {"error": f"No contact named '{args['name']}'"}
        db.delete(c)
        db.commit()
        return {"deleted": True, "name": args["name"]}

    return {"error": f"Unknown tool: {name}"}


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
def create_document(doc: DocumentCreate, db: Session = Depends(get_db)):
    # 1. Create the parent document row
    db_doc = DocumentDB(text=doc.text)
    db.add(db_doc)
    db.flush()                          # assigns db_doc.id without committing yet

    # 2. Chunk the text
    chunks = chunk_text(doc.text)

    # 3. Embed all chunks in ONE batched API call (cheaper + faster)
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=chunks,
    )
    chunk_embeddings = [item.embedding for item in response.data]

    # 4. Insert chunk rows
    for i, (chunk_text_str, emb) in enumerate(zip(chunks, chunk_embeddings)):
        db.add(ChunkDB(
            document_id=db_doc.id,
            chunk_index=i,
            text=chunk_text_str,
            embedding=emb,
        ))
    db.commit()
    db.refresh(db_doc)
    return Document(id=db_doc.id, text=db_doc.text)

@app.get("/documents", response_model=list[Document], dependencies=[Depends(verify_api_key)])
def list_documents(db: Session = Depends(get_db)):
    return [Document(id=d.id, text=d.text) for d in db.scalars(select(DocumentDB)).all()]


@app.get("/search", response_model=list[ChunkResult], dependencies=[Depends(verify_api_key)])
def search(q: str, k: int = 3, db: Session = Depends(get_db)):
    q_emb = get_embedding(q)
    stmt = (
        select(
            ChunkDB,
            ChunkDB.embedding.cosine_distance(q_emb).label("distance"),
        )
        .order_by(ChunkDB.embedding.cosine_distance(q_emb))
        .limit(k)
    )
    rows = db.execute(stmt).all()
    return [
        ChunkResult(
            chunk_id=row.ChunkDB.id,
            document_id=row.ChunkDB.document_id,
            text=row.ChunkDB.text,
            similarity=1.0 - row.distance,
        )
        for row in rows
    ]


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(verify_api_key)])
def ask(req: AskRequest, db: Session = Depends(get_db)):
    first = db.scalars(select(ChunkDB).limit(1)).first()
    if first is None:
        raise HTTPException(status_code=400, detail="No documents stored yet. POST some to /documents first.")

    q_emb = get_embedding(req.question)
    stmt = (
        select(ChunkDB)
        .order_by(ChunkDB.embedding.cosine_distance(q_emb))
        .limit(req.k)
    )
    top_chunks = db.scalars(stmt).all()

    # Context labels each chunk with its ID
    context = "\n\n".join(f"[{c.id}] {c.text}" for c in top_chunks)

    response = openai_client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You answer questions using ONLY the provided context. "
                    "If the answer isn't in the context, say 'I don't have enough information to answer that.' — do NOT make anything up. "
                    "Each context item starts with its ID in brackets like [3]. "
                    "When you return sources, list the IDs of the context items you actually used."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {req.question}",
            },
        ],
        response_format=AskResponse,
    )
    return response.choices[0].message.parsed


@app.post("/ask/stream", dependencies=[Depends(verify_api_key)])
def ask_stream(req: AskRequest, db: Session = Depends(get_db)):
    first = db.scalars(select(ChunkDB).limit(1)).first()
    if first is None:
        raise HTTPException(status_code=400, detail="No documents stored yet.")

    q_emb = get_embedding(req.question)
    stmt = (
        select(ChunkDB)
        .order_by(ChunkDB.embedding.cosine_distance(q_emb))
        .limit(req.k)
    )
    top_chunks = db.scalars(stmt).all()
    context = "\n\n".join(f"[{c.id}] {c.text}" for c in top_chunks)

    # ↓ FROM HERE, 4 SPACES (one level inside ask_stream)
    def token_stream():
        stream = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "You answer questions using ONLY the provided context. If the answer isn't in the context, say 'I don't have enough information to answer that.' Use the context to construct a complete, helpful answer when the information is present."},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {req.question}"},
            ],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return StreamingResponse(token_stream(), media_type="text/plain")

@app.post("/ask/stream", dependencies=[Depends(verify_api_key)])
def ask_stream(req: AskRequest, db: Session = Depends(get_db)):
    first = db.scalars(select(ChunkDB).limit(1)).first()
    if first is None:
        raise HTTPException(status_code=400, detail="No documents stored yet.")

    q_emb = get_embedding(req.question)
    stmt = (
        select(ChunkDB)
        .order_by(ChunkDB.embedding.cosine_distance(q_emb))
        .limit(req.k)
    )
    top_chunks = db.scalars(stmt).all()
    context = "\n\n".join(f"[{c.id}] {c.text}" for c in top_chunks)

    # ↓ FROM HERE, 4 SPACES (one level inside ask_stream)
    def token_stream():
        stream = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "You answer questions using ONLY the provided context. If the answer isn't in the context, say 'I don't have enough information to answer that.' Use the context to construct a complete, helpful answer when the information is present."},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {req.question}"},
            ],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return StreamingResponse(token_stream(), media_type="text/plain")


@app.post("/agent", response_model=AgentResponse, dependencies=[Depends(verify_api_key)])
def run_agent(req: AgentRequest, db: Session = Depends(get_db)):
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful contacts assistant. You can list, add, find, and delete contacts "
                "by calling the provided tools. Use tools when needed; after you have what you need, "
                "give the user a concise natural-language summary of what you did."
            ),
        },
        {"role": "user", "content": req.query},
    ]
    steps: list[AgentStep] = []

    for _ in range(req.max_steps):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=CONTACT_TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # No tool calls → final answer
        if not msg.tool_calls:
            return AgentResponse(answer=msg.content or "", steps=steps)

        # Append the assistant's message (with the tool_calls intact) to history
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool call, append result
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = execute_tool(tc.function.name, args, db)
            steps.append(AgentStep(tool=tc.function.name, args=args, result=result))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })
        # loop continues — LLM sees the tool results and decides next move

    # Hit max_steps without a final answer
    return AgentResponse(answer="(agent stopped after max_steps without finishing)", steps=steps)
