import requests

url = 'https://www.datos.gov.co/resource/rtxx-3nky.json'
resp = requests.get(url, params={'$limit': 1})
print(resp.status_code)
print(resp.text)
