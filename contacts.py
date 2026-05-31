import json

def add_contact(name, age, email):
    contact = {"name": name, "age": age, "email": email}
    contacts.append(contact)

def list_contacts():
    if len(contacts) == 0:
        print("No contacts yet.")
        return
    for contact in contacts:
        print(f"{contact['name']} - {contact['age']} - {contact['email']}")

def find_contact(name):
    for contact in contacts:
        if contact["name"] == name:
            return contact
    return None

def save_contacts():
    with open("contacts.json", "w") as f:
        json.dump(contacts, f, indent=2)

def load_contacts():
    try:
        with open("contacts.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

contacts = load_contacts()

while True:
    print("\n1. Add Contact")
    print("2. List Contacts")
    print("3. Search Contacts")
    print("4. Quit")
    choice = input("Choose an option: ")

    if choice == '1':
        name = input("Name: ")
        age = int(input("Age: "))
        email = input("Email: ")
        add_contact(name, age, email)
        save_contacts()
        print("Contact was added successfully")
    elif choice == '2':
        print("\nContacts: ")
        list_contacts()
    elif choice == '3':
        name = input("Enter a name: ")
        result = find_contact(name)
        if result is None:
            print("This contact doesn't exist.")
        else:
            print(f"{result['name']} - {result['age']} - {result['email']}")
    elif choice == '4':
        print("Goodbye!")
        break
    else:
        print("Invalid choice. Please try again.")






