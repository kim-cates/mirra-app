import tomllib
import requests
from oura import build_oauth_authorize_url

with open('.streamlit/secrets.toml','rb') as f:
    s = tomllib.load(f)

client_id = s.get('OURA_CLIENT_ID')
redirect = s.get('OURA_REDIRECT_URI')
url = build_oauth_authorize_url(client_id, redirect, 'CHECKSTATE')
print('Authorize URL:', url)
try:
    resp = requests.get(url, allow_redirects=False, timeout=15)
    print('Status:', resp.status_code)
    print('Content-Type:', resp.headers.get('Content-Type'))
    loc = resp.headers.get('Location')
    if loc:
        print('Location header:', loc)
    print('Body snippet:', resp.text[:500])
except Exception as e:
    print('Request error:', e)
