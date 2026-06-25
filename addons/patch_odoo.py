import os

def patch():
    path = '/usr/lib/python3/dist-packages/odoo/addons/website_sale/models/product_image.py'
    if not os.path.exists(path):
        print(f"Path {path} does not exist. Skipping patch.")
        return

    print(f"Patching {path}...")
    with open(path, 'r') as f:
        code = f.read()

    target = "for image in self:\n            image.can_image_1024_be_zoomed = image.image_1920 and is_image_size_above(image.image_1920, image.image_1024)"
    
    replacement = """for image in self.with_context(prefetch_fields=False):
            try:
                image.can_image_1024_be_zoomed = image.image_1920 and is_image_size_above(image.image_1920, image.image_1024)
            except Exception:
                image.can_image_1024_be_zoomed = False"""

    if target in code:
        new_code = code.replace(target, replacement)
        with open(path, 'w') as f:
            f.write(new_code)
        print("Successfully patched product_image.py!")
    else:
        print("Target code pattern not found in product_image.py. Checking alternative pattern...")
        target_alt = "for image in self:\n            image.can_image_1024_be_zoomed"
        replacement_alt = "for image in self.with_context(prefetch_fields=False):\n            image.can_image_1024_be_zoomed"
        if target_alt in code:
            new_code = code.replace(target_alt, replacement_alt)
            with open(path, 'w') as f:
                f.write(new_code)
            print("Successfully patched loop line in product_image.py!")
        else:
            print("Failed to patch product_image.py: patterns not found.")

if __name__ == '__main__':
    patch()
