"""解释器自举：让脚本在缺 Pillow 的 python3 下自动切到自带 Pillow 的解释器。

本机系统 python3 没有 PIL（项目零依赖），简历检测/渲染相关脚本都需要 Pillow。
cron / 调度器往往用极简 PATH 调起系统 python3，因此每个需要 PIL 的脚本第一件事就是自举。

用法（必须放在 from PIL import Image 之前）：
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _pyboot import ensure_pillow
    ensure_pillow()
    from PIL import Image
"""
import glob
import os
import sys


def _candidates():
    out = []
    env = os.environ.get("DSH_PYTHON")
    if env:
        out.append(env)
    out += sorted(glob.glob(os.path.expanduser("~/.dsh/dsh-runtimes/*/dependencies/python/bin/python3")))
    out.append("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/primary-runtime/dependencies/python/bin/python3")
    out += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
    return out


def ensure_pillow():
    """当前解释器没有 PIL 时，exec 到一个有 PIL 的解释器（最多尝试一轮）。"""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass

    tried = {p for p in os.environ.get("_PYBOOT_TRIED", "").split(os.pathsep) if p}
    me = os.path.realpath(sys.executable)
    for cand in _candidates():
        if not cand or not os.path.exists(cand):
            continue
        real = os.path.realpath(cand)
        if real == me or real in tried:
            continue
        tried.add(real)
        env = dict(os.environ, _PYBOOT_TRIED=os.pathsep.join(sorted(tried)))
        try:
            os.execve(real, [real, os.path.abspath(sys.argv[0])] + sys.argv[1:], env)
        except OSError:
            continue
    raise SystemExit("缺少 Pillow：未找到带 PIL 的 Python，请用 DSH_PYTHON 指定解释器")
