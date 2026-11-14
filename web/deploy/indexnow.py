"""Tell IndexNow search engines (Bing, Yandex, Naver, Seznam…) which pages exist or changed.

    python3 web/deploy/indexnow.py        # after deploying; submits every URL in web/static/urls.txt

The key is the name of the 32-hex .txt file in web/static (served at the site root, as IndexNow requires).
Google and Baidu do not use IndexNow: submit sitemap.xml in their webmaster consoles.
"""
import json
import re
import urllib.request
from pathlib import Path

static = Path(__file__).resolve().parent.parent / "static"
key = next(p.stem for p in static.glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}", p.stem))
urls = (static / "urls.txt").read_text().split()
host = urls[0].split("/")[2]
body = json.dumps({"host": host, "key": key, "keyLocation": f"https://{host}/{key}.txt", "urlList": urls}).encode()
request = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
with urllib.request.urlopen(request, timeout=30) as response:
    print(f"IndexNow: HTTP {response.status} for {len(urls)} URLs on {host}")
