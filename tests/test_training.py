import importlib.util
import unittest

@unittest.skipUnless(importlib.util.find_spec('sklearn') and importlib.util.find_spec('pandas'),'optional lab dependencies not installed')
class TrainingTests(unittest.TestCase):
    def test_features_do_not_use_future_rows(self):
        import numpy as np
        import pandas as pd
        from app.experiments.training import features
        df=pd.DataFrame({'close':np.arange(100,200),'high':np.arange(101,201),'low':np.arange(99,199),'volume':np.arange(1000,1100)})
        original=features(df).iloc[:70].copy()
        df.loc[70:,'close']=100000
        pd.testing.assert_frame_equal(original,features(df).iloc[:70])
    def test_label_end_before_next_partition(self):
        import numpy as np
        from app.experiments.training import split_indices
        for horizon in [1,5]:
            tr,ca,te=split_indices(np.arange(20,1200),horizon)
            self.assertLess(tr[-1]+horizon,ca[0])
            self.assertLess(ca[-1]+horizon,te[0])
    def test_unfinished_daily_bar_excluded(self):
        from app.experiments.training import parse_naver
        from datetime import datetime
        from zoneinfo import ZoneInfo
        body=b'<protocol><chartdata><item data="20261005|100|101|99|100|1000"/><item data="20261006|100|101|99|100|1000"/></chartdata></protocol>'
        df=parse_naver(body,now=datetime(2026,10,6,14,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(len(df),1)
    def test_train_outputs_and_probability_normalization(self):
        import tempfile
        import numpy as np
        import pandas as pd
        from app.experiments.training import train_experiment
        rng=np.random.default_rng(42)
        close=10000*np.exp(np.cumsum(rng.normal(0,.02,700)))
        df=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=700).strftime('%Y-%m-%d'),'open':close,'high':close*1.01,'low':close*.99,'close':close,'volume':rng.integers(10000,100000,700)})
        with tempfile.TemporaryDirectory() as tmp:
            report=train_experiment(df,tmp,'test-fixture-hash','synthetic-test-fixture')
            self.assertFalse(report['trading_connected'])
            for e in report['experiments']:
                self.assertAlmostEqual(sum(e['latest']['probabilities'].values()),1)
