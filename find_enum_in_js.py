import re

with open("found_api_chunk.js", "r", encoding="utf-8") as f:
    text = f.read()

for m in re.finditer(r'model:o\.z\.([^\)]+\))', text):
    print("Found model schema:", m.group(0))

for m in re.finditer(r'enum\(\[([^\]]+)\]\)', text):
    content = m.group(1)
    if "NANO" in content or "gpt" in content.lower() or "seed" in content.lower():
        print("Found enum:", content[:300])
