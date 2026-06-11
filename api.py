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

class ContactDB(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    age: Mapped[int]
    email: Mapped[str]

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



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


@app.post("/summarize", response_model=SummarizeResponse, dependencies=[Depends(verify_api_key)])
def summarize_text(req: SummarizeRequest):
    response = openai_client.chat.completions.create(
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
        ]
    )
    summary = response.choices[0].message.content
    return SummarizeResponse(summary=summary)