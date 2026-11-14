"""Evaluation: Solve screen on coding-interview screenshots, with the returned code actually executed.

Each problem is rendered as a coding-site style page (headless Chrome), sent through the engine's
analyze_screen (real OpenAI, key from ~/.env), and the Python code in the answer is run against test cases.

    uv run python evals/coding_screen.py [problem-id …]      # report → evals/reports/coding_screen.json

Only the generated problem images are sent; nothing from the real screen.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from frlocal.config import Settings
from frlocal.openai import OpenAI
from frlocal.screen import analyze_screen

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# id, level, statement (HTML), starter code, tests (python source asserting on the solution's function/class)
PROBLEMS = [
    ("valid-parentheses", "easy", "<h2>20. Valid Parentheses</h2><p>Given a string <code>s</code> containing just the characters ()[]{} , determine if the input string is valid: "
     "open brackets must be closed by the same type of brackets, in the correct order.</p><p>Example: s = \"()[]{}\" → true; s = \"(]\" → false</p>",
     "def is_valid(s: str) -> bool:\n    # your code here\n    pass",
     "assert is_valid('()[]{}') and not is_valid('(]') and not is_valid('(') and is_valid('') and not is_valid('([)]') and is_valid('{[]}') and not is_valid(']')"),
    ("merge-intervals", "medium", "<h2>56. Merge Intervals</h2><p>Given an array of <code>intervals</code> where intervals[i] = [start, end], merge all overlapping intervals and return "
     "the non-overlapping intervals that cover all the input.</p><p>Example: [[1,3],[2,6],[8,10],[15,18]] → [[1,6],[8,10],[15,18]]</p>",
     "def merge(intervals: list[list[int]]) -> list[list[int]]:\n    pass",
     "assert merge([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]\nassert merge([[1,4],[4,5]]) == [[1,5]]\nassert merge([]) == []\n"
     "assert merge([[5,6],[1,10]]) == [[1,10]]\nassert merge([[1,4],[0,0]]) == [[0,0],[1,4]]"),
    ("lru-cache", "medium", "<h2>146. LRU Cache</h2><p>Design a data structure that follows the constraints of a Least Recently Used cache. <code>get(key)</code> returns the value or -1; "
     "<code>put(key, value)</code> updates or inserts, evicting the least recently used key when capacity is exceeded. Both must run in O(1) average time.</p>",
     "class LRUCache:\n    def __init__(self, capacity: int):\n        pass\n    def get(self, key: int) -> int:\n        pass\n    def put(self, key: int, value: int) -> None:\n        pass",
     "c = LRUCache(2); c.put(1, 1); c.put(2, 2); assert c.get(1) == 1; c.put(3, 3); assert c.get(2) == -1; c.put(4, 4)\n"
     "assert c.get(1) == -1 and c.get(3) == 3 and c.get(4) == 4\nd = LRUCache(1); d.put(2, 1); d.put(2, 2); assert d.get(2) == 2; d.put(3, 3); assert d.get(2) == -1"),
    ("trapping-rain-water", "hard", "<h2>42. Trapping Rain Water</h2><p>Given <code>n</code> non-negative integers representing an elevation map where the width of each bar is 1, "
     "compute how much water it can trap after raining.</p><p>Example: height = [0,1,0,2,1,0,1,3,2,1,2,1] → 6</p>",
     "def trap(height: list[int]) -> int:\n    pass",
     "assert trap([0,1,0,2,1,0,1,3,2,1,2,1]) == 6 and trap([4,2,0,3,2,5]) == 9 and trap([]) == 0 and trap([3]) == 0 and trap([5,4,3,2,1]) == 0 and trap([2,0,2]) == 2"),
    ("custom-rate-limiter", "medium (not a well-known problem)", "<h2>Sliding-window rate limiter</h2><p>Implement <code>allowed(events, limit, window)</code>. <code>events</code> is a list of "
     "(timestamp_seconds, user_id) sorted by timestamp. A request is <b>accepted</b> if that user has fewer than <code>limit</code> accepted requests in the last <code>window</code> seconds "
     "(interval (t − window, t]); rejected requests do not count. Return the list of booleans, one per event.</p>"
     "<p>Example: events = [(1,'a'),(2,'a'),(3,'a'),(12,'a')], limit = 2, window = 10 → [True, True, False, True]</p>",
     "def allowed(events: list[tuple[int, str]], limit: int, window: int) -> list[bool]:\n    pass",
     "assert allowed([(1,'a'),(2,'a'),(3,'a'),(12,'a')], 2, 10) == [True, True, False, True]\n"
     "assert allowed([(1,'a'),(1,'b'),(1,'a'),(1,'a'),(11,'a'),(11,'a')], 2, 10) == [True, True, True, False, True, True]\n"
     "assert allowed([], 1, 1) == [] and allowed([(5,'x')], 0, 10) == [False]\nassert allowed([(1,'a'),(11,'a')], 1, 10) == [True, True]"),
    ("debug-binary-search", "debugging", "<h2>Find the bug</h2><p>This function should return the index of the first element ≥ target in a sorted list (len(nums) if none), "
     "but it loops forever on some inputs. Fix it.</p><p style='color:#ff7a7a'>TimeoutError: lower_bound([1, 3, 5], 4) did not finish in 2 s</p>",
     "def lower_bound(nums: list[int], target: int) -> int:\n    lo, hi = 0, len(nums)\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if nums[mid] < target:\n            lo = mid\n        else:\n            hi = mid\n    return lo",
     "assert lower_bound([1,3,5], 4) == 2 and lower_bound([1,3,5], 0) == 0 and lower_bound([1,3,5], 6) == 3 and lower_bound([], 1) == 0 and lower_bound([2,2,2], 2) == 0"),
    ("regex-matching", "hard (dynamic programming)", "<h2>10. Regular Expression Matching</h2><p>Given an input string <code>s</code> and a pattern <code>p</code>, implement regular expression "
     "matching with support for '.' (any single character) and '*' (zero or more of the preceding element). The matching must cover the <b>entire</b> input string.</p>"
     "<p>Example: s = \"aab\", p = \"c*a*b\" → true; s = \"mississippi\", p = \"mis*is*p*.\" → false</p>",
     "def is_match(s: str, p: str) -> bool:\n    pass",
     "assert is_match('aab', 'c*a*b') and not is_match('mississippi', 'mis*is*p*.') and is_match('', 'a*') and not is_match('aa', 'a') and is_match('ab', '.*') "
     "and not is_match('ab', '.*c') and is_match('aaa', 'ab*a*c*a') and not is_match('a', '') and is_match('', '')"),
    ("median-two-arrays", "hard (O(log n) required)", "<h2>4. Median of Two Sorted Arrays</h2><p>Given two sorted arrays <code>nums1</code> and <code>nums2</code>, return the median of the two "
     "sorted arrays. The overall run time complexity should be O(log (m+n)).</p><p>Example: nums1 = [1,3], nums2 = [2] → 2.0; nums1 = [1,2], nums2 = [3,4] → 2.5</p>",
     "def find_median_sorted_arrays(nums1: list[int], nums2: list[int]) -> float:\n    pass",
     "f = find_median_sorted_arrays\nassert f([1,3],[2]) == 2 and f([1,2],[3,4]) == 2.5 and f([],[1]) == 1 and f([2],[]) == 2 and f([1,1,1],[1,1]) == 1 "
     "and f([1,2,3,4,5],[6,7,8,9,10,11]) == 6 and f([100],[1,2,3]) == 2.5"),
    ("custom-build-time", "hard (not a well-known problem)", "<h2>Parallel build time</h2><p>A build has <code>n</code> tasks. <code>duration[i]</code> is the time task i takes; "
     "<code>deps</code> is a list of pairs (a, b) meaning task a must finish before task b starts. With unlimited workers, return the earliest time at which all tasks are finished. "
     "If the dependencies contain a cycle, return -1.</p><p>Example: duration = [3,2,4], deps = [(0,2),(1,2)] → 7; duration = [1,1], deps = [(0,1),(1,0)] → -1</p>",
     "def build_time(duration: list[int], deps: list[tuple[int, int]]) -> int:\n    pass",
     "assert build_time([3,2,4], [(0,2),(1,2)]) == 7 and build_time([1,1], [(0,1),(1,0)]) == -1 and build_time([], []) == 0 and build_time([5], []) == 5\n"
     "assert build_time([1,2,3,4], [(0,1),(1,2),(0,3)]) == 6 and build_time([2,2,2], [(0,1),(1,2),(2,1)]) == -1 and build_time([4,1,1], []) == 4"),
    ("chinese-top-k", "medium (Chinese statement)", "<h2>347. 前 K 个高频元素</h2><p>给你一个整数数组 <code>nums</code> 和一个整数 <code>k</code>，请返回其中出现频率前 k 高的元素，"
     "可以按任意顺序返回。要求时间复杂度优于 O(n log n)。</p><p>示例：nums = [1,1,1,2,2,3], k = 2 → [1,2]</p>",
     "def top_k_frequent(nums: list[int], k: int) -> list[int]:\n    pass",
     "assert sorted(top_k_frequent([1,1,1,2,2,3], 2)) == [1,2] and top_k_frequent([1], 1) == [1] and sorted(top_k_frequent([4,4,5,5,6], 2)) == [4,5]"),
]


def render(statement: str, starter: str, path: Path) -> None:
    code = "".join(f'<div><span class="n">{i + 1}</span>{line.replace("<", "&lt;") or "&nbsp;"}</div>' for i, line in enumerate(starter.split("\n")))
    html = f"""<html><body style="margin:0;background:#1a1a1a;color:#eee;font:15px/1.6 -apple-system,'PingFang SC',sans-serif;display:flex;height:100vh">
