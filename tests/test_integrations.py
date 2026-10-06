import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app.engine import Engine
from app.integrations import parse_feed, NewsService, analyze

RSS=b'<rss><channel><item><title>security contract</title><link>https://example.com/story#fragment</link><pubDate>Tue, 06 Oct 2026 07:00:00 GMT</pubDate></item></channel></rss>'

class IntegrationTests(unittest.TestCase):
    def test_feed_dates_and_unsafe_link(self):
        row=parse_feed(RSS,'test')[0]
        self.assertEqual(row['url'],'https://example.com/story')
        self.assertEqual(row['published_at'],'2026-10-06T07:00:00+00:00')
        self.assertEqual(parse_feed(RSS.replace(b'https://example.com/story#fragment',b'javascript:alert(1)'),'test'),[])
    def test_atom_and_invalid_date(self):
        body=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>news</title><link href="https://example.com/a"/><updated>2026-10-06T07:00:00Z</updated></entry></feed>'
        self.assertEqual(len(parse_feed(body,'test')),1)
    def test_xml_entity_rejected(self):
        with self.assertRaises(Exception):parse_feed(b'<!DOCTYPE rss [<!ENTITY test "bad">]><rss>&test;</rss>','test')
    def test_collection_dedup_and_failure_isolation(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'NEWS_RSS_URLS':'https://example.com/feed,https://example.com/bad'}):
                e=Engine(Path(tmp)/'db');service=NewsService(e)
                def handler(req):return httpx.Response(200,content=RSS) if req.url.path=='/feed' else httpx.Response(503)
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                    await service.collect(c);self.assertEqual(service.added,1)
                    await service.collect(c);self.assertEqual(service.added,0)
                    self.assertEqual(len(service.errors),1)
                self.assertEqual(len(e.snapshot()['news']),1)
                self.assertIsNotNone(e.snapshot()['news'][0]['published_at'])
        asyncio.run(scenario())
    def test_ai_contract_and_untrusted_symbols(self):
        async def scenario():
            parsed=dict(summary='제목 기준 보안 수주 관련',impact='positive',importance=70,symbols=['053800'],horizon='unknown',uncertainty='실제 수주 규모는 제목으로 확인 불가')
            def handler(req):
                data=json.loads(req.content)
                self.assertTrue(data['text']['format']['strict'])
                return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(parsed)}]}]})
            with patch.dict(os.environ,{'OPENAI_API_KEY':'test-key','OPENAI_MODEL':'test-model'}):
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                    self.assertEqual((await analyze('안랩 수주','',c))['method'],'openai')
                    parsed['symbols']=['INVALID']
                    with self.assertRaises(ValueError):await analyze('안랩 수주','',c)
        asyncio.run(scenario())
    def test_ai_missing_configuration(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','OPENAI_MODEL':''}):
            with self.assertRaises(ValueError):asyncio.run(analyze('news',''))
    def test_history_and_concurrent_quote_sales(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            e=Engine(Path(tmp)/'db');e.quote('053800',10000,0)
            e.order('053800','buy',5,'request-123')
            with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:e.quote('053800',9000,0),range(2)))
            self.assertEqual(len(e.snapshot()['orders']),2)
            self.assertEqual(len(e.history('053800')),3)
