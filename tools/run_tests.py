"""Run synthetic tests only; no installed game or user saves are touched."""
import json
from pathlib import Path
import platform
import sys
import time
import unittest
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
if __name__=='__main__':
    start=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'created_utc':datetime.now(timezone.utc).isoformat(),
             'python':platform.python_version(),'platform':platform.platform(),
             'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'skipped':[(str(test),reason) for test,reason in result.skipped],
             'elapsed_seconds':round(time.perf_counter()-start,3),
             'passed':result.wasSuccessful(),
             'note':'Testes com dados sinteticos. Nao executam Crimson Moon nem editam saves instalados.'}
    print('\nRESUMO\n'+json.dumps(summary,ensure_ascii=False,indent=2))
    if len(sys.argv)==3 and sys.argv[1]=='--out':
        dest=Path(sys.argv[2])
        if dest.exists() or dest.suffix.lower()!='.json':
            print('Relatorio nao sobrescrito: escolha novo caminho .json.');raise SystemExit(2)
        dest.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
