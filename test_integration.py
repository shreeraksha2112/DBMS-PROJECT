import urllib.request
import urllib.error
import json

BASE_URL = 'http://127.0.0.1:5000/api'

def make_request(url, method='GET', headers=None, data=None):
    if headers is None: headers = {}
    if data:
        data = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
        
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def test_integration():
    print("Testing Backend Integration...")
    
    # 1. Register
    print("\n[1] Registering user...")
    status, res = make_request(f"{BASE_URL}/auth/register", 'POST', data={
        "name": "Integration Tester",
        "email": "test@example.com",
        "password": "password123"
    })
    print(status, res)

    # 2. Login
    print("\n[2] Logging in...")
    status, res = make_request(f"{BASE_URL}/auth/login", 'POST', data={
        "email": "test@example.com",
        "password": "password123"
    })
    print(status, res)
    
    if status != 200:
        print("Login failed, aborting.")
        return
        
    token = res.get('token')
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Check Dashboard
    print("\n[3] Fetching Dashboard...")
    status, res = make_request(f"{BASE_URL}/dashboard", 'GET', headers=headers)
    print(status, res)
    
    # 4. Submit Activity (Cycling, activity_id=1, 5km)
    print("\n[4] Submitting Activity...")
    status, res = make_request(f"{BASE_URL}/activities/", 'POST', headers=headers, data={
        "activity_id": 1,
        "quantity": 5.0
    })
    print(status, res)
    
    # 5. Check Dashboard again for updated wallet
    print("\n[5] Fetching Dashboard (verify wallet balance)...")
    status, res = make_request(f"{BASE_URL}/dashboard", 'GET', headers=headers)
    print(status, res)
    
    print("\nIntegration Test Complete.")

if __name__ == '__main__':
    test_integration()


if __name__ == '__main__':
    test_integration()
