"""Check real WebGL completion at bounded preview size and responsive layouts."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import json
import os
import threading
from playwright.sync_api import sync_playwright,TimeoutError as PlaywrightTimeoutError
ROOT=Path(__file__).resolve().parents[1]
output=ROOT/'test-results';output.mkdir(exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
COMPLETED="""expected => {
    const state = window.getCloudPreviewDiagnostics();
    const frame = state.lastCompleted;
    return !state.failed && !state.lost && !state.pending
        && state.scene === expected.scene && state.generation === expected.generation
        && state.completedFrames >= expected.minimumFrames && frame !== null
        && frame.scene === expected.scene && frame.generation === expected.generation;
}"""

def wait_for_completed(page,scene,generation,minimum_frames=1,timeout=45000):
    try:
        page.wait_for_function(COMPLETED,arg={'scene':scene,'generation':generation,'minimumFrames':minimum_frames},polling=50,timeout=timeout)
    except PlaywrightTimeoutError:
        # Preserve the actual terminal state; do not reinterpret a stopped frame
        # or capability fallback as a completed render.
        if timeout > 300:
            failure=page.evaluate("""() => ({diagnostics:window.getCloudPreviewDiagnostics(),
                summary:document.getElementById('errorSummary').textContent,
                detail:document.getElementById('errorLog').textContent})""")
            (output/'failure.json').write_text(json.dumps(failure,indent=2)+'\n')
        raise
    return page.evaluate('window.getCloudPreviewDiagnostics()')

def hold_animation_frames(page):
    page.evaluate("""() => {
        const request = window.requestAnimationFrame, cancel = window.cancelAnimationFrame;
        const queued = new Map(); let next = -1;
        window.requestAnimationFrame = callback => { const id = next--; queued.set(id,callback); return id; };
        window.cancelAnimationFrame = id => { if (!queued.delete(id)) cancel.call(window,id); };
        window.resumeAuditAnimationFrames = () => {
            window.requestAnimationFrame = request; window.cancelAnimationFrame = cancel;
            for (const callback of queued.values()) request.call(window,callback);
            delete window.resumeAuditAnimationFrames;
        };
    }""")

try:
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(**({'channel':os.environ['CYBR_BROWSER_CHANNEL']} if os.environ.get('CYBR_BROWSER_CHANNEL') else {}))
        page=browser.new_page(viewport={'width':1280,'height':720})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}/cloud-v17/cloud-flight.html')
        page.locator('#quality').select_option('160')
        for scene in ['cinematic','erosion']:
            regression=None
            if scene == 'erosion':
                # Hold actual frame submission, switch scene, and deliberately retain
                # the prior Paused label. The completion predicate must still reject it.
                previous=page.evaluate('window.getCloudPreviewDiagnostics()')
                previous_label=page.locator('#stageStatus').inner_text()
                assert previous['completedFrames'] > 0 and previous_label.startswith('Paused')
                hold_animation_frames(page)
                try:
                    page.locator('#scene').select_option(scene)
                    reset=page.evaluate('window.getCloudPreviewDiagnostics()')
                    assert reset['generation'] > previous['generation']
                    assert reset['completedFrames'] == 0 and reset['lastCompleted'] is None
                    assert not page.locator('#stageStatus').inner_text().startswith('Paused')
                    page.locator('#stageStatus').evaluate('(element,label) => element.textContent=label',previous_label)
                    try:
                        wait_for_completed(page,scene,reset['generation'],timeout=300)
                    except PlaywrightTimeoutError:
                        regression={'stale_paused_label_rejected':True,'before':previous,'while_frames_held':reset}
                    else:
                        raise AssertionError('Scene switch accepted a stale completed frame')
                finally:
                    page.evaluate('window.resumeAuditAnimationFrames()')
            else:
                page.locator('#scene').select_option(scene)
            generation=page.evaluate('window.getCloudPreviewDiagnostics().generation')
            completed=wait_for_completed(page,scene,generation)
            assert not page.locator('#error').is_visible()
            evidence={'scene':scene,'status':page.locator('#status').inner_text(),'completed':page.locator('#stageStatus').inner_text(),'diagnostics':completed,'viewports':[]}
            if regression: evidence['regression']=regression
            for width,height in [(1280,720),(390,844),(844,390)]:
                if page.viewport_size != {'width':width,'height':height}:
                    before=page.evaluate('window.getCloudPreviewDiagnostics().completedFrames')
                    page.set_viewport_size({'width':width,'height':height})
                    completed=wait_for_completed(page,scene,generation,minimum_frames=before+1)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'{scene}-{width}x{height}.png'),timeout=15000)
                evidence['viewports'].append({'width':width,'height':height,'diagnostics':completed})
            results.append(evidence)
        assert not errors,errors
        browser.close()
finally:
    server.shutdown();(output/'browser.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
