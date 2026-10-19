"""Publication boundaries must survive local resource customization."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_audit',ROOT/'tools/audit_public.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class PublicationTests(unittest.TestCase):
    def test_public_build_refuses_private_override(self):
        with patch.dict(os.environ,{'CM_EDITOR_RESOURCES':'private-resources'}):
            with self.assertRaisesRegex(RuntimeError,'Unset'):audit.audit()

    def test_replaced_localization_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir();(root/'assets').mkdir()
            (root/'data/game_data.json').write_text('{"private":"imported localization"}',encoding='utf-8')
            (root/'public-resources.json').write_text(json.dumps({'files':{'data/game_data.json':'0'*64}}),encoding='utf-8')
            (root/'tools').mkdir()
            (root/'tools/bootstrap_public_assets.py').write_bytes((ROOT/'tools/bootstrap_public_assets.py').read_bytes())
            with patch.object(audit,'ROOT',root),patch.dict(os.environ,{'CM_EDITOR_RESOURCES':''}):
                with self.assertRaisesRegex(RuntimeError,'Resources differ'):audit.audit()

    def test_runtime_override_is_explicit(self):
        from crimson.resource_paths import resource_root
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'CM_EDITOR_RESOURCES':temp}):
            self.assertEqual(resource_root(),Path(temp).resolve())

if __name__=='__main__':unittest.main()
