import tempfile
import unittest
from pathlib import Path
import httpx
from app.experiments.storage import config,check_budget,DriveStorage

class StorageTests(unittest.TestCase):
    def test_budget_boundaries(self):
        s=config()
        check_budget(s,0,0,'prices',250000000)
        with self.assertRaises(ValueError):check_budget(s,0,0,'prices',250000001)
        with self.assertRaises(ValueError):check_budget(s,4250000000,0,'reports',1)
        self.assertEqual(sum(s['category_limits_bytes'].values())+s['reserve_bytes'],s['budget_bytes'])
    def test_inventory_pages_subfolders_and_revisions(self):
        def handler(req):
            if 'pageToken' in req.url.params:return httpx.Response(200,json={'files':[{'id':'b','mimeType':'text/plain','size':'3','quotaBytesUsed':'5'}]})
            if "'child'" in req.url.params['q']:return httpx.Response(200,json={'files':[{'id':'c','mimeType':'text/plain','size':'7'}]})
            return httpx.Response(200,json={'nextPageToken':'next','files':[{'id':'child','mimeType':'application/vnd.google-apps.folder'}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            self.assertEqual(DriveStorage(c).inventory('rootfolder'),12)
    def test_incomplete_inventory_blocks(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'incompleteSearch':True}))) as c:
            with self.assertRaises(ValueError):DriveStorage(c).inventory('folder')
    def test_upload_over_budget_never_posts(self):
        posted=[]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv';p.write_text('test')
            with httpx.Client(transport=httpx.MockTransport(lambda r:posted.append(r))) as c:
                storage=DriveStorage(c)
                storage.usage=lambda:{'total_bytes':4250000000,'categories':{'prices':0}}
                with self.assertRaises(ValueError):storage.upload(p,'prices')
                self.assertEqual(posted,[])

    def test_upload_checks_account_and_uses_related_multipart(self):
        posted=[]
        def handler(req):
            if req.url.path.endswith('/about'):return httpx.Response(200,json={'storageQuota':{'usage':'0','limit':'10000000000'}})
            posted.append(req)
            self.assertIn('multipart/related',req.headers['content-type'])
            return httpx.Response(200,json={'id':'uploaded','size':'4'})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv';p.write_text('test')
            with httpx.Client(transport=httpx.MockTransport(handler)) as c:
                storage=DriveStorage(c)
                storage.usage=lambda:{'total_bytes':0,'categories':{'prices':0}}
                self.assertEqual(storage.upload(p,'prices')['id'],'uploaded')
                self.assertEqual(len(posted),1)
