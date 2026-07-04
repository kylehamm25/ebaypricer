import requests, base64, os, urllib.parse, webbrowser
from dotenv import load_dotenv

from ebaypricer.paths import ENV_PATH

load_dotenv(dotenv_path=ENV_PATH)

CLIENT_ID     = os.getenv("EBAY_APP_ID")
CLIENT_SECRET = os.getenv("EBAY_SECRET")
RUNAME        = os.getenv("RUNAME")
SCOPE         = "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly https://api.ebay.com/oauth/api_scope/sell.marketing"

auth_url = "https://auth.ebay.com/oauth2/authorize?" + urllib.parse.urlencode({
    "client_id":     CLIENT_ID,
    "redirect_uri":  RUNAME,
    "response_type": "code",
    "scope":         SCOPE
})

print("Opening eBay login in your browser...")
webbrowser.open(auth_url)
print(f"\nIf the browser doesn't open, copy this URL:\n{auth_url}\n")

raw = input("\nPaste the FULL redirect URL").strip()

if "code=" in raw:
    code = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [None])[0]
    if not code:
        code = raw.split("code=")[1].split("&")[0]
else:
    code = raw

print(f"\nExtracted code: {repr(code[:30])} ...")
print(f"Code length: {len(code)}")

basic_auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

r = requests.post(
    "https://api.ebay.com/identity/v1/oauth2/token",
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {basic_auth}"
    },
    data={
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": RUNAME
    }
)

data = r.json()
print("\nSTATUS:", r.status_code)
print("RESPONSE:", data)

if r.status_code != 200:
    print("\nToken exchange failed — check your credentials and RUNAME.")
    exit(1)

access_token = data.get("access_token", "")
refresh_token = data.get("refresh_token", "")

with open(ENV_PATH, "r") as f:
    lines = f.readlines()

new_lines = []
written_at = False
written_ref = False
for line in lines:
    if line.startswith("ACCESS_TOKEN="):
        new_lines.append(f'ACCESS_TOKEN="{access_token}"\n')
        written_at = True
    elif line.startswith("REFRESH_TOKEN="):
        if refresh_token:
            new_lines.append(f'REFRESH_TOKEN="{refresh_token}"\n')
        written_ref = True
    else:
        new_lines.append(line)

if not written_at:
    new_lines.append(f'ACCESS_TOKEN="{access_token}"\n')
if refresh_token and not written_ref:
    new_lines.append(f'REFRESH_TOKEN="{refresh_token}"\n')

with open(ENV_PATH, "w") as f:
    f.writelines(new_lines)

print(f"\nACCESS_TOKEN saved to .env ({len(access_token)} chars)")
if refresh_token:
    print(f"REFRESH_TOKEN saved to .env ({len(refresh_token)} chars)")
else:
    print("No refresh_token returned — token will expire in ~2 hours.")
