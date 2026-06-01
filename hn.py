import requests

TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
STORY_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

def fetch_top_ids():
    """Return a list of top story IDs."""
    response = requests.get(TOP_STORIES_URL)
    response.raise_for_status()
    return response.json()

def fetch_story(story_id):
    """Return one story dict, or None if not found."""
    url = STORY_URL.format(id=story_id)
    response = requests.get(url)
    if response.status_code != 200:
        return None
    return response.json()

def main():
    ids = fetch_top_ids()
    print(f"Got {len(ids)} story IDs.")
    print(f"First 5 IDs: {ids[:5]}")

    for story_id in ids[:10]:
        story = fetch_story(story_id)
        if story is None:
            print(f"Skipped {story_id} (not found)")
            continue
        print(f" {story['title']} ({story.get('score', 0)} points)")

main()