import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
import json
import re

merchant_id = "9cfc0a24-71de-4e9a-a4d5-11e6b59307cd"
api_user = "entegra_dev"
api_password = "4jZaDnHe1Ngf"

clean_merchant_id = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', merchant_id)
clean_user = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', api_user)
clean_pass = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', api_password)

base_url = f"https://oms-external.hepsiburada.com/packages/merchantid/{clean_merchant_id}"
headers = {
    "Accept": "application/json",
    "User-Agent": clean_user
}

offset = 0
while True:
    params = {
        'limit': 50,
        'offset': offset
    }
    
    try:
        response = requests.get(
            base_url, 
            headers=headers, 
            auth=HTTPBasicAuth(clean_merchant_id, clean_pass),
            params=params,
            timeout=30
        )
    except Exception as e:
        print(f"Exception: {e}")
        break
        
    if response.status_code != 200:
        print(f"ERROR {response.status_code}: {response.text}")
        break
    
    data = response.json()
    if isinstance(data, list):
        items = data
    else:
        items = data.get('items', [])
        
    if not items:
        break
        
    print(f"+{len(items)} paket bulundu!")
    total_packages += len(items)
    
    if len(items) < 50:
        break
    offset += 50

print(f"\nTOPLAM BULUNAN PAKET SAYISI: {total_packages}")
