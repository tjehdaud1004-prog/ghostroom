"""EMQX 를 막았을 때 HiveMQ 로 넘어가는지, 360px 폭에서 가로 넘침이 없는지 본다. (실제 중계 사용)"""
import secrets, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 9300 + secrets.randbelow(500)
URL = f"http://127.0.0.1:{PORT}/index.html"
srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(ROOT)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
fails = []
try:
    time.sleep(1)
    pw = "f-" + secrets.token_hex(5)
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--host-resolver-rules=MAP broker.emqx.io 127.0.0.1"])
        pages = []
        for _ in range(2):
            ctx = br.new_context(viewport={"width": 360, "height": 740})
            pg = ctx.new_page()
            pg.goto(URL)
            pages.append(pg)
        pages[0].fill("#pw", pw); pages[0].click("#createBtn")
        pages[0].wait_for_function("() => !document.getElementById('screenRoom').hidden", timeout=60000)
        pages[0].click("#revealBtn")
        room = pages[0].inner_text("#revealBtn")
        pages[1].fill("#code", room); pages[1].click("#joinBtn")
        for pg in pages:
            pg.wait_for_function("() => document.getElementById('stateText').textContent.includes('연결됨')", timeout=60000)
        relays = [pg.inner_text("#relayText") for pg in pages]
        print("relays:", relays)
        if not all("HiveMQ" in r for r in relays):
            fails.append("fallback")
        pages[0].fill("#compose", "hi " * 300)
        pages[0].click("#sendBtn")
        pages[1].wait_for_selector(".msg.theirs")
        over = [pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") for pg in pages]
        print("가로 넘침(px):", over)
        if any(o > 0 for o in over):
            fails.append("overflow")
        br.close()
finally:
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
