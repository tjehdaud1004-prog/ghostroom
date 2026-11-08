"""GhostRoom 자동 시험 (Playwright, 실제 공개 중계 사용).

실행: python -X utf8 tests/e2e.py
로컬 http 서버를 자기가 띄웠다가 끝에 자기 것만 끈다. 비밀번호와 숫자는 매번 무작위.
"""
import os, re, secrets, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765 + secrets.randbelow(500)
BASE = f"http://127.0.0.1:{PORT}/index.html"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""), flush=True)


INIT = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
"""


def new_ctx(browser, errors, tag):
    ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    ctx.add_init_script(INIT)
    return ctx


def new_page(ctx, errors, tag, query="?leaveSeconds=5"):
    p = ctx.new_page()
    p.on("console", lambda m: errors.append(f"{tag} console.{m.type}: {m.text}") if m.type == "error" else None)
    p.on("pageerror", lambda e: errors.append(f"{tag} pageerror: {e}"))
    p.goto(BASE + query)
    return p


def make(p, prefix):
    """'방 만들기' 로 방을 만들고, 가림 상자를 열어 방 코드를 읽는다(읽은 뒤 다시 가린다)."""
    p.fill("#pw", prefix)
    p.click("#createBtn")
    p.wait_for_function("() => !document.getElementById('screenRoom').hidden", timeout=60000)
    p.click("#revealBtn")
    code = p.inner_text("#revealBtn")
    p.click("#revealBtn")
    return code


def enter(p, code):
    p.fill("#code", code)
    p.click("#joinBtn")


def state(p):
    return p.inner_text("#stateText")


def wait_state(p, text, timeout=60000):
    p.wait_for_function(
        "t => document.getElementById('stateText').textContent.includes(t) && !document.getElementById('screenRoom').hidden",
        arg=text, timeout=timeout)


def main():
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(ROOT)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []
    t0 = time.time()
    try:
        time.sleep(1)
        pw = "t-" + secrets.token_hex(6) + " 가나"
        with sync_playwright() as pwr:
            browser = pwr.chromium.launch()
            ctxA, ctxB, ctxC, ctxD = (new_ctx(browser, errors, t) for t in "ABCD")
            A, B = new_page(ctxA, errors, "A"), new_page(ctxB, errors, "B")

            # 시험 모드 표시와 첫 화면
            check("첫 화면: 시험 모드 표시", A.is_visible("#testBadge") and A.is_visible("#joinBtn"))

            # 1. 연결 + 양방향 + 공백 보존
            code1 = make(A, pw)
            check("0a. 방 만들기: 코드가 앞부분 + 숫자 4자리", re.fullmatch(re.escape(pw) + r"\d{4}", code1) is not None, "앞부분 뒤 숫자 4자리")
            # 가림 상자
            hidden_txt = A.inner_text("body")
            check("0b. 가린 상태에서 페이지 글자에 코드 없음", code1 not in hidden_txt and pw not in hidden_txt and A.inner_text("#revealBtn") == "비밀번호")
            A.click("#revealBtn")
            check("0c. 누르면 코드가 보이고 복사 버튼 나옴", A.inner_text("#revealBtn") == code1 and A.is_visible("#codeCopyBtn"))
            A.click("#codeCopyBtn")
            cc = A.evaluate("navigator.clipboard.readText()")
            check("0d. 방 코드 복사 버튼", cc == code1)
            A.click("#revealBtn")
            check("0e. 다시 누르면 다시 가려짐(DOM 에서도 사라짐)",
                  code1 not in A.inner_text("body") and A.inner_text("#revealBtn") == "비밀번호"
                  and A.evaluate("() => !document.documentElement.outerHTML.includes(%r)" % code1))
            enter(B, code1)
            wait_state(A, "연결됨")
            wait_state(B, "연결됨")
            check("1a. 둘 다 같은 값 -> 연결됨", True, f"A={state(A)!r} B={state(B)!r}")
            relay_a, relay_b = A.inner_text("#relayText"), B.inner_text("#relayText")
            check("1b. 상태줄에 같은 중계 이름", relay_a == relay_b and "중계:" in relay_a, relay_a)

            raw = "\n\n  cd /tmp  \n\techo   'a  b'\n\n    \n"
            want = "  cd /tmp  \n\techo   'a  b'"
            A.fill("#compose", raw)
            A.click("#sendBtn")
            B.wait_for_selector(".msg.theirs pre", timeout=20000)
            got = B.inner_text(".msg.theirs pre") if False else B.eval_on_selector(".msg.theirs pre", "e => e.textContent")
            check("1c. A->B 도착, 여러 줄·공백 보존", got == want, repr(got))
            B.fill("#compose", "한글 <b>x</b> & \"q\"\nline2")
            B.press("#compose", "Control+Enter")
            A.wait_for_selector(".msg.theirs pre", timeout=20000)
            got2 = A.eval_on_selector(".msg.theirs pre", "e => e.textContent")
            xss_safe = A.eval_on_selector("#messages", "e => e.querySelectorAll('b').length") == 0
            check("1d. B->A 도착, HTML 은 글자로만", got2 == "한글 <b>x</b> & \"q\"\nline2" and xss_safe, repr(got2))

            big = "x" * 20001
            A.fill("#compose", big)
            A.click("#sendBtn")
            check("1e. 20,000자 초과는 안내하고 안 보냄",
                  "너무 깁니다" in A.inner_text("#roomNote") and A.locator(".msg.mine").count() == 1)
            ok_big = "y" * 20000
            A.fill("#compose", ok_big)
            A.click("#sendBtn")
            B.wait_for_function("n => document.querySelectorAll('.msg.theirs').length === 2 && document.querySelectorAll('.msg.theirs pre')[1].textContent.length === n", arg=20000, timeout=30000)
            check("1f. 20,000자는 통과", True)

            # 2. 다른 숫자 -> 서로 안 보임
            D = new_page(ctxD, errors, "D")
            make(D, pw)
            wait_state(D, "기다리는 중")
            time.sleep(8)
            check("2. 다른 숫자 4자리 -> 서로 안 보임",
                  "기다리는 중" in state(D) and "연결됨" in state(A) and "연결됨" in state(B)
                  and D.locator(".msg").count() == 0, f"D={state(D)!r}")

            # 3. 셋째
            C = new_page(ctxC, errors, "C")
            enter(C, code1)
            C.wait_for_function("() => document.getElementById('joinMsg').textContent.includes('이미 두 명')", timeout=60000)
            c_msg = C.inner_text("#joinMsg")
            check("3a. 셋째는 '두 명' 안내 후 첫 화면으로", "이미 두 명" in c_msg, c_msg)
            check("3b. 앞의 둘은 유지", "연결됨" in state(A) and "연결됨" in state(B))
            A.fill("#compose", "still-ok")
            A.click("#sendBtn")
            B.wait_for_function("() => document.querySelectorAll('.msg.theirs').length === 3", timeout=20000)
            check("3c. 셋째 뒤에도 A->B 전달", True)

            # 5. 복사
            B.click(".msg.theirs >> nth=0 >> button.copy")
            # 윈도우 클립보드는 줄바꿈을 \r\n 으로 바꿔 돌려준다(운영체제 동작) — 그것만 되돌려 비교
            clip = B.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
            check("5a. 복사 버튼 -> 클립보드가 원문과 같음", clip == want, repr(clip))
            B.click("#copyAllBtn")
            clip_all = B.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
            check("5b. 전체 복사에 모든 글 포함", want in clip_all and "still-ok" in clip_all and "한글 <b>x</b>" in clip_all)

            # 6. 저장소
            for tag, pg in (("A", A), ("B", B), ("C", C), ("D", D)):
                st = pg.evaluate("""async () => ({
                    ls: localStorage.length, ss: sessionStorage.length, ck: document.cookie.length,
                    idb: (indexedDB.databases ? (await indexedDB.databases()).length : 0) })""")
                check(f"6. {tag} 저장소 비어 있음", st == {"ls": 0, "ss": 0, "ck": 0, "idb": 0}, str(st))

            # 7. 콘솔 오류 · CSP (퇴장 시험 전 중간 점검)
            csp = [pg.evaluate("window.__csp") for pg in (A, B, C, D)]
            check("7a. CSP 위반 0", all(not x for x in csp), str(csp))

            # 4. 퇴장: pagehide 로 LEAVE -> A 에 카운트다운 -> 5초 뒤 첫 화면
            B.close(run_before_unload=True)
            wait_state(A, "상대가 나갔습니다", timeout=15000)
            t1 = time.time()
            check("4a. B 닫음 -> A 에 카운트다운", True, state(A))
            dbg_mid = A.evaluate("window.__grDebug()")
            A.wait_for_function("() => !document.getElementById('screenJoin').hidden", timeout=15000)
            dt = time.time() - t1
            dbg = A.evaluate("window.__grDebug()")
            check("4b. 5초 뒤 A 첫 화면", 3 <= dt <= 9, f"{dt:.1f}s")
            check("4c. 기록·키·집합 비워짐",
                  dbg["log"] == 0 and dbg["seen"] == 0 and dbg["peers"] == 0 and not dbg["hasKey"]
                  and not dbg["hasClient"] and dbg["domMsgs"] == 0 and dbg_mid["log"] >= 3, f"전 {dbg_mid} 후 {dbg}")
            check("4d. 입력칸 비움", A.input_value("#pw") == "" and A.input_value("#code") == "" and A.evaluate("window.__grDebug()")["hasCode"] is False)
            check("4e. 첫 화면 안내문", "지웠습니다" in A.inner_text("#joinMsg"), A.inner_text("#joinMsg"))
            for pg in (A, C, D):
                pg.close()
            ctxA.close(); ctxB.close(); ctxC.close(); ctxD.close()

            # 4f. LEAVE 없이 사라짐(컨텍스트 강제 종료) -> 하트비트 시간 초과 판정
            pw2 = "u-" + secrets.token_hex(6)
            ctxE, ctxF = new_ctx(browser, errors, "E"), new_ctx(browser, errors, "F")
            E, F = new_page(ctxE, errors, "E"), new_page(ctxF, errors, "F")
            c3 = make(E, pw2); enter(F, c3)
            wait_state(E, "연결됨"); wait_state(F, "연결됨")
            F.evaluate("window.__grKill = true")
            ctxF.close()
            t2 = time.time()
            wait_state(E, "상대가 나갔습니다", timeout=30000)
            d1 = time.time() - t2
            E.wait_for_function("() => !document.getElementById('screenJoin').hidden", timeout=20000)
            check("4f. LEAVE 없이 닫힘 -> 10초 안팎 뒤 카운트다운 -> 첫 화면", 4 <= d1 <= 16, f"감지 {d1:.1f}s")
            E.close(); ctxE.close()

            # R. 랜덤방: 200번 뽑기(생성기) + 실제 버튼으로 만든 방에 상대가 들어가기
            ctxR1, ctxR2 = new_ctx(browser, errors, "R1"), new_ctx(browser, errors, "R2")
            R1, R2 = new_page(ctxR1, errors, "R1"), new_page(ctxR2, errors, "R2")
            samples = R1.evaluate("() => Array.from({length: 200}, () => window.__grGen.randomPrefix() + window.__grGen.digits4())")
            lens = {len(x) - 4 for x in samples}
            check("R1. 랜덤방 200개: 정규식 맞고 앞부분 길이 1·2·3 모두 나옴",
                  all(re.fullmatch(r"[A-Za-z0-9]{1,3}\d{4}", x) for x in samples) and lens == {1, 2, 3}, f"길이 {sorted(lens)}")
            R1.click("#randomBtn")
            R1.wait_for_function("() => !document.getElementById('screenRoom').hidden", timeout=60000)
            R1.click("#revealBtn")
            rcode = R1.inner_text("#revealBtn")
            check("R2. 랜덤방 버튼이 만든 코드 형식", re.fullmatch(r"[A-Za-z0-9]{1,3}\d{4}", rcode) is not None, "형식 맞음")
            enter(R2, rcode)
            wait_state(R1, "연결됨"); wait_state(R2, "연결됨")
            check("R3. 상대가 '들어가기'에 코드를 쳐서 연결됨", True)
            R2.click("#revealBtn")
            check("R4. 들어온 쪽도 같은 자리에서 코드 보임", R2.inner_text("#revealBtn") == rcode)
            R1.set_viewport_size({"width": 360, "height": 740})
            R1.screenshot(path=str(Path(os.environ.get("GR_SHOT_DIR", ROOT / "tests")) / "shot_room_360.png"))
            ow = R1.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("R5. 360px 방 화면 가로 넘침 없음", ow <= 0, f"{ow}px")
            R1.click("#leaveBtn")
            R1.set_viewport_size({"width": 360, "height": 740})
            R1.screenshot(path=str(Path(os.environ.get("GR_SHOT_DIR", ROOT / "tests")) / "shot_join_360.png"))
            ow2 = R1.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("R6. 360px 첫 화면 가로 넘침 없음", ow2 <= 0, f"{ow2}px")
            ctxR1.close(); ctxR2.close()

            # 4g. 돌아오면 카운트다운 멈춤 (버튼으로 나갔다가 같은 값으로 재입장)
            pw3 = "v-" + secrets.token_hex(6)
            ctxG, ctxH = new_ctx(browser, errors, "G"), new_ctx(browser, errors, "H")
            G = new_page(ctxG, errors, "G", "?leaveSeconds=30")
            H = new_page(ctxH, errors, "H", "?leaveSeconds=30")
            c4 = make(G, pw3); enter(H, c4)
            wait_state(G, "연결됨"); wait_state(H, "연결됨")
            H.click("#leaveBtn")
            wait_state(G, "상대가 나갔습니다", timeout=15000)
            enter(H, c4)
            wait_state(G, "연결됨", timeout=40000)
            wait_state(H, "연결됨", timeout=40000)
            time.sleep(3)
            check("4g. 돌아오면 카운트다운이 멈추고 다시 연결됨", "연결됨" in state(G) and "나갔" not in state(G), state(G))
            G.fill("#compose", "back-again"); G.click("#sendBtn")
            H.wait_for_selector(".msg.theirs", timeout=20000)
            check("4h. 돌아온 뒤 메시지 전달", True)
            errs_g = [pg.evaluate("window.__csp") for pg in (G, H)]
            check("7b. 추가 CSP 위반 0", all(not x for x in errs_g), str(errs_g))
            ctxG.close(); ctxH.close()

            # 8. 혼자 있을 때 미리 쓰기: 글상자 활성, 대기열, 상대 입장 후 전송, 나가기 시 비움
            pw4 = "w-" + secrets.token_hex(6)
            ctxI, ctxJ, ctxK = new_ctx(browser, errors, "I"), new_ctx(browser, errors, "J"), new_ctx(browser, errors, "K")
            I, J, K = new_page(ctxI, errors, "I"), new_page(ctxJ, errors, "J"), new_page(ctxK, errors, "K")
            c5 = make(I, pw4)
            wait_state(I, "상대를 기다리는 중")
            check("8a. 혼자 있어도 글상자·보내기 활성", I.is_enabled("#compose") and I.is_enabled("#sendBtn"))
            check("8b. '코드처럼 보기'가 페이지에 없음",
                  "코드처럼 보기" not in I.inner_text("body") and "코드처럼 보기" not in I.content()
                  and I.query_selector("#codeToggle") is None)
            I.fill("#compose", "ls -la\n  echo hi")
            I.click("#sendBtn")
            I.wait_for_selector(".msg.mine .st.wait", timeout=10000)
            st_txt = I.inner_text(".msg.mine .st")
            check("8c. 혼자 보내면 '대기 중' 표시 + 대기열 1", "대기 중" in st_txt and I.evaluate("window.__grDebug()")["queued"] == 1, st_txt)
            enter(J, c5)
            wait_state(I, "연결됨"); wait_state(J, "연결됨")
            J.wait_for_selector(".msg.theirs", timeout=30000)
            got = J.inner_text(".msg.theirs pre")
            I.wait_for_function("() => document.querySelector('.msg.mine .st') && document.querySelector('.msg.mine .st').textContent === '보냄'", timeout=20000)
            check("8d. 상대 입장 후 도착(공백·줄바꿈 보존)·표시 '보냄'·대기열 0",
                  got == "ls -la\n  echo hi" and I.evaluate("window.__grDebug()")["queued"] == 0, repr(got))
            ctxI.close(); ctxJ.close()
            make(K, "x-" + secrets.token_hex(6))
            wait_state(K, "상대를 기다리는 중")
            K.fill("#compose", "pending-1"); K.click("#sendBtn")
            K.fill("#compose", "pending-2"); K.click("#sendBtn")
            K.wait_for_function("() => window.__grDebug().queued === 2", timeout=10000)
            K.click("#leaveBtn")
            K.wait_for_function("() => !document.getElementById('screenJoin').hidden", timeout=10000)
            dk = K.evaluate("window.__grDebug()")
            check("8e. 대기 글이 있는 채 나가면 대기열·기록 비워짐", dk["queued"] == 0 and dk["log"] == 0 and dk["domMsgs"] == 0, str(dk))
            ctxK.close()
            browser.close()

        check("7c. 콘솔 오류·pageerror 0", not errors, "; ".join(errors[:5]))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} 통과, {time.time() - t0:.0f}초")
    if bad:
        print("실패:", bad)
        sys.exit(1)


if __name__ == "__main__":
    main()
