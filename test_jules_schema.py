import os, requests, json

api_key = None
with open('.env', 'r') as f:
    for line in f:
        if line.startswith('JULES_API_KEY='):
            api_key = line.split('=', 1)[1].strip()

url = 'https://jules.googleapis.com/v1alpha/sessions'
headers = {'X-Goog-Api-Key': api_key, 'Content-Type': 'application/json'}

tests = [
    {'sourceContext': {'source': 'sources/github/watkajtys/ouroboros-test-1771557814'}},
    {'sourceContext': {'source': 'sources/github/watkajtys/ouroboros-test-1771557814', 'githubRepoContext': {}}},
    {'sourceContext': {'source': 'sources/github/watkajtys/ouroboros-test-1771557814', 'githubRepoContext': {'startingBranch': 'main'}}},
    {'sourceContext': {'source': 'sources/github/watkajtys/ouroboros-test-1771557814', 'gitRepoContext': {'startingBranch': 'main'}}},
    {'sourceContext': {'source': 'sources/github/watkajtys/ouroboros-test-1771557814', 'startingBranch': 'main'}},
    {'source': 'sources/github/watkajtys/ouroboros-test-1771557814'}
]

for t in tests:
    payload = {'prompt': 'test', **t}
    resp = requests.post(url, headers=headers, json=payload)
    err = resp.json().get('error', {}).get('message', '')
    if resp.status_code != 400 or 'Unknown name' in err:
        print(f"[{resp.status_code}] {json.dumps(t)} -> {err}")
    else:
        print(f"[X] {list(t.keys())[0]} format invalid")
