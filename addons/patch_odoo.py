import os
import re

def patch():
    path = '/usr/lib/python3/dist-packages/odoo/addons/website_sale/models/product_image.py'
    if not os.path.exists(path):
        print(f"Path {path} does not exist. Skipping patch.")
        return

    print(f"Patching {path}...")
    with open(path, 'r') as f:
        code = f.read()

    # Regex ile _compute_can_image_1024_be_zoomed metodunun gövdesini bulup
    # görsel verisini (image_1920) hiç yüklemeyecek şekilde can_image_1024_be_zoomed = True yapar.
    # Bu sayede binlerce görsel olan veri tabanlarında RAM dolup MemoryError vermez.
    pattern = r'def _compute_can_image_1024_be_zoomed\(self\):.*?(?=\n\s*def|\n\s*class|\Z)'
    replacement = "def _compute_can_image_1024_be_zoomed(self):\n        for image in self:\n            image.can_image_1024_be_zoomed = True"

    if re.search(pattern, code, flags=re.DOTALL):
        new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)
        with open(path, 'w') as f:
            f.write(new_code)
        print("Successfully patched _compute_can_image_1024_be_zoomed to set can_image_1024_be_zoomed = True without loading image binary!")
    else:
        print("Could not find _compute_can_image_1024_be_zoomed method definition in product_image.py.")

if __name__ == '__main__':
    patch()
