from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel

app = FastAPI()

@app.get("/")
def hello():
    return {"message": "Hello, World!"}

class GithubUserResponse(BaseModel):
    username: str
    name: str | None
    bio: str | None
    followers: int
    public_repos: int

@app.get("/github/{username}", response_model=GithubUserResponse)
def get_github_user(username: str):
    response = httpx.get(f"https://api.github.com/users/{username}")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"GitHub user '{username}' not found")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub API error")
    data = response.json()
    return GithubUserResponse(
        username=data["login"],
        name=data.get("name"),
        bio=data.get("bio"),
        followers=data["followers"],
        public_repos=data["public_repos"],
    )

contacts_db: list[dict] = []

class ContactCreate(BaseModel):
    name: str
    age: int
    email: str

class Contact(BaseModel):
    name: str
    age: int
    email: str

@app.get("/contacts", response_model=list[Contact])
def list_contacts():
    return contacts_db


@app.post("/contacts", response_model=Contact, status_code=201)
def create_contact(contact: ContactCreate):
    contacts_db.append(contact.model_dump())
    return contact

@app.get("/contacts/{name}", response_model=Contact)
def get_contact(name: str):
    for contact in contacts_db:
        if contact["name"] == name:
            return contact
    raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")


@app.delete("/contacts/{name}", response_model=Contact)
def delete_contact(name: str):
    for i, contact in enumerate(contacts_db):
        if contact["name"] == name:
            return contacts_db.pop(i)
    raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")