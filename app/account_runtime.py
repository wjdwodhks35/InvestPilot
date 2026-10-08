"""Stable account-scoped paper stores; request identity is set by auth middleware."""
from contextvars import ContextVar
from pathlib import Path
import os
import threading
from app.engine import Engine
from app.experiments.ai_paper import Wallet, OllamaExperiment

current_user=ContextVar('investpilot_user',default='owner')


class AccountRuntime:
    def __init__(self,engine,wallet,experiment):
        self.items={'owner':dict(engine=engine,wallet=wallet,experiment=experiment)}
        self.lock=threading.RLock();self.tasks={}

    def get(self,user_id=None):
        user_id=user_id or current_user.get()
        with self.lock:
            if user_id not in self.items:
                import re
                if not re.fullmatch('[0-9a-f]{32}',user_id): raise ValueError('Invalid account identity')
                root=Path(os.getenv('INVESTPILOT_DATA_DIR','data'))/'accounts'/user_id
                engine=Engine(root/'paper.db',tenant=user_id)
                wallet=Wallet(root/'ai.db',tenant=user_id)
                self.items[user_id]=dict(engine=engine,wallet=wallet,experiment=OllamaExperiment(wallet))
            return self.items[user_id]


class Scoped:
    def __init__(self,runtime,name):
        object.__setattr__(self,'runtime',runtime);object.__setattr__(self,'name',name)
    def __getattr__(self,key): return getattr(self.runtime.get()[self.name],key)
    def __setattr__(self,key,value): setattr(self.runtime.get()[self.name],key,value)
