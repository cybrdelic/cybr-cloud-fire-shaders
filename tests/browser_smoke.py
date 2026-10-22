"""Check real WebGL completion at bounded preview size and responsive layouts."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import json
import os
import threading
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
output=ROOT/'test-results';output.mkdir(exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
try:
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(**({'channel':os.environ['CYBR_BROWSER_CHANNEL']} if os.environ.get('CYBR_BROWSER_CHANNEL') else {}))
        page=browser.new_page(viewport={'width':1280,'height':720})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}/cloud-v17/cloud-flight.html')
        page.locator('#quality').select_option('160')
        for scene in ['cinematic','erosion']:
            page.locator('#scene').select_option(scene)
            page.wait_for_function("document.getElementById('stageStatus').textContent.startsWith('Paused')",timeout=45000)
            assert not page.locator('#error').is_visible()
            results.append({'scene':scene,'status':page.locator('#status').inner_text(),'completed':page.locator('#stageStatus').inner_text()})
            for width,height in [(1280,720),(390,844),(844,390)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'{scene}-{width}x{height}.png'),timeout=15000)
        assert not errors,errors
        browser.close()
finally:
    server.shutdown();(output/'browser.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
