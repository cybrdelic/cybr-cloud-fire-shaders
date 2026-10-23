from pathlib import Path
import contextlib
import io
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'pressure_fire'))
import portable_gl
import fields
import numpy as np

class PortabilityTests(unittest.TestCase):
    def test_explicit_initial_preview_quality(self):
        subprocess.run(['node',str(ROOT/'tests/test_initial_quality.cjs')],check=True)

    def test_completed_frame_before_elapsed_policy(self):
        subprocess.run(['node',str(ROOT/'tests/test_frame_completion.cjs')],check=True)

    def test_desktop_noise_namespace_preserves_body_and_builtin_calls(self):
        original='float noise3(vec3 p) { return p.x*p.y; } void main(){ float n=noise3(vec3(1)); }'
        self.assertEqual(portable_gl.desktop_identifiers(original).replace('cybr_scalar_noise3','noise3'),original)
        builtin='void main(){ vec3 n=noise3(vec3(1)); }'
        self.assertEqual(portable_gl.desktop_identifiers(builtin),builtin)

    def test_native_windows_and_macos_do_not_request_egl(self):
        for system in ['Windows','Darwin']:
            calls=[]
            context=types.SimpleNamespace(version_code=330,info={'GL_RENDERER':'unit-test'})
            module=types.SimpleNamespace(create_standalone_context=lambda **kw:(calls.append(kw) or context))
            with patch.dict(sys.modules,moderngl=module),patch('platform.system',return_value=system),patch.dict('os.environ',{'CYBR_GL_BACKEND':'auto'}),contextlib.redirect_stderr(io.StringIO()):
                self.assertIs(portable_gl.create_context(),context)
            self.assertEqual(calls,[{'require':330}])

    def test_failed_linux_egl_falls_back_and_errors_remain_actionable(self):
        calls=[]
        def fail(**kwargs):
            calls.append(kwargs);raise RuntimeError('no display')
        with patch.dict(sys.modules,moderngl=types.SimpleNamespace(create_standalone_context=fail)),patch('platform.system',return_value='Linux'),patch.dict('os.environ',{'CYBR_GL_BACKEND':'auto'}):
            with self.assertRaisesRegex(RuntimeError,'egl: RuntimeError: no display; default: RuntimeError: no display'):
                portable_gl.create_context()
        self.assertEqual(len(calls),2)

    def test_volume_round_trip_and_positive_thermodynamics(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem=Path(temporary)/'initial';fields.initialize(stem,(8,10,8),'oil')
            volume,metadata=fields.load(stem);fields.export_npz(stem,volume,metadata)
            with np.load(stem.with_suffix('.npz')) as archive:
                self.assertTrue(np.array_equal(volume,archive['U']))
                self.assertTrue(np.isfinite(archive['temperature']).all())
                self.assertGreater(float(archive['pressure'].min()),0)

if __name__ == '__main__': unittest.main()
