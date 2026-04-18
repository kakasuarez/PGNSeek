import requests
from bs4 import BeautifulSoup
import json

doc = requests.get("https://lumbrasgigabase.com/en/eco-codes-en/")

soup = BeautifulSoup(doc.text, "html.parser")

codes = []

for t in soup.find_all("td"):
    if t.text == "AL":
        break
    if t.text.startswith("1") or t.text.startswith("*"):
        continue
    new_text = t.text.replace("’", "'").replace("…", "...")
    codes.append(new_text)

eco_to_opening_name = dict()

for i in range(0, len(codes) - 1, 2):
    eco = codes[i]
    opening = codes[i + 1]
    eco_to_opening_name[eco] = opening


with open("eco_to_opening.json", "w") as f:
    json.dump(eco_to_opening_name, f, ensure_ascii=False)
