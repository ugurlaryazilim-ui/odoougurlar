import re
with open('desktop_app.py', 'r', encoding='utf-8') as f:
    code = f.read()

def replacer(m):
    return '"' + m.group(1).lower().replace('_', '') + '"'

new_code = re.sub(r'ft\.Colors\.([A-Z0-9_]+)', replacer, code)

with open('desktop_app.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
print('Replaced colors successfully.')