<div style="width:46%;padding:26px 30px;border-right:1px solid #333">{statement}</div>
<div style="flex:1;padding:18px 0;font:14px/1.7 Menlo,monospace;white-space:pre"><div style="padding:0 20px 10px;color:#888">Python3 ▾</div>{code}</div>
<style>.n{{display:inline-block;width:44px;text-align:right;margin-right:16px;color:#666}} code{{background:#333;padding:1px 5px;border-radius:4px}}</style></body></html>"""
    page = path.with_suffix(".html")
    page.write_text(html)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,820", f"--screenshot={path}", f"file://{page}"],
                   check=True, capture_output=True, timeout=60)


def extract_code(answer: str) -> str | None:
    blocks = re.findall(r"```(?:python|py|python3)?\n(.*?)```", answer, re.S)
    return max(blocks, key=len) if blocks else None


def run_tests(code: str, tests: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("from __future__ import annotations\nfrom typing import *\nimport collections, heapq, bisect\n" + code + "\n\n" + tests + "\nprint('TESTS-OK')\n")
    try:
        done = subprocess.run([sys.executable, f.name], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    return "TESTS-OK" in done.stdout, (done.stderr.strip().splitlines() or [""])[-1][:160]


async def main(only: list[str]) -> None:
    settings = Settings(accounts_dir=Path(tempfile.mkdtemp()), workspace_dir=Path(tempfile.mkdtemp()), token="x" * 32)
    openai = OpenAI(settings.openai_base, settings.openai_ws_base, settings.env_file, settings.openai_proxy)
    work = Path(tempfile.mkdtemp())
    extra = json.loads(sys_extra) if (sys_extra := __import__("os").environ.get("EVAL_SCREEN_KWARGS", "")) else {}
    results = []
    for pid, level, statement, starter, tests in PROBLEMS:
        if only and pid not in only:
            continue
        image = work / f"{pid}.png"
        render(statement, starter, image)
        answers: list[str] = []
        started = time.monotonic()
        result = await analyze_screen(openai, settings, image=image.read_bytes(), mime="image/png", purpose="solve",
                                      publish=lambda _id, text, sink=answers: sink.append(text) or True, **extra)
        seconds = time.monotonic() - started
        answer = answers[0] if answers else ""
        code = extract_code(answer)
        passed, error = run_tests(code, tests) if code else (False, "no code block in the answer")
        row = {"id": pid, "level": level, "status": result["status"], "seconds": round(seconds, 1), "has_code": bool(code), "tests_pass": passed, "error": error,
               "mentions_complexity": bool(re.search(r"O\([^)]+\)", answer)), "mentions_edge_cases": bool(re.search(r"edge case|边界|空(数组|列表|字符串|输入)|empty", answer, re.I)),
               "answer_chars": len(answer), "answer": answer}
        results.append(row)
        print(f"{pid:24} {level:34} {seconds:5.1f}s code={'yes' if code else 'NO ':3} tests={'PASS' if passed else 'FAIL'} "
              f"complexity={'yes' if row['mentions_complexity'] else 'no '} edge={'yes' if row['mentions_edge_cases'] else 'no '} {error}")
    await openai.close()
    report = Path(__file__).parent / "reports" / "coding_screen.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    ok = sum(r["tests_pass"] for r in results)
    print(f"\n{ok}/{len(results)} solutions pass their tests; median {sorted(r['seconds'] for r in results)[len(results) // 2]} s; report: {report}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
