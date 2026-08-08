import tomllib
from oura import build_oauth_authorize_url

with open('.streamlit/secrets.toml','rb') as f:
	s = tomllib.load(f)

client_id = s.get('OURA_CLIENT_ID')
redirect = s.get('OURA_REDIRECT_URI')
print(build_oauth_authorize_url(client_id, redirect, 'TESTSTATE123'))
