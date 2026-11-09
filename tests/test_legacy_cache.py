import pathlib
import shutil
import subprocess
import unittest

class LegacyCacheTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_error_object_is_evicted_but_arrays_survive(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / 'static/js/app.js').read_text()
        function = source[source.index('function getCache(key)'):source.index('function setCache(key')]
        script = '''const assert = require('node:assert/strict');
const PLAYLIST_CACHE_TTL = 86400000;
const storage = new Map();
const localStorage = {getItem:k=>storage.get(k), removeItem:k=>storage.delete(k)};
''' + function + '''
storage.set('bad', JSON.stringify({data:{error:'Forbidden'},timestamp:Date.now()}));
assert.equal(getCache('bad'), null);
assert.equal(storage.has('bad'), false);
storage.set('good', JSON.stringify({data:[],timestamp:Date.now()}));
assert.deepEqual(getCache('good'), []);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
