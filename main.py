name = input("What is your name?")
while True:
    try:
        age = int(input("What is your age?"))
        break
    except ValueError:
        print("Please enter a valid age.")
print(f"Hello, {name}! In 10 years you will be {age + 10} years old.")