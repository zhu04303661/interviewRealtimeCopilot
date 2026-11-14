"""Solve screen with the candidate's coding language set to C++: the returned code is compiled (clang++) and run.

    uv run python evals/coding_screen_cpp.py
"""
import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

from coding_screen import render
from frlocal.config import Settings
from frlocal.openai import OpenAI
from frlocal.screen import analyze_screen

STATEMENT = ("<h2>42. Trapping Rain Water</h2><p>Given <code>n</code> non-negative integers representing an elevation map where the width of each bar is 1, "
             "compute how much water it can trap after raining.</p><p>Example: height = [0,1,0,2,1,0,1,3,2,1,2,1] → 6</p>")
STARTER = "class Solution {\npublic:\n    int trap(vector<int>& height) {\n        \n    }\n};"
MAIN = """
int main() { Solution s; vector<int> a{0,1,0,2,1,0,1,3,2,1,2,1}, b{4,2,0,3,2,5}, c{}, d{2,0,2};
  if (s.trap(a) != 6 || s.trap(b) != 9 || s.trap(c) != 0 || s.trap(d) != 2) return 1; puts("TESTS-OK"); return 0; }
"""


async def main() -> None:
    settings = Settings(accounts_dir=Path(tempfile.mkdtemp()), workspace_dir=Path(tempfile.mkdtemp()), token="x" * 32)
    openai = OpenAI(settings.openai_base, settings.openai_ws_base, settings.env_file, settings.openai_proxy)
    work = Path(tempfile.mkdtemp())
    render(STATEMENT, STARTER, work / "p.png")
    answers: list[str] = []
    await analyze_screen(openai, settings, image=(work / "p.png").read_bytes(), mime="image/png", purpose="solve",
                         publish=lambda _id, text: answers.append(text) or True, coding_language="C++")
    await openai.close()
    blocks = re.findall(r"```(\w+)?\n(.*?)```", answers[0] if answers else "", re.S)
    if not blocks:
        raise SystemExit("FAIL: no code block")
    language, code = max(blocks, key=lambda b: len(b[1]))
    (work / "a.cpp").write_text("#include <bits/stdc++.h>\nusing namespace std;\n" if False else
                                "#include <vector>\n#include <algorithm>\n#include <cstdio>\n#include <string>\n#include <unordered_map>\n#include <stack>\nusing namespace std;\n" + code + MAIN)
    build = subprocess.run(["clang++", "-std=c++17", "-o", str(work / "a"), str(work / "a.cpp")], capture_output=True, text=True)
    if build.returncode:
        raise SystemExit(f"FAIL: does not compile: {build.stderr[:300]}")
    out = subprocess.run([str(work / "a")], capture_output=True, text=True, timeout=10).stdout
    print(f"C++ ({language}): {'PASS' if 'TESTS-OK' in out else 'FAIL'}")


asyncio.run(main())
