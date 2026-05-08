import importlib
from datetime import datetime, timedelta
import gobia_auditor.secop_client as sc
importlib.reload(sc)
client = sc.SecopClient('https://www.datos.gov.co/resource/rtxx-3nky.json')
records = []
limit = 100
offset = 0
cutoff = datetime.utcnow() - timedelta(days=30)
for i in range(3):
    params = {'$limit': min(limit, 1 - len(records)), '$offset': offset}
    print('req', i, params)
    r = client.session.get(client.api_base, params=params, timeout=10)
    print('status', r.status_code)
    payload = r.json()
    print('type', type(payload), 'len', len(payload))
    page_records = payload if isinstance(payload, list) else payload.get('results') or payload.get('data') or []
    print('page len', len(page_records))
    if not page_records:
        break
    offset += params['$limit']
    print('next offset', offset)
