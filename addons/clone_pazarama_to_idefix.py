import os
import shutil

src_dir = r"c:\Users\PC\Desktop\odoougurlar\addons\pazarama_integration"
dest_dir = r"c:\Users\PC\Desktop\odoougurlar\addons\idefix_integration"

if os.path.exists(dest_dir):
    shutil.rmtree(dest_dir)
os.makedirs(dest_dir)

for root, dirs, files in os.walk(src_dir):
    # Skip __pycache__
    if "__pycache__" in root:
        continue
        
    rel_path = os.path.relpath(root, src_dir)
    dest_path = os.path.join(dest_dir, rel_path) if rel_path != "." else dest_dir
    
    if not os.path.exists(dest_path):
        os.makedirs(dest_path)
        
    for file in files:
        if file.endswith('.pyc'):
            continue
            
        src_file = os.path.join(root, file)
        
        # Rename filename
        new_file = file.replace('pazarama', 'idefix').replace('Pazarama', 'Idefix')
        dest_file = os.path.join(dest_path, new_file)
        
        # Binary files just copy (like images)
        if file.endswith('.png') or file.endswith('.jpg'):
            shutil.copy2(src_file, dest_file)
            continue
            
        # Text files: replace content
        try:
            with open(src_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Replace
            content = content.replace('pazarama', 'idefix')
            content = content.replace('Pazarama', 'Idefix')
            content = content.replace('PAZARAMA', 'IDEFIX')
            
            with open(dest_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Skipping {src_file} due to error {e}")
            shutil.copy2(src_file, dest_file)

print("Klonlama tamamlandi.")
