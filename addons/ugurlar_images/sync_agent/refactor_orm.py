import re

with open('sync_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r"self\._execute\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,?(.*?)\)", re.DOTALL)

def replacer(match):
    model = match.group(1)
    method = match.group(2)
    args = match.group(3)
    if args.strip():
        return f"self.env['{model}'].{method}({args})"
    else:
        return f"self.env['{model}'].{method}()"

new_content = pattern.sub(replacer, content)

with open('sync_agent.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Refactored sync_agent.py to use ORM')
