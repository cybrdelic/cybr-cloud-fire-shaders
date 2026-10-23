"""Bounded C++ execution and checkpoint validation, not a full simulation audit."""
from pathlib import Path
import sys
import tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pressure_fire'))
import fields
from run import run
with tempfile.TemporaryDirectory(prefix='cybr-solver-') as temporary:
    initial=Path(temporary)/'initial';output=Path(temporary)/'run'
    fields.initialize(initial,(8,10,8),'oil')
    diagnostics=run(initial,output,end=.01,output_dt=.01,threads=1)
    assert diagnostics and diagnostics[-1]['time'] >= .01
    states=list(output.glob('state_*.raw')); assert len(states)>=2
    for state in states:
        volume,metadata=fields.load(state)
        assert np.isfinite(volume).all() and (volume[...,0]>0).all()
    print(f'PASS: {len(states)} finite checkpoints with positive density through 0.01 seconds')
