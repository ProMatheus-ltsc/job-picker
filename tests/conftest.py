"""pytest 配置：把 tests/ 加入 sys.path，使 `from helpers import ...` 在仓库根目录直接可用。

为什么需要：门禁与 CI 都从仓库根执行 `python -m pytest -q`，此时 tests/ 不是包，
`from helpers import probe` 会失败。用 conftest 注入路径比要求调用方设 PYTHONPATH 更可靠
（少一个"必须记得设的环境变量"）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
