"""index.html 의 인라인 <script>/<style> 해시를 계산해 CSP 메타에 넣는다. --check 면 맞는지만 본다."""
import base64, hashlib, re, sys
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "index.html"
html = path.read_text(encoding="utf-8")


def h(s: str) -> str:
    return base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()


# 속성 없는 인라인 <script> (src 없는 것) 하나, <style> 하나
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
styles = re.findall(r"<style>(.*?)</style>", html, re.S)
assert len(scripts) == 1 and len(styles) == 1, (len(scripts), len(styles))
sh, st = h(scripts[0]), h(styles[0])

m = re.search(r"script-src 'sha256-([^']+)'", html)
m2 = re.search(r"style-src 'sha256-([^']+)'", html)
assert m and m2
if "--check" in sys.argv:
    ok = m.group(1) == sh and m2.group(1) == st
    print("CSP 해시 일치" if ok else "CSP 해시 불일치")
    sys.exit(0 if ok else 1)
html = html.replace(m.group(1), sh, 1).replace(m2.group(1), st, 1)
path.write_text(html, encoding="utf-8", newline="")
print("script", sh)
print("style ", st)
