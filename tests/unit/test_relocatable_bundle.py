import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

VERIFY = load('verify_relocatable_bundle')
GENERATE = load('generate_bundle_manifest')

class Result:
    def __init__(self, text='', code=0): self.stdout, self.returncode = text, code

class RelocatableBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.tmp.name) / 'edgeomni-relocatable-work-current' / 'bundle'
        (self.root/'bin').mkdir(parents=True); (self.root/'lib').mkdir()
        (self.root/'bin'/'tool').write_bytes(b'ELF'); (self.root/'lib'/'libllama.so').write_bytes(b'ELF')
        (self.root/'lib'/'libllama.so.0').symlink_to('libllama.so')
    def tearDown(self): self.tmp.cleanup()
    def manifest(self):
        import hashlib
        rows=[]
        for p,r in [(self.root/'bin'/'tool','$ORIGIN/../lib'),(self.root/'lib'/'libllama.so','$ORIGIN')]:
            rows.append({'path':str(p.relative_to(self.root)),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rpath':r})
        return {'canonical_elf':rows,'symlinks':[{'path':'lib/libllama.so.0','target':'libllama.so'}]}
    def verify(self, manifest=None, ldd='libllama.so => {lib}/libllama.so\n', rpath=None):
        m=self.manifest() if manifest is None else manifest; mp=self.root/'manifest.json'; mp.write_text(json.dumps(m))
        rpath=rpath or {'bin/tool':'$ORIGIN/../lib','lib/libllama.so':'$ORIGIN'}
        def call(cmd, **kw):
            s=' '.join(map(str,cmd)); path=pathlib.Path(cmd[-1]); rel=str(path.relative_to(self.root)) if path.exists() else ''
            if cmd[:2]==['readelf','-h']: return Result(code=0)
            if cmd[:2]==['readelf','-d']: return Result(f' 0x0 (RUNPATH) Library runpath: [{rpath[rel]}]\n')
            if 'ldd' in cmd: self.assertIn('env',cmd); self.assertIn('-u',cmd); return Result(ldd.format(lib=self.root/'lib'))
            return Result()
        with patch.object(VERIFY.subprocess,'run',side_effect=call), patch.object(VERIFY.sys,'argv',['v','--bundle',str(self.root),'--manifest',str(mp)]): return VERIFY.main()
    def test_normal_and_symlink_separation(self): self.assertEqual(self.verify(),0)
    def test_bad_rpath_not_found_and_external_private_fail(self):
        self.assertEqual(self.verify(rpath={'bin/tool':'/bad','lib/libllama.so':'$ORIGIN'}),1)
        self.assertEqual(self.verify(ldd='libllama.so => not found\n'),1)
        self.assertEqual(self.verify(ldd='libllama.so => /tmp/libllama.so\n'),1)
        self.assertEqual(self.verify(ldd='libllama.so => '+str(self.root/'bin'/'..'/'lib'/'libllama.so')+'\n'),0)
        self.assertEqual(self.verify(ldd='libllama.so => /tmp/another-clone/lib/libllama.so\n'),1)
        self.assertIn('private dependency outside bundle/lib', GENERATE.ldd_failures(
            'libllama.so => /tmp/another-clone/lib/libllama.so\n', self.root))
    def test_manifest_paths_sets_hashes_and_links_fail(self):
        m=self.manifest(); m['canonical_elf'][0]['path']='../escape'; self.assertEqual(self.verify(m),1)
        m=self.manifest(); m['canonical_elf'].pop(); self.assertEqual(self.verify(m),1)
        m=self.manifest(); m['canonical_elf'][0]['sha256']='0'*64; self.assertEqual(self.verify(m),1)
        (self.root/'lib'/'bad').symlink_to('/tmp'); self.assertEqual(self.verify(),1)

if __name__ == '__main__': unittest.main()
