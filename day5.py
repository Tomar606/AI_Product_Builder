import time
import asyncio
import httpx

usernames = ["torvalds", "gaeron", "octocat", "tomar606", "tj"]

async def fetch_user(client,username):
    response = await client.get(f"https://api.github.com/users/{username}")
    if response.status_code == 200:
        data = response.json()
        print(f"Name: {data['name']}")
    else:
        print(f"Failed to fetch data for {username}. Status code: {respone.status_code})")

async def main():
    start = time.time()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_user(client, u) for u in usernames]
        await asyncio.gather(*tasks)
    end = time.time()
    print(f"\nTime taken: {end - start:.2f} seconds")

asyncio.run(main())
