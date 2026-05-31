import json

data = [
    {"name": "Gaurav", "age": 21, "email": "gst@x.com"},
    {"name": "Aman", "age": 21, "email": "aman@x.com"},
]

with open("contacts.json", "w") as f:
    json.dump(data, f, indent=2)

with open("contacts.json", "r") as f:
    loaded = json.load(f)
print(loaded)