import requests

username = input("Enter a GitHub username: ")
url = f"https://api.github.com/users/{username}"

response = requests.get(url)

if response.status_code == 200:
    data = response.json()
    print(f"Profile of {username}: ")
    print(f"\nName: {data['name']}")
    print(f"Bio: {data['bio']}")
    print(f"Public Repositories: {data['public_repos']}")
    print(f"Followers: {data['followers']}")
    print(f"Location: {data['location']}")
    print(f"Blog: {data['blog']}")
elif response.status_code == 404:
    print(f"No user found with the username '{username}'.")
else:
    print(f"Something went Wrong. Status code: {response.status_code}")