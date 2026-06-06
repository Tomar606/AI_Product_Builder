import time
import asyncio
import httpx
import json

TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
STORY_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

async def fetch_top_ids(client):
    response = await client.get(TOP_STORIES_URL)
    response.raise_for_status()
    return response.json()


async def fetch_story(client, story_id):
    url = STORY_URL.format(id=story_id)
    response = await client.get(url)
    if response.status_code != 200:
        return None
    return response.json()

async def fetch_all_stories(client, ids):
    tasks = [fetch_story(client, sid) for sid in ids]
    results = await asyncio.gather(*tasks)
    return [s for s in results if s is not None]

def save_stories(stories):
    with open("hn_cache.json", "w") as f:
        json.dump(stories, f, indent=2)

def load_stories():
    try:
        with open("hn_cache.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    
def display_stories(stories):
    for i, s in enumerate(stories, start=1):
        title = s.get("title", "(no title)")
        score = s.get("score", 0)
        comments = s.get("descendants", 0)
        author = s.get("by", "anonymous")
        url = s.get("url", "(no URL - discussion only)")
        print(f"[{i}] {score} pts | {comments} comments | by {author}")
        print(f"    {title}")
        print(f"    {url}\n")

async def main():
    async with httpx.AsyncClient() as client:
        ids = await fetch_top_ids(client)
        print(f"Got {len(ids)} story IDs")

        start = time.time()
        stories = await fetch_all_stories(client, ids[:30])
        end = time.time()

        save_stories(stories)
        display_stories(stories)

asyncio.run(main())