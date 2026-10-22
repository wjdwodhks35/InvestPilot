"""Drive storage for research artifacts only. No broker or portfolio imports."""
import json
import os
import uuid
import re
import time
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).resolve().parents[2]/'config/model_lab_storage.json'
BASE = 'https://www.googleapis.com/drive/v3'


def config():
    private=Path(os.getenv('MODEL_LAB_STORAGE_CONFIG','data/model_lab_storage.json'))
    return json.loads((private if private.exists() else CONFIG_PATH).read_text())


def check_budget(settings, total_used, category_used, category, incoming):
    if category not in settings['folders']: raise ValueError('알 수 없는 저장 분류')
    if incoming < 0: raise ValueError('파일 크기 오류')
    usable = settings['budget_bytes'] - settings['reserve_bytes']
    if total_used + incoming > usable: raise ValueError('총 저장 한도 초과 (예비 공간 보존)')
    if category_used + incoming > settings['category_limits_bytes'][category]:
        raise ValueError('분류별 저장 한도 초과')


class DriveCredentials:
    """In-memory access tokens; refresh credentials remain in existing secret env vars."""
    def __init__(self, env=None, client=None, clock=time.monotonic):
        self.env = os.environ if env is None else env
        self.client, self.clock = client, clock
        self.cached, self.expires = None, 0

    def access_token(self):
        if self.cached and self.clock() < self.expires:
            return self.cached
        refresh = self.env.get('GOOGLE_DRIVE_REFRESH_TOKEN', '')
        if not refresh:
            token = self.env.get('GOOGLE_DRIVE_ACCESS_TOKEN', '')
            if not token:
                raise ValueError('Drive OAuth configuration required')
            return token
        data = dict(grant_type='refresh_token', refresh_token=refresh,
                    client_id=self.env.get('GOOGLE_DRIVE_CLIENT_ID', ''),
                    client_secret=self.env.get('GOOGLE_DRIVE_CLIENT_SECRET', ''))
        if not data['client_id'] or not data['client_secret']:
            raise ValueError('Drive OAuth configuration incomplete')
        def request(client):
            response = client.post('https://oauth2.googleapis.com/token', data=data)
            response.raise_for_status()
            result = response.json()
            token, lifetime = result.get('access_token'), int(result.get('expires_in', 0))
            if not isinstance(token, str) or not token or lifetime <= 0:
                raise ValueError('Invalid Drive token response')
            self.cached = token
            self.expires = self.clock()+max(0, lifetime-60)
            return token
        if self.client is not None:
            return request(self.client)
        with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
            return request(client)


class DriveStorage:
    def __init__(self, client=None, credentials=None):
        self.settings=config()
        self.client=client or httpx.Client(timeout=60,trust_env=False,
            headers={'Authorization':'Bearer '+(credentials or DriveCredentials()).access_token()})

    def inventory(self, folder, seen=None):
        seen=seen if seen is not None else set()
        if folder in seen: return 0
        seen.add(folder)
        total=0;page=None
        while True:
            params={'q':f"'{folder}' in parents and trashed = false",'pageSize':1000,
                    'fields':'nextPageToken,incompleteSearch,files(id,mimeType,size,quotaBytesUsed)'}
            if page:params['pageToken']=page
            r=self.client.get(BASE+'/files',params=params);r.raise_for_status();d=r.json()
            if d.get('incompleteSearch'):raise ValueError('Drive 사용량 검색이 불완전합니다')
            for item in d.get('files',[]):
                if item['mimeType']=='application/vnd.google-apps.folder':
                    total+=self.inventory(item['id'],seen)
                else:
                    size=item.get('quotaBytesUsed',item.get('size'))
                    if size is None:raise ValueError('파일 저장 사용량을 확인할 수 없습니다')
                    total+=int(size)
            page=d.get('nextPageToken')
            if not page:break
        return total

    def usage(self):
        s=self.settings
        if not s['root_folder_id'] or not all(s['folders'].values()):
            raise ValueError('비공개 Drive 폴더 설정을 data/model_lab_storage.json에 저장하세요')
        return dict(total_bytes=self.inventory(s['root_folder_id']),
                    categories={k:self.inventory(v) for k,v in s['folders'].items()},
                    budget_bytes=s['budget_bytes'],reserve_bytes=s['reserve_bytes'])

    def upload(self, path, category, artifact_id=None):
        path=Path(path)
        allowed=('.csv','.csv.gz','.json','.jsonl.gz','.parquet','.txt','.md','.npz')
        if not path.name.endswith(allowed):raise ValueError('허용되지 않은 실험 파일 형식')
        if category not in self.settings['folders']:raise ValueError('알 수 없는 저장 분류')
        if artifact_id is not None:
            if not re.fullmatch('[0-9a-f]{64}', artifact_id):
                raise ValueError('Invalid artifact digest')
            folder = self.settings['folders'][category]
            if not folder:
                raise ValueError('Drive folder configuration required')
            response = self.client.get(BASE+'/files', params={
                'q': "'"+folder+"' in parents and trashed = false and appProperties has { key='investpilot_digest' and value='"+artifact_id+"' }",
                'fields':'files(id),incompleteSearch', 'pageSize':2})
            response.raise_for_status()
            existing = response.json()
            if existing.get('incompleteSearch'):
                raise ValueError('Incomplete duplicate search')
            if existing.get('files'):
                return {'id':existing['files'][0]['id']}
        size=path.stat().st_size
        if size>32_000_000:raise ValueError('파일을 32MB 이하 조각으로 나눠 저장하세요')
        u=self.usage()
        check_budget(self.settings,u['total_bytes'],u['categories'][category],category,size)
        quota=self.client.get(BASE+'/about',params={'fields':'storageQuota'})
        quota.raise_for_status();q=quota.json()['storageQuota']
        if 'limit' in q and int(q['usage'])+size>int(q['limit']):
            raise ValueError('Google 계정 전체 저장 공간 부족')
        # Snapshot the bounded bytes, so a growing source file cannot bypass the checked size.
        body=path.read_bytes()
        if len(body)!=size:raise ValueError('업로드 준비 중 파일 크기가 변경되었습니다')
        metadata={'name':path.name,'parents':[self.settings['folders'][category]]}
        if artifact_id:
            metadata['appProperties']={'investpilot_digest':artifact_id}
        metadata=json.dumps(metadata)
        boundary='investpilot-'+uuid.uuid4().hex
        payload=(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()+metadata.encode()+
                 f'\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+body+f'\r\n--{boundary}--\r\n'.encode())
        r=self.client.post('https://www.googleapis.com/upload/drive/v3/files',params={'uploadType':'multipart','fields':'id,name,size,webViewLink'},
            headers={'Content-Type':'multipart/related; boundary='+boundary},content=payload)
        r.raise_for_status()
        return r.json()
