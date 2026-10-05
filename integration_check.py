import json
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:5000/api'


def request(path, method='GET', token=None, payload=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        return e.code, json.loads(body) if body else None


email = 'finalcheck3@example.com'
print('1) REGISTER:', request('/auth/register', 'POST', payload={'name': 'Final Checker', 'email': email, 'password': 'pw12345'}))
status, login = request('/auth/login', 'POST', payload={'email': email, 'password': 'pw12345'})
print('2) LOGIN:', status, login)
token = login.get('token')
print('3) DASHBOARD:', request('/dashboard', 'GET', token=token))
print('4) CHALLENGE LIST:', request('/challenges/', 'GET', token=token))
print('5) JOIN CHALLENGE:', request('/challenges/1/join', 'POST', token=token))
print('6) SUBMIT ACTIVITY:', request('/activities/', 'POST', token=token, payload={'activity_id': 1, 'quantity': 100.0}))
print('7) DASHBOARD AFTER ACTIVITY:', request('/dashboard', 'GET', token=token))
print('8) REWARD LIST:', request('/rewards/', 'GET', token=token))
print('9) REDEEM REWARD:', request('/rewards/1/redeem', 'POST', token=token))
print('10) LEADERBOARD:', request('/leaderboard', 'GET', token=token))
